#include "audio/WavStream.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include "prototype/Phase32ResearchEngine.h"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>

namespace {
using Clock=std::chrono::steady_clock;
ts::StretchConfig frozen(std::uint32_t rate,int channels,double ratio) {
    ts::StretchConfig c;
    c.sampleRate=rate;c.channels=channels;c.timeRatio=ratio;
    c.enableMultiResolution=true;c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
}
int main(int argc,char** argv) {
    if (argc!=5 && argc!=6) {
        std::cerr<<"Usage: phase32_render input.wav output.wav speed "
                    "baseline|no_lock|no_reset|no_propagation [stems]\n";
        return 2;
    }
    try {
        const std::filesystem::path input=argv[1],output=argv[2];
        const std::string kind=argv[4];
        const double speed=std::stod(argv[3]);
        if (!std::isfinite(speed) || speed<0.25 || speed>0.50 ||
            (kind!="baseline" && kind!="no_lock" && kind!="no_reset" &&
             kind!="no_propagation"))
            throw std::invalid_argument("Invalid research speed or mode");
        if (argc==6 && std::string(argv[5])!="stems")
            throw std::invalid_argument("Unknown output option");
        const auto micros=std::llround(speed*1000000.0);
        if (std::abs(speed*1000000.0-micros)>1e-7)
            throw std::invalid_argument("Speed needs at most six decimals");
        const double normalized=double(micros)/1000000.0;
        const double ratio=1.0/normalized;
        ts::WavStreamReader reader(input);
        auto config=frozen(reader.sampleRate(),static_cast<int>(reader.channels()),ratio);
        if (kind=="no_lock") config.enablePhaseLocking=false;
        ts::Phase32Options options;
        options.resetOnTransient=kind!="no_reset";
        options.resetEveryFrame=kind=="no_propagation";
        options.writeResolutionStems=argc==6;
        rusage before{};getrusage(RUSAGE_SELF,&before);
        const auto started=Clock::now();
        const auto result=ts::Phase32ResearchEngine(config,options).processWav(input,output,16384);
        const auto seconds=std::chrono::duration<double>(Clock::now()-started).count();
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        const auto secondsFor=[](const timeval& value) {
            return value.tv_sec+value.tv_usec/1000000.0;
        };
        std::cout<<std::setprecision(12)
                 <<"quality_status=diagnostic_only\n"
                 <<"mode="<<kind<<'\n'<<"speed="<<normalized<<'\n'
                 <<"analysis_hop="<<(normalized<0.5?"1024/512/128":"2048/1024/256")<<'\n'
                 <<"input_frames="<<result.inputFrames<<'\n'
                 <<"output_frames="<<result.outputFrames<<'\n'
                 <<"events="<<result.eventCount<<'\n'
                 <<"anchors="<<result.anchoredEventCount<<'\n'
                 <<"map_hash="<<result.timeMapHash<<'\n'
                 <<"peak="<<result.peak<<'\n'
                 <<"elapsed_seconds="<<seconds<<'\n'
                 <<"user_cpu_seconds="<<secondsFor(usage.ru_utime)-secondsFor(before.ru_utime)<<'\n'
                 <<"system_cpu_seconds="<<secondsFor(usage.ru_stime)-secondsFor(before.ru_stime)<<'\n'
                 <<"peak_rss_bytes="<<usage.ru_maxrss<<'\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr<<"Phase 32 render: "<<e.what()<<'\n';
        return 1;
    }
}
