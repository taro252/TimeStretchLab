#pragma once
#include "prototype/Phase36StreamingSpeedEngine.h"
#include "prototype/Phase39TimeMap.h"
#include <array>
#include <cstddef>
#include <vector>

namespace ts::prototype {

struct Phase42CandidateTiming {
    std::size_t inputSample=0;
    bool accepted=false;
    bool probed=false;
    double wallSeconds=0,threadCpuSeconds=0;
    std::array<double,3> weightCheckSeconds{};
};
struct Phase42DensityDecision {
    bool safe=false;
    std::size_t inputSample=0;
    std::array<long long,3> maximumHop{};
    std::array<long long,3> maximumHopStep{};
    std::array<double,3> minimumWeight{};
    std::array<double,3> minimumLocalSpeed{};
    std::array<double,3> maximumLocalSpeed{};
    std::array<std::size_t,3> reconstructedHistoryMismatches{};
    std::array<long long,3> reconstructedHistoryMaxDifference{};
    std::array<double,3> actualWeight{},predictedActualWeight{},weightPredictionAbsoluteError{};
    std::size_t candidatesTried=0;
    double guardWallSeconds=0,guardThreadCpuSeconds=0;
    std::vector<Phase42CandidateTiming> candidateTimings;
};

// Research-only guard. It reads the proposed shared TimeMap and the live
// resolution frontiers; it does not alter phase, OLA, FIR, or published PCM.
Phase42DensityDecision chooseSafeDensitySwitch(
    const TimeMap& map,const Phase39Plan& plan,
    const Phase36StreamingSpeedEngine::Frontier& frontier,
    const std::vector<std::pair<std::size_t,bool>>& earlierChanges,
    bool currentHalf,bool targetHalf,std::size_t firstMutableOutput,
    std::size_t inputFrames,bool profile=false);

} // namespace ts::prototype
