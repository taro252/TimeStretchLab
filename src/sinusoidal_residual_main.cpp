#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/SinusoidalResidualEngine.h"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>

namespace {
double number(const char* text) {
    std::size_t used=0;
    const double value=std::stod(text,&used);
    if (used!=std::string(text).size() || !std::isfinite(value))
        throw std::invalid_argument("Invalid number");
    return value;
}
}
int main(int argc,char** argv) {
    if (argc<5 || argc%2==0) {
        std::cerr << "Usage: sinusoidal_residual_stretch input.wav output.wav "
                     "--speed 0.75 [--analysis-hop 512] [--residual-phase random|analysis] "
                     "[--diagnostics directory]\n";
        return 2;
    }
    try {
        ts::SinusoidalResidualConfig config;
        double speed=0;
        std::filesystem::path diagnostics;
        for (int i=3;i<argc;i+=2) {
            const std::string key=argv[i];
            if (key=="--speed") speed=number(argv[i+1]);
            else if (key=="--analysis-hop") {
                const double hop=number(argv[i+1]);
                if (hop<128 || hop>2048 || std::floor(hop)!=hop)
                    throw std::invalid_argument("Invalid analysis hop");
                config.analysisHop=static_cast<std::size_t>(hop);
            } else if (key=="--diagnostics") diagnostics=argv[i+1];
            else if (key=="--residual-phase") {
                const std::string value=argv[i+1];
                if (value=="random") config.residualPhaseMode=ts::ResidualPhaseMode::Random;
                else if (value=="analysis")
                    config.residualPhaseMode=ts::ResidualPhaseMode::AnalysisContinuity;
                else throw std::invalid_argument("--residual-phase expects random|analysis");
            }
            else throw std::invalid_argument("Unknown option: "+key);
        }
        if (!(speed>0 && speed<=2)) throw std::invalid_argument("Invalid speed");
        auto input=ts::WavReader::read(argv[1]);
        if (input.channels.size()!=1)
            throw std::invalid_argument("Phase 9A prototype requires mono input");
        config.sampleRate=input.sampleRate;
        config.timeRatio=1/speed;
        if (!diagnostics.empty()) std::filesystem::create_directories(diagnostics);
        ts::SinusoidalResidualEngine engine(config);
        const auto start=std::chrono::steady_clock::now();
        const auto result=engine.processMono(input.channels[0],
            diagnostics.empty() ? std::filesystem::path{} : diagnostics/"tracks.csv");
        const double seconds=std::chrono::duration<double>(
            std::chrono::steady_clock::now()-start).count();
        ts::WavWriter::write(argv[2],{input.sampleRate,{result.output}});
        if (!diagnostics.empty()) {
            ts::WavWriter::write(diagnostics/"sinusoidal_input.wav",
                                 {input.sampleRate,{result.sinusoidalInput}});
            ts::WavWriter::write(diagnostics/"residual_input.wav",
                                 {input.sampleRate,{result.residualInput}});
            ts::WavWriter::write(diagnostics/"sinusoidal_output.wav",
                                 {input.sampleRate,{result.sinusoidalOutput}});
            ts::WavWriter::write(diagnostics/"residual_output.wav",
                                 {input.sampleRate,{result.residualOutput}});
        }
        rusage resources{};getrusage(RUSAGE_SELF,&resources);
        const auto& stats=result.stats;
        std::cout << "inputFrames=" << input.channels[0].size()
                  << " outputFrames=" << result.output.size()
                  << " tracks=" << engine.tracks().size()
                  << " averageActiveTracks=" << stats.averageActiveTracks
                  << " medianLifetimeSeconds=" << stats.medianTrackLifetimeSeconds
                  << " birthsPerSecond=" << stats.birthsPerSecond
                  << " deathsPerSecond=" << stats.deathsPerSecond
                  << " explainedEnergyRatio=" << stats.explainedEnergyRatio
                  << " residualInputRmsRatio=" << stats.residualInputRmsRatio
                  << " processingSeconds=" << seconds
                  << " peakRSSBytes=" << resources.ru_maxrss << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
