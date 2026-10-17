// Full independent legacy DSP oracle: link a pre-Phase57 Phase36 object first.
// This host never calls Phase58/Phase61 seek code.
#include "prototype/Phase36StreamingSpeedEngine.h"
#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase45PcmDigest.h"
#include "audio/WavStream.h"
#include <fstream>
#include <iostream>
using namespace ts;using namespace ts::prototype;
int main(int argc,char** argv){try{
    if(argc<6)throw std::invalid_argument("input micros preset raw inputFrame...");
    WavStreamReader reader(argv[1]);const auto speed=Phase39Speed{std::uint32_t(std::stoul(argv[2]))};
    const std::string preset=argv[3];if(preset!="candidate"&&preset!="baseline")throw std::invalid_argument("preset");
    StretchConfig c;c.sampleRate=reader.sampleRate();c.channels=reader.channels();c.timeRatio=speed.timeRatio();c.qualityMode=QualityMode::Experimental;
    c.enableMultiResolution=c.enablePhaseLocking=c.enableTransientHandling=c.enableAdaptiveTimeMapping=c.enablePreciseTransientAnchoring=c.enableStereoCoherence=true;
    auto ac=c;ac.timeRatio=2;const auto analysis=Phase13StreamingEngine(ac).analyzeTransientEvents(argv[1]);
    Phase39TimeMap timeline(analysis,reader.sampleRate(),speed,preset=="candidate"?Phase39Planning::L2:Phase39Planning::C);
    const auto output=std::size_t(std::llround(reader.frames()*c.timeRatio));
    std::ofstream raw(argv[4],std::ios::binary);if(!raw)throw std::runtime_error("raw output");
    Phase45PcmDigest hash;std::vector<float> packed(2048*reader.channels());std::size_t total=0;
    Phase36StreamingSpeedEngine(c).process(argv[1],analysis,timeline.current(),output,2048,[&](auto p,std::size_t n,const auto&){
        for(std::size_t i=0;i<n;++i)for(std::size_t ch=0;ch<reader.channels();++ch)packed[i*reader.channels()+ch]=p[ch][i];
        raw.write(reinterpret_cast<const char*>(packed.data()),n*reader.channels()*sizeof(float));hash.update(packed.data(),n*reader.channels()*sizeof(float));total+=n;
    },{});
    if(!raw||total!=output)throw std::runtime_error("reference length/write");
    std::cout<<"{\"output_frames\":"<<output<<",\"input_frames\":"<<reader.frames()<<",\"channels\":"<<reader.channels()<<",\"rate\":"<<reader.sampleRate()<<",\"sha256\":\""<<hash.finish()<<"\",\"positions\":[";
    for(int i=5;i<argc;++i){const auto f=std::stoull(argv[i]);if(f>reader.frames())throw std::out_of_range("seek");const auto at=f==reader.frames()?output:std::min(output,std::size_t(std::max(0LL,std::llround(timeline.current().outputPositionForInputSample(double(f))))));if(i>5)std::cout<<',';std::cout<<at;}
    std::cout<<"]}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
