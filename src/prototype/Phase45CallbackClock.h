#pragma once
#include <cstdint>
#include <stdexcept>

namespace ts::prototype {
// Research clock: slot n is scheduled at n*Hs/fs and must complete before
// (n+1)*Hs/fs. Device elapsed time is independent of the delivered PCM cursor.
// Expired slots are NOT rendered in a catch-up loop and NOT labelled DSP underruns.
class Phase45CallbackClock {
public:
    Phase45CallbackClock(std::uint64_t frames, std::uint64_t rate,
                         double latePeriodLimit=1.0)
        : frames_(frames), rate_(rate), latePeriodLimit_(latePeriodLimit) {
        if (!frames || !rate || latePeriodLimit<=0)
            throw std::invalid_argument("Invalid callback clock");
    }
    std::int64_t scheduledNs(std::uint64_t slot) const {
        return static_cast<std::int64_t>((static_cast<long double>(slot)*frames_*1e9L)/rate_);
    }
    double periodNs() const { return double(frames_)*1e9/double(rate_); }
    struct Wake {
        std::uint64_t renderSlot=0, expiredSlots=0;
        std::int64_t lateNs=0;
        bool invalid=false;
    };
    Wake wake(std::uint64_t slot, std::int64_t elapsedNs) const {
        const auto late=elapsedNs-scheduledNs(slot);
        const auto expired=late>0 ? static_cast<std::uint64_t>(late/periodNs()) : 0;
        return {slot+expired,expired,late,late>periodNs()*latePeriodLimit_};
    }
    std::uint64_t deviceFrames(std::int64_t elapsedNs) const {
        return elapsedNs>0 ? static_cast<std::uint64_t>(
            (static_cast<long double>(elapsedNs)*rate_)/1e9L) : 0;
    }
private:
    std::uint64_t frames_,rate_;
    double latePeriodLimit_;
};
}
