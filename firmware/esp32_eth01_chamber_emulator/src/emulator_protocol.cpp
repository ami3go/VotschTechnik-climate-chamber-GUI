#include "emulator_protocol.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cerrno>
#include <cctype>

namespace emu {
namespace {
constexpr char SEP = static_cast<char>(0xB6);
std::string ok(const std::string &value) { return std::string("1") + SEP + value + "\r"; }
std::string ok() { return "1\r"; }
std::string error(const char *code) { return std::string("0") + SEP + code + "\r"; }
std::string format(double value) {
    char buffer[40];
    std::snprintf(buffer, sizeof(buffer), "%.3f", value);
    return buffer;
}
bool number(const std::string &text, double &value) {
    if (text.empty()) return false;
    for (unsigned char c : text) {
        if (!((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E'))
            return false;
    }
    char *end = nullptr;
    errno = 0;
    value = std::strtod(text.c_str(), &end);
    return end != text.c_str() && *end == '\0' && errno != ERANGE && std::isfinite(value);
}
bool index(const Request &r, size_t count, const char *expected = "1") {
    return r.args.size() == count && r.args[0] == expected;
}
} // namespace

bool Chamber::set_temperature(double value) {
    if (!std::isfinite(value) || value < min_temp || value > max_temp) return false;
    target = value;
    return true;
}
bool Chamber::set_gradient(bool up, double value) {
    if (!std::isfinite(value) || value < 0.01 || value > (up ? 5.0 : 3.5)) return false;
    if (up) heating = value; else cooling = value;
    return true;
}
void Chamber::set_mode(ThermalMode value) {
    mode = value;
    velocity_c_per_min = 0;
    speed = value == ThermalMode::Accelerated ? 10.0 : 1.0;
}
bool Chamber::set_speed(double factor) {
    if (!std::isfinite(factor) || factor < 0.1 || factor > 100.0) return false;
    speed = factor;
    return true;
}
void Chamber::advance(double dt, const Faults &faults) {
    if (!std::isfinite(dt) || dt <= 0 || dt > 3600 || faults.freeze_temperature) return;
    if (running && (faults.runaway_heat || faults.runaway_cool)) {
        const double runaway = faults.runaway_heat ? 15.0 : -15.0;
        actual = std::max(min_temp - 20.0, std::min(max_temp + 20.0,
                          actual + runaway * dt / 60.0));
    } else {
        double destination = target;
        double rate = actual < target ? heating : cooling;
        double scale = speed;
        if (!running) {
            velocity_c_per_min = 0.0;
            if (!passive_relaxation) return;
            destination = ambient;
            rate = 0.2; scale = 1.0;
        }
        const double sign = actual <= destination ? 1.0 : -1.0;
        double movement = rate * scale * dt / 60.0;
        if (mode == ThermalMode::Realistic && running) {
            const double alpha = 1.0 - std::exp(-dt / inertia_seconds);
            velocity_c_per_min += (sign * rate * scale - velocity_c_per_min) * alpha;
            movement = std::max(0.0, sign * velocity_c_per_min) * dt / 60.0;
        }
        if (actual < destination) actual = std::min(destination, actual + movement);
        else actual = std::max(destination, actual - movement);
        if (actual == destination) velocity_c_per_min = 0.0;
    }
    // Deterministic xorshift noise affects readback only, never true temperature.
    if (noise_amplitude > 0) {
        noise_seed ^= noise_seed << 13;
        noise_seed ^= noise_seed >> 17;
        noise_seed ^= noise_seed << 5;
        noise_offset = noise_amplitude *
            (2.0 * (double(noise_seed) / 4294967295.0) - 1.0);
    } else noise_offset = 0;
}

bool parse_request(const std::string &frame, Request &request) {
    request = Request{};
    if (frame.size() < 8 || frame.size() > MAX_FRAME || frame.back() != '\r') return false;
    std::vector<std::string> fields;
    size_t start = 0;
    for (size_t i = 0; i + 1 < frame.size(); ++i) {
        const unsigned char c = static_cast<unsigned char>(frame[i]);
        if (c == static_cast<unsigned char>(SEP)) {
            if (i == start) return false;
            fields.emplace_back(frame.substr(start, i - start));
            start = i + 1;
        } else if (c < 0x20 || c > 0x7E) return false;
    }
    if (start >= frame.size() - 1) return false;
    fields.emplace_back(frame.substr(start, frame.size() - 1 - start));
    if (fields.size() < 2 || fields.size() > 6 || fields[0].size() != 5 || fields[1] != "1")
        return false;
    for (char c : fields[0]) if (c < '0' || c > '9') return false;
    for (const auto &field : fields) if (field.empty()) return false;
    request.command = std::atoi(fields[0].c_str());
    request.args.assign(fields.begin() + 2, fields.end());
    return true;
}

std::string handle_frame(const std::string &frame, Chamber &m, const Faults &faults) {
    Request r;
    if (!parse_request(frame, r)) return error("MALFORMED");
    double value = 0;
    bool boolean = false;
    switch (r.command) {
        case 99997: // GET CHAMBER INFO: 1=model, 2=year, 3=serial
            if (r.args.size() != 1) return error("ARG");
            if (r.args[0] == "1") return ok(m.model);
            if (r.args[0] == "2") return ok(m.year);
            if (r.args[0] == "3") return ok(m.serial);
            return error("INDEX");
        case 10012: // provisional chamber status: active flag (requires physical capture)
            if (!r.args.empty()) return error("ARG");
            return ok(faults.alarm ? "ALARM" : (m.running ? "1" : "0"));
        case 11018: if (!r.args.empty()) return error("ARG"); return ok("1");
        case 11026: if (!index(r, 1)) return error("INDEX"); return ok("Temperature");
        case 11023: if (!index(r, 1)) return error("INDEX"); return ok("C");
        case 11007: if (!index(r, 1)) return error("INDEX"); return ok(format(m.min_temp));
        case 11009: if (!index(r, 1)) return error("INDEX"); return ok(format(m.max_temp));
        case 11002: if (!index(r, 1)) return error("INDEX"); return ok(format(m.target));
        case 11004:
            if (!index(r, 1)) return error("INDEX");
            if (faults.invalid_sensor) return error("SENSOR_UNAVAILABLE");
            return ok(format(m.actual + m.noise_offset));
        case 11001:
            if (!index(r, 2) || !number(r.args[1], value) || !m.set_temperature(value))
                return error("RANGE");
            return ok();
        case 14007: if (!r.args.empty()) return error("ARG"); return ok("8");
        case 14010:
            if (!index(r, 1) && !index(r, 1, "7") && !index(r, 1, "8")) return error("INDEX");
            return ok(r.args[0] == "1" ? "Running" : (r.args[0] == "7" ? "Compressed air" : "Dryer"));
        case 14003:
            if (r.args.size() != 1) return error("ARG");
            if (r.args[0] == "1") return ok(m.running ? "1" : "0");
            if (r.args[0] == "7") return ok(m.compressed_air ? "1" : "0");
            if (r.args[0] == "8") return ok(m.dryer ? "1" : "0");
            return error("INDEX");
        case 14001:
            // Same numeric opcode for START MANUAL_MODE (output 1) and
            // SET DIGITAL_OUT VALUE (aux outputs 7/8). Index disambiguates.
            if (r.args.size() != 2 ||
                (r.args[0] != "1" && r.args[0] != "7" && r.args[0] != "8") ||
                (r.args[1] != "0" && r.args[1] != "1")) return error("ARG");
            boolean = r.args[1] == "1";
            if (r.args[0] == "7") { m.compressed_air = boolean; return ok(); }
            if (r.args[0] == "8") { m.dryer = boolean; return ok(); }
            if (!boolean && faults.sticky_stop) return ok();
            m.running = boolean;
            return ok();
        case 11066: if (!index(r, 1)) return error("INDEX"); return ok(format(m.heating));
        case 11070: if (!index(r, 1)) return error("INDEX"); return ok(format(m.cooling));
        case 11068:
        case 11072:
            if (!index(r, 2) || !number(r.args[1], value) ||
                !m.set_gradient(r.command == 11068, value)) return error("RANGE");
            return ok();
        default: return error("UNSUPPORTED");
    }
}
} // namespace emu
