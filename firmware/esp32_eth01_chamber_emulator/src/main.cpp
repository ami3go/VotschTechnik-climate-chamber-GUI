// WT32-ETH01 v1 reference firmware. GUI activation is NOT authorized by this code.
#include <Arduino.h>
#include <ETH.h>
#include <WiFi.h>
#include <Preferences.h>
#include <esp_task_wdt.h>
#include <esp_system.h>
#include <array>
#include <string>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include "emulator_protocol.h"

namespace {
constexpr unsigned MAX_SESSIONS = 4;
constexpr uint32_t IDLE_MS = 10000;
const char *VERSION = "0.1.0";
Preferences prefs;
emu::Chamber chamber;
emu::Faults faults;
WiFiServer server(emu::PROTOCOL_PORT);
volatile bool has_ip = false;
volatile bool has_link = false;
bool server_active = false;
uint32_t last_tick = 0;
uint32_t last_diag = 0;

struct Session {
    WiFiClient client;
    char data[emu::MAX_FRAME + 1]{};
    size_t length = 0;
    uint32_t last_activity = 0;
    uint32_t reply_at = 0;
    std::string pending;
    bool waiting = false;
    bool close_after = false;
};
std::array<Session, MAX_SESSIONS> sessions;
char uart_line[96]{};
size_t uart_len = 0;

void event_handler(WiFiEvent_t event) {
    // Event callback runs in the network event task: update flags only.
    switch (event) {
        case ARDUINO_EVENT_ETH_CONNECTED: has_link = true; break;
        case ARDUINO_EVENT_ETH_DISCONNECTED:
        case ARDUINO_EVENT_ETH_STOP: has_link = false; has_ip = false; break;
        case ARDUINO_EVENT_ETH_GOT_IP: has_link = true; has_ip = true; break;
        default: break;
    }
}

void close_session(Session &s) {
    s.client.stop();
    s.pending.clear();
    s.length = 0;
    s.waiting = false;
    s.close_after = false;
}

void diagnostics() {
    Serial.printf("ESP-EMU %s reset=%d ETH link=%u ipReady=%u IP=%s MAC=%s heap=%u RUN=%u actual=%.2f target=%.2f\n",
        VERSION, static_cast<int>(esp_reset_reason()), unsigned(has_link), unsigned(has_ip),
        ETH.localIP().toString().c_str(), ETH.macAddress().c_str(),
        ESP.getFreeHeap(), unsigned(chamber.running), chamber.actual, chamber.target);
}

bool valid_serial(const String &value) {
    if (value.length() < 1 || value.length() > 40) return false;
    for (size_t i = 0; i < value.length(); ++i)
        if (!std::isalnum(static_cast<unsigned char>(value[i]))) return false;
    return true;
}
bool valid_ip(const String &value) {
    IPAddress parsed;
    return parsed.fromString(value);
}

void handle_uart(String command) {
    command.trim();
    if (command == "help") {
        Serial.println("status | fault clear | fault sticky_stop|drop_stop|timeout|partial|invalid_sensor|freeze|alarm|reset|off | fault delay <0..2000> | speed <0.1..100> | identity serial <alphanumeric> | net dhcp | net static <ip> <mask> <gw> <dns> | nvs reset");
    } else if (command == "status") {
        diagnostics();
    } else if (command == "fault clear" || command == "fault off") {
        faults = emu::Faults{};
        Serial.println("FAULTS DISABLED");
    } else if (command.startsWith("fault ")) {
        emu::Faults next; // enabling a single scenario clears other faults
        if (command == "fault sticky_stop") next.sticky_stop = true;
        else if (command == "fault drop_stop") next.drop_stop_reply = true;
        else if (command == "fault timeout") next.timeout_reply = true;
        else if (command == "fault partial") next.partial_reply = true;
        else if (command == "fault invalid_sensor") next.invalid_sensor = true;
        else if (command == "fault freeze") next.freeze_temperature = true;
        else if (command == "fault alarm") next.alarm = true;
        else if (command == "fault reset") next.reset_on_command = true;
        else if (command.startsWith("fault delay ")) {
            String n = command.substring(12);
            long v = n.toInt();
            if (v < 0 || v > 2000 || n != String(v)) { Serial.println("ERR delay 0..2000"); return; }
            next.response_delay_ms = unsigned(v);
        } else { Serial.println("ERR unknown fault"); return; }
        faults = next;
        Serial.printf("FAULT ENABLED: %s\n", command.c_str());
    } else if (command.startsWith("speed ")) {
        String arg = command.substring(6);
        char *end = nullptr;
        double value = std::strtod(arg.c_str(), &end);
        if (end == arg.c_str() || *end || !chamber.set_speed(value)) {
            Serial.println("ERR speed range 0.1..100");
        } else Serial.printf("simulation_speed=%.3f; wall-clock dwell is NOT accelerated\n", chamber.speed);
    } else if (command.startsWith("identity serial ")) {
        String serial = command.substring(16);
        if (!valid_serial(serial)) { Serial.println("ERR serial alphanumeric 1..40"); return; }
        prefs.putString("serial", serial);
        chamber.serial = serial.c_str();
        Serial.println("identity changed; disconnect/reconnect driver for new identity");
    } else if (command == "net dhcp") {
        prefs.putBool("static", false);
        Serial.println("DHCP saved; rebooting STOPPED");
        delay(25); ESP.restart();
    } else if (command.startsWith("net static ")) {
        char ip[20]{}, mask[20]{}, gw[20]{}, dns[20]{}, extra[2]{};
        int count = std::sscanf(command.c_str(), "net static %19s %19s %19s %19s %1s",
                                ip, mask, gw, dns, extra);
        if (count != 4 || !valid_ip(ip) || !valid_ip(mask) || !valid_ip(gw) || !valid_ip(dns)) {
            Serial.println("ERR usage: net static <ip> <mask> <gateway> <dns>");
            return;
        }
        prefs.putString("ip", ip); prefs.putString("mask", mask);
        prefs.putString("gw", gw); prefs.putString("dns", dns);
        prefs.putBool("static", true);
        Serial.println("static config saved; rebooting STOPPED");
        delay(25); ESP.restart();
    } else if (command == "nvs reset") {
        prefs.clear();
        Serial.println("NVS reset; rebooting STOPPED");
        delay(25); ESP.restart();
    } else if (command.length()) Serial.println("ERR unknown command (help)");
}

void poll_console() {
    for (unsigned n = 0; n < 32 && Serial.available(); ++n) {
        int c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (uart_len) { uart_line[uart_len] = 0; handle_uart(String(uart_line)); uart_len = 0; }
        } else if (c >= 0x20 && c <= 0x7e) {
            if (uart_len < sizeof(uart_line) - 1) uart_line[uart_len++] = char(c);
            else { uart_len = 0; Serial.println("ERR UART line too long"); }
        }
    }
}

void apply_network_config() {
    if (!prefs.getBool("static", false)) { Serial.println("ETH DHCP selected"); return; }
    IPAddress ip, mask, gw, dns;
    if (!ip.fromString(prefs.getString("ip")) ||
        !mask.fromString(prefs.getString("mask")) ||
        !gw.fromString(prefs.getString("gw")) ||
        !dns.fromString(prefs.getString("dns"))) {
        Serial.println("INVALID NVS static IP; using DHCP; reset with 'net dhcp'");
        return;
    }
    if (!ETH.config(ip, gw, mask, dns)) Serial.println("ETH.config failed (check wiring)");
}

void dispatch(Session &s, const std::string &request, uint32_t now) {
    // Execute synchronously bounded, with no wait/sleep. Faults only from UART.
    const std::string response = emu::handle_frame(request, chamber, faults);
    if (faults.reset_on_command) {
        Serial.println("FAULT reset-on-command; reboot -> STOPPED");
        Serial.flush(); ESP.restart();
    }
    const bool is_stop = request.find(std::string("14001") + char(0xB6) + "1" +
                               char(0xB6) + "1" + char(0xB6) + "0\r") == 0;
    s.pending = response;
    s.close_after = false;
    s.waiting = true;
    s.reply_at = now + faults.response_delay_ms;
    if (faults.drop_stop_reply && is_stop) {
        // State was already updated, but driver MUST report outcome UNKNOWN.
        Serial.println("FAULT STOP executed; reply lost; closing session");
        s.pending.clear(); s.close_after = true;
    } else if (faults.timeout_reply) {
        Serial.println("FAULT suppressing reply; driver timeout expected");
        s.pending.clear(); s.reply_at = now + 2500; s.close_after = true;
    } else if (faults.partial_reply) {
        Serial.println("FAULT partial reply");
        s.pending = std::string("1") + char(0xB6);
        s.close_after = true;
    }
}

void tick_network(uint32_t now) {
    if (!has_ip) {
        if (server_active) {
            server.end(); server_active = false;
            Serial.println("TCP shutdown: Ethernet IP lost");
        }
        for (auto &s : sessions) if (s.client) close_session(s);
        return;
    }
    if (!server_active) {
        server.begin();
        server_active = true;
        Serial.printf("TCP %d ready\n", emu::PROTOCOL_PORT);
        diagnostics();
    }
    WiFiClient incoming = server.available();
    if (incoming) {
        incoming.setTimeout(50);
        incoming.setNoDelay(true);
        bool assigned = false;
        for (auto &s : sessions) {
            if (!s.client || !s.client.connected()) {
                close_session(s);
                s.client = incoming; s.last_activity = now;
                assigned = true; break;
            }
        }
        if (!assigned) incoming.stop(); // bounded concurrency
    }
    for (auto &s : sessions) {
        if (!s.client) continue;
        if (!s.client.connected() && !s.client.available()) { close_session(s); continue; }
        if (now - s.last_activity > IDLE_MS) { close_session(s); continue; }
        if (s.waiting) {
            if (int32_t(now - s.reply_at) >= 0) {
                if (!s.pending.empty())
                    s.client.write(reinterpret_cast<const uint8_t*>(s.pending.data()), s.pending.size());
                if (s.close_after) { close_session(s); continue; }
                s.waiting = false; s.pending.clear();
                s.last_activity = now;
            }
            continue;
        }
        // Total work budget: at most 64 bytes per session per loop.
        for (unsigned i = 0; i < 64 && s.client.available() && !s.waiting; ++i) {
            int v = s.client.read();
            if (v < 0) break;
            s.last_activity = now;
            if (s.length == emu::MAX_FRAME) {
                Serial.println("TCP oversized request closed");
                close_session(s);
                break;
            }
            s.data[s.length++] = char(v);
            if (v == '\r') {
                dispatch(s, std::string(s.data, s.length), now);
                s.length = 0;
            }
        }
    }
}
} // namespace

void setup() {
    Serial.begin(115200);
    delay(100);
    prefs.begin("espemu", false);
    String serial = prefs.getString("serial", "SIMESP0001");
    if (valid_serial(serial)) chamber.serial = serial.c_str();
    // Volatile model always starts STOPPED, even after WDT or brownout reset.
    chamber.running = false;
    faults = emu::Faults{};
    WiFi.mode(WIFI_OFF); // NO Wi-Fi fallback
    WiFi.onEvent(event_handler);
    Serial.printf("ESP-EMU %s boot, STOPPED, reset_reason=%d\n", VERSION, int(esp_reset_reason()));
    if (!ETH.begin(1, 16, 23, 18, ETH_PHY_LAN8720, ETH_CLOCK_GPIO0_IN))
        Serial.println("ETH.begin failed; inspect LAN8720 and GPIO0 oscillator");
    apply_network_config();
    // Core 2.x / IDF 4.4 task watchdog; the loop task feeds only itself.
    esp_err_t wdt = esp_task_wdt_init(8, true);
    if (wdt != ESP_OK && wdt != ESP_ERR_INVALID_STATE)
        Serial.printf("WDT init error: %d\n", int(wdt));
    if (esp_task_wdt_add(nullptr) != ESP_OK) Serial.println("WDT loop enrollment failed");
    last_tick = millis(); last_diag = last_tick;
    diagnostics();
}

void loop() {
    uint32_t now = millis();
    chamber.advance(double(uint32_t(now - last_tick)) / 1000.0, faults);
    last_tick = now;
    poll_console();
    tick_network(now);
    if (now - last_diag >= 60000) { diagnostics(); last_diag = now; }
    esp_task_wdt_reset();
    delay(1); // yield to IP stack; not a command-response sleep
}
