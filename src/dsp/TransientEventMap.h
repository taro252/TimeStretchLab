#pragma once
#include "dsp/TransientDetector.h"
#include <cstddef>
#include <vector>

namespace ts {
struct TransientEvent {
    std::size_t onsetFrame = 0;
    std::size_t peakFrame = 0;
    std::size_t endFrame = 0;
    float strength = 0;
};

struct EventMapConfig {
    int minimumDistanceFrames = 4;
    int decayMergeFrames = 12;
    int preRollFrames = 2;
    int postRollFrames = 5;
    double maximumCompensation = 1.5;
};

// Offline event grouping and one shared, duration-conserving synthesis timeline.
class TransientEventMap {
public:
    TransientEventMap(const std::vector<TransientFrame>& frames, std::size_t activeFrameCount,
                      int analysisHop, double globalRatio, EventMapConfig config = {});
    const std::vector<TransientEvent>& events() const { return events_; }
    const std::vector<double>& localRatios() const { return localRatios_; }
    const std::vector<long long>& starts() const { return starts_; }
    int eventIdAt(std::size_t frame) const { return eventIds_[frame]; }
    float eventStrengthAt(std::size_t frame) const { return eventStrengths_[frame]; }
    bool isTransientRegion(std::size_t frame) const { return regionWeights_[frame] > 0; }
    bool resetAt(std::size_t frame) const { return resetMask_[frame]; }
private:
    std::vector<TransientEvent> events_;
    std::vector<double> localRatios_;
    std::vector<long long> starts_;
    std::vector<int> eventIds_;
    std::vector<float> eventStrengths_;
    std::vector<double> regionWeights_;
    std::vector<bool> resetMask_;
};
}
