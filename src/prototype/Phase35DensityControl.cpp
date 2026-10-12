#include "audio/WavStream.h"
#include "dsp/Phase13StreamingEngine.h"
#include "prototype/Phase35TimeMap.h"
#include "prototype/Phase35TransitionEngine.h"
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// Diagnostic control: change analysis-frame density at a constant 0.50x.
// The audio TimeMap and every quality setting remain fixed.
int main(int argc,char** argv) {
    if (argc!=5) {
        std::cerr<<"Usage: phase35_density_control input.wav output.wav "
                    "A_to_B|B_to_A|B_only switch_input_sample\n";
        return 2;
    }
    try {
        const std::string mode=argv[3];
        const auto requested=std::stoull(argv[4]);
        const auto change=((requested+2047)/2048)*2048;
        ts::WavStreamReader reader(argv[1]);
        if (change>=reader.frames() ||
            (mode!="A_to_B" && mode!="B_to_A" && mode!="B_only"))
            throw std::invalid_argument("Invalid density control");
        ts::StretchConfig c;
        c.sampleRate=reader.sampleRate();
        c.channels=static_cast<int>(reader.channels());
        c.timeRatio=2.0;
        c.enableMultiResolution=true;
        c.qualityMode=ts::QualityMode::Experimental;
        c.enablePhaseLocking=true;
        c.enableTransientHandling=true;
        c.enableAdaptiveTimeMapping=true;
        c.enablePreciseTransientAnchoring=true;
        c.enableStereoCoherence=true;
        const ts::Phase13StreamingEngine analyzer(c);
        const auto analysis=analyzer.analyzeTransientEvents(argv[1]);
        const ts::prototype::Phase35TimeMap map(analysis,reader.sampleRate(),
            ts::prototype::Phase35Speed::fromDouble(0.50));
        std::vector<std::pair<std::size_t,bool>> changes;
        if (mode!="A_to_B") changes.emplace_back(0,true);
        if (mode=="A_to_B") changes.emplace_back(change,true);
        if (mode=="B_to_A") changes.emplace_back(change,false);
        const auto result=ts::Phase35TransitionEngine(c).processWav(
            argv[1],argv[2],map.current(),changes,
            static_cast<std::size_t>(std::round(reader.frames()*2.0)));
        std::cout<<"output_frames="<<result.outputFrames<<"\npeak="<<result.peak<<'\n';
    } catch (const std::exception& e) {
        std::cerr<<"Phase 35 density control: "<<e.what()<<'\n';
        return 1;
    }
}
