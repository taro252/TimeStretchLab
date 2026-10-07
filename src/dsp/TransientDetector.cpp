#include "dsp/TransientDetector.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace ts {
TransientDetector::TransientDetector(std::size_t binCount, TransientConfig config)
    : binCount_(binCount), config_(config), previousLog_(binCount, 0.0f) {
    if (binCount < 3 || !std::isfinite(config.logGain) || config.logGain <= 0 ||
        !std::isfinite(config.sensitivity) || config.sensitivity < 0 ||
        !std::isfinite(config.minimumFlux) || config.minimumFlux <= 0 ||
        !std::isfinite(config.resetStrengthThreshold) ||
        config.resetStrengthThreshold < 0 || config.resetStrengthThreshold > 1 ||
        config.historyFrames < 1 || config.cooldownFrames < 0 || config.lookbackFrames < 0)
        throw std::invalid_argument("Invalid transient detector configuration");
}
void TransientDetector::reset() {
    std::fill(previousLog_.begin(), previousLog_.end(), 0.0f);
    frames_.clear();
    previousLogSum_ = 0;
    transientCount_ = 0;
}
void TransientDetector::pushMagnitudes(const float* magnitudes) {
    double positiveChange = 0, currentSum = 0;
    // Ignore DC and Nyquist: their large stationary level can obscure attacks.
    for (std::size_t k = 1; k + 1 < binCount_; ++k) {
        const double current = std::log1p(config_.logGain * std::max(0.0f, magnitudes[k]));
        positiveChange += std::max(0.0, current - previousLog_[k]);
        currentSum += current;
        previousLog_[k] = static_cast<float>(current);
    }
    frames_.push_back({positiveChange / (currentSum + 1e-8), currentSum, previousLogSum_,
                       0, 0, false, false});
    previousLogSum_ = currentSum;
}
double TransientDetector::median(std::vector<double>& values) const {
    if (values.empty()) return 0;
    std::sort(values.begin(), values.end());
    const auto middle = values.size() / 2;
    return values.size() & 1 ? values[middle] : 0.5 * (values[middle - 1] + values[middle]);
}
void TransientDetector::finalize(std::size_t activeFrameCount) {
    transientCount_ = 0;
    std::vector<double> history, deviations;
    history.reserve(config_.historyFrames);
    deviations.reserve(config_.historyFrames);
    long long lastDetected = -static_cast<long long>(config_.cooldownFrames) - 1;
    for (std::size_t frame = 0; frame < frames_.size(); ++frame) {
        history.clear();
        const auto start = frame > static_cast<std::size_t>(config_.historyFrames)
            ? frame - config_.historyFrames : 0;
        for (std::size_t j = start; j < frame; ++j) history.push_back(frames_[j].spectralFlux);
        const double baseline = median(history);
        deviations.clear();
        for (std::size_t j = start; j < frame; ++j)
            deviations.push_back(std::abs(frames_[j].spectralFlux - baseline));
        const double mad = median(deviations);
        const double threshold = std::max(double(config_.minimumFlux),
                                          baseline + config_.sensitivity * mad);
        auto& current = frames_[frame];
        current.threshold = threshold;
        current.strength = static_cast<float>(std::clamp(
            (current.spectralFlux - threshold) / threshold, 0.0, 1.0));
        const bool localMaximum = (frame == 0 || current.spectralFlux >= frames_[frame - 1].spectralFlux) &&
            (frame + 1 == frames_.size() || current.spectralFlux > frames_[frame + 1].spectralFlux);
        const bool cooldownFinished = static_cast<long long>(frame) - lastDetected > config_.cooldownFrames;
        // Frame zero already initializes the vocoder phase, so a reset there
        // is redundant and would count every non-silent file as an onset.
        const bool risingEnergy = current.logEnergy > current.previousLogEnergy * 1.02;
        // Frames whose analysis window extends beyond the real input can show
        // large leakage from the artificial zero padding at the file tail.
        if (frame > 0 && frame < activeFrameCount && localMaximum && cooldownFinished && risingEnergy &&
            current.strength >= config_.resetStrengthThreshold && current.spectralFlux > threshold) {
            current.detected = true;
            lastDetected = static_cast<long long>(frame);
            auto resetFrame = frame > static_cast<std::size_t>(config_.lookbackFrames)
                ? frame - config_.lookbackFrames : 0;
            // Do not move the reset into silence. The first non-silent frame
            // already initializes phase, and a reset before it cannot help.
            if (frames_[resetFrame].logEnergy < current.logEnergy * 0.05)
                resetFrame = frame;
            frames_[resetFrame].resetApplied = true;
            ++transientCount_;
        }
    }
}
}
