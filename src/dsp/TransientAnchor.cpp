#include "dsp/TransientAnchor.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace ts {
std::vector<TransientAnchor> TransientAnchorLocator::locate(
    const std::vector<std::vector<float>>& input,
    const std::vector<TransientEvent>& events, std::size_t analysisHop,
    AnchorLocatorConfig config) {
    if (input.empty()) throw std::invalid_argument("Invalid anchor input");
    const auto length = input.front().size();
    for (const auto& channel : input)
        if (channel.size() != length) throw std::invalid_argument("Unequal anchor channels");
    return locate(length, input.size(),
        [&](std::size_t channel, std::size_t position) { return input[channel][position]; },
        events, analysisHop, config);
}
std::vector<TransientAnchor> TransientAnchorLocator::locate(
    std::size_t length, std::size_t channels,
    const std::function<float(std::size_t, std::size_t)>& sample,
    const std::vector<TransientEvent>& events, std::size_t analysisHop,
    AnchorLocatorConfig config) {
    if (channels == 0 || analysisHop == 0) throw std::invalid_argument("Invalid anchor input");
    if (!std::isfinite(config.minimumCrestFactor) || config.minimumCrestFactor <= 0 ||
        !std::isfinite(config.minimumPeakToRunnerUp) || config.minimumPeakToRunnerUp < 1)
        throw std::invalid_argument("Invalid anchor confidence configuration");
    std::vector<TransientAnchor> anchors;
    anchors.reserve(events.size());
    for (const auto& event : events) {
        const auto center = event.peakFrame * analysisHop;
        TransientAnchor anchor{event.peakFrame, 0, static_cast<double>(center), 0, false};
        const auto lo = center > analysisHop ? center - analysisHop : 0;
        const auto hi = std::min(length, center + 2 * analysisHop);
        if (hi <= lo) { anchors.push_back(anchor); continue; }
        double totalEnergy = 0, peakEnergy = 0;
        std::size_t peakSample = lo;
        for (auto sampleIndex = lo; sampleIndex < hi; ++sampleIndex) {
            double energy = 0;
            for (std::size_t channel = 0; channel < channels; ++channel) {
                const auto value = sample(channel, sampleIndex);
                energy += double(value) * value;
            }
            totalEnergy += energy;
            if (energy > peakEnergy) { peakEnergy = energy; peakSample = sampleIndex; }
        }
        if (peakEnergy > 0 && totalEnergy > 0) {
            anchor.crestFactor = std::sqrt(peakEnergy / (totalEnergy / (hi - lo)));
            double runnerUp = 0;
            for (auto sampleIndex = lo; sampleIndex < hi; ++sampleIndex) {
                if (sampleIndex + 4 >= peakSample && sampleIndex <= peakSample + 4) continue;
                double energy = 0;
                for (std::size_t channel = 0; channel < channels; ++channel) {
                    const auto value = sample(channel, sampleIndex);
                    energy += double(value) * value;
                }
                runnerUp = std::max(runnerUp, energy);
            }
            const bool interior = peakSample > lo && peakSample + 1 < hi;
            if (anchor.crestFactor >= config.minimumCrestFactor &&
                peakEnergy >= config.minimumPeakToRunnerUp *
                    config.minimumPeakToRunnerUp * runnerUp &&
                (!config.requireInteriorPeak || interior)) {
                anchor.confident = true;
                anchor.sampleOffset = static_cast<double>(peakSample) - center;
                anchor.absoluteInputSample = static_cast<double>(peakSample);
            }
        }
        anchors.push_back(anchor);
    }
    return anchors;
}
}
