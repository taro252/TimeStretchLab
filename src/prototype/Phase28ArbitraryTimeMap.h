#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include "prototype/Phase22VariableTimeMap.h"
#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <vector>

namespace ts::prototype {

// Six decimal places are the persistent speed identity. The ratio is computed
// once as 1.0 / (micros / 1000000.0), matching the offline CLI's operation.
struct DecimalSpeed {
    std::uint32_t micros=0;
    static DecimalSpeed fromDouble(double value);
    double value() const noexcept { return static_cast<double>(micros)/1000000.0; }
    double timeRatio() const noexcept { return 1.0/value(); }
    bool valid() const noexcept { return micros>=500000 && micros<=1000000; }
    bool operator==(const DecimalSpeed&) const = default;
};

enum class ArbitraryOutcome { Applied, Duplicate, Busy, Stale, Invalid, NoSafeInterval, Truncated };
struct ArbitraryRequest {
    std::uint64_t generation=0;
    DecimalSpeed target;
    std::size_t requestedInputSample=0;
    long long publishedOutputSample=0;
    double transitionOutputMs=50.0;
};
struct ArbitraryPlan {
    ArbitraryOutcome outcome=ArbitraryOutcome::NoSafeInterval;
    std::size_t requestedFrame=0,appliedFrame=0,rampEndFrame=0;
    long long appliedOutputSample=0,completionOutputSample=0;
    std::size_t protectedEventsSkipped=0;
    bool applied() const noexcept { return outcome==ArbitraryOutcome::Applied; }
};

// Independent coordinate-only prototype. No phase, OLA, FIR or playback state.
class Phase28ArbitraryTimeMap {
public:
    Phase28ArbitraryTimeMap(const Phase13TransientAnalysis& analysis,
                            std::uint32_t sampleRate,DecimalSpeed initial);
    // The shared ownership lease remains valid even when the cache evicts it.
    std::shared_ptr<const TimeMap> fixed(DecimalSpeed speed);
    const TimeMap& current() const noexcept { return current_; }
    const std::vector<ArbitraryPlan>& history() const noexcept { return history_; }
    ArbitraryPlan submit(const ArbitraryRequest& request);
    bool monotonic() const noexcept;
    bool touchesProtected(const ArbitraryPlan& plan) const noexcept;
    std::array<HopRange,3> measureHops() const;
    std::size_t fixedMapBytes() const noexcept;
private:
    std::size_t protectedEndAt(std::size_t frame) const noexcept;
    Phase13TransientAnalysis analysis_;
    std::map<std::uint32_t,std::shared_ptr<const TimeMap>> fixed_;
    TimeMap current_;
    std::vector<TransientEvent> events_;
    std::uint32_t sampleRate_;
    DecimalSpeed tail_;
    std::uint64_t lastGeneration_=0;
    long long lastPublished_=0,completionOutput_=-1;
    std::vector<ArbitraryPlan> history_;
};
}
