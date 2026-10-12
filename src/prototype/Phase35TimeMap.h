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
struct Phase35Speed {
    std::uint32_t micros=0;
    static Phase35Speed fromDouble(double value);
    double value() const noexcept { return static_cast<double>(micros)/1000000.0; }
    double timeRatio() const noexcept { return 1.0/value(); }
    bool valid() const noexcept { return micros>=400000 && micros<=1000000; }
    bool operator==(const Phase35Speed&) const = default;
};

enum class Phase35Outcome { Applied, Duplicate, Busy, Stale, Invalid, NoSafeInterval, Truncated };
struct Phase35Request {
    std::uint64_t generation=0;
    Phase35Speed target;
    std::size_t requestedInputSample=0;
    long long publishedOutputSample=0;
    double transitionOutputMs=50.0;
};
struct Phase35Plan {
    Phase35Outcome outcome=Phase35Outcome::NoSafeInterval;
    std::size_t requestedFrame=0,appliedFrame=0,rampEndFrame=0;
    long long appliedOutputSample=0,completionOutputSample=0;
    std::size_t protectedEventsSkipped=0;
    bool applied() const noexcept { return outcome==Phase35Outcome::Applied; }
};

// Independent coordinate-only prototype. No phase, OLA, FIR or playback state.
class Phase35TimeMap {
public:
    Phase35TimeMap(const Phase13TransientAnalysis& analysis,
                            std::uint32_t sampleRate,Phase35Speed initial);
    // The shared ownership lease remains valid even when the cache evicts it.
    std::shared_ptr<const TimeMap> fixed(Phase35Speed speed);
    const TimeMap& current() const noexcept { return current_; }
    const std::vector<Phase35Plan>& history() const noexcept { return history_; }
    Phase35Plan submit(const Phase35Request& request);
    bool monotonic() const noexcept;
    bool touchesProtected(const Phase35Plan& plan) const noexcept;
    std::array<HopRange,3> measureHops() const;
    std::size_t fixedMapBytes() const noexcept;
private:
    std::size_t protectedEndAt(std::size_t frame) const noexcept;
    Phase13TransientAnalysis analysis_;
    std::map<std::uint32_t,std::shared_ptr<const TimeMap>> fixed_;
    TimeMap current_;
    std::vector<TransientEvent> events_;
    std::uint32_t sampleRate_;
    Phase35Speed tail_;
    std::uint64_t lastGeneration_=0;
    long long lastPublished_=0,completionOutput_=-1;
    std::vector<Phase35Plan> history_;
};
}
