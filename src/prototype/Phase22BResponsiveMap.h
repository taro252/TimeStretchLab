#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include "dsp/TimeMap.h"
#include "prototype/Phase22VariableTimeMap.h"
#include <cstddef>
#include <cstdint>
#include <vector>

namespace ts::prototype {

// Independent Phase 22B experiment. Protected intervals use an exact fixed
// speed hop while the 0.50 -> 0.75 transition is paused.
struct PausedTransition {
    enum class Outcome { Unapplied, Partial, Completed };
    Outcome outcome=Outcome::Unapplied;
    TimeMap map;
    std::size_t firstChangedFrame=0;
    std::size_t completionFrame=0;
    std::size_t pausedIntervals=0;
    std::size_t protectedIntervalsChanged=0;
};

PausedTransition buildPausedTransition(
    const Phase13TransientAnalysis& analysis,
    const TimeMap& half, const TimeMap& threeQuarter,
    std::uint32_t sampleRate,std::size_t requestedInputSample,
    long long publishedOutputSample,double transitionOutputMs);

}
