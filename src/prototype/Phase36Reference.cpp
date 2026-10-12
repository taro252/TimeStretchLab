#include "prototype/Phase35TimeMap.h"
#include "prototype/Phase35TransitionEngine.h"
#include "audio/WavStream.h"
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <cmath>
#include <vector>

using namespace ts;
using namespace ts::prototype;
int main(int argc,char** argv) {
    if (argc!=5) {
        std::cerr<<"Usage: phase36_reference input.wav output.wav initial_speed plans.csv\n";
        return 2;
    }
    try {
        WavStreamReader reader(argv[1]);
        const auto initial=Phase35Speed::fromDouble(std::stod(argv[3]));
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
        Phase35TimeMap timeline(analysis,reader.sampleRate(),initial);
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
            const auto target=Phase35Speed::fromDouble(std::stod(fields[4]));
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
        if (std::string(argv[2])=="-") {
            std::cout<<"input_sample,output_sample\n";
            for (std::size_t i=0;i<timeline.current().starts().size();++i)
                std::cout<<i*1024<<','<<timeline.current().starts()[i]<<'\n';
            return 0;
        }
        const auto result=Phase35TransitionEngine(config).processWav(
            argv[1],argv[2],timeline.current(),modes,outputFrames);
        std::cout<<"frames="<<result.outputFrames<<"\nchanges="<<modes.size()<<'\n';
    } catch (const std::exception& error) {
        std::cerr<<"Phase 36 reference: "<<error.what()<<'\n';return 1;
    }
}
