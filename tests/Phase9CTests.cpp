#include "dsp/SinusoidalResidualEngine.h"
#include "dsp/TonalResidualEngine.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
void check(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}
double rms(const std::vector<float>& audio) {
    double total=0;
    for (float sample:audio) total+=double(sample)*sample;
    return std::sqrt(total/std::max(std::size_t(1),audio.size()));
}
}
int main() {
    try {
        constexpr std::size_t rate=48000;
        std::vector<float> pure(rate*2),breathy(rate*2),silence(rate);
        for (std::size_t n=0;n<pure.size();++n) {
            pure[n]=static_cast<float>(0.2*std::sin(2*std::numbers::pi*165*n/rate)+
                0.1*std::sin(2*std::numbers::pi*330*n/rate));
            const double noise=std::sin(2*std::numbers::pi*17777*n/rate)*
                std::sin(2*std::numbers::pi*20003*n/rate);
            breathy[n]=pure[n]+static_cast<float>(0.02*noise);
        }
        for (double ratio:{1.0,4.0/3.0,2.0}) {
            ts::SinusoidalResidualConfig config;
            config.timeRatio=ratio;
            for (const auto* input:{&pure,&breathy,&silence}) {
                ts::TonalResidualEngine engine(config);
                const auto a=engine.processMono(*input);
                const auto b=engine.processMono(*input);
                check(a.output==b.output,"Phase 9C random seed changed output");
                check(a.output.size()==std::llround(input->size()*ratio),
                      "Phase 9C duration mismatch");
                for (std::size_t n=0;n<a.output.size();++n) {
                    check(std::isfinite(a.output[n]),"Nonfinite Phase 9C output");
                    check(std::abs(a.output[n]-(a.primary[n]+a.tonalOutput[n]+
                        a.noiseOutput[n]))<1e-5,"Component sum mismatch");
                }
                if (input==&silence) check(rms(a.output)<1e-9,"Silence noise");
                if (input==&pure && ratio>1)
                    check(rms(a.noiseInput)<0.04*rms(*input),
                          "Pure vowel leaked substantially into noise input");
            }
            ts::SinusoidalResidualEngine baseline(config);
            const auto before=baseline.processMono(pure);
            const auto after=baseline.processMono(pure);
            check(before.output==after.output,"Phase 9A regression");
        }
        std::cout << "phase9c PASS\n";
    } catch (const std::exception& error) {
        std::cerr << "phase9c FAIL: " << error.what() << '\n';
        return 1;
    }
}
