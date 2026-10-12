#include "audio/WavStream.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include "dsp/Phase13StreamingEngine.h"
#include "prototype/Phase31ResearchEngine.h"
#include "prototype/Phase35TimeMap.h"
#include "prototype/Phase35TransitionEngine.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <vector>

namespace {
struct Change { std::size_t inputSample; ts::prototype::Phase35Speed target; };
ts::prototype::Phase35Speed speedFromText(const std::string& text) {
    std::size_t used=0;
    const double value=std::stod(text,&used);
    if (used!=text.size()) throw std::invalid_argument("Invalid speed text");
    return ts::prototype::Phase35Speed::fromDouble(value);
}
ts::StretchConfig frozen(std::uint32_t rate,std::size_t channels,double ratio) {
    ts::StretchConfig c;
    c.sampleRate=rate;c.channels=static_cast<int>(channels);c.timeRatio=ratio;
    c.enableMultiResolution=true;c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
std::vector<Change> readSchedule(const std::string& path,std::size_t inputFrames) {
    std::ifstream file(path);
    if (!file) throw std::runtime_error("Cannot open speed schedule");
    std::vector<Change> changes;
    std::string line;
    while (std::getline(file,line)) {
        if (line.empty() || line[0]=='#' || line=="input_sample,target_speed") continue;
        const auto comma=line.find(',');
        if (comma==std::string::npos) throw std::invalid_argument("Invalid speed schedule");
        std::size_t inputUsed=0;
        const auto input=std::stoull(line.substr(0,comma),&inputUsed);
        if (inputUsed!=comma) throw std::invalid_argument("Invalid input sample text");
        if (input>=inputFrames || (!changes.empty() && input<=changes.back().inputSample))
            throw std::invalid_argument("Speed requests must be strictly ordered inside input");
        const auto text=line.substr(comma+1);
        changes.push_back({static_cast<std::size_t>(input),
                           speedFromText(text)});
    }
    return changes;
}
}
int main(int argc,char** argv) {
    if (argc<6 || argc>8) {
        std::cerr<<"Usage: phase35_render input.wav output.wav initial_speed "
                    "schedule.csv diagnostics-prefix [output-block=16384] "
                    "[--prototype-fixed]\n";
        return 2;
    }
    try {
        const auto speed=speedFromText(argv[3]);
        const std::size_t block=argc>=7?std::stoull(argv[6]):16384;
        const bool prototypeFixed=argc==8 && std::string(argv[7])=="--prototype-fixed";
        if (argc==8 && !prototypeFixed) throw std::invalid_argument("Unknown diagnostic option");
        if (block<8192 || block>65536) throw std::invalid_argument("Invalid output block");
        const ts::WavStreamReader input(argv[1]);
        if (input.frames()==0) throw std::invalid_argument("Empty input");
        const auto changes=readSchedule(argv[4],input.frames());
        const auto config=frozen(input.sampleRate(),input.channels(),speed.timeRatio());
        rusage before{};getrusage(RUSAGE_SELF,&before);
        const auto begun=std::chrono::steady_clock::now();
        if (changes.empty() && !prototypeFixed) {
            const auto result=speed.value()<0.50
                ? ts::Phase31ResearchEngine(config).processWav(argv[1],argv[2],block)
                : ts::ChunkedTimeStretchEngine(config).processWav(
                    argv[1],argv[2],block,ts::AblationMode::Full);
            std::cout<<"mode=fixed\ninput_frames="<<input.frames()
                     <<"\noutput_frames="<<result.outputFrames
                     <<"\nmap_hash="<<result.timeMapHash<<'\n';
        } else {
            ts::Phase13StreamingEngine analyzer(frozen(input.sampleRate(),input.channels(),2.0));
            const auto analysis=analyzer.analyzeTransientEvents(argv[1]);
            ts::prototype::Phase35TimeMap planner(analysis,input.sampleRate(),speed);
            std::ofstream plans(std::string(argv[5])+".plans.csv");
            std::ofstream frames(std::string(argv[5])+".frames.csv");
            if (!plans || !frames) throw std::runtime_error("Cannot open diagnostics");
            plans<<"generation,request_input,target_speed,published_output,planning_fence,"
                   "applied_frame,applied_output,completion_frame,completion_output,"
                   "protected_events_skipped,planning_ms\n";
            frames<<"fft,frame,input_sample,analysis_hop,output_sample,synthesis_hop,reset,"
                     "peak_bin,analysis_phase_rad,synthesis_phase_rad,peak_magnitude\n";
            std::vector<std::pair<std::size_t,bool>> modeChanges;
            long long previousComplete=0;
            for (std::size_t i=0;i<changes.size();++i) {
                const auto& change=changes[i];
                const auto requested=std::llround(planner.current().outputPositionForInputSample(
                    double(change.inputSample)));
                // Offline prototype: model an 8192-sample committed prefix and
                // an additional 8192-sample OLA/FIR dependency fence.
                const auto published=std::max(previousComplete,requested+8192);
                const auto fence=published+8192;
                const auto planStart=std::chrono::steady_clock::now();
                const auto plan=planner.submit({i+1,change.target,change.inputSample,fence,50.0});
                const auto planMs=std::chrono::duration<double,std::milli>(
                    std::chrono::steady_clock::now()-planStart).count();
                plans<<i+1<<','<<change.inputSample<<','<<change.target.value()<<','
                     <<published<<','<<fence<<','<<plan.appliedFrame<<','
                     <<plan.appliedOutputSample<<','<<plan.rampEndFrame<<','
                     <<plan.completionOutputSample<<','<<plan.protectedEventsSkipped<<','
                     <<planMs<<'\n';
                if (!plan.applied() || !planner.monotonic() || planner.touchesProtected(plan))
                    throw std::runtime_error("No safe speed transition interval");
                modeChanges.emplace_back(plan.appliedFrame*1024,change.target.value()<0.50);
                previousComplete=plan.completionOutputSample;
            }
            const auto& map=planner.current();
            const auto outputFrames=changes.empty()
                ? static_cast<std::size_t>(std::round(input.frames()*speed.timeRatio()))
                : static_cast<std::size_t>(std::llround(
                    map.outputPositionForInputSample(double(input.frames()))));
            const auto result=ts::Phase35TransitionEngine(config).processWav(
                argv[1],argv[2],map,modeChanges,outputFrames,block,&frames);
            std::cout<<"mode=transition\ninput_frames="<<input.frames()
                     <<"\noutput_frames="<<result.outputFrames
                     <<"\nmap_hash="<<result.timeMapHash
                     <<"\nchanges="<<changes.size()<<'\n';
        }
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        const auto seconds=[](const timeval& value) {
            return value.tv_sec+value.tv_usec/1000000.0;
        };
        std::cout<<"elapsed_seconds="<<std::chrono::duration<double>(
            std::chrono::steady_clock::now()-begun).count()
                 <<"\nuser_cpu_seconds="<<seconds(usage.ru_utime)-seconds(before.ru_utime)
                 <<"\nsystem_cpu_seconds="<<seconds(usage.ru_stime)-seconds(before.ru_stime)
                 <<"\npeak_rss_bytes="<<usage.ru_maxrss<<'\n';
    } catch (const std::exception& error) {
        std::cerr<<"Phase 35: "<<error.what()<<'\n';
        return 1;
    }
}
