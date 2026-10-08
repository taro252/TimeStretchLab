#include "dsp/WSOLAEngine.h"
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
std::vector<float> sine(double phase=0) {
    std::vector<float> x(48000*2);
    for (std::size_t i=0;i<x.size();++i)
        x[i]=0.3f*std::sin(2*std::numbers::pi*440*i/48000+phase);
    return x;
}
double frequency(const std::vector<float>& x) {
    std::vector<double> crossings;
    for (std::size_t i=24000;i+1<x.size()-24000;++i)
        if (x[i]<=0 && x[i+1]>0 && x[i+1]!=x[i])
            crossings.push_back(i-x[i]/double(x[i+1]-x[i]));
    check(crossings.size()>10,"Too few crossings");
    return 48000*(crossings.size()-1)/(crossings.back()-crossings.front());
}
double rms(const std::vector<float>& x) {
    double sum=0;
    for (std::size_t i=24000;i+24000<x.size();++i) sum+=double(x[i])*x[i];
    return std::sqrt(sum/(x.size()-48000));
}
}
int main() {
    try {
        for (double speed:{0.75,0.5}) {
            ts::WSOLAConfig cfg;
            cfg.timeRatio=1/speed;
            ts::WSOLAEngine engine(cfg);
            auto input=sine();
            auto result=engine.processOffline({input});
            check(result[0].size()==std::llround(input.size()/speed),"Duration mismatch");
            for (float sample:result[0]) check(std::isfinite(sample),"Nonfinite sample");
            const double hz=frequency(result[0]);
            std::cout << "speed=" << speed << " sineHz=" << hz << " rms=" << rms(result[0]) << '\n';
            check(std::abs(hz-440)<8,"Sine pitch changed");
            check(rms(result[0])>0.10 && rms(result[0])<0.30,"Sine gain changed");
            check(engine.stats().grainCount>0,"No grains");
            for (const auto& grain:engine.grains())
                check(std::abs(grain.offsetSamples)<=cfg.searchRadius,"Search offset out of range");
            std::vector<float> right=input;
            for (float& sample:right) sample*=0.8f;
            auto stereo=engine.processOffline({input,right});
            double stereoError=0;
            for (std::size_t i=0;i<stereo[0].size();++i)
                stereoError=std::max(stereoError,
                    std::abs(double(stereo[1][i])-0.8*stereo[0][i]));
            check(stereoError<1e-6,"Stereo channels used different offsets");
            auto silent=engine.processOffline({std::vector<float>(48000,0),std::vector<float>(48000,0)});
            for (const auto& channel:silent)
                for (float sample:channel) check(sample==0,"Silence changed");
        }
        ts::WSOLAConfig cfg;
        cfg.timeRatio=1;
        cfg.searchRadius=0;
        ts::WSOLAEngine unity(cfg);
        auto input=sine();
        auto output=unity.processOffline({input});
        double error=0;
        for (std::size_t i=0;i<input.size();++i)
            error=std::max(error,std::abs(double(input[i])-output[0][i]));
        std::cout << "unityMaxError=" << error << '\n';
        check(error<1e-5,"Hann normalization failed");
        std::cout << "phase8a PASS\n";
    } catch (const std::exception& e) {
        std::cerr << "phase8a FAIL: " << e.what() << '\n';
        return 1;
    }
}
