#include "prototype/Phase39TimeMap.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace ts;
using namespace ts::prototype;

int main(int argc,char** argv) {
    if (argc!=8 && argc!=9) {
        std::cerr<<"Usage: phase41_map_trace input.wav from to requested_input fence A|B|C output.csv [hold-density|delay-density]\n";
        return 2;
    }
    try {
        WavStreamReader reader(argv[1]);
        const auto from=Phase39Speed::fromDouble(std::stod(argv[2]));
        const auto to=Phase39Speed::fromDouble(std::stod(argv[3]));
        const auto requested=std::stoull(argv[4]);
        const auto fence=std::stoll(argv[5]);
        const std::string method=argv[6];
        const std::string densityOption=argc==9 ? argv[8] : "";
        if (argc==9 && densityOption!="hold-density" && densityOption!="delay-density")
            throw std::invalid_argument("Unknown diagnostic density option");
        const auto strategy=method=="A" ? Phase39Planning::A :
            method=="B" ? Phase39Planning::B :
            method=="C" ? Phase39Planning::C :
            throw std::invalid_argument("Strategy");
        StretchConfig config;
        config.sampleRate=reader.sampleRate();config.channels=reader.channels();
        config.timeRatio=2.0;
        config.enableMultiResolution=true;
        config.qualityMode=QualityMode::Experimental;
        config.enablePhaseLocking=true;
        config.enableTransientHandling=true;
        config.enableAdaptiveTimeMapping=true;
        config.enablePreciseTransientAnchoring=true;
        config.enableStereoCoherence=true;
        const auto analysis=Phase13StreamingEngine(config).analyzeTransientEvents(argv[1]);
        Phase39TimeMap timeline(analysis,reader.sampleRate(),from,strategy);
        const auto old=timeline.current();
        const auto target=timeline.fixed(to);
        const auto plan=timeline.submit({1,to,requested,fence,50.0});
        if (!plan.applied()) throw std::runtime_error("Transition not applied");
        const auto& next=timeline.current();
        std::ofstream output(argv[7]);
        if (!output) throw std::runtime_error("CSV open failed");
        output<<"resolution,analysis_frame,input_sample,output_sample,old_hop,target_hop,actual_hop,hop_change,local_speed,protected,event_peak_frame,density_half,mid_node,ramp_weight_estimate,cumulative_safe_ms\n";
        constexpr int baseHop[3]={2048,1024,256};
        constexpr int fftSize[3]={8192,4096,1024};
        const auto finalInput=analysis.inputFrames()+4096;
        const auto traceBegin=plan.appliedFrame*1024>65536 ?
            plan.appliedFrame*1024-65536 : 0;
        for (int resolution=0;resolution<3;++resolution) {
            const bool oldHalf=from.value()<0.50;
            const bool newHalf=to.value()<0.50;
            std::size_t input=0,previousInput=0;
            long long previousOld=0,previousTarget=0,previousActual=0,previousHop=0;
            double safeElapsed=0;
            for (std::size_t frame=0;input<finalInput;++frame) {
                const auto densityFrame=densityOption=="delay-density" ?
                    plan.rampEndFrame : plan.appliedFrame;
                const auto half=densityOption=="hold-density" ? oldHalf :
                    (input<densityFrame*1024 ? oldHalf : newHalf);
                const int analysisHop=half ? baseHop[resolution]/2 : baseHop[resolution];
                const auto oldAt=std::llround(old.outputPositionForInputSample(double(input)));
                const auto targetAt=std::llround(target->outputPositionForInputSample(double(input)));
                const auto actualAt=std::llround(next.outputPositionForInputSample(double(input)));
                const auto oldHop=frame ? oldAt-previousOld : 0;
                const auto targetHop=frame ? targetAt-previousTarget : 0;
                const auto actualHop=frame ? actualAt-previousActual : 0;
                const auto midNode=input/1024;
                int protectedFrame=0;
                long long nearestEvent=-1;
                std::size_t distance=std::numeric_limits<std::size_t>::max();
                for (const auto& event:analysis.events()) {
                    const auto begin=event.onsetFrame>2 ? event.onsetFrame-2 : 0;
                    const auto end=std::max(event.endFrame,event.peakFrame)+5;
                    if (midNode>=begin && midNode<=end) protectedFrame=1;
                    const auto gap=midNode>event.peakFrame ? midNode-event.peakFrame : event.peakFrame-midNode;
                    if (gap<distance) {distance=gap;nearestEvent=event.peakFrame;}
                }
                const double weight=frame && targetHop!=oldHop ?
                    double(actualHop-oldHop)/double(targetHop-oldHop) : 0.0;
                if (resolution==1 && frame && !protectedFrame &&
                    input>=plan.appliedFrame*1024 && input<=plan.rampEndFrame*1024)
                    safeElapsed+=std::max(1LL,std::min(oldHop,targetHop)-1)/
                        (double(reader.sampleRate())/1000.0);
                if (input>=traceBegin &&
                    input<=plan.rampEndFrame*1024+65536)
                    output<<resolution<<','<<frame<<','<<input<<','<<actualAt<<','
                          <<oldHop<<','<<targetHop<<','<<actualHop<<','
                          <<(frame ? actualHop-previousHop : 0)<<','
                          <<(frame && actualHop>0 ?
                             double(input-previousInput)/double(actualHop) : 0.0)<<','
                          <<protectedFrame<<','<<nearestEvent<<','<<int(half)<<','
                          <<midNode<<','<<weight<<','<<safeElapsed<<'\n';
                if (frame && (actualHop<=0 || actualHop>=fftSize[resolution]))
                    throw std::runtime_error("Unsafe hop");
                previousInput=input;previousOld=oldAt;
                previousTarget=targetAt;previousActual=actualAt;
                previousHop=actualHop;
                input+=analysisHop;
            }
        }
        std::cout<<"applied_frame="<<plan.appliedFrame<<"\nramp_end_frame="
                 <<plan.rampEndFrame<<"\napplied_output="<<plan.appliedOutputSample
                 <<"\ncompletion_output="<<plan.completionOutputSample<<'\n';
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<'\n';return 1;
    }
}
