#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include "prototype/Phase22VariableTimeMap.h"
#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <vector>
#include <functional>

namespace ts::prototype {

// Six decimal places are the persistent speed identity. The ratio is computed
// once as 1.0 / (micros / 1000000.0), matching the offline CLI's operation.
struct Phase39Speed {
    std::uint32_t micros=0;
    static Phase39Speed fromDouble(double value);
    double value() const noexcept { return static_cast<double>(micros)/1000000.0; }
    double timeRatio() const noexcept { return 1.0/value(); }
    bool valid() const noexcept { return micros>=400000 && micros<=2000000; }
    bool operator==(const Phase39Speed&) const = default;
};

enum class Phase39Outcome { Applied, Duplicate, Busy, Stale, Invalid, NoSafeInterval, Truncated };
// A preserves the Phase 39 behaviour. B starts in the first complete safe
// interval; C accumulates the ramp across safe intervals and holds protected
// hops at their previously committed values.
enum class Phase39Planning { A, B, C, C0, L2 }; // C0 retains the initial unguarded diagnostic.
struct Phase39Request {
    std::uint64_t generation=0;
    Phase39Speed target;
    std::size_t requestedInputSample=0;
    long long publishedOutputSample=0;
    double transitionOutputMs=50.0;
};
struct Phase39Plan {
    Phase39Outcome outcome=Phase39Outcome::NoSafeInterval;
    std::size_t requestedFrame=0,appliedFrame=0,rampEndFrame=0;
    long long appliedOutputSample=0,completionOutputSample=0;
    std::size_t protectedEventsSkipped=0;
    bool protectedEventsPaused=false;
    std::size_t firstMutableFrame=0, firstSafeFrame=0;
    std::size_t nextEventFrame=0, protectionEndFrame=0;
    std::size_t safeFramesUsed=0, heldFrames=0;
    bool applied() const noexcept { return outcome==Phase39Outcome::Applied; }
};

// Independent coordinate-only prototype. No phase, OLA, FIR or playback state.
class Phase39TimeMap {
public:
    Phase39TimeMap(const Phase13TransientAnalysis& analysis,
                            std::uint32_t sampleRate,Phase39Speed initial,
                            Phase39Planning planning=Phase39Planning::A);
    // Phase59 research: actual certified coordinate prefix, never a provisional
    // whole-file analysis. Factory must return the same certified node count.
    using CertifiedFixedFactory=std::function<TimeMap(Phase39Speed)>;
    Phase39TimeMap(TimeMap certifiedInitial,std::uint32_t sampleRate,
        Phase39Speed initial,Phase39Planning planning,CertifiedFixedFactory);
    // Phase59 normal-thread continuation: coordinates already contain all
    // committed ramps. Restore guards/history without submitting them again.
    void restoreCertifiedHistory(std::uint64_t generation,long long published,
        long long completion,const std::vector<Phase39Plan>& history);
    // The shared ownership lease remains valid even when the cache evicts it.
    std::shared_ptr<const TimeMap> fixed(Phase39Speed speed);
    const TimeMap& current() const noexcept { return current_; }
    const std::vector<Phase39Plan>& history() const noexcept { return history_; }
    Phase39Plan submit(const Phase39Request& request);
    // Research clone only. Identical coordinates/history/cache; no live state mutation.
    Phase39TimeMap researchWithPlanning(Phase39Planning mode) const {
        auto copy=*this;copy.planning_=mode;return copy;
    }
    bool monotonic() const noexcept;
    bool touchesProtected(const Phase39Plan& plan) const noexcept;
    std::array<HopRange,3> measureHops() const;
    std::size_t fixedMapBytes() const noexcept;
    // Read-only diagnostics; planning and its safety tests remain unchanged.
    bool diagnosticProtected(std::size_t frame) const noexcept {
        return frame<protectedEndByFrame_.size() && protectedEndByFrame_[frame]!=static_cast<std::size_t>(-1);
    }
    bool diagnosticSafeRun(std::size_t frame) const noexcept {
        return frame<safeRunEligible_.size() && safeRunEligible_[frame];
    }
private:
    void indexProtection();
    std::size_t protectedEndAt(std::size_t frame) const noexcept;
    Phase13TransientAnalysis analysis_;
    std::map<std::uint32_t,std::shared_ptr<const TimeMap>> fixed_;
    TimeMap current_;
    std::vector<TransientEvent> events_;
    std::vector<std::size_t> protectedEndByFrame_;
    std::vector<bool> safeRunEligible_;
    std::uint32_t sampleRate_;
    Phase39Speed tail_;
    std::uint64_t lastGeneration_=0;
    long long lastPublished_=0,completionOutput_=-1;
    std::vector<Phase39Plan> history_;
    Phase39Planning planning_;
    CertifiedFixedFactory certifiedFactory_;
};
}
