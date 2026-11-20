#pragma once
// Fixed-buffer S!MPAC engine for ATmega32U4. Does not require Arduino or STL.
// The external Votsch Python driver remains the authoritative wire contract.
#include <stddef.h>
#include <stdint.h>

namespace leonardo {
static const size_t MAX_REQUEST = 80;
static const size_t MAX_RESPONSE = 64;
static const uint16_t CHAMBER_PORT = 2049;

inline bool dhcp_maintenance_due(bool has_dhcp, bool client_active,
                                 bool running, uint32_t elapsed_ms) {
    return has_dhcp && !client_active && !running && elapsed_ms >= 1000UL;
}

struct Faults {
    bool sticky_stop = false;
    bool invalid_sensor = false;
    bool freeze_temperature = false;
    bool alarm = false;
    bool runaway_heat = false;
    bool runaway_cool = false;
    bool drop_stop_reply = false;
    bool suppress_reply = false;
    bool partial_reply = false;
    bool reset_on_command = false;
    uint16_t delay_ms = 0;
};

struct Chamber {
    char serial[17] = "SIMLEO0001";
    // Centidegrees Celsius / centidegrees per minute, not floating-point I/O.
    int32_t actual_centi = 2300;
    int32_t target_centi = 2300;
    int32_t ambient_centi = 2300;
    uint16_t heating_centi_min = 200;
    uint16_t cooling_centi_min = 200;
    uint8_t thermal_speed = 1; // 1x Basic or 10x Accelerated
    bool running = false;
    // Outputs 2..8 are packed into bits 0..6. Output 1 is `running`.
    uint8_t auxiliary_outputs = 0;
    uint32_t fractional_movement = 0;
    int8_t previous_direction = 0;

    void advance(uint32_t elapsed_ms, const Faults& faults);
    void reset_thermal_accumulator();
};

// Returns the complete CR-terminated response byte count (zero only for
// invalid output capacity); never mutates input. No dynamic allocation.
size_t handle_frame(const uint8_t* frame, size_t size, Chamber& chamber,
                    const Faults& faults, uint8_t* response, size_t capacity);

// Used by transport to inject a lost STOP acknowledgement after execution.
bool is_stop_frame(const uint8_t* frame, size_t size);
} // namespace leonardo
