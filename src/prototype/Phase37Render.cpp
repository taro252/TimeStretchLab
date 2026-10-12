#include "prototype/Phase37HighSpeedMap.h"
#include "prototype/Phase37SynthesisEngine.h"
#include "audio/WavStream.h"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <sys/resource.h>

namespace {
using Clock=std::chrono::steady_clock;
ts::StretchConfig configuration(std::uint32_t rate,int channels,double ratio) {
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
    if (argc!=5) {
        std::cerr<<"Usage: phase37_render input.wav output.wav speed A|B\n";
        return 2;
    }
    try {
        const auto speed=std::stod(argv[3]);
        const auto micros=std::llround(speed*1000000.0);
        if (!std::isfinite(speed) || speed<1.0 || speed>2.0 ||
            std::abs(speed*1000000.0-micros)>1e-7 ||
            (std::string(argv[4])!="A" && std::string(argv[4])!="B"))
            throw std::invalid_argument("Invalid research speed or mode");
        const auto normalized=double(micros)/1000000.0;
        const double ratio=1.0/normalized;
        ts::WavStreamReader source(argv[1]);
        auto config=configuration(source.sampleRate(),static_cast<int>(source.channels()),ratio);
        const auto outputFrames=static_cast<std::size_t>(std::llround(source.frames()*ratio));
        rusage before{};getrusage(RUSAGE_SELF,&before);
        const auto begin=Clock::now();
        auto analysisConfig=config;
        analysisConfig.timeRatio=1.0;
        ts::Phase13StreamingEngine analyzer(analysisConfig);
        const auto analysis=analyzer.analyzeTransientEvents(argv[1]);
        const auto analyzed=Clock::now();
        ts::prototype::Phase37MapDiagnostics diagnostics;
        const auto map=ts::prototype::phase37Map(analysis,source.frames(),ratio,
                                                 std::string(argv[4])=="B",&diagnostics);
        const auto mapped=Clock::now();
        if (std::string(argv[2])=="-") {
            std::vector<bool> eventPeak(map.starts().size());
            for (const auto& event:analysis.events())
                if (event.peakFrame<eventPeak.size()) eventPeak[event.peakFrame]=true;
            std::cout<<"input_sample,output_sample,event_peak\n";
            for (std::size_t i=0;i<map.starts().size();++i)
                std::cout<<i*1024<<','<<map.starts()[i]<<','<<int(eventPeak[i])<<'\n';
            return 0;
        }
        ts::WavStreamWriter writer(argv[2],source.sampleRate(),source.channels(),outputFrames);
        ts::prototype::Phase37SynthesisEngine processor(config);
        const auto result=processor.process(argv[1],analysis,map,outputFrames,
            [&](const float* const* audio,std::size_t frames){writer.write(audio,frames);});
        writer.finish();
        const auto finished=Clock::now();
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        const auto seconds=[](auto start,auto end) {
            return std::chrono::duration<double>(end-start).count();
        };
        const auto cpu=[](const timeval& value) {
            return value.tv_sec+value.tv_usec/1000000.0;
        };
        std::cout<<std::setprecision(12)
            <<"mode="<<argv[4]<<'\n'<<"speed="<<normalized<<'\n'
            <<"input_frames="<<source.frames()<<'\n'
            <<"output_frames="<<result.processing.outputFrames<<'\n'
            <<"events="<<diagnostics.events<<'\n'
            <<"protected_segments="<<diagnostics.protectedSegments<<'\n'
            <<"capacity_limited_segments="<<diagnostics.capacityLimitedSegments<<'\n'
            <<"dense_fallback_segments="<<diagnostics.denseFallbackSegments<<'\n'
            <<"min_local_ratio="<<diagnostics.minimumLocalRatio<<'\n'
            <<"max_local_ratio="<<diagnostics.maximumLocalRatio<<'\n'
            <<"max_anchor_error_samples="<<diagnostics.maximumAnchorError<<'\n'
            <<"min_mid_hop="<<diagnostics.minimumMidHop<<'\n'
            <<"max_mid_hop="<<diagnostics.maximumMidHop<<'\n'
            <<"analysis_seconds="<<seconds(begin,analyzed)<<'\n'
            <<"map_seconds="<<seconds(analyzed,mapped)<<'\n'
            <<"dsp_seconds="<<seconds(mapped,finished)<<'\n'
            <<"wall_seconds="<<seconds(begin,finished)<<'\n'
            <<"user_cpu_seconds="<<cpu(usage.ru_utime)-cpu(before.ru_utime)<<'\n'
            <<"system_cpu_seconds="<<cpu(usage.ru_stime)-cpu(before.ru_stime)<<'\n'
            <<"peak_rss_bytes="<<usage.ru_maxrss<<'\n';
        if (result.processing.outputFrames!=outputFrames)
            throw std::runtime_error("Incorrect output length");
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"Phase 37 render: "<<error.what()<<'\n';return 1;
    }
}
