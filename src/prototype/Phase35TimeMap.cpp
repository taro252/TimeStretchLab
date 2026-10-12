#include "prototype/Phase35TimeMap.h"
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
double validatedRatio(Phase35Speed speed) {
    if (!speed.valid())
        throw std::invalid_argument("Invalid initial speed");
    return speed.timeRatio();
}
}
Phase35Speed Phase35Speed::fromDouble(double speed) {
    if (!std::isfinite(speed) || speed<0.40 || speed>1.00 ||
        std::abs(speed*1000000.0-std::round(speed*1000000.0))>1e-7)
        throw std::invalid_argument("Speed must be a six-decimal value in [0.40, 1.00]");
    return {static_cast<std::uint32_t>(std::llround(speed*1000000.0))};
}
Phase35TimeMap::Phase35TimeMap(
    const Phase13TransientAnalysis& analysis,std::uint32_t rate,Phase35Speed initial)
    : analysis_(analysis),current_(makeFixed(analysis,validatedRatio(initial))),
      events_(analysis.events()),sampleRate_(rate),tail_(initial) {
    if (rate==0 || current_.starts().size()<2)
        throw std::invalid_argument("Invalid Phase 28 initialization");
    fixed_.emplace(initial.micros,std::make_shared<TimeMap>(current_));
}
std::shared_ptr<const TimeMap> Phase35TimeMap::fixed(Phase35Speed speed) {
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
std::size_t Phase35TimeMap::protectedEndAt(std::size_t frame) const noexcept {
    const auto limit=current_.starts().size()-1;
    for (const auto& event:events_) {
        const auto begin=event.onsetFrame>2 ? event.onsetFrame-2 : 0;
        const auto end=std::min(limit,std::max(event.endFrame,event.peakFrame)+5);
        if (frame>=begin && frame<=end) return end;
    }
    return std::numeric_limits<std::size_t>::max();
}
Phase35Plan Phase35TimeMap::submit(const Phase35Request& request) {
    Phase35Plan result;
    if (!request.target.valid() || request.publishedOutputSample<0 ||
        !std::isfinite(request.transitionOutputMs) ||
        request.transitionOutputMs<=0 || request.transitionOutputMs>1000) {
        result.outcome=Phase35Outcome::Invalid;
        return result;
    }
    if (request.generation<=lastGeneration_ || request.publishedOutputSample<lastPublished_) {
        result.outcome=Phase35Outcome::Stale;
        return result;
    }
    lastGeneration_=request.generation;
    lastPublished_=request.publishedOutputSample;
    if (request.target==tail_) { result.outcome=Phase35Outcome::Duplicate; return result; }
    if (completionOutput_>=0 && request.publishedOutputSample<completionOutput_) {
        result.outcome=Phase35Outcome::Busy;return result;
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
    const auto duration=std::llround(request.transitionOutputMs*sampleRate_/1000.0);
    if (duration<1 || candidate>=count-1) return result;
    while (candidate<count-1) {
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
    if (candidate>=count-1) return result;
    auto output=before;
    const auto start=output[candidate];
    std::size_t end=count-1;
    for (auto i=candidate;i+1<count;++i) {
        const auto elapsed=output[i]-start;
        const auto weight=smooth(double(elapsed)/double(duration));
        const auto hop=std::llround((1.0-weight)*(before[i+1]-before[i])+
                                     weight*(target[i+1]-target[i]));
        if (hop<=0) throw std::runtime_error("Non-monotonic arbitrary-speed hop");
        output[i+1]=output[i]+hop;
        if (elapsed>=duration) { end=i;break; }
    }
    if (end==count-1) { result.outcome=Phase35Outcome::Truncated;return result; }
    for (auto i=end+1;i<count;++i)
        output[i]=output[end]+target[i]-target[end];
    current_=TimeMap(1024,std::move(output),events_);
    tail_=request.target;
    completionOutput_=current_.starts()[end];
    result.outcome=Phase35Outcome::Applied;
    result.appliedFrame=candidate;
    result.rampEndFrame=end;
    result.appliedOutputSample=start;
    result.completionOutputSample=completionOutput_;
    history_.push_back(result);
    return result;
}
bool Phase35TimeMap::monotonic() const noexcept {
    const auto& starts=current_.starts();
    for (std::size_t i=1;i<starts.size();++i)
        if (starts[i]<=starts[i-1]) return false;
    return true;
}
bool Phase35TimeMap::touchesProtected(const Phase35Plan& plan) const noexcept {
    if (!plan.applied()) return false;
    for (auto i=plan.appliedFrame;i<=plan.rampEndFrame;++i)
        if (protectedEndAt(i)!=std::numeric_limits<std::size_t>::max()) return true;
    return false;
}
std::array<HopRange,3> Phase35TimeMap::measureHops() const {
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
std::size_t Phase35TimeMap::fixedMapBytes() const noexcept {
    std::size_t bytes=current_.starts().size()*sizeof(long long);
    for (const auto& [speed,map]:fixed_) { (void)speed;bytes+=map->starts().size()*sizeof(long long); }
    return bytes;
}
}
