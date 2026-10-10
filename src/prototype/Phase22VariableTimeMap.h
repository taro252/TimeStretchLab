#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace ts::prototype {

// Research-only coordinate plan. No DSP, FIFO or playback state is owned here.
struct SpeedRequest {
    std::uint64_t generation = 0;
    std::size_t requestedInputSample = 0;
    long long publishedOutputSample = 0;
    double transitionOutputMs = 50.0;
};
struct HopRange {
    long long minimum = 0;
    long long maximum = 0;
    std::size_t nonPositive = 0;
    std::size_t outsideWindow = 0;
};
enum class PlanOutcome : std::uint8_t {
    Applied,
    NoSafeInterval,
    AlreadyActive
};
struct SpeedPlan {
    bool applied = false;
    PlanOutcome outcome = PlanOutcome::NoSafeInterval;
    std::uint64_t generation = 0;
    std::size_t requestedFrame = 0;
    std::size_t appliedFrame = 0;
    std::size_t rampEndFrame = 0;
    long long appliedOutputSample = 0;
    long long publishedOutputSample = 0;
    std::size_t deferredInputSamples = 0;
    std::size_t protectedEventsSkipped = 0;
    bool truncatedByEnd = false;
};

class VariableTimeMap {
public:
    VariableTimeMap(const Phase13TransientAnalysis& analysis, std::uint32_t sampleRate);
    const TimeMap& fixedHalf() const noexcept { return half_; }
    const TimeMap& fixedThreeQuarter() const noexcept { return threeQuarter_; }
    const TimeMap& current() const noexcept { return current_; }
    SpeedPlan submit(const SpeedRequest& request);
    std::array<HopRange,3> measureHops() const;
    bool monotonic() const noexcept;
    bool rampTouchesProtectedEvent(const SpeedPlan& plan) const noexcept;
    std::size_t frameCount() const noexcept { return current_.starts().size(); }
private:
    std::size_t protectedEndAt(std::size_t frame) const noexcept;
    TimeMap half_;
    TimeMap threeQuarter_;
    TimeMap current_;
    std::vector<TransientEvent> events_;
    std::uint32_t sampleRate_;
    std::uint64_t latestGeneration_ = 0;
    std::size_t plannedStart_ = 0;
    bool hasPlan_ = false;
    long long lastPublished_ = 0;
};
}
