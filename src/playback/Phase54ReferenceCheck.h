#pragma once
#include "audio/WavStream.h"
#include "prototype/Phase35TransitionEngine.h"
#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase45PcmDigest.h"
#include "playback/PlaybackEngine.h"
namespace ts::playback::verification {
struct ReferenceEnd{};
inline std::string referenceHash(const std::filesystem::path& input,double speed,Preset preset,
    const std::vector<prototype::Phase39PlanMetric>& plans,std::size_t first,std::size_t end){
    prototype::Phase45PcmDigest digest;if(first>end)throw std::runtime_error("Invalid reference span");if(first==end)return digest.finish();
    WavStreamReader reader(input);StretchConfig c;c.sampleRate=reader.sampleRate();c.channels=reader.channels();c.timeRatio=1/speed;
    c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;
    auto detector=c;detector.timeRatio=2;auto analysis=Phase13StreamingEngine(detector).analyzeTransientEvents(input);
    prototype::Phase39TimeMap timeline(analysis,reader.sampleRate(),prototype::Phase39Speed::fromDouble(speed),preset==Preset::Candidate?prototype::Phase39Planning::L2:prototype::Phase39Planning::C);
    std::vector<std::pair<std::size_t,bool>> modes;auto previous=prototype::Phase39Speed::fromDouble(speed);
    for(auto& metric:plans){auto plan=timeline.submit({metric.generation,metric.target,metric.requestedInput,static_cast<long long>(metric.planningFence),50});
        if(!plan.applied()||plan.appliedFrame!=metric.plan.appliedFrame||plan.appliedOutputSample!=metric.plan.appliedOutputSample||plan.completionOutputSample!=metric.plan.completionOutputSample)throw std::runtime_error("Reference plan mismatch");
        if((previous.value()<.5)!=(metric.target.value()<.5))modes.emplace_back(metric.firstDensityChangedInput,metric.target.value()<.5);previous=metric.target;}
    auto length=plans.empty()?std::llround(reader.frames()/speed):std::llround(timeline.current().outputPositionForInputSample(double(reader.frames())));
    if(end>static_cast<std::size_t>(length))throw std::runtime_error("Reference span outside output");
    std::size_t cursor=0;std::vector<float> scratch(16384*reader.channels());
    try{Phase35TransitionEngine(c).processWav(input,{},timeline.current(),modes,length,16384,nullptr,[&](const float*const* p,std::size_t n){
        auto begin=std::max(first,cursor),stop=std::min(end,cursor+n);std::size_t at=0;
        for(auto i=begin;i<stop;++i)for(std::size_t ch=0;ch<reader.channels();++ch)scratch[at++]=p[ch][i-cursor];
        if(at)digest.update(scratch.data(),at*sizeof(float));cursor+=n;if(cursor>=end)throw ReferenceEnd{};
    });}catch(const ReferenceEnd&){}
    return digest.finish();
}
}
