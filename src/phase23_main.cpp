#include "audio/WavStream.h"
#include "prototype/Phase22VariableTimeMap.h"
#include "prototype/Phase23VariableSpeedEngine.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>

namespace {
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
std::size_t firstChanged(const ts::TimeMap& old,const ts::TimeMap& now) {
    for (std::size_t i=0;i+1<old.starts().size();++i)
        if (now.starts()[i+1]-now.starts()[i]!=old.starts()[i+1]-old.starts()[i])
            return i;
    return old.starts().size();
}
}
int main(int argc,char** argv) {
    if (argc<5 || argc>7) {
        std::cerr<<"Usage: phase23_audio input.wav output.wav 050|075|switch "
                    "diagnostics.csv [request-input-frame] [block-frames]\n";
        return 2;
    }
    try {
        const std::string mode=argv[3];
        if (mode!="050" && mode!="075" && mode!="switch")
            throw std::invalid_argument("Expected 050, 075, or switch");
        if (mode=="switch" ? (argc!=6 && argc!=7) : (argc!=5 && argc!=6))
            throw std::invalid_argument("Switch requires an input-frame request");
        const std::size_t block=(mode=="switch" ? argc==7 : argc==6)
            ? std::stoull(argv[argc-1]) : 16384;
        const ts::WavStreamReader input(argv[1]);
        const auto ratio=mode=="075" ? 4.0/3.0 : 2.0;
        auto config=frozen(input.sampleRate(),input.channels(),ratio);
        const auto start=std::chrono::steady_clock::now();
        ts::Phase13StreamingEngine analysisEngine(frozen(input.sampleRate(),input.channels(),2.0));
        const auto analysis=analysisEngine.analyzeTransientEvents(argv[1]);
        const auto analyzed=std::chrono::steady_clock::now();
        ts::prototype::VariableTimeMap timeline(analysis,input.sampleRate());
        ts::prototype::SpeedPlan plan;
        std::size_t requested=0;
        long long committedOutput=0,planningFence=0;
        if (mode=="switch") {
            requested=std::stoull(argv[5]);
            if (requested>=input.frames()) throw std::invalid_argument("Request past input end");
            committedOutput=std::llround(timeline.fixedHalf()
                .outputPositionForInputSample(double(requested)));
            // Low STFT uses 4096 samples of synthesis lookbehind. Reserve
            // additional FIR lookahead so already committed PCM is immutable.
            planningFence=committedOutput+8192;
            plan=timeline.submit({1,requested,planningFence,50.0});
            if (!plan.applied || plan.truncatedByEnd)
                throw std::runtime_error("A50 could not finish the requested transition");
        }
        const auto& map=mode=="050" ? timeline.fixedHalf()
                      : mode=="075" ? timeline.fixedThreeQuarter() : timeline.current();
        const auto frames=mode=="switch"
            ? static_cast<std::size_t>(std::llround(map.outputPositionForInputSample(
                double(input.frames()))))
            : static_cast<std::size_t>(std::llround(input.frames()*ratio));
        if (!frames) throw std::runtime_error("No output frames");
        std::ofstream diagnostics(argv[4]);
        if (!diagnostics) throw std::runtime_error("Cannot open diagnostics");
        diagnostics<<"frame,input_sample,output_sample,mid_hop,low_hop,high_hop,"
                     "request_input,applied_frame,completion_frame\n";
        const auto& starts=map.starts();
        const auto changed=mode=="switch"
            ? firstChanged(timeline.fixedHalf(),map) : starts.size();
        const auto from=changed>32 ? changed-32 : 0;
        const auto to=std::min(starts.size()-1,changed+32);
        for (auto i=from;i<=to && i+1<starts.size();++i) {
            const auto hop=[&](std::size_t scale) {
                const auto a=std::llround(map.outputPositionForInputSample(double(i*1024)));
                const auto b=std::llround(map.outputPositionForInputSample(double(i*1024+scale)));
                return b-a;
            };
            diagnostics<<i<<','<<i*1024<<','<<starts[i]<<','
                       <<starts[i+1]-starts[i]<<','<<hop(2048)<<','<<hop(256)<<','
                       <<requested<<','<<plan.appliedFrame<<','<<plan.rampEndFrame<<'\n';
        }
        diagnostics.close();
        auto stagePath=std::filesystem::path(argv[4]);
        stagePath.replace_extension(".stages.csv");
        std::ofstream stageTrace(stagePath);
        if (!stageTrace) throw std::runtime_error("Cannot open stage diagnostics");
        stageTrace<<"stage,resolution,frame,input_sample,output_sample,fft,phase,"
                     "ifft,ola,low_fir,high_fir,output_fir\n";
        ts::WavStreamWriter writer(argv[2],input.sampleRate(),input.channels(),frames);
        ts::prototype::Phase23VariableSpeedEngine engine(config);
        const auto processed=engine.process(argv[1],analysis,map,frames,
            [&](const float* const* audio,std::size_t count) { writer.write(audio,count); },
            block,&stageTrace,mode=="switch" ? requested : input.frames()/2);
        writer.finish();
        const auto done=std::chrono::steady_clock::now();
        rusage usage{};
        getrusage(RUSAGE_SELF,&usage);
        std::cout<<"mode="<<mode<<'\n'
                 <<"input_frames="<<input.frames()<<'\n'
                 <<"output_frames="<<frames<<'\n'
                 <<"request_input="<<requested<<'\n'
                 <<"committed_output="<<committedOutput<<'\n'
                 <<"planning_fence_output="<<planningFence<<'\n'
                 <<"applied_input="<<plan.appliedFrame*1024<<'\n'
                 <<"applied_output="<<plan.appliedOutputSample<<'\n'
                 <<"completion_output="<<(plan.applied ? starts[plan.rampEndFrame] : 0)<<'\n'
                 <<"first_changed_frame="<<changed<<'\n'
                 <<"analysis_seconds="<<std::chrono::duration<double>(analyzed-start).count()<<'\n'
                 <<"dsp_seconds="<<std::chrono::duration<double>(done-analyzed).count()<<'\n'
                 <<"peak_rss_kib="<<usage.ru_maxrss/1024<<'\n'
                 <<"ola_ring_samples="<<processed.processing.olaRingSamples<<'\n'
                 <<"fir_ring_samples="<<processed.processing.firRingSamples<<'\n'
                 <<"peak="<<processed.processing.peak<<'\n'
                 <<"timemap_hash="<<processed.processing.timeMapHash<<'\n';
        for (std::size_t i=0;i<3;++i)
            std::cout<<"stage"<<i<<"_fft="<<processed.stages.fft[i]<<'\n'
                     <<"stage"<<i<<"_phase="<<processed.stages.phase[i]<<'\n'
                     <<"stage"<<i<<"_ifft="<<processed.stages.ifft[i]<<'\n'
                     <<"stage"<<i<<"_ola="<<processed.stages.ola[i]<<'\n';
        std::cout<<"low_fir="<<processed.stages.lowFir<<'\n'
                 <<"high_fir="<<processed.stages.highFir<<'\n'
                 <<"output_fir="<<processed.stages.fir<<'\n';
    } catch (const std::exception& error) {
        std::cerr<<"Phase 23: "<<error.what()<<'\n';
        return 1;
    }
}
