#include "audio/WavStream.h"
#include "prototype/Phase23VariableSpeedEngine.h"
#include "prototype/Phase28ArbitraryTimeMap.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <vector>

namespace {
using ts::prototype::DecimalSpeed;
struct Change { std::size_t inputSample; DecimalSpeed target; };
DecimalSpeed speedFromText(const std::string& value) {
    std::size_t used=0;
    const double number=std::stod(value,&used);
    if (used!=value.size()) throw std::invalid_argument("Invalid speed text");
    return DecimalSpeed::fromDouble(number);
}
std::vector<Change> readChanges(const std::string& path,std::size_t inputFrames) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("Cannot open speed schedule");
    std::vector<Change> changes;
    std::string line;
    std::size_t previous=0;
    while (std::getline(input,line)) {
        if (line.empty() || line[0]=='#' || line=="input_sample,target_speed") continue;
        const auto comma=line.find(',');
        if (comma==std::string::npos) throw std::invalid_argument("Invalid schedule row");
        std::size_t used=0;
        const auto position=std::stoull(line.substr(0,comma),&used);
        if (used!=comma || position>=inputFrames ||
            (!changes.empty() && position<=previous))
            throw std::invalid_argument("Schedule samples must increase inside the input");
        changes.push_back({position,speedFromText(line.substr(comma+1))});
        previous=position;
    }
    return changes;
}
ts::StretchConfig frozen(std::uint32_t rate,std::size_t channels,double ratio) {
    ts::StretchConfig config;
    config.sampleRate=rate;
    config.channels=static_cast<int>(channels);
    config.timeRatio=ratio;
    config.enableMultiResolution=true;
    config.qualityMode=ts::QualityMode::Experimental;
    config.enablePhaseLocking=true;
    config.enableTransientHandling=true;
    config.enableAdaptiveTimeMapping=true;
    config.enablePreciseTransientAnchoring=true;
    config.enableStereoCoherence=true;
    return config;
}
std::uint64_t hashMap(const ts::TimeMap& map) {
    std::uint64_t hash=14695981039346656037ULL;
    for (const auto start:map.starts()) {
        hash^=static_cast<std::uint64_t>(start);
        hash*=1099511628211ULL;
    }
    return hash;
}
}
int main(int argc,char** argv) {
    if (argc<6 || argc>7) {
        std::cerr<<"Usage: phase29_audio input.wav output.wav initial_speed "
                    "schedule.csv diagnostics-prefix [block-frames]\n";
        return 2;
    }
    try {
        const auto initial=speedFromText(argv[3]);
        const auto block=argc==7 ? std::stoull(argv[6]) : 16384;
        if (block<8192 || block>65536)
            throw std::invalid_argument("Output block must be 8192..65536");
        const ts::WavStreamReader input(argv[1]);
        if (input.frames()==0) throw std::invalid_argument("Empty WAV");
        const auto schedule=readChanges(argv[4],input.frames());
        const auto begin=std::chrono::steady_clock::now();
        ts::Phase13StreamingEngine analyzer(frozen(input.sampleRate(),input.channels(),2.0));
        const auto analysis=analyzer.analyzeTransientEvents(argv[1]);
        const auto analyzed=std::chrono::steady_clock::now();
        ts::prototype::Phase28ArbitraryTimeMap timeline(analysis,input.sampleRate(),initial);
        std::ofstream planLog(std::string(argv[5])+".plans.csv");
        if (!planLog) throw std::runtime_error("Cannot create plan diagnostics");
        planLog<<"generation,request_input,target_speed,published_output,"
                   "planning_fence,outcome,applied_frame,applied_output,completion_frame,"
                   "completion_output,skipped_events,planning_ms,map_bytes\n";
        long long completed=0;
        std::size_t probe=input.frames()/2;
        for (std::size_t i=0;i<schedule.size();++i) {
            const auto& change=schedule[i];
            if (i==0) probe=change.inputSample;
            const auto requested=std::llround(timeline.current().outputPositionForInputSample(
                double(change.inputSample)));
            // The first 8192 samples model PCM already committed at request time.
            // A second 8192-sample dependency fence protects the earlier PCM
            // from the future OLA windows and both non-causal FIR branches.
            const auto published=std::max(completed,requested+8192);
            const auto planningFence=published+8192;
            const auto start=std::chrono::steady_clock::now();
            const auto plan=timeline.submit({i+1,change.target,change.inputSample,
                                             planningFence,50.0});
            const auto elapsed=std::chrono::duration<double,std::milli>(
                std::chrono::steady_clock::now()-start).count();
            planLog<<i+1<<','<<change.inputSample<<','<<std::fixed
                   <<std::setprecision(6)<<change.target.value()<<','<<published<<','
                   <<planningFence<<','
                   <<static_cast<int>(plan.outcome)<<','<<plan.appliedFrame<<','
                   <<plan.appliedOutputSample<<','<<plan.rampEndFrame<<','
                   <<plan.completionOutputSample<<','<<plan.protectedEventsSkipped<<','
                   <<elapsed<<','<<timeline.fixedMapBytes()<<'\n';
            if (!plan.applied() || !timeline.monotonic() || timeline.touchesProtected(plan))
                throw std::runtime_error("Speed request could not safely complete");
            for (const auto& range:timeline.measureHops())
                if (range.minimum<=0 || range.nonPositive || range.outsideWindow)
                    throw std::runtime_error("Unsafe synthesis hop");
            completed=plan.completionOutputSample;
        }
        planLog.close();
        const auto& map=timeline.current();
        const auto frames=schedule.empty()
            ? static_cast<std::size_t>(std::round(input.frames()*initial.timeRatio()))
            : static_cast<std::size_t>(std::llround(
                map.outputPositionForInputSample(double(input.frames()))));
        if (frames==0) throw std::runtime_error("No output frames");
        std::ofstream stageLog(std::string(argv[5])+".stages.csv");
        if (!stageLog) throw std::runtime_error("Cannot create stage diagnostics");
        stageLog<<"stage,resolution,frame,input_sample,output_sample,fft,phase,"
                    "ifft,ola,low_fir,high_fir,output_fir\n";
        ts::WavStreamWriter writer(argv[2],input.sampleRate(),input.channels(),frames);
        ts::prototype::Phase23VariableSpeedEngine synthesizer(
            frozen(input.sampleRate(),input.channels(),initial.timeRatio()));
        const auto result=synthesizer.process(argv[1],analysis,map,frames,
            [&](const float* const* audio,std::size_t count){ writer.write(audio,count); },
            block,&stageLog,probe);
        writer.finish();
        const auto done=std::chrono::steady_clock::now();
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        std::cout<<"input_frames="<<input.frames()<<'\n'
                 <<"output_frames="<<frames<<'\n'
                 <<"changes="<<schedule.size()<<'\n'
                 <<"map_hash="<<hashMap(map)<<'\n'
                 <<"analysis_seconds="<<std::chrono::duration<double>(analyzed-begin).count()<<'\n'
                 <<"dsp_seconds="<<std::chrono::duration<double>(done-analyzed).count()<<'\n'
                 <<"peak_rss_bytes="<<usage.ru_maxrss<<'\n'
                 <<"peak="<<result.processing.peak<<'\n';
        constexpr const char* labels[]={"low","mid","high"};
        const auto hops=timeline.measureHops();
        for (std::size_t i=0;i<3;++i)
            std::cout<<labels[i]<<"_hop_min="<<hops[i].minimum<<'\n'
                     <<labels[i]<<"_hop_max="<<hops[i].maximum<<'\n'
                     <<labels[i]<<"_fft="<<result.stages.fft[i]<<'\n'
                     <<labels[i]<<"_phase="<<result.stages.phase[i]<<'\n'
                     <<labels[i]<<"_ifft="<<result.stages.ifft[i]<<'\n'
                     <<labels[i]<<"_ola="<<result.stages.ola[i]<<'\n';
        std::cout<<"low_fir="<<result.stages.lowFir<<'\n'
                 <<"high_fir="<<result.stages.highFir<<'\n'
                 <<"output_fir="<<result.stages.fir<<'\n';
    } catch (const std::exception& error) {
        std::cerr<<"Phase 29: "<<error.what()<<'\n';
        return 1;
    }
}
