#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <numbers>
#include <random>
#include <stdexcept>

namespace {
constexpr int rate=48000;
ts::AudioBuffer makeVowel() {
    ts::AudioBuffer audio{rate,std::vector<std::vector<float>>(2,std::vector<float>(rate*3))};
    double phase=0;
    for (std::size_t i=0;i<audio.channels[0].size();++i) {
        const double t=double(i)/rate;
        phase+=2*std::numbers::pi*170*std::exp2(15*std::sin(2*std::numbers::pi*6*t)/1200)/rate;
        double value=0,right=0;
        for (int h=1;h<=16;++h) {
            const double f=h*170;
            const double envelope=0.1+std::exp(-0.5*std::pow((f-720)/220,2))+
                0.7*std::exp(-0.5*std::pow((f-1450)/330,2));
            value+=0.13*envelope*std::sin(h*phase)/h;
            right+=0.12*envelope*std::sin(h*phase+0.35)/h;
        }
        if (i==rate) {value+=0.6;right+=0.55;}
        audio.channels[0][i]=static_cast<float>(value);
        audio.channels[1][i]=static_cast<float>(right);
    }
    return audio;
}
void check() {
    const auto base=std::filesystem::temp_directory_path()/"phase7_test";
    const auto input=base.string()+"_input.wav";
    const auto off=base.string()+"_off.wav";
    const auto on=base.string()+"_on.wav";
    const auto other=base.string()+"_other.wav";
    ts::WavWriter::write(input,makeVowel());
    ts::StretchConfig config;
    config.sampleRate=rate;config.channels=2;config.timeRatio=2;
    config.enablePhaseLocking=true;config.enableTransientHandling=true;
    config.enableAdaptiveTimeMapping=true;config.enablePreciseTransientAnchoring=true;
    config.enableStereoCoherence=true;config.enableMultiResolution=true;
    const auto baseline=ts::ChunkedTimeStretchEngine(config).processWav(input,off);
    config.enablePVSOLA=true;
    bool rejected=false;
    try {ts::TimeStretchEngine(config).processOffline(makeVowel().channels);}
    catch (const std::invalid_argument&) {rejected=true;}
    if (!rejected) throw std::runtime_error("Offline PVSOLA was silently ignored");
    config.enablePartialTracking=true;
    rejected=false;
    try {ts::ChunkedTimeStretchEngine invalid(config);}
    catch (const std::invalid_argument&) {rejected=true;}
    if (!rejected) throw std::runtime_error("PVSOLA/partial tracking combination accepted");
    config.enablePartialTracking=false;
    const auto tracked=ts::ChunkedTimeStretchEngine(config).processWav(input,on,8192);
    ts::ChunkedTimeStretchEngine(config).processWav(input,other,65536);
    const auto a=ts::WavReader::read(off);
    const auto b=ts::WavReader::read(on);
    const auto c=ts::WavReader::read(other);
    if (a.channels[0].size()!=b.channels[0].size() ||
        b.channels[0].size()!=rate*6 || baseline.timeMapHash!=tracked.timeMapHash ||
        tracked.resyncApplied<5 || tracked.resyncApplied>=tracked.resyncScheduled ||
        tracked.resyncTransientSuppressed==0 ||
        tracked.averageResyncCorrelation<0.65)
        throw std::runtime_error("PVSOLA timing, gate, or resync count failed");
    double maxDifference=0,maxDerivative=0,outputDifference=0;
    for (int channel=0;channel<2;++channel)
        for (std::size_t i=0;i<b.channels[channel].size();++i) {
            const double value=b.channels[channel][i];
            if (!std::isfinite(value)) throw std::runtime_error("Nonfinite PVSOLA output");
            maxDifference=std::max(maxDifference,std::abs(value-c.channels[channel][i]));
            outputDifference=std::max(outputDifference,std::abs(value-a.channels[channel][i]));
            if (i) maxDerivative=std::max(maxDerivative,
                std::abs(value-b.channels[channel][i-1]));
        }
    auto correlation=[](const ts::AudioBuffer& audio) {
        double dot=0,left=0,right=0;
        for (std::size_t i=0;i<audio.channels[0].size();++i) {
            const double l=audio.channels[0][i],r=audio.channels[1][i];
            dot+=l*r;left+=l*l;right+=r*r;
        }
        return dot/std::sqrt(left*right);
    };
    const double correlationChange=std::abs(correlation(a)-correlation(b));
    std::cout << "resync=" << tracked.resyncApplied << '/' << tracked.resyncScheduled
              << " correlation=" << tracked.averageResyncCorrelation
              << " transient_suppressed=" << tracked.resyncTransientSuppressed
              << " chunk_max_difference=" << maxDifference
              << " baseline_max_difference=" << outputDifference
              << " max_derivative=" << maxDerivative
              << " correlation_change=" << correlationChange << '\n';
    if (maxDifference>1e-5 || outputDifference<1e-4 || maxDerivative>0.7 ||
        correlationChange>0.05)
        throw std::runtime_error("PVSOLA chunk mismatch or discontinuity");
    for (const auto& path:{input,off,on,other}) std::filesystem::remove(path);
}
}
int main() {
    try { check(); }
    catch (const std::exception& error) {std::cerr << error.what() << '\n';return 1;}
}
