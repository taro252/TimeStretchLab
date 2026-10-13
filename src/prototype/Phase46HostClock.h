#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace ts::prototype {
// SourceNode timestamps describe the HAL render timeline, not callback entry.
// A downstream SRC may invalidate sampleTime; hostTime remains mandatory here.
// This is a research continuity/budget check, not proof of hardware presentation.
class Phase46HostClock {
public:
    struct Evidence {
        std::int64_t startMinusHostNs=0,hostDeltaNs=0,hostProgressErrorNs=0;
        double sampleDelta=0,sampleProgressError=0;
        bool first=false,hostMissing=false,hostBackwards=false;
        bool cadenceError=false,sampleError=false,halWindowMiss=false;
        bool offsetOutlier=false;
    };
    Evidence observe(std::uint64_t epoch,std::uint64_t start,std::uint64_t end,
        bool hostValid,std::uint64_t host,bool sampleValid,double sample,
        std::uint64_t frames,double rate) noexcept {
        Evidence e;
        e.first=!hasPrevious_ || epoch!=epoch_;
        const auto tolerance=std::max(100000.0,2.0e9/rate);
        e.hostMissing=!hostValid || !host;
        if (!e.hostMissing) {
            e.startMinusHostNs=static_cast<std::int64_t>(start)-static_cast<std::int64_t>(host);
            // Calibrated research route is the local native speaker. Do not
            // silently accept a wrong timebase displaced by seconds.
            e.offsetOutlier=std::abs(static_cast<double>(e.startMinusHostNs))>1e9;
            // Ready by the HAL first-frame target, with 100us / two samples
            // research margin. Independently record execution > frame budget.
            e.halWindowMiss=static_cast<long double>(end)>
                static_cast<long double>(host)+tolerance;
            if (!e.first && previousHostValid_) {
                e.hostDeltaNs=static_cast<std::int64_t>(host)-static_cast<std::int64_t>(previousHost_);
                e.hostBackwards=e.hostDeltaNs<=0;
                e.hostProgressErrorNs=e.hostDeltaNs-
                    static_cast<std::int64_t>(std::llround(previousFrames_*1e9/rate));
                e.cadenceError=std::abs(static_cast<double>(e.hostProgressErrorNs))>tolerance;
            }
        }
        if (sampleValid) {
            if (!std::isfinite(sample)) e.sampleError=true;
            else if (!e.first && previousSampleValid_) {
                e.sampleDelta=sample-previousSample_;
                e.sampleProgressError=e.sampleDelta-static_cast<double>(previousFrames_);
                e.sampleError=e.sampleDelta<=0 || std::abs(e.sampleProgressError)>2.0;
            }
        }
        hasPrevious_=true;epoch_=epoch;previousFrames_=frames;
        previousHostValid_=!e.hostMissing;previousHost_=host;
        previousSampleValid_=sampleValid && std::isfinite(sample);previousSample_=sample;
        return e;
    }
private:
    bool hasPrevious_=false,previousHostValid_=false,previousSampleValid_=false;
    std::uint64_t epoch_=0,previousHost_=0,previousFrames_=0;
    double previousSample_=0;
};
}
