#include "prototype/Phase22BResponsiveMap.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace ts::prototype {
namespace {
double smooth(double value) {
    value=std::clamp(value,0.0,1.0);
    return value*value*(3.0-2.0*value);
}
}
PausedTransition buildPausedTransition(
    const Phase13TransientAnalysis& analysis,
    const TimeMap& half,const TimeMap& threeQuarter,
    std::uint32_t sampleRate,std::size_t requestedInputSample,
    long long publishedOutputSample,double transitionOutputMs) {
    if (!sampleRate || publishedOutputSample<0 ||
        !std::isfinite(transitionOutputMs) || transitionOutputMs<=0 ||
        half.starts().size()!=threeQuarter.starts().size())
        throw std::invalid_argument("Invalid Phase 22B transition");
    const auto duration=std::llround(transitionOutputMs*sampleRate/1000.0);
    if (duration<1) throw std::invalid_argument("Transition too short");
    const auto& old=half.starts();
    const auto& target=threeQuarter.starts();
    const auto size=old.size();
    PausedTransition result;
    result.map=half;
    if (size<2) return result;
    std::vector<bool> protectedFrame(size);
    for (const auto& event:analysis.events()) {
        const auto begin=event.onsetFrame>2 ? event.onsetFrame-2 : 0;
        const auto end=std::min(size-1,std::max(event.endFrame,event.peakFrame)+5);
        for (auto i=begin;i<=end;++i) protectedFrame[i]=true;
    }
    auto candidate=std::max(
        std::min(size-1,requestedInputSample/1024+
            static_cast<std::size_t>(requestedInputSample%1024!=0)),
        static_cast<std::size_t>(
            std::lower_bound(old.begin(),old.end(),publishedOutputSample)-old.begin()));
    if (candidate>=size-1) return result;
    auto output=old;
    long long activeOutput=0;
    bool firstChange=false,completed=false;
    for (auto i=candidate;i+1<size;++i) {
        const auto oldHop=old[i+1]-old[i];
        const auto targetHop=target[i+1]-target[i];
        long long hop=oldHop;
        if (activeOutput>=duration) {
            if (!completed) { result.completionFrame=i; completed=true; }
            hop=targetHop;
        } else if (protectedFrame[i] || protectedFrame[i+1]) {
            // The entire protected interval keeps its original 0.50 hop.
            ++result.pausedIntervals;
        } else {
            const auto weight=smooth(double(activeOutput)/double(duration));
            hop=std::llround((1.0-weight)*oldHop+weight*targetHop);
            activeOutput+=hop;
        }
        if (hop<=0) throw std::runtime_error("Phase 22B produced non-positive hop");
        if (hop!=oldHop && !firstChange) {
            result.firstChangedFrame=i;
            firstChange=true;
        }
        if (!completed && (protectedFrame[i] || protectedFrame[i+1]) &&
            hop!=oldHop)
            ++result.protectedIntervalsChanged;
        output[i+1]=output[i]+hop;
    }
    if (!firstChange) return result;
    result.outcome=completed ? PausedTransition::Outcome::Completed
                             : PausedTransition::Outcome::Partial;
    if (!completed) result.completionFrame=size-1;
    result.map=TimeMap(1024,std::move(output),analysis.events());
    return result;
}
}
