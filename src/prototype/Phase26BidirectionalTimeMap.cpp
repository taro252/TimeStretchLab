#include "prototype/Phase26BidirectionalTimeMap.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace ts::prototype {
namespace {
double smooth(double t) {
    t=std::clamp(t,0.0,1.0);
    return t*t*(3.0-2.0*t);
}
}
Phase26BidirectionalTimeMap::Phase26BidirectionalTimeMap(
    const Phase13TransientAnalysis& analysis,std::uint32_t sampleRate,
    PlaybackSpeed initial)
    : half_(VariableTimeMap(analysis,sampleRate).fixedHalf()),
      threeQuarter_(VariableTimeMap(analysis,sampleRate).fixedThreeQuarter()),
      current_(initial==PlaybackSpeed::Half ? half_ : threeQuarter_),
      events_(analysis.events()),sampleRate_(sampleRate),tailSpeed_(initial) {
    if (sampleRate==0 || current_.starts().size()<2)
        throw std::invalid_argument("Phase 26 requires analyzed input");
    history_.reserve(2);
}
const TimeMap& Phase26BidirectionalTimeMap::fixed(PlaybackSpeed speed) const noexcept {
    return speed==PlaybackSpeed::Half ? half_ : threeQuarter_;
}
std::size_t Phase26BidirectionalTimeMap::protectedEndAt(std::size_t frame) const noexcept {
    const auto limit=current_.starts().size()-1;
    for (const auto& event:events_) {
        const auto begin=event.onsetFrame>2 ? event.onsetFrame-2 : 0;
        const auto end=std::min(limit,std::max(event.endFrame,event.peakFrame)+5);
        if (frame>=begin && frame<=end) return end;
    }
    return std::numeric_limits<std::size_t>::max();
}
BidirectionalPlan Phase26BidirectionalTimeMap::submit(const BidirectionalRequest& request) {
    BidirectionalPlan result;
    result.generation=request.generation;
    result.from=tailSpeed_;
    result.target=request.target;
    if (request.generation<=lastGeneration_ ||
        request.protectedOutputSample<lastProtectedOutput_ ||
        request.protectedOutputSample<0 || !std::isfinite(request.transitionOutputMs) ||
        request.transitionOutputMs<=0 || request.transitionOutputMs>1000) {
        result.outcome=BidirectionalOutcome::Stale;
        return result;
    }
    lastGeneration_=request.generation;
    lastProtectedOutput_=request.protectedOutputSample;
    if (request.target==tailSpeed_) {
        result.outcome=BidirectionalOutcome::AlreadyTarget;
        return result;
    }
    if (previousCompletionOutput_>=0 &&
        request.protectedOutputSample<previousCompletionOutput_) {
        result.outcome=BidirectionalOutcome::TransitionBusy;
        return result;
    }
    const auto& before=current_.starts();
    const auto& target=fixed(request.target).starts();
    const auto frameCount=before.size();
    const auto requested=std::min(frameCount-1,
        request.requestedInputSample/1024+
        static_cast<std::size_t>(request.requestedInputSample%1024!=0));
    result.requestedFrame=requested;
    auto candidate=std::max(requested,static_cast<std::size_t>(
        std::lower_bound(before.begin(),before.end(),request.protectedOutputSample)-before.begin()));
    const auto duration=std::llround(request.transitionOutputMs*sampleRate_/1000.0);
    if (duration<1 || candidate>=frameCount-1) return result;
    while (candidate<frameCount-1) {
        auto end=candidate;
        long long minimumElapsed=0;
        while (end+1<frameCount && minimumElapsed<duration) {
            minimumElapsed+=std::max(1LL,std::min(
                before[end+1]-before[end],target[end+1]-target[end])-1);
            ++end;
        }
        std::size_t conflictEnd=candidate;
        bool conflict=false;
        for (auto frame=candidate;frame<=end;++frame) {
            const auto protectedEnd=protectedEndAt(frame);
            if (protectedEnd!=std::numeric_limits<std::size_t>::max()) {
                conflict=true;
                conflictEnd=std::max(conflictEnd,protectedEnd);
            }
        }
        if (!conflict) break;
        ++result.protectedEventsSkipped;
        candidate=conflictEnd+1;
    }
    if (candidate>=frameCount-1) return result;
    auto output=before;
    const auto start=output[candidate];
    std::size_t rampEnd=frameCount-1;
    for (auto i=candidate;i+1<frameCount;++i) {
        const auto elapsed=output[i]-start;
        const auto weight=smooth(double(elapsed)/double(duration));
        const auto oldHop=before[i+1]-before[i];
        const auto targetHop=target[i+1]-target[i];
        const auto hop=std::llround((1.0-weight)*oldHop+weight*targetHop);
        if (hop<=0) throw std::runtime_error("Non-monotonic Phase 26 hop");
        output[i+1]=output[i]+hop;
        if (elapsed>=duration) { rampEnd=i; break; }
    }
    if (rampEnd==frameCount-1) {
        result.outcome=BidirectionalOutcome::Truncated;
        return result;
    }
    for (auto i=rampEnd+1;i<frameCount;++i)
        output[i]=output[rampEnd]+target[i]-target[rampEnd];
    current_=TimeMap(1024,std::move(output),events_);
    tailSpeed_=request.target;
    previousCompletionOutput_=current_.starts()[rampEnd];
    result.outcome=BidirectionalOutcome::Applied;
    result.appliedFrame=candidate;
    result.rampEndFrame=rampEnd;
    result.appliedOutputSample=start;
    result.completionOutputSample=previousCompletionOutput_;
    history_.push_back(result);
    return result;
}
bool Phase26BidirectionalTimeMap::monotonic() const noexcept {
    const auto& starts=current_.starts();
    for (std::size_t i=1;i<starts.size();++i)
        if (starts[i]<=starts[i-1]) return false;
    return true;
}
bool Phase26BidirectionalTimeMap::rampTouchesProtectedEvent(
    const BidirectionalPlan& plan) const noexcept {
    if (!plan.applied()) return false;
    for (auto i=plan.appliedFrame;i<=plan.rampEndFrame;++i)
        if (protectedEndAt(i)!=std::numeric_limits<std::size_t>::max()) return true;
    return false;
}
std::array<HopRange,3> Phase26BidirectionalTimeMap::measureHops() const {
    constexpr std::array<int,3> fft{8192,4096,1024};
    constexpr std::array<int,3> hop{2048,1024,256};
    std::array<HopRange,3> ranges{};
    const auto lastInput=(current_.starts().size()-2)*1024;
    for (std::size_t r=0;r<3;++r) {
        auto& range=ranges[r];
        range.minimum=std::numeric_limits<long long>::max();
        long long previous=0;
        bool first=true;
        for (std::size_t input=0;input<=lastInput;input+=hop[r]) {
            const auto at=std::llround(current_.outputPositionForInputSample(double(input)));
            if (!first) {
                const auto step=at-previous;
                range.minimum=std::min(range.minimum,step);
                range.maximum=std::max(range.maximum,step);
                if (step<=0) ++range.nonPositive;
                if (step>=fft[r]) ++range.outsideWindow;
            }
            first=false;
            previous=at;
        }
    }
    return ranges;
}
}
