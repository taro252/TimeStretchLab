// Small playback-boundary clips only; no full-song stretched PCM cache.
#include "prototype/Phase35TransitionEngine.h"
#include "prototype/Phase39TimeMap.h"
#include "audio/WavWriter.h"
#include "audio/WavStream.h"
#include <iostream>
#include <iomanip>
using namespace ts;using namespace ts::prototype;
struct EndClip{};
int main(int argc,char** argv){try{
    if(argc!=5)throw std::invalid_argument("input speed target_input_seconds output_directory");
    auto speed=std::stod(argv[2]);WavStreamReader reader(argv[1]);const auto rate=reader.sampleRate();const auto channels=reader.channels();
    StretchConfig c;c.sampleRate=rate;c.channels=channels;c.timeRatio=1/speed;c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;c.enablePhaseLocking=true;c.enableTransientHandling=true;c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;
    auto detector=c;detector.timeRatio=2;auto analysis=Phase13StreamingEngine(detector).analyzeTransientEvents(argv[1]);
    Phase39TimeMap timeline(analysis,rate,Phase39Speed::fromDouble(speed),Phase39Planning::L2);
    const auto start=std::size_t(std::llround(timeline.current().outputPositionForInputSample(std::stod(argv[3])*rate)));
    const auto tailEnd=std::size_t(std::llround(timeline.current().outputPositionForInputSample(2.*rate)));
    const auto tailBegin=tailEnd-std::min(tailEnd,std::size_t(rate/5));const auto end=std::min(std::size_t(std::llround(reader.frames()/speed)),start+std::size_t(rate*1.5));
    AudioBuffer tail,head;tail.sampleRate=head.sampleRate=rate;tail.channels.resize(channels);head.channels.resize(channels);std::size_t cursor=0;
    try{Phase35TransitionEngine(c).processWav(argv[1],{},timeline.current(),{},std::llround(reader.frames()/speed),16384,nullptr,[&](const float*const* p,std::size_t n){
        for(std::size_t i=0;i<n;++i){auto at=cursor+i;for(std::size_t ch=0;ch<channels;++ch){if(at>=tailBegin&&at<tailEnd)tail.channels[ch].push_back(p[ch][i]);if(at>=start&&at<end)head.channels[ch].push_back(p[ch][i]);}}
        cursor+=n;if(cursor>=std::max(tailEnd,end))throw EndClip{};
    });}catch(const EndClip&){}
    std::filesystem::create_directory(argv[4]);std::cout<<std::setprecision(17)<<"fade_frames,boundary_input_seconds,boundary_clip_seconds,peak_first_256_before_gain,energy_first_256_ratio\n";
    for(unsigned fade:{0,64,128,256}){AudioBuffer clip=tail;double peak=0,energy=0,original=0;
        for(std::size_t ch=0;ch<channels;++ch)for(std::size_t i=0;i<head.channels[ch].size();++i){const double gain=fade&&i<fade?double(i)/fade:1.;auto value=head.channels[ch][i]*gain;
            if(i<256){peak=std::max(peak,std::abs(value));energy+=value*value;original+=double(head.channels[ch][i])*head.channels[ch][i];}clip.channels[ch].push_back(float(value));}
        for(auto& channel:clip.channels)for(auto& sample:channel)sample*=.5f;
        WavWriter::write(std::filesystem::path(argv[4])/("fade_"+std::to_string(fade)+".wav"),clip);
        std::cout<<fade<<','<<argv[3]<<','<<double(tail.channels[0].size())/rate<<','<<peak<<','<<(original?energy/original:0)<<'\n';}
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
