#pragma once
#include "dsp/Phase13StreamingEngine.h"
#include <array>
#include <bit>
#include <fstream>
#include <stdexcept>
#include <vector>
namespace ts::prototype::phase56 {
inline constexpr std::size_t maxMaps=161;
inline constexpr auto speeds=[]{std::array<double,maxMaps> a{};for(std::size_t i=0;i<maxMaps;++i)a[i]=double(i+40)/100.0;return a;}();
inline std::vector<std::uint32_t> percentSpeedMicros(){std::vector<std::uint32_t> v;for(std::uint32_t i=40;i<=200;++i)v.push_back(i*10000);return v;}
inline constexpr std::uint64_t protocolMagic=0x3256503635524354ULL;
struct ReferenceData {
    std::uint64_t rate=0,channels=0,input=0,active=0,transients=0;
    std::vector<TransientFrame> frames;
    std::vector<TransientEvent> events;
    std::vector<TransientAnchor> anchors;
    std::vector<std::vector<long long>> maps;
    std::vector<std::uint32_t> speedMicros;
};
// Explicit fields and IEEE bits; no struct padding or decimal round trips.
inline void number(std::ostream& s,std::uint64_t n){for(unsigned i=0;i<8;++i)s.put(char(n>>(i*8)));}
inline std::uint64_t number(std::istream& s){std::uint64_t n=0;for(unsigned i=0;i<8;++i){int c=s.get();if(c<0)throw std::runtime_error("Truncated reference");n|=std::uint64_t(c)<<(i*8);}return n;}
inline void write(std::ostream& s,const ReferenceData& r){
    if(r.maps.size()!=r.speedMicros.size())throw std::runtime_error("Reference speed/map mismatch");
    number(s,protocolMagic);
    for(auto n:{r.rate,r.channels,r.input,r.active,r.transients})number(s,n);
    number(s,r.frames.size());for(const auto& f:r.frames){
        for(double d:{f.spectralFlux,f.logEnergy,f.previousLogEnergy,f.threshold})number(s,std::bit_cast<std::uint64_t>(d));
        number(s,std::bit_cast<std::uint32_t>(f.strength));number(s,f.detected);number(s,f.resetApplied);
    }
    number(s,r.events.size());for(const auto& e:r.events){for(auto n:{e.onsetFrame,e.peakFrame,e.attackEndFrame,e.endFrame})number(s,n);number(s,std::bit_cast<std::uint32_t>(e.strength));}
    number(s,r.anchors.size());for(const auto& a:r.anchors){number(s,a.frame);for(auto d:{a.sampleOffset,a.absoluteInputSample,a.crestFactor})number(s,std::bit_cast<std::uint64_t>(d));number(s,a.confident);}
    number(s,r.speedMicros.size());for(auto speed:r.speedMicros)number(s,speed);
    for(const auto& map:r.maps){number(s,map.size());for(auto n:map)number(s,std::uint64_t(n));}
    if(!s)throw std::runtime_error("Reference write failed");
}
inline ReferenceData read(std::istream& s){
    if(number(s)!=protocolMagic)throw std::runtime_error("Expected Phase56 reference protocol v2");
    ReferenceData r;r.rate=number(s);r.channels=number(s);r.input=number(s);r.active=number(s);r.transients=number(s);
    const auto count=[&]{const auto n=number(s);if(n>10000000)throw std::runtime_error("Reference too large");return std::size_t(n);};
    r.frames.resize(count());for(auto& f:r.frames){f.spectralFlux=std::bit_cast<double>(number(s));f.logEnergy=std::bit_cast<double>(number(s));f.previousLogEnergy=std::bit_cast<double>(number(s));f.threshold=std::bit_cast<double>(number(s));f.strength=std::bit_cast<float>(std::uint32_t(number(s)));f.detected=number(s);f.resetApplied=number(s);}
    r.events.resize(count());for(auto& e:r.events){e.onsetFrame=number(s);e.peakFrame=number(s);e.attackEndFrame=number(s);e.endFrame=number(s);e.strength=std::bit_cast<float>(std::uint32_t(number(s)));}
    r.anchors.resize(count());for(auto& a:r.anchors){a.frame=number(s);a.sampleOffset=std::bit_cast<double>(number(s));a.absoluteInputSample=std::bit_cast<double>(number(s));a.crestFactor=std::bit_cast<double>(number(s));a.confident=number(s);}
    const auto speeds=count();if(speeds>maxMaps)throw std::runtime_error("Too many reference speeds");
    r.speedMicros.resize(speeds);for(auto& speed:r.speedMicros)speed=static_cast<std::uint32_t>(number(s));r.maps.resize(speeds);
    for(auto& map:r.maps){map.resize(count());for(auto& n:map)n=static_cast<long long>(number(s));}
    if(s.peek()!=EOF)throw std::runtime_error("Reference has trailing data");return r;
}
}
