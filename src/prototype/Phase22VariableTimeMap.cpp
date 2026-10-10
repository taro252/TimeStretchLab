#include "prototype/Phase22VariableTimeMap.h"
#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace ts::prototype {
namespace {
TimeMap makeFixed(const Phase13TransientAnalysis& analysis,double ratio) {
    constexpr int hop=1024;
    TransientEventMap map(analysis.detectorFrames(),analysis.activeFrameCount(),
                          hop,ratio,EventMapConfig{},analysis.events());
    std::vector<double> offsets;
    offsets.reserve(analysis.anchors().size());
    for (const auto& anchor:analysis.anchors()) offsets.push_back(anchor.sampleOffset);
    map.refineAnchors(offsets);
    return TimeMap(hop,map.starts(),map.events());
}
double smooth(double t) {
    t=std::clamp(t,0.0,1.0);
    return t*t*(3.0-2.0*t);
}
}
VariableTimeMap::VariableTimeMap(const Phase13TransientAnalysis& analysis,
    std::uint32_t sampleRate)
    : half_(makeFixed(analysis,2.0)),
      threeQuarter_(makeFixed(analysis,4.0/3.0)),
      current_(half_),events_(analysis.events()),sampleRate_(sampleRate) {
    if (sampleRate==0 || half_.starts().size()<2)
        throw std::invalid_argument("Phase 22 requires nonempty analyzed input");
}
std::size_t VariableTimeMap::protectedEndAt(std::size_t frame) const noexcept {
    const auto limit=frameCount()-1;
    for (const auto& event:events_) {
        const auto begin=event.onsetFrame>2 ? event.onsetFrame-2 : 0;
        const auto end=std::min(limit,std::max(event.endFrame,event.peakFrame)+5);
        if (frame>=begin && frame<=end) return end;
    }
    return std::numeric_limits<std::size_t>::max();
}
SpeedPlan VariableTimeMap::submit(const SpeedRequest& request) {
    if (request.generation<=latestGeneration_ || request.publishedOutputSample<lastPublished_ ||
        request.publishedOutputSample<0 || !std::isfinite(request.transitionOutputMs) ||
        request.transitionOutputMs<=0 || request.transitionOutputMs>1000)
        throw std::invalid_argument("Invalid or stale Phase 22 speed request");
    const auto duration=std::llround(request.transitionOutputMs*sampleRate_/1000.0);
    if (duration<1) throw std::invalid_argument("Transition duration too short");
    latestGeneration_=request.generation;
    lastPublished_=request.publishedOutputSample;
    SpeedPlan result;
    result.generation=request.generation;
    result.publishedOutputSample=request.publishedOutputSample;
    const auto& previous=current_.starts();
    const auto firstUnpublished=static_cast<std::size_t>(
        std::lower_bound(previous.begin(),previous.end(),request.publishedOutputSample)-previous.begin());
    // A pending, unpublished request is superseded. Rebuild only its unpublished
    // suffix from the original 0.50 map, anchored to the last published frame.
    if (hasPlan_ && plannedStart_>=firstUnpublished) {
        auto reset=previous;
        const auto& baseline=half_.starts();
        const auto origin=std::min(firstUnpublished,reset.size()-1);
        for (auto i=origin+1;i<reset.size();++i)
            reset[i]=reset[origin]+baseline[i]-baseline[origin];
        current_=TimeMap(1024,std::move(reset),events_);
        hasPlan_=false;
    } else if (hasPlan_) {
        // The previous change has already entered the published range. It
        // cannot be rolled back; repeated 0.75 requests are idempotent.
        result.outcome=PlanOutcome::AlreadyActive;
        return result;
    }
    const auto& before=current_.starts();
    const auto requested=std::min(frameCount()-1,
        request.requestedInputSample/1024+
        static_cast<std::size_t>(request.requestedInputSample%1024!=0));
    result.requestedFrame=requested;
    auto candidate=std::max(requested,static_cast<std::size_t>(
        std::lower_bound(before.begin(),before.end(),request.publishedOutputSample)-before.begin()));
    if (candidate>=frameCount()-1) return result;
    // Avoid modifying an event or crossing its attack/decay protection range.
    // Defer to the first interval that can hold the entire output-time ramp.
    const auto& targetStarts=threeQuarter_.starts();
    while (candidate<frameCount()-1) {
        auto end=candidate;
        long long minimumElapsed=0;
        while (end+1<frameCount() && minimumElapsed<duration) {
            // Blending can make the ramp span more input frames than the
            // current 0.50 map predicts. Bound it using the smaller of both
            // candidate hops and one sample of rounding allowance.
            minimumElapsed+=std::max(1LL,std::min(
                before[end+1]-before[end],
                targetStarts[end+1]-targetStarts[end])-1);
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
    if (candidate>=frameCount()-1) return result;
    const auto target=threeQuarter_.starts();
    auto output=before;
    const auto start=output[candidate];
    std::size_t rampEnd=frameCount()-1;
    for (auto i=candidate;i+1<frameCount();++i) {
        const auto elapsed=output[i]-start;
        const auto weight=smooth(double(elapsed)/double(duration));
        const auto oldHop=before[i+1]-before[i];
        const auto targetHop=target[i+1]-target[i];
        const auto hop=std::llround((1.0-weight)*oldHop+weight*targetHop);
        if (hop<=0) throw std::runtime_error("Non-monotonic Phase 22 hop");
        output[i+1]=output[i]+hop;
        if (elapsed>=duration) { rampEnd=i; break; }
    }
    if (rampEnd<frameCount()-1) {
        for (auto i=rampEnd+1;i<frameCount();++i)
            output[i]=output[rampEnd]+target[i]-target[rampEnd];
    } else result.truncatedByEnd=true;
    current_=TimeMap(1024,std::move(output),events_);
    plannedStart_=candidate;
    hasPlan_=true;
    result.applied=true;
    result.outcome=PlanOutcome::Applied;
    result.appliedFrame=candidate;
    result.rampEndFrame=rampEnd;
    result.appliedOutputSample=start;
    result.deferredInputSamples=candidate*1024-request.requestedInputSample;
    return result;
}
bool VariableTimeMap::monotonic() const noexcept {
    const auto& starts=current_.starts();
    for (std::size_t i=1;i<starts.size();++i)
        if (starts[i]<=starts[i-1]) return false;
    return true;
}
bool VariableTimeMap::rampTouchesProtectedEvent(const SpeedPlan& plan) const noexcept {
    if (!plan.applied) return false;
    for (auto i=plan.appliedFrame;i<=plan.rampEndFrame;++i)
        if (protectedEndAt(i)!=std::numeric_limits<std::size_t>::max()) return true;
    return false;
}
std::array<HopRange,3> VariableTimeMap::measureHops() const {
    constexpr std::array<int,3> fft{8192,4096,1024};
    constexpr std::array<int,3> hop{2048,1024,256};
    std::array<HopRange,3> ranges{};
    const auto lastInput=(frameCount()-2)*1024;
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
