#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include <cstddef>

namespace ts::prototype {
struct Phase37MapDiagnostics {
    std::size_t events=0;
    std::size_t protectedSegments=0;
    std::size_t capacityLimitedSegments=0;
    std::size_t denseFallbackSegments=0;
    double minimumLocalRatio=0;
    double maximumLocalRatio=0;
    long long maximumAnchorError=0;
    long long minimumMidHop=0;
    long long maximumMidHop=0;
};

// Research-only compression map. Mode A reproduces the frozen high-speed
// TransientEventMap. Mode B changes only synthesis timestamps; the events,
// resets, FFT, phase propagation, OLA and FIR processing stay the same.
TimeMap phase37Map(const Phase13TransientAnalysis& analysis,
                   std::size_t inputFrames,double timeRatio,bool protectAttacks,
                   Phase37MapDiagnostics* diagnostics=nullptr);
}
