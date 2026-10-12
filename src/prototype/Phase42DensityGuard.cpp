#include "prototype/Phase42DensityGuard.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <numbers>
#include <chrono>
#include <ctime>

namespace ts::prototype {
namespace {
constexpr std::array<std::size_t,3> fft={8192,4096,1024};
constexpr std::array<std::size_t,3> hop={2048,1024,256};
constexpr double minimumHannSquaredWeight=0.15;
double threadCpuSeconds() {
    timespec stamp{};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID,&stamp)!=0) return 0;
    return double(stamp.tv_sec)+double(stamp.tv_nsec)*1e-9;
}

const std::vector<double>& hannSquared(std::size_t resolution) {
    static const auto tables=[] {
        std::array<std::vector<double>,3> result;
        for (std::size_t r=0;r<3;++r) {
            result[r].resize(fft[r]);
            for (std::size_t n=0;n<fft[r];++n) {
                const auto window=0.5*(1-std::cos(
                    2*std::numbers::pi*double(n)/double(fft[r])));
                result[r][n]=window*window;
            }
        }
        return result;
    }();
    return tables[resolution];
}

bool protectedInput(const TimeMap& map,std::size_t input) {
    const auto node=input/1024;
    for (const auto& event:map.events()) {
        const auto first=event.onsetFrame>2 ? event.onsetFrame-2 : 0;
        const auto last=std::max(event.endFrame,event.peakFrame)+5;
        if (node>=first && node<=last) return true;
    }
    return false;
}

bool probe(const TimeMap& map,const Phase39Plan& plan,
           const Phase36StreamingSpeedEngine::Frontier& frontier,
           std::size_t changeInput,bool currentHalf,bool targetHalf,
           Phase42DensityDecision& result,Phase42CandidateTiming* timing) {
    for (std::size_t r=0;r<3;++r) {
        const auto oldHop=hop[r]/(currentHalf ? 2 : 1);
        const auto newHop=hop[r]/(targetHalf ? 2 : 1);
        std::vector<long long> starts;
        starts.reserve(256);
        // Use the frame positions actually consumed by the DSP. Earlier
        // density switches can make a constant-hop reconstruction incorrect.
        const auto count=frontier.recentFrameCount[r];
        if (count==0) return false;
        const auto first=count>5 ? count-5 : 0;
        for (std::size_t i=first;i<count;++i) {
            starts.push_back(frontier.recentFrameOutput[r][i]);
            const auto framesBack=count-1-i;
            if (frontier.lastProcessedInput[r]<framesBack*oldHop) continue;
            const auto reconstructed=std::llround(map.outputPositionForInputSample(
                double(frontier.lastProcessedInput[r]-framesBack*oldHop)));
            const auto difference=std::llabs(reconstructed-starts.back());
            if (difference) ++result.reconstructedHistoryMismatches[r];
            result.reconstructedHistoryMaxDifference[r]=std::max(
                result.reconstructedHistoryMaxDifference[r],difference);
        }
        const auto sample=static_cast<long long>(frontier.actualWeightSample[r]);
        const auto& actualWindow=hannSquared(r);
        double predicted=0;
        for (std::size_t i=0;i<count;++i) {
            const auto delta=sample-frontier.recentFrameOutput[r][i];
            if (delta>=0 && delta<static_cast<long long>(fft[r]))
                predicted+=actualWindow[static_cast<std::size_t>(delta)];
        }
        result.actualWeight[r]=frontier.actualWeight[r];
        result.predictedActualWeight[r]=predicted;
        result.weightPredictionAbsoluteError[r]=std::abs(predicted-frontier.actualWeight[r]);
        if (result.weightPredictionAbsoluteError[r]>1e-4) return false;
        auto input=frontier.nextInput[r];
        auto previousInput=frontier.lastProcessedInput[r];
        auto previousStep=starts.size()>1 ? starts.back()-starts[starts.size()-2] : 0;
        const auto end=changeInput+fft[r]*4;
        long long firstChanged=-1;
        while (input<=end && starts.size()<4096) {
            const auto at=std::llround(map.outputPositionForInputSample(double(input)));
            const auto step=at-starts.back();
            if (step<=0 || step>=static_cast<long long>(fft[r])) return false;
            result.maximumHop[r]=std::max(result.maximumHop[r],step);
            if (previousStep>0) result.maximumHopStep[r]=std::max(
                result.maximumHopStep[r],std::llabs(step-previousStep));
            const auto speed=double(input-previousInput)/double(step);
            if (result.minimumLocalSpeed[r]==0 || speed<result.minimumLocalSpeed[r])
                result.minimumLocalSpeed[r]=speed;
            result.maximumLocalSpeed[r]=std::max(result.maximumLocalSpeed[r],speed);
            starts.push_back(at);
            if (firstChanged<0 && input>=changeInput) firstChanged=at;
            previousInput=input;
            previousStep=step;
            input+=input>=changeInput ? newHop : oldHop;
        }
        if (firstChanged<0 || starts.back()<firstChanged+static_cast<long long>(fft[r]))
            return false;
        double minimum=100;
        // A delayed switch must also be safe before it takes effect. This is
        // especially important when moving from normal to half density: the
        // old sparse frames may become unsafe as the synthesis hops grow.
        const auto firstSample=std::max<long long>(
            plan.appliedOutputSample,starts.front()+static_cast<long long>(fft[r]));
        if (firstSample>=firstChanged+static_cast<long long>(fft[r])) return false;
        const auto& window=hannSquared(r);
        const auto weightBegin=std::chrono::steady_clock::now();
        for (long long sample=firstSample;
             sample<firstChanged+static_cast<long long>(fft[r]);++sample) {
            double weight=0;
            const auto first=std::lower_bound(starts.begin(),starts.end(),
                                             sample-static_cast<long long>(fft[r])+1);
            const auto last=std::upper_bound(first,starts.end(),sample);
            for (auto it=first;it!=last;++it) {
                weight+=window[static_cast<std::size_t>(sample-*it)];
            }
            minimum=std::min(minimum,weight);
        }
        if (timing) timing->weightCheckSeconds[r]=std::chrono::duration<double>(
            std::chrono::steady_clock::now()-weightBegin).count();
        result.minimumWeight[r]=minimum;
        if (minimum<minimumHannSquaredWeight) return false;
    }
    return true;
}
} // namespace

Phase42DensityDecision chooseSafeDensitySwitch(
    const TimeMap& map,const Phase39Plan& plan,
    const Phase36StreamingSpeedEngine::Frontier& frontier,
    const std::vector<std::pair<std::size_t,bool>>& earlierChanges,
    bool currentHalf,bool targetHalf,std::size_t firstMutableOutput,
    std::size_t inputFrames,bool profile) {
    const auto guardBegin=std::chrono::steady_clock::now();
    const auto guardCpuBegin=profile ? threadCpuSeconds() : 0.0;
    Phase42DensityDecision decision;
    const auto finish=[&] {
        if (profile) {
            decision.guardWallSeconds=std::chrono::duration<double>(
                std::chrono::steady_clock::now()-guardBegin).count();
            decision.guardThreadCpuSeconds=threadCpuSeconds()-guardCpuBegin;
        }
    };
    if (currentHalf==targetHalf) {decision.safe=true;finish();return decision;}
    // Reducing frame density waits until the old, long output hops are over.
    // Increasing density must precede the first large output hop.
    auto candidate=(targetHalf ? plan.appliedFrame : plan.rampEndFrame)*1024;
    candidate=std::max(candidate,*std::max_element(
        frontier.nextInput.begin(),frontier.nextInput.end()));
    if (!earlierChanges.empty()) candidate=std::max(candidate,earlierChanges.back().first+1);
    candidate=(candidate+1023)/1024*1024;
    for (std::size_t attempt=0;attempt<128 && candidate<inputFrames;++attempt,candidate+=1024) {
        ++decision.candidatesTried;
        Phase42CandidateTiming timing;
        timing.inputSample=candidate;
        const auto candidateBegin=std::chrono::steady_clock::now();
        const auto candidateCpuBegin=profile ? threadCpuSeconds() : 0.0;
        if (candidate<=*std::max_element(frontier.lastProcessedInput.begin(),
                                          frontier.lastProcessedInput.end()) ||
            std::llround(map.outputPositionForInputSample(double(candidate)))<=
                static_cast<long long>(firstMutableOutput) || protectedInput(map,candidate)) {
            if (profile) {
                timing.wallSeconds=std::chrono::duration<double>(
                    std::chrono::steady_clock::now()-candidateBegin).count();
                timing.threadCpuSeconds=threadCpuSeconds()-candidateCpuBegin;
                decision.candidateTimings.push_back(timing);
            }
            continue;
        }
        Phase42DensityDecision probeResult;
        timing.probed=true;
        const auto accepted=probe(map,plan,frontier,candidate,currentHalf,targetHalf,
            probeResult,profile ? &timing : nullptr);
        if (profile) {
            timing.accepted=accepted;
            timing.wallSeconds=std::chrono::duration<double>(
                std::chrono::steady_clock::now()-candidateBegin).count();
            timing.threadCpuSeconds=threadCpuSeconds()-candidateCpuBegin;
            decision.candidateTimings.push_back(timing);
        }
        if (!accepted) continue;
        probeResult.candidateTimings=std::move(decision.candidateTimings);
        decision=probeResult;
        decision.safe=true;
        decision.inputSample=candidate;
        decision.candidatesTried=attempt+1;
        finish();
        return decision;
    }
    finish();
    return decision;
}
} // namespace ts::prototype
