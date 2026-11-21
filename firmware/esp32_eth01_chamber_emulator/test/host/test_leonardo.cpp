// Golden contract tests for the exact fixed-buffer AVR command engine, host-side.
#include "leonardo_core.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <string>
#include <vector>
using namespace leonardo;

static std::string req(const char* command, const char* arg1 = 0, const char* arg2 = 0) {
    std::string s(command);
    s.push_back(char(0xB6)); s += "1";
    if (arg1) { s.push_back(char(0xB6)); s += arg1; }
    if (arg2) { s.push_back(char(0xB6)); s += arg2; }
    s.push_back('\r');
    return s;
}
static std::string response(const std::string& r, Chamber& chamber, const Faults& faults) {
    uint8_t out[MAX_RESPONSE] = {};
    const size_t count = handle_frame(reinterpret_cast<const uint8_t*>(r.data()), r.size(),
                                      chamber, faults, out, sizeof(out));
    assert(count >= 2 && count <= MAX_RESPONSE && out[count-1] == '\r');
    return std::string(reinterpret_cast<char*>(out), count);
}
static std::string ok_value(const char* text) {
    return std::string("1") + char(0xB6) + text + "\r";
}
static void rejected(const std::string& s, Chamber& c, const Faults& f) {
    assert(response(s, c, f).at(0) == '0');
}

int main() {
    assert(dhcp_maintenance_due(true, false, false, 1000));
    assert(!dhcp_maintenance_due(true, true, false, 1000));
    assert(!dhcp_maintenance_due(true, false, true, 1000));
    assert(!dhcp_maintenance_due(true, false, false, 999));
    assert(!dhcp_maintenance_due(false, false, false, 1000));
    assert(!dhcp_maintenance_due(true, false, false, 59999, 60000));
    assert(dhcp_maintenance_due(true, false, false, 60000, 60000));
    assert(!dhcp_maintenance_due(true, true, false, 60000, 60000));
    assert(!dhcp_maintenance_due(true, false, true, 60000, 60000));
    Chamber c;
    Faults f;
    assert(response(req("99997", "1"),c,f) == ok_value("VT4011-EMULATOR"));
    assert(response(req("99997", "2"),c,f) == ok_value("2026"));
    assert(response(req("99997", "3"),c,f) == ok_value("SIMLEO0001"));
    assert(response(req("14003", "1"),c,f) == ok_value("0"));
    assert(response(req("14007"),c,f) == ok_value("8"));
    for (uint8_t output=1; output<=8; ++output) {
        const char number[] = {static_cast<char>('0' + output), 0};
        assert(response(req("14010", number),c,f).find("1\xB6") == 0);
        assert(response(req("14003", number),c,f) == ok_value("0"));
        if (output > 1) {
            assert(response(req("14001", number, "1"),c,f) == "1\r");
            assert(response(req("14003", number),c,f) == ok_value("1"));
            assert(response(req("14001", number, "0"),c,f) == "1\r");
        }
    }
    assert(response(req("11018"),c,f) == ok_value("1"));
    assert(response(req("11026", "1"),c,f) == ok_value("Temperature"));
    assert(response(req("11023", "1"),c,f) == ok_value("C"));
    assert(response(req("11007", "1"),c,f) == ok_value("-40.000"));
    assert(response(req("11009", "1"),c,f) == ok_value("180.000"));
    assert(response(req("11004", "1"),c,f) == ok_value("23.000"));
    assert(response(req("11002", "1"),c,f) == ok_value("23.000"));
    assert(response(req("10012"),c,f) == ok_value("0"));
    assert(response(req("11001", "1", "25.5"),c,f) == "1\r");
    assert(response(req("11002", "1"),c,f) == ok_value("25.500"));
    assert(response(req("11068", "1", "5.0"),c,f) == "1\r");
    assert(response(req("11072", "1", "3.5"),c,f) == "1\r");
    assert(response(req("11066", "1"),c,f) == ok_value("5.000"));
    assert(response(req("11070", "1"),c,f) == ok_value("3.500"));
    assert(response(req("14001", "1", "1"),c,f) == "1\r");
    assert(response(req("14003", "1"),c,f) == ok_value("1"));
    c.advance(60000, f);
    assert(response(req("11004", "1"),c,f) == ok_value("25.500"));
    c.target_centi = -2500;
    c.reset_thermal_accumulator();
    c.advance(60000, f); // cooling max 3.5 C/min
    assert(c.actual_centi == 2200);
    assert(response(req("14001", "1", "0"),c,f) == "1\r");
    assert(response(req("14003", "1"),c,f) == ok_value("0"));
    c.advance(60000, f); assert(c.actual_centi == 2200); // STOP freezes
    for (int i=0; i<3; ++i) {
        assert(response(req("14001", "1", "1"),c,f) == "1\r");
        assert(c.running);
        assert(response(req("14001", "1", "0"),c,f) == "1\r");
        assert(!c.running);
    }
    assert(response(req("14001", "7", "1"),c,f) == "1\r");
    assert(response(req("14003", "7"),c,f) == ok_value("1"));
    assert(response(req("14001", "8", "1"),c,f) == "1\r");
    assert(response(req("14003", "8"),c,f) == ok_value("1"));
    assert(response(req("14001", "8", "0"),c,f) == "1\r");
    assert(response(req("14003", "8"),c,f) == ok_value("0"));

    rejected(req("99999"),c,f);
    rejected(req("99997","4"),c,f);
    rejected(req("11001","2","24"),c,f);
    rejected(req("11001","1","181"),c,f);
    rejected(req("11001","1","NaN"),c,f);
    rejected(req("11001","1","inf"),c,f);
    rejected(req("11001","1","0.1\\r"),c,f);
    rejected(req("11068","1","5.01"),c,f);
    rejected(req("11072","1","3.51"),c,f);
    rejected(req("14001","1","2"),c,f);
    rejected(req("14003","0"),c,f);
    rejected(req("14003","9"),c,f);
    rejected(req("11001","1","--1"),c,f);
    rejected(req("11001","1","1e999"),c,f);
    rejected("11004\xB6" "1\n",c,f);
    rejected(std::string(MAX_REQUEST + 1, 'A')+"\r",c,f);
    rejected("11004\xB6" "2\xB6" "1\r",c,f);
    rejected("11004\xC2\xB6" "1\xB6" "1\r",c,f); // UTF-8 separator wrong
    rejected("11004\xB6" "1\xB6\r",c,f);
    rejected("11004\xB6" "1\xB6" "1\xB6" "2\xB6" "3\xB6" "4\xB6" "5\r",c,f);
    assert(!c.running); // invalid commands never start chamber

    assert(is_stop_frame(reinterpret_cast<const uint8_t*>(req("14001","1","0").data()),
                         req("14001","1","0").size()));
    f.sticky_stop=true;
    response(req("14001","1","1"),c,f);
    response(req("14001","1","0"),c,f);
    assert(c.running); // ACK + still running readback
    f.sticky_stop=false;
    response(req("14001","1","0"),c,f);
    assert(!c.running);
    f.invalid_sensor=true; rejected(req("11004","1"),c,f);
    f.invalid_sensor=false; f.alarm=true;
    assert(response(req("10012"),c,f) == ok_value("ALARM"));
    f.alarm=false;
    c.running=true; c.actual_centi=2300; c.target_centi=5000; c.reset_thermal_accumulator();
    f.freeze_temperature=true; c.advance(1000,f); assert(c.actual_centi==2300);
    f.freeze_temperature=false;
    c.thermal_speed=10; c.advance(60000,f); assert(c.actual_centi==5000);
    c.actual_centi=2300; c.reset_thermal_accumulator(); c.thermal_speed=1;
    f.runaway_heat=true; c.advance(60000,f); assert(c.actual_centi==3800);
    f.runaway_heat=false; f.runaway_cool=true;
    c.advance(60000,f); assert(c.actual_centi==2300);
    // 100 ms model steps must accumulate sub-centidegree remainders.
    f = Faults{}; c.actual_centi=2300; c.target_centi=2500;
    c.heating_centi_min=200; c.reset_thermal_accumulator();
    for(int i=0;i<600;++i) c.advance(100,f);
    assert(c.actual_centi==2500);
    // Long-run bounded parser/model liveness with periodic malformed frames.
    for(uint32_t i=0;i<100000UL;++i) {
        assert(response(req("11004","1"),c,f).find("1\xB6") == 0);
        if (!(i % 1000UL)) rejected("11004\xB6" "1\n",c,f);
        c.advance(10,f);
    }
    std::cout << "PASS Leonardo S!MPAC: frames, identity, gradients, start/stop, faults, tick/accumulator\n";
}
