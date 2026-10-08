#pragma once
#include "dsp/TransientEventMap.h"
#include <cstddef>
#include <functional>
#include <vector>

namespace ts {
struct TransientAnchor {
    std::size_t frame = 0;
    double sampleOffset = 0;
    double absoluteInputSample = 0;
    double crestFactor = 0;
    bool confident = false;
};

struct AnchorLocatorConfig {
    double minimumCrestFactor = 20.0;
    double minimumPeakToRunnerUp = 1.0;
    bool requireInteriorPeak = false;
};

// Refines only isolated, sample-localized events. Ambiguous events retain
// the Phase 3.5 frame anchor (sampleOffset == 0).
class TransientAnchorLocator {
public:
    static std::vector<TransientAnchor> locate(
        const std::vector<std::vector<float>>& input,
        const std::vector<TransientEvent>& events, std::size_t analysisHop,
        AnchorLocatorConfig config = {});
    static std::vector<TransientAnchor> locate(
        std::size_t length, std::size_t channels,
        const std::function<float(std::size_t, std::size_t)>& sample,
        const std::vector<TransientEvent>& events, std::size_t analysisHop,
        AnchorLocatorConfig config = {});
};
}
