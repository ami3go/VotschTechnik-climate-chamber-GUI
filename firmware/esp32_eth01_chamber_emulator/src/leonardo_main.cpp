// Arduino Leonardo R3 + W5500 Shield V2.0 chamber emulator (same hardware as USB-UPS-Simulator).
// Separate from ESP32 implementation; no GUI or physical-HIL authorization bypass.
#include <Arduino.h>
#include <SPI.h>
#include <Ethernet.h>
#include <EEPROM.h>
#include <avr/wdt.h>
#include <string.h>
#include <stdlib.h>
#include "leonardo_core.h"

namespace {
const uint8_t ETH_CS = 10;
const uint8_t SD_CS = 4;
const uint32_t CLIENT_IDLE_MS = 5000UL;
const uint32_t WRITE_DEADLINE_MS = 1000UL;
const uint16_t DHCP_RETRY_MS = 60000U;
const uint16_t DHCP_FIRST_TIMEOUT_MS = 10000;
const uint16_t DHCP_RESPONSE_MS = 2000;
const uint16_t VERSION_MARKER = 0x4C32; // L2

struct Config {
    uint16_t marker;
    char serial[17];
    uint8_t mac_tail;
    uint8_t static_network;
    uint8_t ip[4], mask[4], gateway[4], dns[4];
    uint8_t checksum;
};
Config cfg;
leonardo::Chamber chamber;
leonardo::Faults faults;
EthernetServer server(leonardo::CHAMBER_PORT);
EthernetClient client;
bool ethernet_ready = false;
bool has_dhcp = false;
bool prior_link = false;
bool pending = false;
bool close_after_reply = false;
uint8_t request[leonardo::MAX_REQUEST];
uint8_t response[leonardo::MAX_RESPONSE];
uint8_t request_len = 0, response_len = 0, response_offset = 0;
uint32_t last_client_ms = 0, reply_at_ms = 0, write_started_ms = 0;
uint32_t last_tick_ms = 0, last_maintain_ms = 0, last_led_ms = 0;
uint16_t dhcp_maintenance_interval_ms = 1000U;
char usb_line[100], uart_line[100];
uint8_t usb_len = 0, uart_len = 0;
bool led_state = false;

uint8_t checksum_config(const Config& c) {
    const uint8_t* p = reinterpret_cast<const uint8_t*>(&c);
    uint8_t result = 0xA5;
    for (size_t i = 0; i < sizeof(Config) - 1; ++i) result ^= p[i];
    return result;
}
bool valid_serial(const char* s) {
    if (!s || !*s) return false;
    size_t n = 0;
    while (s[n] && n <= 16) {
        if (!((s[n] >= '0' && s[n] <= '9') ||
              (s[n] >= 'A' && s[n] <= 'Z') ||
              (s[n] >= 'a' && s[n] <= 'z'))) return false;
        ++n;
    }
    return n && n <= 16 && s[n] == 0;
}
bool valid_mask(const uint8_t* a) {
    uint32_t mask = (uint32_t(a[0]) << 24) | (uint32_t(a[1]) << 16) |
                    (uint32_t(a[2]) << 8) | a[3];
    uint32_t inverse = ~mask;
    return mask && mask != 0xFFFFFFFFUL && (inverse & (inverse + 1UL)) == 0;
}
bool valid_network(const Config& c) {
    if (!valid_mask(c.mask) || c.ip[0] == 0 || c.ip[0] >= 224 ||
        c.ip[3] == 0 || c.ip[3] == 255 || c.gateway[0] >= 224) return false;
    return true;
}
void default_config() {
    memset(&cfg, 0, sizeof(cfg));
    cfg.marker = VERSION_MARKER;
    strcpy(cfg.serial, "SIMLEO0001");
    cfg.mac_tail = 1;
    cfg.checksum = checksum_config(cfg);
}
void save_config() {
    cfg.checksum = checksum_config(cfg);
    EEPROM.put(0, cfg); // AVR EEPROM.update semantics: changes only.
}
void load_config() {
    EEPROM.get(0, cfg);
    if (cfg.marker != VERSION_MARKER || cfg.checksum != checksum_config(cfg) ||
        !memchr(cfg.serial, 0, sizeof(cfg.serial)) || !valid_serial(cfg.serial) ||
        cfg.mac_tail == 0 || cfg.mac_tail == 255 ||
        cfg.static_network > 1 || (cfg.static_network && !valid_network(cfg))) {
        default_config();
    }
    strncpy(chamber.serial, cfg.serial, sizeof(chamber.serial));
    chamber.serial[sizeof(chamber.serial) - 1] = 0;
}
void reset_board() {
    // Config persists; volatile chamber state and faults restart STOPPED.
    wdt_enable(WDTO_15MS);
    for (;;) { } // deliberate watchdog reboot
}
IPAddress addr(const uint8_t octets[4]) {
    return IPAddress(octets[0], octets[1], octets[2], octets[3]);
}
bool parse_ip(const char* text, uint8_t out[4]) {
    if (!text || !*text) return false;
    for (uint8_t part = 0; part < 4; ++part) {
        if (*text < '0' || *text > '9') return false;
        unsigned n = 0;
        unsigned digits = 0;
        while (*text >= '0' && *text <= '9') {
            n = n * 10 + static_cast<unsigned>(*text++ - '0');
            if (++digits > 3 || n > 255) return false;
        }
        out[part] = static_cast<uint8_t>(n);
        if (part < 3) {
            if (*text++ != '.') return false;
        } else if (*text) return false;
    }
    return true;
}
void print_status(Print& out) {
    out.print(F("LEO-EMU 0.1.0 link="));
    out.print(ethernet_ready && Ethernet.linkStatus() == LinkON ? 1 : 0);
    out.print(F(" IP=")); out.print(Ethernet.localIP());
    out.print(F(" SN=")); out.print(chamber.serial);
    out.print(F(" RUN=")); out.print(chamber.running ? 1 : 0);
    out.print(F(" target_centi=")); out.print(chamber.target_centi);
    out.print(F(" actual_centi=")); out.println(chamber.actual_centi);
}
void console_command(char* text, Print& out) {
    if (!strcmp(text, "status")) {
        print_status(out);
    } else if (!strcmp(text, "help")) {
        out.println(F("status|fault NAME|clear|delay N"));
        out.println(F("speed|identity|net|eeprom (see docs)"));
    } else if (!strcmp(text, "fault clear")) {
        faults = leonardo::Faults{};
        out.println(F("FAULT CLEAR"));
    } else if (!strncmp(text, "fault ", 6)) {
        leonardo::Faults f; // one active scenario at a time
        const char* mode = text + 6;
        if (!strcmp(mode, "sticky_stop")) f.sticky_stop = true;
        else if (!strcmp(mode, "drop_stop")) f.drop_stop_reply = true;
        else if (!strcmp(mode, "timeout")) f.suppress_reply = true;
        else if (!strcmp(mode, "partial")) f.partial_reply = true;
        else if (!strcmp(mode, "invalid_sensor")) f.invalid_sensor = true;
        else if (!strcmp(mode, "freeze")) f.freeze_temperature = true;
        else if (!strcmp(mode, "alarm")) f.alarm = true;
        else if (!strcmp(mode, "runaway_heat")) f.runaway_heat = true;
        else if (!strcmp(mode, "runaway_cool")) f.runaway_cool = true;
        else if (!strcmp(mode, "reset")) f.reset_on_command = true;
        else if (!strncmp(mode, "delay ", 6)) {
            char* end = 0;
            unsigned long delay_ms = strtoul(mode + 6, &end, 10);
            if (end == mode + 6 || *end || delay_ms > 2000) {
                out.println(F("ERR delay")); return;
            }
            f.delay_ms = static_cast<uint16_t>(delay_ms);
        } else { out.println(F("ERR fault")); return; }
        faults = f;
        out.println(F("FAULT ON"));
    } else if (!strncmp(text, "speed ", 6)) {
        if (!strcmp(text + 6, "1")) chamber.thermal_speed = 1;
        else if (!strcmp(text + 6, "10")) chamber.thermal_speed = 10;
        else { out.println(F("ERR speed 1|10")); return; }
        chamber.reset_thermal_accumulator();
        out.println(F("OK speed"));
    } else if (!strncmp(text, "identity serial ", 16)) {
        const char* serial = text + 16;
        if (!valid_serial(serial)) { out.println(F("ERR serial")); return; }
        strcpy(cfg.serial, serial);
        strcpy(chamber.serial, serial);
        save_config();
        out.println(F("OK serial saved; reconnect"));
    } else if (!strcmp(text, "net dhcp")) {
        cfg.static_network = 0; save_config(); out.println(F("OK DHCP reset")); reset_board();
    } else if (!strncmp(text, "net static ", 11)) {
        char* cursor = text + 11;
        char* save = 0;
        char* parts[5] = {};
        for (uint8_t i = 0; i < 5; ++i) parts[i] = strtok_r(i ? 0 : cursor, " ", &save);
        Config candidate = cfg;
        if (!parts[0] || !parts[1] || !parts[2] || !parts[3] || parts[4] ||
            !parse_ip(parts[0], candidate.ip) ||
            !parse_ip(parts[1], candidate.mask) ||
            !parse_ip(parts[2], candidate.gateway) ||
            !parse_ip(parts[3], candidate.dns) || !valid_network(candidate)) {
            out.println(F("ERR static IP MASK GW DNS")); return;
        }
        cfg = candidate; cfg.static_network = 1; save_config();
        out.println(F("OK static reboot")); reset_board();
    } else if (!strncmp(text, "net mac ", 8)) {
        char* end = 0;
        unsigned long tail = strtoul(text + 8, &end, 10);
        if (end == text + 8 || *end || tail < 1 || tail > 254) {
            out.println(F("ERR MAC tail 1..254")); return;
        }
        cfg.mac_tail = static_cast<uint8_t>(tail); save_config();
        out.println(F("OK MAC reboot")); reset_board();
    } else if (!strcmp(text, "eeprom reset")) {
        default_config(); save_config(); out.println(F("OK EEPROM reset")); reset_board();
    } else if (*text) out.println(F("ERR help"));
}
void poll_console(Stream& input, Print& output, char* buffer, uint8_t& len) {
    for (uint8_t count = 0; count < 16 && input.available(); ++count) {
        const int c = input.read();
        if (c == '\r' || c == '\n') {
            if (len) { buffer[len] = 0; console_command(buffer, output); len = 0; }
        } else if (c >= 0x20 && c <= 0x7E) {
            if (len < 99) buffer[len++] = static_cast<char>(c);
            else { len = 0; output.println(F("ERR console")); }
        }
    }
}
void close_client() {
    client.stop();
    request_len = 0;
    response_len = 0;
    response_offset = 0;
    pending = false;
    close_after_reply = false;
}
void start_network() {
    byte mac[] = {0x02, 0x56, 0x4F, 0x54, 0x43, cfg.mac_tail};
    pinMode(ETH_CS, OUTPUT); digitalWrite(ETH_CS, HIGH);
    pinMode(SD_CS, OUTPUT); digitalWrite(SD_CS, HIGH);
    Ethernet.init(ETH_CS);
    if (cfg.static_network) {
        Ethernet.begin(mac, addr(cfg.ip), addr(cfg.dns),
                       addr(cfg.gateway), addr(cfg.mask));
    } else {
        has_dhcp = Ethernet.begin(mac, DHCP_FIRST_TIMEOUT_MS, DHCP_RESPONSE_MS) != 0;
        if (!has_dhcp) {
            // RFC1918 rather than UPS link-local 169.254/16: driver's
            // discover_chambers explicitly refuses link-local scan/probe.
            IPAddress ip(192,168,42,42), dns(0,0,0,0), gw(0,0,0,0), mask(255,255,255,0);
            Ethernet.begin(mac, ip, dns, gw, mask);
        }
    }
    ethernet_ready = Ethernet.hardwareStatus() == EthernetW5500;
    if (ethernet_ready) {
        server.begin();
        prior_link = Ethernet.linkStatus() == LinkON;
    }
    Serial.print(F("LEO-EMU W5500=")); Serial.println(ethernet_ready ? F("YES") : F("NO"));
    print_status(Serial);
    print_status(Serial1);
}
void schedule_response(uint8_t size, uint32_t now, bool is_stop) {
    pending = true;
    response_len = size;
    response_offset = 0;
    write_started_ms = now;
    reply_at_ms = now + faults.delay_ms;
    close_after_reply = false;
    if (faults.drop_stop_reply && is_stop) {
        Serial.println(F("FAULT STOP reply lost"));
        close_client(); return;
    }
    if (faults.suppress_reply) {
        response_len = 0;
        close_after_reply = true;
        reply_at_ms = now + 1500;
        Serial.println(F("FAULT timeout"));
    } else if (faults.partial_reply) {
        response[0] = '1'; response[1] = 0xB6;
        response_len = 2;
        close_after_reply = true;
        Serial.println(F("FAULT partial"));
    }
}
void poll_network(uint32_t now) {
    if (!ethernet_ready) return;
    const bool link = Ethernet.linkStatus() == LinkON;
    if (!link) {
        if (prior_link) {
            close_client();
            Serial.println(F("ETH link lost"));
        }
        prior_link = false;
        return;
    }
    if (!prior_link) {
        // New sockets after reconnection; no auto resume or state reset.
        server.begin();
        Serial.println(F("ETH link restored"));
        prior_link = true;
    }
    // Arduino Ethernet 2.0.2 accept() returns a new connection even before
    // the first received byte; stale sessions may be replaced by a new driver.
    EthernetClient candidate = server.accept();
    if (candidate) {
        close_client();
        client = candidate;
        last_client_ms = now;
    }
    if (!client) return;
    if (!client.connected() && !client.available()) { close_client(); return; }
    if (static_cast<uint32_t>(now - last_client_ms) >= CLIENT_IDLE_MS) {
        close_client(); return;
    }
    if (pending) {
        if (static_cast<int32_t>(now - reply_at_ms) < 0) return;
        if (response_offset < response_len) {
            const size_t remaining = response_len - response_offset;
            size_t written = client.write(response + response_offset,
                                          remaining);
            if (written > remaining) written = 0;
            response_offset += static_cast<uint8_t>(written);
        }
        if (response_offset == response_len) {
            pending = false; last_client_ms = now;
            if (close_after_reply) close_client();
        } else if (static_cast<uint32_t>(now - write_started_ms) > WRITE_DEADLINE_MS) {
            Serial.println(F("TCP write timeout"));
            close_client();
        }
        return;
    }
    for (uint8_t n = 0; n < 32 && client.available(); ++n) {
        const int c = client.read();
        if (c < 0) break;
        last_client_ms = now;
        if (request_len >= leonardo::MAX_REQUEST) {
            Serial.println(F("TCP frame long"));
            close_client(); return;
        }
        request[request_len++] = static_cast<uint8_t>(c);
        if (c == '\r') {
            const bool is_stop = leonardo::is_stop_frame(request, request_len);
            const size_t len = leonardo::handle_frame(request, request_len,
                                    chamber, faults, response, sizeof(response));
            request_len = 0;
            if (faults.reset_on_command) {
                Serial.println(F("FAULT reset"));
                reset_board();
            }
            if (!len) { close_client(); return; }
            schedule_response(static_cast<uint8_t>(len), now, is_stop);
            break;
        }
    }
}
} // namespace

void setup() {
    MCUSR = 0;
    wdt_disable();
    pinMode(LED_BUILTIN, OUTPUT);
    Serial.begin(115200); // native USB CDC, never wait for host enumeration
    Serial1.begin(115200); // D0/D1 optional 5 V TTL bench console
    load_config();
    chamber.running = false;
    faults = leonardo::Faults{};
    start_network();
    last_tick_ms = millis();
    last_maintain_ms = last_tick_ms;
    last_led_ms = last_tick_ms;
    wdt_enable(WDTO_8S);
}

void loop() {
    const uint32_t now = millis();
    chamber.advance(static_cast<uint32_t>(now - last_tick_ms), faults);
    last_tick_ms = now;
    poll_console(Serial, Serial, usb_line, usb_len);
    poll_console(Serial1, Serial1, uart_line, uart_len);
    poll_network(now);
    if (leonardo::dhcp_maintenance_due(
            has_dhcp, static_cast<bool>(client), chamber.running,
            static_cast<uint32_t>(now - last_maintain_ms),
            dhcp_maintenance_interval_ms)) {
        // Ethernet.maintain may block: never call during a client session or run.
        const int rc = Ethernet.maintain();
        last_maintain_ms = millis();
        // Keep the reference timestamp in the past. Moving it into the future
        // would make unsigned elapsed-time arithmetic wrap and retry at once.
        dhcp_maintenance_interval_ms =
            (rc == 1 || rc == 3) ? DHCP_RETRY_MS : 1000U;
    }
    if (static_cast<uint32_t>(now - last_led_ms) >= 1000UL) {
        led_state = !led_state;
        digitalWrite(LED_BUILTIN, led_state ? HIGH : LOW);
        last_led_ms = now;
    }
    wdt_reset(); // only successful main-loop progress refreshes WDT
}
