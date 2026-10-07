#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace ts {
TransientEventMap::TransientEventMap(const std::vector<TransientFrame>& frames,
                                   std::size_t activeFrameCount, int analysisHop,
                                   double globalRatio, EventMapConfig config)
    : localRatios_(frames.size(), globalRatio), starts_(frames.size()),
      eventIds_(frames.size(), -1), eventStrengths_(frames.size()),
      regionWeights_(frames.size()), resetMask_(frames.size()) {
    if (analysisHop <= 0 || !std::isfinite(globalRatio) || globalRatio <= 0 ||
        config.minimumDistanceFrames < 0 || config.decayMergeFrames < config.minimumDistanceFrames ||
        config.preRollFrames < 0 || config.postRollFrames < 0 ||
        !std::isfinite(config.maximumCompensation) || config.maximumCompensation < 1)
        throw std::invalid_argument("Invalid transient event map configuration");
    const auto active = std::min(activeFrameCount, frames.size());
    // Start an event at a significant flux rise. Nearby candidates, and weak
    // aftershocks following a strong attack, join the same physical event.
    for (std::size_t i = 1; i < active; ++i) {
        const auto& frame = frames[i];
        if (frame.spectralFlux <= frame.threshold || frame.strength < 0.25f ||
            frame.logEnergy <= frame.previousLogEnergy * 1.02) continue;
        if (events_.empty()) {
            events_.push_back({i, i, i, frame.strength});
            continue;
        }
        auto& event = events_.back();
        const auto gap = i - event.endFrame;
        const bool nearby = gap <= static_cast<std::size_t>(config.minimumDistanceFrames);
        const bool decayingAftershock = gap <= static_cast<std::size_t>(config.decayMergeFrames) &&
            frame.logEnergy < frames[event.peakFrame].logEnergy * 0.2;
        if (!nearby && !decayingAftershock) {
            events_.push_back({i, i, i, frame.strength});
            continue;
        }
        event.endFrame = i;
        if (frame.spectralFlux > frames[event.peakFrame].spectralFlux) event.peakFrame = i;
        event.strength = std::max(event.strength, frame.strength);
    }
    for (std::size_t id = 0; id < events_.size(); ++id) {
        const auto& event = events_[id];
        resetMask_[event.peakFrame] = true;
        for (std::size_t i = event.onsetFrame; i <= event.endFrame; ++i) {
            eventIds_[i] = static_cast<int>(id);
            eventStrengths_[i] = event.strength;
        }
        // Raised-cosine shoulder has continuous slope at the edges. The
        // central peak uses an unstretched analysis hop.
        const auto left = event.onsetFrame > static_cast<std::size_t>(config.preRollFrames)
            ? event.onsetFrame - config.preRollFrames : 0;
        const auto right = std::min(frames.size() - 1, event.peakFrame + config.postRollFrames);
        for (std::size_t i = left; i <= right; ++i) {
            const double distance = i < event.peakFrame
                ? double(event.peakFrame - i) / std::max(1, config.preRollFrames + 1)
                : double(i - event.peakFrame) / std::max(1, config.postRollFrames + 1);
            const double weight = distance < 1 ? 0.5 * (1 + std::cos(std::numbers::pi * distance)) : 0;
            regionWeights_[i] = std::max(regionWeights_[i], weight);
            if (weight > 0 && eventIds_[i] < 0) {
                eventIds_[i] = static_cast<int>(id);
                eventStrengths_[i] = event.strength;
            }
        }
    }
    const auto intervals = frames.empty() ? 0 : frames.size() - 1;
    std::vector<std::size_t> anchors{0};
    for (const auto& event : events_)
        if (event.peakFrame > anchors.back() && event.peakFrame < intervals)
            anchors.push_back(event.peakFrame);
    if (intervals > anchors.back()) anchors.push_back(intervals);
    // Conserve duration between successive event peaks, not only across the
    // whole file. This keeps a click train's beat positions on the global grid.
    if (globalRatio > 1) for (std::size_t segment = 1; segment < anchors.size(); ++segment) {
        const auto first = anchors[segment - 1], last = anchors[segment];
        double totalWeight = 0;
        for (auto i = first; i < last; ++i) totalWeight += regionWeights_[i];
        if (totalWeight == 0) continue;
        const double count = last - first;
        const double maxBaseline = globalRatio * config.maximumCompensation;
        const double maxDepth = (maxBaseline - globalRatio) * count /
            (totalWeight * (maxBaseline - 1));
        const double depth = std::clamp(maxDepth, 0.0, 1.0);
        totalWeight *= depth;
        const double baseline = (count * globalRatio - totalWeight) / (count - totalWeight);
        for (auto i = first; i < last; ++i)
            localRatios_[i] = baseline + (1 - baseline) * regionWeights_[i] * depth;
    }
    double position = 0;
    for (std::size_t i = 0; i < frames.size(); ++i) {
        starts_[i] = std::llround(position);
        if (i < intervals) position += analysisHop * localRatios_[i];
    }
}
}
