// Whole-product fixed-length oracle. Link the pre-Phase57 Phase36 object.
// Phase54PlaybackPipeline uses round(inputFrames * initial.timeRatio()).
#include "prototype/Phase36StreamingSpeedEngine.h"
#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase45PcmDigest.h"
#include "audio/WavStream.h"
#include "playback/StartupDiagnostics.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sys/resource.h>
using namespace ts;using namespace ts::prototype;
int main(int argc,char** argv){try{
    if(argc!=5)throw std::invalid_argument("input.wav speed_micros candidate|baseline raw.f32|-");
    const auto micros=std::stoul(argv[2]);if(micros<400000||micros>2000000||micros%10000)throw std::invalid_argument("Invalid 1-percent speed");
    const std::string preset=argv[3];if(preset!="candidate"&&preset!="baseline")throw std::invalid_argument("Invalid preset");
    WavStreamReader reader(argv[1]);StretchConfig c;c.sampleRate=reader.sampleRate();c.channels=int(reader.channels());c.timeRatio=Phase39Speed{std::uint32_t(micros)}.timeRatio();
    c.qualityMode=QualityMode::Experimental;c.enableMultiResolution=true;c.enablePhaseLocking=true;c.enableTransientHandling=true;c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;
    const bool save=std::string(argv[4])!="-";std::ofstream raw;if(save){raw.open(argv[4],std::ios::binary);if(!raw)throw std::runtime_error("Cannot open raw output");}
    Phase45PcmDigest digest;std::vector<float> interleaved(2048*reader.channels());std::size_t frames=0;double firstGenerated=-1,firstPublished=-1,lead=-1;
    playback::StageClock total;auto ac=c;ac.timeRatio=2;auto a=Phase13StreamingEngine(ac).analyzeTransientEvents(argv[1]);const auto analysis=total.elapsed();
    Phase39TimeMap timeline(a,reader.sampleRate(),{std::uint32_t(micros)},preset=="candidate"?Phase39Planning::L2:Phase39Planning::C);
    const auto output=std::size_t(std::llround(reader.frames()*c.timeRatio));
    const auto mapReady=total.elapsed();playback::StageClock dsp;Phase36StreamingSpeedEngine(c).process(argv[1],a,timeline.current(),output,2048,[&](auto p,std::size_t n,const auto&){
        if(firstGenerated<0)firstGenerated=total.elapsed().wallSeconds;
        for(std::size_t i=0;i<n;++i)for(std::size_t ch=0;ch<reader.channels();++ch)interleaved[i*reader.channels()+ch]=p[ch][i];
        digest.update(interleaved.data(),n*reader.channels()*sizeof(float));if(save)raw.write(reinterpret_cast<const char*>(interleaved.data()),n*reader.channels()*sizeof(float));frames+=n;
        const auto now=total.elapsed().wallSeconds;if(firstPublished<0)firstPublished=now;if(lead<0&&frames>=(preset=="candidate"?16384u:12288u))lead=now;
    },{});const auto dt=dsp.elapsed(),t=total.elapsed();rusage u{};getrusage(RUSAGE_SELF,&u);if(save&&!raw)throw std::runtime_error("Raw write failed");
    std::cout<<std::setprecision(17)<<"{\"PASS\":true,\"speed_micros\":"<<micros<<",\"preset\":\""<<preset<<"\",\"rate\":"<<reader.sampleRate()<<",\"channels\":"<<reader.channels()<<",\"input_frames\":"<<reader.frames()<<",\"output_frames\":"<<frames<<",\"pcm_sha256\":\""<<digest.finish()<<"\",\"analysis_wall_s\":"<<analysis.wallSeconds<<",\"analysis_cpu_s\":"<<analysis.threadCpuSeconds<<",\"dsp_wall_s\":"<<dt.wallSeconds<<",\"dsp_cpu_s\":"<<dt.threadCpuSeconds<<",\"wall_s\":"<<t.wallSeconds<<",\"cpu_s\":"<<t.threadCpuSeconds<<",\"peak_rss_bytes\":"<<u.ru_maxrss;
    std::cout<<",\"first_event_s\":"<<(a.events().empty()?-1:analysis.wallSeconds)<<",\"first_map_s\":"<<mapReady.wallSeconds<<",\"first_generated_s\":"<<firstGenerated<<",\"first_published_s\":"<<firstPublished<<",\"lead_ready_s\":"<<lead<<",\"analysis_done_s\":"<<analysis.wallSeconds<<"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
