#include "emulator_protocol.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <string>
using namespace emu;

static std::string cmd(std::string code, std::string args = "") {
    return code + "\xB6" "1" + (args.empty() ? "" : std::string("\xB6") + args) + "\r";
}
int main() {
    Chamber m;
    Faults faults;
    auto call = [&](const std::string &s) { return handle_frame(s, m, faults); };
    assert(call(cmd("99997", "1")) == "1\xB6" "VT4011-EMULATOR\r");
    assert(call(cmd("99997", "3")) == "1\xB6" "SIMESP0001\r");
    assert(call(cmd("14003", "1")) == "1\xB6" "0\r");
    assert(call(cmd("14001", "1\xB6" "1")) == "1\r");
    assert(call(cmd("14003", "1")) == "1\xB6" "1\r");
    assert(call(cmd("11001", "1\xB6" "25.5")) == "1\r");
    assert(call(cmd("11002", "1")) == "1\xB6" "25.500\r");
    m.advance(60, faults); assert(std::abs(m.actual - 25.0) < 1e-8);
    m.advance(60, faults); assert(std::abs(m.actual - 25.5) < 1e-8);
    assert(call(cmd("11068", "1\xB6" "5")) == "1\r");
    assert(call(cmd("11072", "1\xB6" "3.5")) == "1\r");
    assert(call(cmd("11066", "1")) == "1\xB6" "5.000\r");
    assert(call(cmd("11070", "1")) == "1\xB6" "3.500\r");
    assert(call(cmd("14001", "7\xB6" "1")) == "1\r");
    assert(call(cmd("14003", "7")) == "1\xB6" "1\r");
    assert(call(cmd("14001", "8\xB6" "1")) == "1\r");
    assert(call(cmd("14003", "8")) == "1\xB6" "1\r");
    assert(call(cmd("14001", "8\xB6" "0")) == "1\r");
    assert(call(cmd("14003", "8")) == "1\xB6" "0\r");
    assert(call(cmd("14001", "1\xB6" "0")) == "1\r");
    assert(call(cmd("14003", "1")) == "1\xB6" "0\r");
    assert(call(cmd("14001", "1\xB6" "1")) == "1\r");
    assert(call(cmd("14001", "1\xB6" "0")) == "1\r");
    assert(!m.running);
    assert(call(cmd("11001", "1\xB6" "nan")).rfind("0\xB6", 0) == 0);
    assert(call(cmd("11001", "1\xB6" "inf")).rfind("0\xB6", 0) == 0);
    assert(call(cmd("11001", "1\xB6" "999")).rfind("0\xB6", 0) == 0);
    assert(call(cmd("11001", "2\xB6" "25")).rfind("0\xB6", 0) == 0);
    assert(call(cmd("99998")).rfind("0\xB6", 0) == 0);
    assert(call("11004\xB6" "1\n").rfind("0\xB6", 0) == 0);
    assert(call(std::string(200, 'A') + "\r").rfind("0\xB6", 0) == 0);
    assert(call(cmd("14001", "1\xB6" "2")).rfind("0\xB6", 0) == 0);
    faults.sticky_stop = true;
    call(cmd("14001", "1\xB6" "1"));
    call(cmd("14001", "1\xB6" "0"));
    assert(m.running); // STOP readback deliberately remains RUNNING
    faults.sticky_stop = false;
    call(cmd("14001", "1\xB6" "0"));
    assert(!m.running);
    m.actual = 20; m.target = 100; m.running = true;
    faults.freeze_temperature = true; m.advance(100, faults); assert(m.actual == 20);
    faults.freeze_temperature = false; assert(!m.set_speed(0) && m.set_speed(10));
    m.advance(6, faults); assert(std::abs(m.actual - 25) < 1e-8);
    faults.invalid_sensor = true;
    assert(call(cmd("11004", "1")).rfind("0\xB6", 0) == 0);
    std::cout << "PASS: golden framing, rejects, thermal dynamics, STOP, fault flags\n";
}
