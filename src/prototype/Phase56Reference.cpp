// Build/freeze this executable BEFORE introducing the incremental engine.
#include "prototype/Phase56ReferenceData.h"
#include "prototype/Phase39TimeMap.h"
#include "audio/WavStream.h"
#include "playback/StartupDiagnostics.h"
#include <iostream>
#include <iomanip>
#include <sys/resource.h>
using namespace ts;using namespace ts::prototype;using namespace ts::prototype::phase56;
int main(int argc,char** argv){try{
    if(argc!=3)throw std::invalid_argument("input.wav output.bin");
    WavStreamReader reader(argv[1]);StretchConfig c;c.sampleRate=reader.sampleRate();c.channels=int(reader.channels());c.timeRatio=2;
    c.qualityMode=QualityMode::Experimental;c.enableMultiResolution=true;c.enablePhaseLocking=true;
    c.enableTransientHandling=true;c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;
    playback::StageClock clock;auto a=Phase13StreamingEngine(c).analyzeTransientEvents(argv[1]);auto t=clock.elapsed();
    ReferenceData r{reader.sampleRate(),reader.channels(),a.inputFrames(),a.activeFrameCount(),a.transientCount(),a.detectorFrames(),a.events(),a.anchors(),{}};
    r.speedMicros=percentSpeedMicros();r.maps.resize(r.speedMicros.size());
    if(r.input)for(std::size_t i=0;i<speeds.size();++i)r.maps[i]=Phase39TimeMap(a,reader.sampleRate(),Phase39Speed::fromDouble(speeds[i])).current().starts();
    const auto total=clock.elapsed();rusage usage{};getrusage(RUSAGE_SELF,&usage);
    std::ofstream out(argv[2],std::ios::binary);write(out,r);
    std::cout<<std::setprecision(17)<<"{\"analysis_wall_seconds\":"<<t.wallSeconds<<",\"analysis_thread_cpu_seconds\":"<<t.threadCpuSeconds<<",\"analysis_bytes\":"<<a.memoryBytes()<<",\"frames\":"<<r.frames.size()<<",\"speed_count\":"<<r.speedMicros.size()<<",\"analysis_and_maps_wall_seconds\":"<<total.wallSeconds<<",\"analysis_and_maps_cpu_seconds\":"<<total.threadCpuSeconds<<",\"peak_rss_bytes\":"<<usage.ru_maxrss<<"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
