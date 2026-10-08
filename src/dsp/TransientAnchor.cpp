#include "dsp/TransientAnchor.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace ts {
std::vector<TransientAnchor> TransientAnchorLocator::locate(
    const std::vector<std::vector<float>>& input,
    const std::vector<TransientEvent>& events, std::size_t analysisHop,
    AnchorLocatorConfig config) {
    if (input.empty() || analysisHop == 0) throw std::invalid_argument("Invalid anchor input");
    if (!std::isfinite(config.minimumCrestFactor) || config.minimumCrestFactor <= 0 ||
        !std::isfinite(config.minimumPeakToRunnerUp) || config.minimumPeakToRunnerUp < 1)
        throw std::invalid_argument("Invalid anchor confidence configuration");
    const auto length = input.front().size();
    for (const auto& channel : input)
        if (channel.size() != length) throw std::invalid_argument("Unequal anchor channels");
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
        for (auto sample = lo; sample < hi; ++sample) {
            double energy = 0;
            for (const auto& channel : input)
                energy += double(channel[sample]) * channel[sample];
            totalEnergy += energy;
            if (energy > peakEnergy) { peakEnergy = energy; peakSample = sample; }
        }
        if (peakEnergy > 0 && totalEnergy > 0) {
            anchor.crestFactor = std::sqrt(peakEnergy / (totalEnergy / (hi - lo)));
            double runnerUp = 0;
            for (auto sample = lo; sample < hi; ++sample) {
                if (sample + 4 >= peakSample && sample <= peakSample + 4) continue;
                double energy = 0;
                for (const auto& channel : input)
                    energy += double(channel[sample]) * channel[sample];
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
