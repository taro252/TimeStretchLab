#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase35TransitionEngine.h"
#include "audio/WavStream.h"
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <cmath>
#include <vector>
#include <array>
#include <limits>

using namespace ts;
using namespace ts::prototype;
int main(int argc,char** argv) {
    if (argc!=5) {
        std::cerr<<"Usage: phase36_reference input.wav output.wav initial_speed plans.csv\n";
        return 2;
    }
    try {
        WavStreamReader reader(argv[1]);
        const auto initial=Phase39Speed::fromDouble(std::stod(argv[3]));
        StretchConfig config;
        config.sampleRate=reader.sampleRate();config.channels=reader.channels();
        config.timeRatio=initial.timeRatio();
        config.enableMultiResolution=true;config.qualityMode=QualityMode::Experimental;
        config.enablePhaseLocking=true;config.enableTransientHandling=true;
        config.enableAdaptiveTimeMapping=true;
        config.enablePreciseTransientAnchoring=true;
        config.enableStereoCoherence=true;
        auto analysisConfig=config;analysisConfig.timeRatio=2.0;
        const auto analysis=Phase13StreamingEngine(analysisConfig).analyzeTransientEvents(argv[1]);
        Phase39TimeMap timeline(analysis,reader.sampleRate(),initial);
        std::vector<std::pair<std::size_t,bool>> modes;
        std::ifstream csv(argv[4]);
        std::string line;std::getline(csv,line);
        auto previous=initial;
        while (std::getline(csv,line)) {
            std::istringstream row(line);
            std::vector<std::string> fields;
            while (std::getline(row,line,',')) fields.push_back(line);
            if (fields.size()<14) throw std::runtime_error("Invalid plan row");
            const auto generation=std::stoull(fields[0]);
            const auto requestedInput=std::stoull(fields[2]);
            const auto target=Phase39Speed::fromDouble(std::stod(fields[4]));
            const auto fence=std::stoll(fields[5]);
            const auto expectedFrame=std::stoull(fields[8]);
            const auto plan=timeline.submit({generation,target,requestedInput,fence,50.0});
            if (!plan.applied() || plan.appliedFrame!=expectedFrame)
                throw std::runtime_error("Offline TimeMap replay differs");
            if ((target.value()<0.50)!=(previous.value()<0.50))
                modes.emplace_back(plan.appliedFrame*1024,target.value()<0.50);
            previous=target;
        }
        const auto outputFrames=static_cast<std::size_t>(std::llround(
            timeline.current().outputPositionForInputSample(double(reader.frames()))));
        constexpr std::array<std::size_t,3> fft{8192,4096,1024};
        constexpr std::array<std::size_t,3> normalHop{2048,1024,256};
        std::array<long long,3> minHop{},maxHop{};
        for (std::size_t r=0;r<3;++r) {
            minHop[r]=std::numeric_limits<long long>::max();
            auto input=std::size_t{0};
            auto previousOutput=std::llround(timeline.current().outputPositionForInputSample(0));
            while (input<reader.frames()) {
                bool half=initial.value()<0.50;
                for (const auto& [at,mode]:modes)
                    if (input>=at) half=mode;
                input+=normalHop[r]/(half ? 2 : 1);
                const auto nextOutput=std::llround(
                    timeline.current().outputPositionForInputSample(double(input)));
                const auto hop=nextOutput-previousOutput;
                minHop[r]=std::min(minHop[r],hop);
                maxHop[r]=std::max(maxHop[r],hop);
                if (hop<=0 || hop>=static_cast<long long>(fft[r]))
                    throw std::runtime_error("Unsafe synthesis hop");
                previousOutput=nextOutput;
            }
        }
        if (std::string(argv[2])=="--hops") {
            std::cout<<"low,"<<minHop[0]<<','<<maxHop[0]<<'\n'
                     <<"mid,"<<minHop[1]<<','<<maxHop[1]<<'\n'
                     <<"high,"<<minHop[2]<<','<<maxHop[2]<<'\n';
            return 0;
        }
        if (std::string(argv[2])=="-") {
            std::cout<<"input_sample,output_sample\n";
            for (std::size_t i=0;i<timeline.current().starts().size();++i)
                std::cout<<i*1024<<','<<timeline.current().starts()[i]<<'\n';
            return 0;
        }
        const auto result=Phase35TransitionEngine(config).processWav(
            argv[1],argv[2],timeline.current(),modes,outputFrames);
        std::cout<<"frames="<<result.outputFrames<<"\nchanges="<<modes.size()
                 <<"\nlow_hop="<<minHop[0]<<':'<<maxHop[0]
                 <<"\nmid_hop="<<minHop[1]<<':'<<maxHop[1]
                 <<"\nhigh_hop="<<minHop[2]<<':'<<maxHop[2]<<'\n';
    } catch (const std::exception& error) {
        std::cerr<<"Phase 39 reference: "<<error.what()<<'\n';return 1;
    }
}
