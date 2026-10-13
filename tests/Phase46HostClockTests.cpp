#include "prototype/Phase46HostClock.h"
#include "prototype/Phase46Statistics.h"
#include <stdexcept>
#include <limits>
#include <iostream>
void check(bool value) { if (!value) throw std::runtime_error("Phase46 clock assertion"); }
int main() {
    ts::prototype::Phase46HostClock clock;
    auto e=clock.observe(1,9000000,9010000,true,10000000,true,0,480,48000);
    check(e.first && e.startMinusHostNs==-1000000 && !e.halWindowMiss);
    e=clock.observe(1,19000000,19010000,true,20000000,true,480,480,48000);
    check(!e.cadenceError && !e.sampleError && e.hostDeltaNs==10000000);
    e=clock.observe(1,29000000,29010000,false,0,false,0,480,48000);
    check(e.hostMissing && !e.sampleError);
    e=clock.observe(2,29000000,29010000,true,30000000,true,0,480,48000);
    check(e.first && !e.cadenceError); // New engine / route epoch.
    e=clock.observe(2,39000000,39010000,true,29900000,true,480,480,48000);
    check(e.hostBackwards && e.cadenceError);
    e=clock.observe(3,9000000,9010000,true,10000000,false,0,441,44100);
    e=clock.observe(3,19000000,19010000,true,20000000,false,0,441,44100);
    check(!e.sampleError && !e.cadenceError); // SRC: sample time legitimately invalid.
    e=clock.observe(4,20000000,22000000,true,10000000,true,
        std::numeric_limits<double>::quiet_NaN(),480,48000);
    check(e.sampleError && e.halWindowMiss);
    e=clock.observe(5,1000000,1001000,true,4000000000,false,0,480,48000);
    check(e.offsetOutlier); // Near-future values pass; implausible local-route timebase does not.
    const auto stats=ts::prototype::phase46LatencySummary({4,1,3,2});
    check(stats[0]==2.5 && stats[1]==4);
    std::cout<<"Phase46 host evidence and ordinary median PASS\n";
}
