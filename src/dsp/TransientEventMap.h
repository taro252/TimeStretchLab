#pragma once
#include "dsp/TransientDetector.h"
#include <cstddef>
#include <vector>

namespace ts {
struct TransientEvent {
    std::size_t onsetFrame = 0;
    std::size_t peakFrame = 0;
    std::size_t attackEndFrame = 0;
    std::size_t endFrame = 0;
    float strength = 0;
};

struct EventMapConfig {
    int minimumDistanceFrames = 4;
    int decayMergeFrames = 12;
    int preRollFrames = 2;
    int postRollFrames = 5;
    double maximumCompensation = 1.5;
    bool preserveAttackRegion = false;
};

// Offline event grouping and one shared, duration-conserving synthesis timeline.
class TransientEventMap {
public:
    // Event grouping depends only on input analysis, not playback speed.
    static std::vector<TransientEvent> consolidateEvents(
        const std::vector<TransientFrame>& frames, std::size_t activeFrameCount,
        EventMapConfig config = {});
    TransientEventMap(const std::vector<TransientFrame>& frames, std::size_t activeFrameCount,
                      int analysisHop, double globalRatio, EventMapConfig config = {});
    TransientEventMap(const std::vector<TransientFrame>& frames, std::size_t activeFrameCount,
                      int analysisHop, double globalRatio,
                      EventMapConfig config,
                      std::vector<TransientEvent> consolidatedEvents);
    const std::vector<TransientEvent>& events() const { return events_; }
    const std::vector<double>& localRatios() const { return localRatios_; }
    const std::vector<long long>& starts() const { return starts_; }
    int eventIdAt(std::size_t frame) const { return eventIds_[frame]; }
    float eventStrengthAt(std::size_t frame) const { return eventStrengths_[frame]; }
    bool isTransientRegion(std::size_t frame) const { return regionWeights_[frame] > 0; }
    bool resetAt(std::size_t frame) const { return resetMask_[frame]; }
    float resetStrengthAt(std::size_t frame) const { return eventStrengths_[frame]; }
    // Optional sub-frame corrections for isolated impulses, in input samples
    // relative to peakFrame * analysisHop. Used by optional precise anchoring.
    void refineAnchors(const std::vector<double>& inputSampleOffsets);
    long long idealStartAt(std::size_t frame) const;
private:
    void buildTimeline();
    std::vector<TransientEvent> events_;
    std::vector<double> localRatios_;
    std::vector<long long> starts_;
    std::vector<int> eventIds_;
    std::vector<float> eventStrengths_;
    std::vector<double> regionWeights_;
    std::vector<bool> resetMask_;
    std::vector<double> anchorCorrections_;
    int analysisHop_;
    double globalRatio_;
    double maximumCompensation_;
};
}
