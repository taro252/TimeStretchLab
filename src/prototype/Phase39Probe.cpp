#include "prototype/Phase36StreamingSpeedEngine.h"
#include "prototype/Phase37HighSpeedMap.h"
#include "prototype/Phase37SynthesisEngine.h"
#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase35TransitionEngine.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <cstring>
#include <iostream>
#include <stdexcept>

int main(int argc,char** argv) {
    if (argc!=4 && argc!=6) { std::cerr<<"Usage: phase39_probe input.wav output.wav speed [request_output_frame target_speed]\n";return 2; }
    try {
        const double speed=std::stod(argv[3]);
        const auto initial=ts::prototype::Phase39Speed::fromDouble(speed);
        ts::WavStreamReader reader(argv[1]);
        ts::StretchConfig config;
        config.sampleRate=reader.sampleRate();config.channels=reader.channels();
        config.timeRatio=1.0/speed;
        config.enableMultiResolution=true;config.qualityMode=ts::QualityMode::Experimental;
        config.enablePhaseLocking=true;config.enableTransientHandling=true;
        config.enableAdaptiveTimeMapping=true;config.enablePreciseTransientAnchoring=true;
        config.enableStereoCoherence=true;
        auto analysisConfig=config;analysisConfig.timeRatio=2.0;
        auto analysis=ts::Phase13StreamingEngine(analysisConfig).analyzeTransientEvents(argv[1]);
        ts::prototype::Phase39TimeMap timeline(analysis,reader.sampleRate(),initial);
        const auto frames=static_cast<std::size_t>(std::llround(reader.frames()*config.timeRatio));
        auto length=frames;
        const auto scratch=std::string(argv[2])+".raw.tmp";
        std::ofstream raw(scratch,std::ios::binary|std::ios::trunc);
        if (!raw) throw std::runtime_error("scratch open failed");
        std::vector<float> interleaved(2048*reader.channels());
        std::vector<std::pair<std::size_t,bool>> modes;
        const auto request=argc==6 ? std::stoull(argv[4]) : 0;
        const auto target=argc==6 ? ts::prototype::Phase39Speed::fromDouble(std::stod(argv[5])) : initial;
        bool attempted=false;
        auto result=ts::prototype::Phase36StreamingSpeedEngine(config).process(argv[1],analysis,
            timeline.current(),frames,2048,
            [&](const float* const* audio,std::size_t count,const std::function<void()>& poll) {
                for (std::size_t i=0;i<count;++i)
                    for (std::size_t c=0;c<reader.channels();++c)
                        interleaved[i*reader.channels()+c]=audio[c][i];
                raw.write(reinterpret_cast<const char*>(interleaved.data()),
                          static_cast<std::streamsize>(count*reader.channels()*sizeof(float)));
                if (!raw) throw std::runtime_error("scratch write failed");
                poll();
            },[&](const ts::prototype::Phase36StreamingSpeedEngine::Frontier& f,
                   ts::TimeMap& map,std::size_t& outputFrames,
                   std::vector<std::pair<std::size_t,bool>>& changes) {
                if (argc!=6 || attempted || f.preparedOutput<request) return;
                attempted=true;
                auto fence=f.preparedOutput;
                constexpr std::size_t hops[3]{2048,1024,256};
                const auto& starts=map.starts();
                for (std::size_t r=0;r<3;++r) {
                    const auto node=std::min(starts.size()-1,f.lastProcessedInput[r]/1024+1);
                    const auto density=std::min(starts.size()-1,(f.nextInput[r]+hops[r]+1023)/1024);
                    fence=std::max({fence,static_cast<std::size_t>(starts[node]),
                        static_cast<std::size_t>(starts[density]),f.finalizedOla[r]});
                }
                for (const auto source:f.firstUnprocessedFirSource)
                    fence=std::max(fence,source+4096);
                const auto requestedNode=static_cast<std::size_t>(
                    std::lower_bound(starts.begin(),starts.end(),static_cast<long long>(f.preparedOutput))-
                    starts.begin());
                const auto requestedInput=requestedNode*1024;
                auto proposal=timeline.submit({1,target,requestedInput,static_cast<long long>(fence),50.0});
                if (!proposal.applied()) {
                    std::cerr<<"plan rejected="<<int(proposal.outcome)<<" fence="<<fence<<'\n';return;
                }
                if (!timeline.monotonic() || timeline.touchesProtected(proposal))
                    throw std::runtime_error("unsafe plan");
                if ((initial.value()<0.50)!=(target.value()<0.50))
                    changes.emplace_back(proposal.appliedFrame*1024,target.value()<0.50);
                map=timeline.current();
                outputFrames=static_cast<std::size_t>(std::llround(
                    map.outputPositionForInputSample(double(reader.frames()))));
                length=outputFrames;
                std::cout<<"requested="<<request<<" applied="<<proposal.appliedOutputSample
                         <<" completed="<<proposal.completionOutputSample
                         <<" fence="<<fence<<" frame="<<proposal.appliedFrame<<'\n';
            },modes);
        raw.close();
        std::ifstream rawInput(scratch,std::ios::binary);
        ts::WavStreamWriter writer(argv[2],reader.sampleRate(),reader.channels(),length);
        std::vector<std::vector<float>> planar(reader.channels(),std::vector<float>(2048));
        std::vector<const float*> pointers(reader.channels());
        for (std::size_t c=0;c<reader.channels();++c) pointers[c]=planar[c].data();
        for (std::size_t start=0;start<length;start+=2048) {
            const auto count=std::min<std::size_t>(2048,length-start);
            rawInput.read(reinterpret_cast<char*>(interleaved.data()),
                          static_cast<std::streamsize>(count*reader.channels()*sizeof(float)));
            if (rawInput.gcount()!=static_cast<std::streamsize>(count*reader.channels()*sizeof(float)))
                throw std::runtime_error("scratch length differs");
            for (std::size_t i=0;i<count;++i)
                for (std::size_t c=0;c<reader.channels();++c)
                    planar[c][i]=interleaved[i*reader.channels()+c];
            writer.write(pointers.data(),count);
        }
        writer.finish();
        std::filesystem::remove(scratch);
        if (argc==4 && speed>=1.0) {
            const auto control=ts::prototype::Phase37SynthesisEngine(config).process(
                argv[1],analysis,timeline.current(),length,
                [](const float* const*,std::size_t){},8192);
            const auto& a=result.stages;
            const auto& b=control.stages;
            std::cout<<"stage_fft="<<(a.fft==b.fft)
                     <<" stage_phase="<<(a.phase==b.phase)
                     <<" stage_ifft="<<(a.ifft==b.ifft)
                     <<" stage_ola="<<(a.ola==b.ola)
                     <<" stage_low_fir="<<(a.lowFir==b.lowFir)
                     <<" stage_high_fir="<<(a.highFir==b.highFir)
                     <<" stage_final="<<(a.fir==b.fir)<<'\n';
        }
        if (argc==6 && attempted) {
            const auto reference=std::string(argv[2])+".reference.wav";
            ts::Phase35TransitionEngine(config).processWav(argv[1],reference,
                timeline.current(),modes,length,8192);
            std::ifstream a(argv[2],std::ios::binary),b(reference,std::ios::binary);
            std::array<char,65536> left{},right{};
            std::size_t differing=0,total=0;
            while (a && b) {
                a.read(left.data(),left.size());b.read(right.data(),right.size());
                if (a.gcount()!=b.gcount()) throw std::runtime_error("reference length differs");
                for (std::streamsize i=0;i<a.gcount();++i) {
                    differing+=left[i]!=right[i];++total;
                }
            }
            std::cout<<"reference_different_bytes="<<differing<<" total_bytes="<<total<<'\n';
        }
        std::cout<<"frames="<<result.processing.outputFrames<<" attempted="<<attempted<<"\n";
    } catch (const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
