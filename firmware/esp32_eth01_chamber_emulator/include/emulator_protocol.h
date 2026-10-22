#pragma once
// Independent of Arduino so this exact command engine can be tested on a host.
#include <string>
#include <vector>
#include <cstddef>

namespace emu {
constexpr size_t MAX_FRAME = 128;
constexpr int PROTOCOL_PORT = 2049;

struct Faults {
    bool sticky_stop = false;
    bool freeze_temperature = false;
    bool invalid_sensor = false;
    bool alarm = false;
    bool drop_stop_reply = false;
    bool timeout_reply = false;
    bool partial_reply = false;
    bool reset_on_command = false;
    unsigned response_delay_ms = 0;
};

class Chamber {
public:
    std::string model = "VT4011-EMULATOR";
    std::string serial = "SIMESP0001";
    std::string year = "2026";
    double ambient = 23.0;
    double actual = 23.0;
    double target = 23.0;
    double heating = 2.0;
    double cooling = 2.0;
    double speed = 1.0;
    double min_temp = -40.0;
    double max_temp = 180.0;
    bool running = false;
    bool dryer = false;
    bool compressed_air = false;
    bool passive_relaxation = false;

    bool set_temperature(double temperature);
    bool set_gradient(bool up, double rate);
    bool set_speed(double factor);
    void advance(double elapsed_seconds, const Faults &faults);
};

struct Request {
    int command = 0;
    std::vector<std::string> args;
};

// Rejects invalid UTF-8/non-printing bytes, malformed delimiters, incorrect
// chamber index, extra args, LF terminators, and oversized request frames.
bool parse_request(const std::string &frame, Request &request);
std::string handle_frame(const std::string &frame, Chamber &model, const Faults &faults);
} // namespace emu
