#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase37HighSpeedMap.h"
#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace ts::prototype {
namespace {
TimeMap makeFixed(const Phase13TransientAnalysis& analysis,double ratio) {
    if (ratio<1.0) return phase37Map(analysis,analysis.inputFrames(),ratio,true);
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
double validatedRatio(Phase39Speed speed) {
    if (!speed.valid())
        throw std::invalid_argument("Invalid initial speed");
    return speed.timeRatio();
}
}
Phase39Speed Phase39Speed::fromDouble(double speed) {
    if (!std::isfinite(speed) || speed<0.40 || speed>2.00 ||
        std::abs(speed*1000000.0-std::round(speed*1000000.0))>1e-7)
        throw std::invalid_argument("Speed must be a six-decimal value in [0.40, 2.00]");
    return {static_cast<std::uint32_t>(std::llround(speed*1000000.0))};
}
Phase39TimeMap::Phase39TimeMap(
    const Phase13TransientAnalysis& analysis,std::uint32_t rate,Phase39Speed initial,
    Phase39Planning planning)
    : analysis_(analysis),current_(makeFixed(analysis,validatedRatio(initial))),
      events_(analysis.events()),sampleRate_(rate),tail_(initial),planning_(planning) {
    if (rate==0 || current_.starts().size()<2)
        throw std::invalid_argument("Invalid Phase 39 initialization");
    const auto limit=current_.starts().size()-1;
    protectedEndByFrame_.assign(current_.starts().size(),
        std::numeric_limits<std::size_t>::max());
    for (const auto& event:events_) {
        const auto begin=event.onsetFrame>2 ? event.onsetFrame-2 : 0;
        const auto end=std::min(limit,std::max(event.endFrame,event.peakFrame)+5);
        for (auto i=begin;i<=end;++i) {
            auto& value=protectedEndByFrame_[i];
            // Keep the first matching event exactly as Phase 39's original
            // linear scan did; the following lookup is only an index.
            if (value==std::numeric_limits<std::size_t>::max()) value=end;
        }
    }
    safeRunEligible_.assign(current_.starts().size(),false);
    // A one-node gap before the next attack is numerically unprotected, but
    // changing one hop there can still affect an overlapping Low window.
    // C therefore uses only safe runs of at least four Mid intervals.
    for (std::size_t first=0;first<limit;) {
        if (protectedEndByFrame_[first]!=std::numeric_limits<std::size_t>::max()) {
            ++first;continue;
        }
        auto last=first;
        while (last<limit && protectedEndByFrame_[last]==
               std::numeric_limits<std::size_t>::max()) ++last;
        if (last-first>=4)
            std::fill(safeRunEligible_.begin()+first,
                      safeRunEligible_.begin()+last,true);
        first=last;
    }
    fixed_.emplace(initial.micros,std::make_shared<TimeMap>(current_));
}
std::shared_ptr<const TimeMap> Phase39TimeMap::fixed(Phase39Speed speed) {
    if (!speed.valid())
        throw std::invalid_argument("Invalid target speed");
    auto it=fixed_.find(speed.micros);
    if (it==fixed_.end()) {
        auto made=std::make_shared<TimeMap>(makeFixed(analysis_,speed.timeRatio()));
        it=fixed_.emplace(speed.micros,std::move(made)).first;
    }
    // A decimal speed may have a million possible values; keep the prototype's
    // coordinate cache bounded independently of the number of requests.
    if (fixed_.size()>5) {
        auto victim=fixed_.begin();
        if (victim==it) ++victim;
        fixed_.erase(victim);
    }
    return it->second;
}
std::size_t Phase39TimeMap::protectedEndAt(std::size_t frame) const noexcept {
    return frame<protectedEndByFrame_.size() ? protectedEndByFrame_[frame] :
        std::numeric_limits<std::size_t>::max();
}
Phase39Plan Phase39TimeMap::submit(const Phase39Request& request) {
    Phase39Plan result;
    if (!request.target.valid() || request.publishedOutputSample<0 ||
        !std::isfinite(request.transitionOutputMs) ||
        request.transitionOutputMs<=0 || request.transitionOutputMs>1000) {
        result.outcome=Phase39Outcome::Invalid;
        return result;
    }
    if (request.generation<=lastGeneration_ || request.publishedOutputSample<lastPublished_) {
        result.outcome=Phase39Outcome::Stale;
        return result;
    }
    lastGeneration_=request.generation;
    lastPublished_=request.publishedOutputSample;
    if (request.target==tail_) { result.outcome=Phase39Outcome::Duplicate; return result; }
    if (completionOutput_>=0 && request.publishedOutputSample<completionOutput_) {
        result.outcome=Phase39Outcome::Busy;return result;
    }
    const auto& before=current_.starts();
    const auto targetLease=fixed(request.target);
    const auto& target=targetLease->starts();
    const auto count=before.size();
    const auto requested=std::min(count-1,request.requestedInputSample/1024+
        static_cast<std::size_t>(request.requestedInputSample%1024!=0));
    result.requestedFrame=requested;
    auto candidate=std::max(requested,static_cast<std::size_t>(
        std::lower_bound(before.begin(),before.end(),request.publishedOutputSample)-before.begin()));
    result.firstMutableFrame=candidate;
    result.nextEventFrame=count-1;
    for (const auto& event:events_)
        if (event.peakFrame>candidate) {
            result.nextEventFrame=event.peakFrame;
            break;
        }
    const auto atProtection=protectedEndAt(candidate);
    result.protectionEndFrame=atProtection==std::numeric_limits<std::size_t>::max() ?
        candidate : atProtection;
    // Phase 37 B redistributes compression inside event-to-event segments.
    // Start at a fresh segment so a new target cannot change any portion of
    // a segment already processed by a resolution or by an FIR source block.
    if (planning_==Phase39Planning::A &&
        (request.target.micros>1000000 || tail_.micros>1000000)) {
        std::size_t next=count-1;
        for (const auto& event:events_)
            if (event.peakFrame>candidate && event.peakFrame<next)
                next=event.peakFrame;
        if (next<count-1) candidate=std::min(count-1,next+6);
    }
    const auto duration=std::llround(request.transitionOutputMs*sampleRate_/1000.0);
    if (duration<1 || candidate>=count-1) return result;
    const auto fallbackStart=candidate;
    if (planning_!=Phase39Planning::A) {
        while (candidate<count-1 &&
               (planning_==Phase39Planning::C ? !safeRunEligible_[candidate] :
                protectedEndAt(candidate)!=std::numeric_limits<std::size_t>::max())) {
            const auto end=protectedEndAt(candidate);
            candidate=end==std::numeric_limits<std::size_t>::max() ?
                candidate+1 : end+1;
            ++result.protectedEventsSkipped;
        }
    }
    result.firstSafeFrame=candidate;
    while (candidate<count-1 && planning_!=Phase39Planning::C &&
           planning_!=Phase39Planning::C0) {
        auto end=candidate;
        long long minimumElapsed=0;
        while (end+1<count && minimumElapsed<duration) {
            minimumElapsed+=std::max(1LL,std::min(
                before[end+1]-before[end],target[end+1]-target[end])-1);
            ++end;
        }
        std::size_t conflictEnd=candidate;
        bool conflict=false;
        for (auto frame=candidate;frame<=end;++frame) {
            const auto protectedEnd=protectedEndAt(frame);
            if (protectedEnd!=std::numeric_limits<std::size_t>::max()) {
                conflict=true;conflictEnd=std::max(conflictEnd,protectedEnd);
            }
        }
        if (!conflict) break;
        ++result.protectedEventsSkipped;
        candidate=conflictEnd+1;
    }
    bool pausedFallback=candidate>=count-1;
    if (planning_==Phase39Planning::C || planning_==Phase39Planning::C0)
        pausedFallback=true;
    if (planning_==Phase39Planning::B && pausedFallback) {
        result.outcome=Phase39Outcome::NoSafeInterval;
        return result;
    }
    if (pausedFallback && planning_==Phase39Planning::A) candidate=fallbackStart;
    if (candidate>=count-1) {
        result.outcome=Phase39Outcome::NoSafeInterval;
        return result;
    }
    result.firstSafeFrame=candidate;
    auto output=before;
    std::size_t end=count-1;
    for (int attempt=0;attempt<(planning_==Phase39Planning::A ? 2 : 1);++attempt) {
        end=count-1;
        output=before;
        long long safeElapsed=0;
        const auto start=output[candidate];
        for (auto i=candidate;i+1<count;++i) {
            const auto oldHop=before[i+1]-before[i];
            const auto newHop=target[i+1]-target[i];
            const bool protectedNow=pausedFallback &&
                (planning_==Phase39Planning::C ? !safeRunEligible_[i] :
                 protectedEndAt(i)!=std::numeric_limits<std::size_t>::max());
            const auto elapsed=pausedFallback ? safeElapsed : output[i]-start;
            const auto weight=smooth(double(elapsed)/double(duration));
            const auto hop=protectedNow ? oldHop :
                std::llround((1.0-weight)*oldHop+weight*newHop);
            if (hop<=0) throw std::runtime_error("Non-monotonic arbitrary-speed hop");
            output[i+1]=output[i]+hop;
            if (protectedNow) ++result.heldFrames;
            else ++result.safeFramesUsed;
            if (pausedFallback && !protectedNow)
                safeElapsed+=std::max(1LL,std::min(oldHop,newHop)-1);
            if (elapsed>=duration && !protectedNow) { end=i;break; }
        }
        if (end<count-1 || pausedFallback) break;
        pausedFallback=true;
        candidate=fallbackStart;
    }
    if (end==count-1) { result.outcome=Phase39Outcome::Truncated;return result; }
    for (auto i=end+1;i<count;++i)
        output[i]=output[end]+target[i]-target[end];
    current_=TimeMap(1024,std::move(output),events_);
    tail_=request.target;
    completionOutput_=current_.starts()[end];
    result.outcome=Phase39Outcome::Applied;
    result.appliedFrame=candidate;
    result.rampEndFrame=end;
    result.appliedOutputSample=before[candidate];
    result.completionOutputSample=completionOutput_;
    result.protectedEventsPaused=pausedFallback;
    history_.push_back(result);
    return result;
}
bool Phase39TimeMap::monotonic() const noexcept {
    const auto& starts=current_.starts();
    for (std::size_t i=1;i<starts.size();++i)
        if (starts[i]<=starts[i-1]) return false;
    return true;
}
bool Phase39TimeMap::touchesProtected(const Phase39Plan& plan) const noexcept {
    if (!plan.applied()) return false;
    if (plan.protectedEventsPaused) return false; // Hops were copied from the old map.
    for (auto i=plan.appliedFrame;i<=plan.rampEndFrame;++i)
        if (protectedEndAt(i)!=std::numeric_limits<std::size_t>::max()) return true;
    return false;
}
std::array<HopRange,3> Phase39TimeMap::measureHops() const {
    constexpr std::array<int,3> fft{8192,4096,1024},hop{2048,1024,256};
    std::array<HopRange,3> ranges{};
    const auto lastInput=(current_.starts().size()-2)*1024;
    for (std::size_t r=0;r<3;++r) {
        auto& range=ranges[r];range.minimum=std::numeric_limits<long long>::max();
        long long previous=0;bool first=true;
        for (std::size_t input=0;input<=lastInput;input+=hop[r]) {
            const auto at=std::llround(current_.outputPositionForInputSample(double(input)));
            if (!first) {
                const auto step=at-previous;
                range.minimum=std::min(range.minimum,step);
                range.maximum=std::max(range.maximum,step);
                if (step<=0) ++range.nonPositive;
                if (step>=fft[r]) ++range.outsideWindow;
            }
            first=false;previous=at;
        }
    }
    return ranges;
}
std::size_t Phase39TimeMap::fixedMapBytes() const noexcept {
    std::size_t bytes=current_.starts().size()*sizeof(long long);
    for (const auto& [speed,map]:fixed_) { (void)speed;bytes+=map->starts().size()*sizeof(long long); }
    return bytes;
}
}
