#include "leonardo_core.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

namespace leonardo {
namespace {
const uint8_t SEP = 0xB6;

struct Request {
    uint32_t code;
    const char* args[4];
    uint8_t nargs;
    char bytes[MAX_REQUEST + 1];
};

bool parse(const uint8_t* frame, size_t size, Request& req) {
    if (!frame || size < 8 || size > MAX_REQUEST || frame[size - 1] != '\r')
        return false;
    const size_t data_len = size - 1;
    for (size_t i = 0; i < data_len; ++i) {
        uint8_t c = frame[i];
        if (c != SEP && (c < 0x20 || c > 0x7E)) return false;
        req.bytes[i] = static_cast<char>(c);
    }
    req.bytes[data_len] = 0;
    char* fields[6] = {};
    uint8_t count = 0;
    fields[count++] = req.bytes;
    for (size_t i = 0; i < data_len; ++i) {
        if (static_cast<uint8_t>(req.bytes[i]) == SEP) {
            if (count >= 6 || i == 0 || i == data_len - 1) return false;
            req.bytes[i] = 0;
            fields[count++] = req.bytes + i + 1;
        }
    }
    if (count < 2 || strlen(fields[0]) != 5 || strcmp(fields[1], "1"))
        return false;
    for (uint8_t i = 0; i < count; ++i)
        if (!*fields[i]) return false;
    uint32_t code = 0;
    for (uint8_t i = 0; i < 5; ++i) {
        if (fields[0][i] < '0' || fields[0][i] > '9') return false;
        code = code * 10 + static_cast<uint8_t>(fields[0][i] - '0');
    }
    req.code = code;
    req.nargs = count - 2;
    for (uint8_t i = 0; i < req.nargs; ++i) req.args[i] = fields[i + 2];
    return true;
}

size_t reply(uint8_t* out, size_t cap, bool success, const char* value) {
    if (!out || !cap) return 0;
    size_t len = value ? strlen(value) : 0;
    size_t total = 1 + (value ? 1 + len : 0) + 1;
    if (total > cap) return 0;
    out[0] = success ? '1' : '0';
    if (value) {
        out[1] = SEP;
        memcpy(out + 2, value, len);
    }
    out[total - 1] = '\r';
    return total;
}
size_t ok(uint8_t* out, size_t cap) { return reply(out, cap, true, 0); }
size_t value(uint8_t* out, size_t cap, const char* val) { return reply(out, cap, true, val); }
size_t error(uint8_t* out, size_t cap, const char* val) { return reply(out, cap, false, val); }

bool single(const Request& r, const char* index = "1") {
    return r.nargs == 1 && !strcmp(r.args[0], index);
}
bool without_args(const Request& r) { return r.nargs == 0; }

// strtod on AVR is finite precision (float). Reject malformed, NaN and Inf,
// and bound BEFORE scaling. Quantize to 0.01 C/0.01 C per minute.
bool number_centi(const char* p, int32_t& result) {
    if (!p || !*p) return false;
    bool digit = false;
    for (const char* s = p; *s; ++s) {
        char c = *s;
        if (c >= '0' && c <= '9') digit = true;
        else if (c != '-' && c != '+' && c != '.' && c != 'e' && c != 'E')
            return false;
    }
    if (!digit) return false;
    char* end = 0;
    double n = strtod(p, &end);
    if (end == p || *end || !(n >= -10000.0 && n <= 10000.0))
        return false; // inequality also rejects NaN / infinities
    const double scaled = n * 100.0;
    result = static_cast<int32_t>(scaled >= 0 ? scaled + 0.5 : scaled - 0.5);
    return true;
}

void format_centi(int32_t centi, char* out, size_t cap) {
    // AVR libc printf omits float formatting by default.
    long magnitude = static_cast<long>(centi < 0 ? -centi : centi);
    snprintf(out, cap, "%s%ld.%02ld0",
             centi < 0 ? "-" : "", magnitude / 100, magnitude % 100);
}
size_t number_reply(uint8_t* out, size_t cap, int32_t n) {
    char text[24];
    format_centi(n, text, sizeof(text));
    return value(out, cap, text);
}

bool boolean_arg(const Request& req, uint8_t& output, bool& state) {
    if (req.nargs != 2) return false;
    if (!strcmp(req.args[0], "1")) output = 1;
    else if (!strcmp(req.args[0], "7")) output = 7;
    else if (!strcmp(req.args[0], "8")) output = 8;
    else return false;
    if (!strcmp(req.args[1], "0")) state = false;
    else if (!strcmp(req.args[1], "1")) state = true;
    else return false;
    return true;
}
} // namespace

void Chamber::reset_thermal_accumulator() {
    fractional_movement = 0;
    previous_direction = 0;
}
void Chamber::advance(uint32_t elapsed_ms, const Faults& faults) {
    if (!elapsed_ms || faults.freeze_temperature) return;
    // Limit leap after long network outages; elapsed is monotonic uint32_t.
    if (elapsed_ms > 60000UL) elapsed_ms = 60000UL;
    if (!running) { reset_thermal_accumulator(); return; }
    const bool runaway = faults.runaway_heat || faults.runaway_cool;
    int8_t direction = runaway ? (faults.runaway_heat ? 1 : -1)
                               : (actual_centi < target_centi ? 1 :
                                  (actual_centi > target_centi ? -1 : 0));
    if (!direction) { reset_thermal_accumulator(); return; }
    if (direction != previous_direction) fractional_movement = 0;
    previous_direction = direction;
    uint16_t rate = runaway ? 1500 :
        (direction > 0 ? heating_centi_min : cooling_centi_min);
    const uint8_t speed = runaway ? 1 : thermal_speed;
    const uint32_t scaled = static_cast<uint32_t>(rate) *
                            elapsed_ms * speed + fractional_movement;
    const uint32_t step = scaled / 60000UL;
    fractional_movement = scaled % 60000UL;
    if (!step) return;
    int32_t destination = runaway ? (direction > 0 ? 20000L : -6000L)
                                   : target_centi;
    if (direction > 0) {
        const int32_t remaining = destination - actual_centi;
        actual_centi += static_cast<int32_t>(step > static_cast<uint32_t>(remaining)
                                            ? remaining : step);
    } else {
        const int32_t remaining = actual_centi - destination;
        actual_centi -= static_cast<int32_t>(step > static_cast<uint32_t>(remaining)
                                            ? remaining : step);
    }
    if (actual_centi == destination) reset_thermal_accumulator();
}

bool is_stop_frame(const uint8_t* frame, size_t size) {
    static const uint8_t pattern[] = {
        '1','4','0','0','1',0xB6,'1',0xB6,'1',0xB6,'0','\r'
    };
    return frame && size == sizeof(pattern) && !memcmp(frame, pattern, sizeof(pattern));
}

size_t handle_frame(const uint8_t* frame, size_t size, Chamber& chamber,
                    const Faults& faults, uint8_t* out, size_t cap) {
    Request req{};
    if (!parse(frame, size, req)) return error(out, cap, "MALFORMED");
    int32_t num = 0;
    uint8_t output = 0;
    bool state = false;
    switch (req.code) {
        case 99997:
            if (req.nargs != 1) return error(out, cap, "ARG");
            if (!strcmp(req.args[0], "1")) return value(out, cap, "VT4011-EMULATOR");
            if (!strcmp(req.args[0], "2")) return value(out, cap, "2026");
            if (!strcmp(req.args[0], "3")) return value(out, cap, chamber.serial);
            return error(out, cap, "INDEX");
        case 10012: // Provisional until real SimServ status trace is available.
            if (!without_args(req)) return error(out, cap, "ARG");
            return value(out, cap, faults.alarm ? "ALARM" :
                         (chamber.running ? "1" : "0"));
        case 11018: if (!without_args(req)) return error(out, cap, "ARG");
                    return value(out, cap, "1");
        case 11026: if (!single(req)) return error(out, cap, "INDEX");
                    return value(out, cap, "Temperature");
        case 11023: if (!single(req)) return error(out, cap, "INDEX");
                    return value(out, cap, "C");
        case 11007: if (!single(req)) return error(out, cap, "INDEX");
                    return number_reply(out, cap, -4000);
        case 11009: if (!single(req)) return error(out, cap, "INDEX");
                    return number_reply(out, cap, 18000);
        case 11002: if (!single(req)) return error(out, cap, "INDEX");
                    return number_reply(out, cap, chamber.target_centi);
        case 11004:
            if (!single(req)) return error(out, cap, "INDEX");
            if (faults.invalid_sensor) return error(out, cap, "SENSOR_UNAVAILABLE");
            return number_reply(out, cap, chamber.actual_centi);
        case 11001:
            if (req.nargs != 2 || strcmp(req.args[0], "1") ||
                !number_centi(req.args[1], num) || num < -4000 || num > 18000)
                return error(out, cap, "RANGE");
            chamber.target_centi = num;
            chamber.reset_thermal_accumulator();
            return ok(out, cap);
        case 14007: if (!without_args(req)) return error(out, cap, "ARG");
                    return value(out, cap, "8");
        case 14010:
            if (single(req)) return value(out, cap, "Running");
            if (single(req, "7")) return value(out, cap, "Compressed air");
            if (single(req, "8")) return value(out, cap, "Dryer");
            return error(out, cap, "INDEX");
        case 14003:
            if (single(req)) return value(out, cap, chamber.running ? "1" : "0");
            if (single(req, "7")) return value(out, cap, chamber.compressed_air ? "1" : "0");
            if (single(req, "8")) return value(out, cap, chamber.dryer ? "1" : "0");
            return error(out, cap, "INDEX");
        case 14001:
            if (!boolean_arg(req, output, state)) return error(out, cap, "ARG");
            if (output == 7) chamber.compressed_air = state;
            else if (output == 8) chamber.dryer = state;
            else if (!(!state && faults.sticky_stop)) {
                chamber.running = state;
                chamber.reset_thermal_accumulator();
            }
            return ok(out, cap);
        case 11066: if (!single(req)) return error(out, cap, "INDEX");
                    return number_reply(out, cap, chamber.heating_centi_min);
        case 11070: if (!single(req)) return error(out, cap, "INDEX");
                    return number_reply(out, cap, chamber.cooling_centi_min);
        case 11068:
        case 11072:
            if (req.nargs != 2 || strcmp(req.args[0], "1") ||
                !number_centi(req.args[1], num) || num < 1 ||
                num > (req.code == 11068 ? 500 : 350))
                return error(out, cap, "RANGE");
            if (req.code == 11068) chamber.heating_centi_min = static_cast<uint16_t>(num);
            else chamber.cooling_centi_min = static_cast<uint16_t>(num);
            return ok(out, cap);
        default: return error(out, cap, "UNSUPPORTED");
    }
}
} // namespace leonardo
