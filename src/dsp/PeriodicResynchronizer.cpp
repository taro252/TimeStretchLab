#include "dsp/PeriodicResynchronizer.h"
#include <algorithm>
#include <cmath>
#include <limits>

namespace ts {
PeriodicResynchronizer::PeriodicResynchronizer(const StretchConfig& config,
                                                 std::size_t fftSize,int hop)
    : sampleRate_(config.sampleRate),intervalMs_(config.pvsolaIntervalMs),
      threshold_(config.pvsolaMinimumCorrelation),
      intervalFrames_(std::max(1,int(std::lround(config.pvsolaIntervalMs*config.sampleRate/
                                                (1000.0*hop))))),
      rangeSamples_(int(std::lround(config.pvsolaSearchMs*config.sampleRate/1000))),
      fftSize_(static_cast<int>(fftSize)) {}

double PeriodicResynchronizer::tonality(const PhaseLocker& peaks) const {
    const auto& mag=peaks.magnitudes();
    const int first=std::max(1,int(std::ceil(150*fftSize_/sampleRate_)));
    const int last=std::min(int(mag.size())-2,int(std::floor(6000*fftSize_/sampleRate_)));
    double total=0,concentrated=0;
    for (int k=first;k<=last;++k) total+=double(mag[k])*mag[k];
    if (total<1e-10) return 0;
    for (const auto& peak:peaks.peaks()) {
        const int bin=peak.bin;
        if (bin<first || bin>last) continue;
        double local=0;
        int count=0;
        for (int k=std::max(first,bin-8);k<=std::min(last,bin+8);++k) {
            local+=mag[k]; ++count;
        }
        if (!count || peak.magnitude<3*local/count) continue;
        for (int k=std::max(first,bin-1);k<=std::min(last,bin+1);++k)
            concentrated+=double(mag[k])*mag[k];
    }
    return std::clamp(concentrated/total,0.0,1.0);
}
double PeriodicResynchronizer::sampleInput(WavStreamReader& reader,long long index) const {
    if (index<0 || index>=static_cast<long long>(reader.frames())) return 0;
    double value=0;
    for (std::size_t c=0;c<reader.channels();++c) value+=reader.sample(c,index);
    return value/reader.channels();
}
double PeriodicResynchronizer::sampleOutput(const std::vector<RingOverlapAdd>& olas,
                                             long long index) const {
    if (index<0) return 0;
    double value=0;
    for (const auto& ola:olas) value+=ola.preview(static_cast<std::size_t>(index));
    return value/olas.size();
}
double PeriodicResynchronizer::correlation(int offset,long long outputStart,long long inputStart,
                                            WavStreamReader& reader,
                                            const std::vector<RingOverlapAdd>& olas) const {
    double dot=0,outPower=0,inPower=0;
    for (int p=256;p<1280;p+=4) {
        const long long out=outputStart+p;
        const long long in=inputStart+offset+p-fftSize_/2;
        const double a=sampleOutput(olas,out)-sampleOutput(olas,out-8);
        const double b=sampleInput(reader,in)-sampleInput(reader,in-8);
        dot+=a*b;outPower+=a*a;inPower+=b*b;
    }
    if (outPower<1e-10 || inPower<1e-10) return 0;
    return dot/std::sqrt(outPower*inPower);
}
ResyncDecision PeriodicResynchronizer::consider(std::size_t frame,long long outputStart,
    long long inputStart,const std::vector<bool>& resets,const PhaseLocker& peaks,
    WavStreamReader& reader,const std::vector<RingOverlapAdd>& olas) {
    ResyncDecision decision;
    if (frame<4 || (hasApplied_ && frame-lastAppliedFrame_<static_cast<std::size_t>(intervalFrames_)))
        return decision;
    decision.scheduled=true;
    ++stats_.scheduled;
    const auto begin=frame>3 ? frame-3 : 0;
    const auto end=std::min(resets.size()-1,frame+3);
    for (std::size_t i=begin;i<=end;++i) if (resets[i]) {
        decision.transientSuppressed=true;
        ++stats_.transientSuppressed;
        return decision;
    }
    decision.tonality=tonality(peaks);
    if (decision.tonality<0.55 || outputStart<0 ||
        inputStart<rangeSamples_ ||
        inputStart+fftSize_+rangeSamples_>
            static_cast<long long>(reader.frames())+fftSize_/2) return decision;
    int bestOffset=0;
    double best=-std::numeric_limits<double>::infinity();
    for (int offset=-rangeSamples_;offset<=rangeSamples_;offset+=16) {
        const double score=correlation(offset,outputStart,inputStart,reader,olas);
        if (score>best) {best=score;bestOffset=offset;}
    }
    const int coarse=bestOffset;
    for (int offset=std::max(-rangeSamples_,coarse-15);
         offset<=std::min(rangeSamples_,coarse+15);++offset) {
        const double score=correlation(offset,outputStart,inputStart,reader,olas);
        if (score>best) {best=score;bestOffset=offset;}
    }
    decision.correlation=best;
    if (best<threshold_) return decision;
    decision.applied=true;
    decision.offsetSamples=bestOffset;
    hasApplied_=true;
    lastAppliedFrame_=frame;
    ++stats_.applied;
    stats_.correlationSum+=best;
    stats_.absoluteOffsetSum+=std::abs(bestOffset);
    return decision;
}
}
