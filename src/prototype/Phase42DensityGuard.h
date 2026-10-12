#pragma once
#include "prototype/Phase36StreamingSpeedEngine.h"
#include "prototype/Phase39TimeMap.h"
#include <array>
#include <cstddef>
#include <vector>

namespace ts::prototype {

struct Phase42DensityDecision {
    bool safe=false;
    std::size_t inputSample=0;
    std::array<long long,3> maximumHop{};
    std::array<long long,3> maximumHopStep{};
    std::array<double,3> minimumWeight{};
    std::array<double,3> minimumLocalSpeed{};
    std::array<double,3> maximumLocalSpeed{};
    std::size_t candidatesTried=0;
};

// Research-only guard. It reads the proposed shared TimeMap and the live
// resolution frontiers; it does not alter phase, OLA, FIR, or published PCM.
Phase42DensityDecision chooseSafeDensitySwitch(
    const TimeMap& map,const Phase39Plan& plan,
    const Phase36StreamingSpeedEngine::Frontier& frontier,
    const std::vector<std::pair<std::size_t,bool>>& earlierChanges,
    bool currentHalf,bool targetHalf,std::size_t firstMutableOutput,
    std::size_t inputFrames);

} // namespace ts::prototype
