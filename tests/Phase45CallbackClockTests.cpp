#include "prototype/Phase45CallbackClock.h"
#include <stdexcept>
#include <iostream>
void check(bool value) { if (!value) throw std::runtime_error("Callback clock assertion"); }
int main() {
    for (const auto frames:{64,128,256,512,1024}) {
        ts::prototype::Phase45CallbackClock clock(frames,48000);
        auto slot=std::uint64_t{1};
        const auto scheduled=clock.scheduledNs(slot);
        const auto normal=clock.wake(slot,scheduled+1000);
        check(!normal.invalid && normal.expiredSlots==0);
        const auto delayed=clock.wake(slot,scheduled+100000000);
        check(delayed.invalid && delayed.expiredSlots>0);
        slot=delayed.renderSlot+1;
        check(clock.scheduledNs(slot)>scheduled+100000000);
        check(clock.deviceFrames(scheduled+100000000)>static_cast<std::uint64_t>(frames));
        const auto next=clock.wake(slot,clock.scheduledNs(slot)+1000);
        check(!next.invalid && next.expiredSlots==0);
    }
    std::cout<<"normal and expired-slot clock tests PASS (deterministic clock)\n";
}
