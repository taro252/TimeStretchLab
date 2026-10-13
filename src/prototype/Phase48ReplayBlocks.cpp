// Test adapter only: replay an existing map/density history with a different
// output block partition. No DSP algorithm or live player code is replaced.
#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase36StreamingSpeedEngine.h"
#include "audio/WavStream.h"
#include <fstream>
#include <sstream>
#include <iostream>
#include <cmath>
using namespace ts;
using namespace ts::prototype;
int main(int argc,char** argv) {
    if (argc!=6) { std::cerr<<"input.wav output.wav initial_speed replay.csv block_frames\n";return 2; }
    try {
        WavStreamReader reader(argv[1]);
        auto initial=Phase39Speed::fromDouble(std::stod(argv[3]));
        const auto block=std::stoull(argv[5]);
        if (block!=1024 && block!=2048) throw std::runtime_error("Expected 1024/2048 block");
        StretchConfig config;config.sampleRate=reader.sampleRate();config.channels=reader.channels();
        config.timeRatio=initial.timeRatio();config.enableMultiResolution=true;
        config.qualityMode=QualityMode::Experimental;config.enablePhaseLocking=true;
        config.enableTransientHandling=true;config.enableAdaptiveTimeMapping=true;
        config.enablePreciseTransientAnchoring=true;config.enableStereoCoherence=true;
        auto ac=config;ac.timeRatio=2.0;
        auto analysis=Phase13StreamingEngine(ac).analyzeTransientEvents(argv[1]);
        Phase39TimeMap timeline(analysis,reader.sampleRate(),initial,Phase39Planning::C);
        std::vector<std::pair<std::size_t,bool>> density;
        std::ifstream csv(argv[4]);if (!csv) throw std::runtime_error("Missing replay CSV");
        std::string line;std::getline(csv,line);auto previous=initial;
        while (std::getline(csv,line)) {
            std::istringstream row(line);std::vector<std::string> fields;std::string field;
            while (std::getline(row,field,',')) fields.push_back(field);
            if (fields.size()<14) throw std::runtime_error("Incomplete replay row");
            auto target=Phase39Speed::fromDouble(std::stod(fields[4]));
            auto plan=timeline.submit({std::stoull(fields[0]),target,std::stoull(fields[2]),std::stoll(fields[5]),50.0});
            if (!plan.applied() || plan.appliedFrame!=std::stoull(fields[8])) throw std::runtime_error("TimeMap mismatch");
            if ((previous.value()<.5)!=(target.value()<.5)) density.emplace_back(std::stoull(fields[11]),target.value()<.5);
            previous=target;
        }
        auto frames=std::size_t(std::llround(timeline.current().outputPositionForInputSample(double(reader.frames()))));
        WavStreamWriter output(argv[2],reader.sampleRate(),reader.channels(),frames);
        Phase36StreamingSpeedEngine engine(config);
        auto result=engine.process(argv[1],analysis,timeline.current(),frames,block,
            [&](const float* const* samples,std::size_t n,const std::function<void()>&){output.write(samples,n);},
            {},density);
        output.finish();
        if (result.processing.outputFrames!=frames) throw std::runtime_error("EOS length mismatch");
        std::cout<<"frames="<<frames<<"\nblock_frames="<<block<<'\n';
    } catch (const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
