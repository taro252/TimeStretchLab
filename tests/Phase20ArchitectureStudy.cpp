#include "dsp/TimeMap.h"
#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::vector<ts::TransientFrame> syntheticEvents() {
    std::vector<ts::TransientFrame> frames(96);
    for (const auto peak : {10, 40, 70}) {
        frames[peak].spectralFlux=10;
        frames[peak].threshold=1;
        frames[peak].logEnergy=100;
        frames[peak].previousLogEnergy=1;
        frames[peak].strength=0.9f;
    }
    return frames;
}

long long maximumSynthesisHop(const ts::TimeMap& map,int analysisHop,int fftSize) {
    long long maximum=0;
    long long previous=0;
    bool first=true;
    const auto finalInput=(map.starts().size()-2)*
        static_cast<std::size_t>(map.sourceHop());
    for (std::size_t input=0;input<=finalInput;input+=analysisHop) {
        const auto position=std::llround(map.outputPositionForInputSample(double(input)));
        if (!first) {
            const auto delta=position-previous;
            require(delta>0,"Non-monotonic synthesis position");
            require(delta<fftSize,"Synthesis hop exceeds the OLA window");
            maximum=std::max(maximum,delta);
        }
        previous=position;
        first=false;
    }
    return maximum;
}
}

int main() {
    try {
        constexpr int midHop=1024;
        const auto frames=syntheticEvents();
        ts::TransientEventMap half(frames,90,midHop,2.0);
        ts::TransientEventMap threeQuarters(frames,90,midHop,4.0/3.0);
        require(half.events().size()==3 && threeQuarters.events().size()==3,
                "Unexpected synthetic event count");
        for (std::size_t i=0;i<half.events().size();++i) {
            const auto& a=half.events()[i];
            const auto& b=threeQuarters.events()[i];
            require(a.onsetFrame==b.onsetFrame && a.peakFrame==b.peakFrame &&
                    a.attackEndFrame==b.attackEndFrame && a.endFrame==b.endFrame &&
                    a.strength==b.strength,"Event identity depends on speed");
        }
        for (std::size_t i=0;i<frames.size();++i)
            require(half.resetAt(i)==threeQuarters.resetAt(i) &&
                    half.eventIdAt(i)==threeQuarters.eventIdAt(i),
                    "Input event/reset position depends on speed");
        const std::vector<double> inputOffsets{128.0,-96.0,64.0};
        half.refineAnchors(inputOffsets);
        threeQuarters.refineAnchors(inputOffsets);
        ts::TimeMap mapHalf(midHop,half.starts(),half.events());
        ts::TimeMap mapThreeQuarters(midHop,threeQuarters.starts(),
                                    threeQuarters.events());
        require(mapHalf.starts()!=mapThreeQuarters.starts(),
                "Output timeline did not respond to speed");
        constexpr std::array<int,3> fft{8192,4096,1024};
        constexpr std::array<int,3> hop{2048,1024,256};
        std::array<long long,3> halfMaximum{},threeQuartersMaximum{};
        for (std::size_t i=0;i<fft.size();++i) {
            halfMaximum[i]=maximumSynthesisHop(mapHalf,hop[i],fft[i]);
            threeQuartersMaximum[i]=maximumSynthesisHop(mapThreeQuarters,hop[i],fft[i]);
        }
        // Coordinate-only probe: translating a future fixed-speed map preserves
        // the output sample at the switch. It says nothing about phase, OLA,
        // FIR continuity or audio quality.
        constexpr double switchInput=24.0*midHop;
        const double oldAtSwitch=mapHalf.outputPositionForInputSample(switchInput);
        const double newAtSwitch=oldAtSwitch+
            mapThreeQuarters.outputPositionForInputSample(switchInput)-
            mapThreeQuarters.outputPositionForInputSample(switchInput);
        const double newAfter=oldAtSwitch+
            mapThreeQuarters.outputPositionForInputSample(switchInput+midHop)-
            mapThreeQuarters.outputPositionForInputSample(switchInput);
        const double oldHop=oldAtSwitch-
            mapHalf.outputPositionForInputSample(switchInput-midHop);
        const double newHop=newAfter-newAtSwitch;
        require(newAtSwitch==oldAtSwitch && newAfter>newAtSwitch,
                "Coordinate bridge is not continuous and increasing");
        std::cout << "events=" << half.events().size()
                  << " switch_input=" << switchInput
                  << " switch_output=" << oldAtSwitch
                  << " old_mid_hop=" << oldHop
                  << " new_mid_hop=" << newHop << '\n';
        for (std::size_t i=0;i<fft.size();++i)
            std::cout << "fft=" << fft[i] << " analysis_hop=" << hop[i]
                      << " max_hs_050=" << halfMaximum[i]
                      << " max_hs_075=" << threeQuartersMaximum[i] << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Phase 20 architecture probe: " << error.what() << '\n';
        return 1;
    }
}
