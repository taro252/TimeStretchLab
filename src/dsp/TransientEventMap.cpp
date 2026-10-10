#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <utility>

namespace ts {
std::vector<TransientEvent> TransientEventMap::consolidateEvents(
    const std::vector<TransientFrame>& frames, std::size_t activeFrameCount,
    EventMapConfig config) {
    const auto active = std::min(activeFrameCount, frames.size());
    std::vector<TransientEvent> events;
    for (std::size_t i = 1; i < active; ++i) {
        const auto& frame = frames[i];
        if (frame.spectralFlux <= frame.threshold || frame.strength < 0.25f ||
            frame.logEnergy <= frame.previousLogEnergy * 1.02) continue;
        if (events.empty()) {
            events.push_back({i, i, i, i, frame.strength});
            continue;
        }
        auto& event = events.back();
        const auto gap = i - event.endFrame;
        const bool nearby = gap <= static_cast<std::size_t>(config.minimumDistanceFrames);
        const bool decayingAftershock = gap <= static_cast<std::size_t>(config.decayMergeFrames) &&
            frame.logEnergy < frames[event.peakFrame].logEnergy * 0.2;
        if (!nearby && !decayingAftershock) {
            events.push_back({i, i, i, i, frame.strength});
            continue;
        }
        event.endFrame = i;
        if (frame.spectralFlux > frames[event.peakFrame].spectralFlux) event.peakFrame = i;
        event.strength = std::max(event.strength, frame.strength);
    }
    return events;
}
TransientEventMap::TransientEventMap(const std::vector<TransientFrame>& frames,
                                   std::size_t activeFrameCount, int analysisHop,
                                   double globalRatio, EventMapConfig config)
    : TransientEventMap(frames, activeFrameCount, analysisHop, globalRatio,
                        config, consolidateEvents(frames, activeFrameCount, config)) {}
TransientEventMap::TransientEventMap(const std::vector<TransientFrame>& frames,
                                   std::size_t activeFrameCount, int analysisHop,
                                   double globalRatio,
                                   EventMapConfig config,
                                   std::vector<TransientEvent> consolidatedEvents)
    : events_(std::move(consolidatedEvents)),
      localRatios_(frames.size(), globalRatio), starts_(frames.size()),
      eventIds_(frames.size(), -1), eventStrengths_(frames.size()),
      regionWeights_(frames.size()), resetMask_(frames.size()),
      analysisHop_(analysisHop), globalRatio_(globalRatio),
      maximumCompensation_(config.maximumCompensation) {
    if (analysisHop <= 0 || !std::isfinite(globalRatio) || globalRatio <= 0 ||
        config.minimumDistanceFrames < 0 || config.decayMergeFrames < config.minimumDistanceFrames ||
        config.preRollFrames < 0 || config.postRollFrames < 0 ||
        !std::isfinite(config.maximumCompensation) || config.maximumCompensation < 1)
        throw std::invalid_argument("Invalid transient event map configuration");
    const auto active = std::min(activeFrameCount, frames.size());
    for (std::size_t id = 0; id < events_.size(); ++id) {
        auto& event = events_[id];
        if (config.preserveAttackRegion) {
            // Follow the flux slope back to its first clear rise, bounded to
            // four frames so preceding rhythmic events cannot be absorbed.
            const auto earliest = event.peakFrame > 4 ? event.peakFrame - 4 : 0;
            event.onsetFrame = event.peakFrame;
            while (event.onsetFrame > earliest) {
                const auto previous = event.onsetFrame - 1;
                if (frames[previous].spectralFlux <= frames[previous].threshold ||
                    frames[previous].spectralFlux < frames[event.peakFrame].spectralFlux * 0.25)
                    break;
                event.onsetFrame = previous;
            }
            // Use the local energy crest plus falling flux. A one-frame
            // impulse ends quickly; a noise burst with early decay persists.
            const auto latest = std::min(active - 1, event.peakFrame + 6);
            double crest = frames[event.peakFrame].logEnergy;
            for (auto i = event.peakFrame; i <= std::min(latest, event.peakFrame + 2); ++i)
                crest = std::max(crest, frames[i].logEnergy);
            event.attackEndFrame = event.peakFrame;
            for (auto i = event.peakFrame + 1; i <= latest; ++i) {
                if (frames[i].spectralFlux < frames[event.peakFrame].spectralFlux * 0.2 &&
                    frames[i].logEnergy < crest * 0.1 &&
                    frames[i].logEnergy <= frames[i].previousLogEnergy * 1.02)
                    break;
                event.attackEndFrame = i;
            }
        }
        resetMask_[event.peakFrame] = true;
        for (std::size_t i = event.onsetFrame; i <= event.endFrame; ++i) {
            eventIds_[i] = static_cast<int>(id);
            eventStrengths_[i] = event.strength;
        }
        // Raised-cosine shoulder has continuous slope at the edges. The
        // central peak uses an unstretched analysis hop.
        const auto left = event.onsetFrame > static_cast<std::size_t>(config.preRollFrames)
            ? event.onsetFrame - config.preRollFrames : 0;
        const auto right = std::min(frames.size() - 1,
            (config.preserveAttackRegion ? event.attackEndFrame : event.peakFrame) + config.postRollFrames);
        for (std::size_t i = left; i <= right; ++i) {
            const double distance = !config.preserveAttackRegion
                ? (i < event.peakFrame
                    ? double(event.peakFrame - i) / std::max(1, config.preRollFrames + 1)
                    : double(i - event.peakFrame) / std::max(1, config.postRollFrames + 1))
                : (i < event.onsetFrame
                    ? double(event.onsetFrame - i) / std::max(1, config.preRollFrames + 1)
                    : (i <= event.attackEndFrame ? 0.0
                        : double(i - event.attackEndFrame) / std::max(1, config.postRollFrames + 1)));
            const double weight = distance < 1 ? 0.5 * (1 + std::cos(std::numbers::pi * distance)) : 0;
            regionWeights_[i] = std::max(regionWeights_[i], weight);
            if (weight > 0 && eventIds_[i] < 0) {
                eventIds_[i] = static_cast<int>(id);
                eventStrengths_[i] = event.strength;
            }
        }
    }
    anchorCorrections_.resize(events_.size());
    buildTimeline();
}
void TransientEventMap::refineAnchors(const std::vector<double>& inputSampleOffsets) {
    if (inputSampleOffsets.size() != events_.size())
        throw std::invalid_argument("One anchor correction is required per event");
    for (std::size_t i = 0; i < events_.size(); ++i) {
        if (!std::isfinite(inputSampleOffsets[i]) ||
            std::abs(inputSampleOffsets[i]) > 2.0 * analysisHop_)
            throw std::invalid_argument("Invalid sub-frame event offset");
        anchorCorrections_[i] = (globalRatio_ - 1.0) * inputSampleOffsets[i];
    }
    buildTimeline();
}
long long TransientEventMap::idealStartAt(std::size_t frame) const {
    double correction = 0;
    for (std::size_t i = 0; i < events_.size(); ++i)
        if (events_[i].peakFrame == frame) { correction = anchorCorrections_[i]; break; }
    return std::llround(frame * analysisHop_ * globalRatio_ + correction);
}
void TransientEventMap::buildTimeline() {
    std::fill(localRatios_.begin(), localRatios_.end(), globalRatio_);
    const auto intervals = starts_.empty() ? 0 : starts_.size() - 1;
    std::vector<std::size_t> anchors{0};
    for (const auto& event : events_)
        if (event.peakFrame > anchors.back() && event.peakFrame < intervals)
            anchors.push_back(event.peakFrame);
    if (intervals > anchors.back()) anchors.push_back(intervals);
    // Conserve duration between successive event peaks, not only across the
    // whole file. This keeps a click train's beat positions on the global grid.
    if (globalRatio_ > 1) for (std::size_t segment = 1; segment < anchors.size(); ++segment) {
        const auto first = anchors[segment - 1], last = anchors[segment];
        double totalWeight = 0;
        for (auto i = first; i < last; ++i) totalWeight += regionWeights_[i];
        const double count = last - first;
        const auto correctionAt = [&](std::size_t frame) {
            for (std::size_t i = 0; i < events_.size(); ++i)
                if (events_[i].peakFrame == frame) return anchorCorrections_[i];
            return 0.0;
        };
        const double firstCorrection = correctionAt(first);
        const double lastCorrection = correctionAt(last);
        // Keep the original Phase 3.5 arithmetic exactly when neither
        // endpoint has a sub-frame correction.
        if (totalWeight == 0 && firstCorrection == 0 && lastCorrection == 0) continue;
        const double segmentRatio = firstCorrection == 0 && lastCorrection == 0
            ? globalRatio_
            : globalRatio_ + (lastCorrection - firstCorrection) / (count * analysisHop_);
        if (totalWeight == 0 || segmentRatio <= 1.0) {
            for (auto i = first; i < last; ++i) localRatios_[i] = segmentRatio;
            continue;
        }
        const double maxBaseline = globalRatio_ * maximumCompensation_;
        const double maxDepth = (maxBaseline - segmentRatio) * count /
            (totalWeight * (maxBaseline - 1));
        const double depth = std::clamp(maxDepth, 0.0, 1.0);
        totalWeight *= depth;
        const double baseline = (count * segmentRatio - totalWeight) / (count - totalWeight);
        for (auto i = first; i < last; ++i)
            localRatios_[i] = baseline + (1 - baseline) * regionWeights_[i] * depth;
    }
    double position = 0;
    for (std::size_t i = 0; i < starts_.size(); ++i) {
        starts_[i] = std::llround(position);
        if (i < intervals) position += analysisHop_ * localRatios_[i];
    }
}
}
