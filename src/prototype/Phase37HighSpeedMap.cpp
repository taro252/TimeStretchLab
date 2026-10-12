#include "prototype/Phase37HighSpeedMap.h"
#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace ts::prototype {
namespace {
constexpr int hop=1024;
double shoulder(std::size_t distance,int length) {
    if (distance>=static_cast<std::size_t>(length)) return 0;
    return 0.5*(1+std::cos(std::numbers::pi*double(distance)/length));
}
}
TimeMap phase37Map(const Phase13TransientAnalysis& analysis,
                   std::size_t inputFrames,double ratio,bool protect,
                   Phase37MapDiagnostics* out) {
    if (!std::isfinite(ratio) || ratio<0.5 || ratio>1.0)
        throw std::invalid_argument("Phase 37 time ratio must be 0.5..1.0");
    TransientEventMap frozen(analysis.detectorFrames(),analysis.activeFrameCount(),
                             hop,ratio,{},analysis.events());
    std::vector<double> offsets;
    offsets.reserve(analysis.anchors().size());
    for (const auto& anchor:analysis.anchors()) offsets.push_back(anchor.sampleOffset);
    if (!offsets.empty()) frozen.refineAnchors(offsets);
    const auto& events=frozen.events();
    const auto count=frozen.starts().size();
    if (!count) throw std::invalid_argument("Empty analysis");
    Phase37MapDiagnostics d;d.events=events.size();
    if (!protect || ratio==1.0 || events.empty()) {
        const auto& starts=frozen.starts();
        for (std::size_t i=1;i<starts.size();++i) {
            const auto delta=starts[i]-starts[i-1];
            if (i==1) d.minimumMidHop=delta;
            d.minimumMidHop=std::min(d.minimumMidHop,delta);
            d.maximumMidHop=std::max(d.maximumMidHop,delta);
        }
        d.minimumLocalRatio=d.maximumLocalRatio=ratio;
        if (out) *out=d;
        return TimeMap(hop,starts,events);
    }
    const auto intervals=count-1;
    std::vector<double> weights(intervals,0);
    for (const auto& event:events) {
        const auto peak=event.peakFrame;
        const auto first=peak>3?peak-3:0;
        const auto last=std::min(intervals,peak+6);
        for (auto i=first;i<last;++i) {
            const double weight=i+1<peak ? shoulder(peak-1-i,3) :
                                i>peak+1 ? shoulder(i-(peak+1),5) : 1.0;
            weights[i]=std::max(weights[i],weight);
        }
    }
    std::vector<std::size_t> anchors{0};
    for (const auto& event:events)
        if (event.peakFrame>anchors.back() && event.peakFrame<intervals)
            anchors.push_back(event.peakFrame);
    if (intervals>anchors.back()) anchors.push_back(intervals);
    std::vector<long long> starts(count,0);
    d.minimumLocalRatio=std::numeric_limits<double>::infinity();
    for (std::size_t segment=1;segment<anchors.size();++segment) {
        const auto first=anchors[segment-1],last=anchors[segment];
        const double atFirst=first==0 ? 0.0 : double(frozen.idealStartAt(first));
        const double atLast=last==intervals ? double(last*hop)*ratio :
                                               double(frozen.idealStartAt(last));
        const double target=(atLast-atFirst)/hop;
        const double length=double(last-first);
        const double segmentRatio=target/length;
        if (segmentRatio<=0 || !std::isfinite(segmentRatio))
            throw std::runtime_error("No monotonic high-speed event interval");
        double sumWeight=0;
        for (auto i=first;i<last;++i) sumWeight+=weights[i];
        double depth=0;
        // Reserve at least half the nominal ratio in the inter-event region.
        // If the protected intervals occupy the whole segment, retain a
        // constant-speed segment and report that protection was impossible.
        const double minimumBaseline=std::max(0.12,ratio*0.5);
        if (sumWeight>0 && sumWeight<length-1e-8 &&
            segmentRatio>minimumBaseline && segmentRatio<1) {
            const double capacity=(target-minimumBaseline*length)/
                                  (sumWeight*(1-minimumBaseline));
            depth=std::clamp(capacity,0.0,1.0);
            if (depth<1-1e-8) ++d.capacityLimitedSegments;
            if (depth>0) ++d.protectedSegments;
        } else if (sumWeight>0) ++d.denseFallbackSegments;
        const double baseline=depth>0 ? (target-depth*sumWeight)/
                                          (length-depth*sumWeight) : segmentRatio;
        double position=atFirst;
        starts[first]=std::llround(atFirst);
        for (auto i=first;i<last;++i) {
            const double local=baseline+(1-baseline)*depth*weights[i];
            d.minimumLocalRatio=std::min(d.minimumLocalRatio,local);
            d.maximumLocalRatio=std::max(d.maximumLocalRatio,local);
            position+=hop*local;
            starts[i+1]=std::llround(position);
        }
        starts[last]=std::llround(atLast);
    }
    if (anchors.size()==1) {
        starts[0]=0;d.minimumLocalRatio=d.maximumLocalRatio=ratio;
    }
    for (std::size_t i=1;i<count;++i) {
        const auto delta=starts[i]-starts[i-1];
        if (delta<=0 || delta>=4096)
            throw std::runtime_error("Unsafe high-speed Mid synthesis hop");
        if (i==1) d.minimumMidHop=delta;
        d.minimumMidHop=std::min(d.minimumMidHop,delta);
        d.maximumMidHop=std::max(d.maximumMidHop,delta);
    }
    for (const auto& event:events)
        d.maximumAnchorError=std::max(d.maximumAnchorError,
            std::llabs(starts[event.peakFrame]-frozen.idealStartAt(event.peakFrame)));
    // The last node is beyond or near input EOS because analysis includes
    // padding. The playback writer still uses round(inputFrames*ratio).
    (void)inputFrames;
    if (out) *out=d;
    return TimeMap(hop,std::move(starts),events);
}
}
