#pragma once
#include "prototype/Phase22VariableTimeMap.h"
#include <cstddef>
#include <cstdint>
#include <vector>

namespace ts::prototype {

enum class PlaybackSpeed : std::uint8_t { Half, ThreeQuarter };
enum class BidirectionalOutcome : std::uint8_t {
    Applied, Stale, AlreadyTarget, TransitionBusy, NoSafeInterval, Truncated
};
struct BidirectionalRequest {
    std::uint64_t generation=0;
    PlaybackSpeed target=PlaybackSpeed::Half;
    std::size_t requestedInputSample=0;
    long long protectedOutputSample=0;
    double transitionOutputMs=50.0;
};
struct BidirectionalPlan {
    BidirectionalOutcome outcome=BidirectionalOutcome::NoSafeInterval;
    std::uint64_t generation=0;
    PlaybackSpeed from=PlaybackSpeed::Half,target=PlaybackSpeed::Half;
    std::size_t requestedFrame=0,appliedFrame=0,rampEndFrame=0;
    long long appliedOutputSample=0,completionOutputSample=0;
    std::size_t protectedEventsSkipped=0;
    bool applied() const noexcept { return outcome==BidirectionalOutcome::Applied; }
};

// Independent Phase 26 study. Phase 22's one-way planner and its fixed maps
// remain unchanged; each accepted request edits only the unprotected suffix.
class Phase26BidirectionalTimeMap {
public:
    Phase26BidirectionalTimeMap(const Phase13TransientAnalysis& analysis,
        std::uint32_t sampleRate,PlaybackSpeed initial);
    const TimeMap& current() const noexcept { return current_; }
    const TimeMap& fixed(PlaybackSpeed speed) const noexcept;
    PlaybackSpeed tailSpeed() const noexcept { return tailSpeed_; }
    const std::vector<BidirectionalPlan>& history() const noexcept { return history_; }
    BidirectionalPlan submit(const BidirectionalRequest& request);
    bool monotonic() const noexcept;
    bool rampTouchesProtectedEvent(const BidirectionalPlan& plan) const noexcept;
    std::array<HopRange,3> measureHops() const;
private:
    std::size_t protectedEndAt(std::size_t frame) const noexcept;
    TimeMap half_,threeQuarter_,current_;
    std::vector<TransientEvent> events_;
    std::uint32_t sampleRate_;
    PlaybackSpeed tailSpeed_;
    std::uint64_t lastGeneration_=0;
    long long lastProtectedOutput_=0;
    long long previousCompletionOutput_=-1;
    std::vector<BidirectionalPlan> history_;
};
}
