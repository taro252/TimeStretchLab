#include "dsp/SinusoidalResidualEngine.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
void check(bool value,const char* message) {
    if (!value) throw std::runtime_error(message);
}
double frequency(const std::vector<float>& audio) {
    std::vector<double> crossings;
    for (std::size_t n=24000;n+24001<audio.size();++n)
        if (audio[n]<=0 && audio[n+1]>0 && audio[n+1]!=audio[n])
            crossings.push_back(n-audio[n]/double(audio[n+1]-audio[n]));
    check(crossings.size()>10,"Too few oscillator crossings");
    return 48000*(crossings.size()-1)/(crossings.back()-crossings.front());
}
}
int main() {
    try {
        std::vector<float> input(48000*2);
        for (std::size_t n=0;n<input.size();++n)
            input[n]=0.2f*std::cos(2*std::numbers::pi*440*n/48000);
        for (double ratio:{1.0,4.0/3.0,2.0}) {
            ts::SinusoidalResidualConfig config;
            config.timeRatio=ratio;
            ts::SinusoidalResidualEngine engine(config);
            auto result=engine.processMono(input);
            check(result.output.size()==std::llround(input.size()*ratio),"Duration mismatch");
            check(!engine.tracks().empty(),"No sinusoidal tracks");
            check(result.stats.residualInputRmsRatio<0.2,
                  "Pure sinusoid leaked substantially into residual");
            for (float sample:result.output) check(std::isfinite(sample),"Nonfinite output");
            if (ratio==1) {
                double maximum=0,squares=0;
                for (std::size_t n=0;n<input.size();++n) {
                    const double difference=input[n]-result.output[n];
                    maximum=std::max(maximum,std::abs(difference));
                    squares+=difference*difference;
                }
                std::cout << "unityMax=" << maximum
                          << " unityRms=" << std::sqrt(squares/input.size()) << '\n';
                check(maximum<1e-6,"Unity reconstruction mismatch");
            } else {
                const double hz=frequency(result.sinusoidalOutput);
                std::cout << "ratio=" << ratio << " oscillatorHz=" << hz
                          << " explained=" << result.stats.explainedEnergyRatio << '\n';
                check(std::abs(hz-440)<5,"Oscillator pitch changed");
            }
        }
        std::vector<float> vibrato(input.size());
        double phase=0;
        for (std::size_t n=0;n<vibrato.size();++n) {
            const double time=double(n)/48000;
            const double hz=440*std::exp2(20*std::sin(2*std::numbers::pi*6*time)/1200);
            phase+=2*std::numbers::pi*hz/48000;
            vibrato[n]=static_cast<float>(0.2*std::cos(phase));
        }
        ts::SinusoidalResidualConfig config;
        config.timeRatio=2;
        ts::SinusoidalResidualEngine vibratoEngine(config);
        const auto result=vibratoEngine.processMono(vibrato);
        const auto sustained=std::count_if(vibratoEngine.tracks().begin(),
            vibratoEngine.tracks().end(),[](const ts::SinusoidalTrack& track) {
                return track.nodes.size()>80;
            });
        check(sustained>=1,"Vibrato track was fragmented");
        check(result.output.size()==2*vibrato.size(),"Vibrato duration mismatch");
        std::cout << "phase9a PASS\n";
    } catch (const std::exception& error) {
        std::cerr << "phase9a FAIL: " << error.what() << '\n';
        return 1;
    }
}
