#include "audio/WavStream.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include "dsp/Phase13StreamingEngine.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
bool identical(const std::filesystem::path& a, const std::filesystem::path& b) {
    std::ifstream left(a, std::ios::binary), right(b, std::ios::binary);
    return std::equal(std::istreambuf_iterator<char>(left), std::istreambuf_iterator<char>(),
                      std::istreambuf_iterator<char>(right), std::istreambuf_iterator<char>());
}
}

int main() {
    const auto dir=std::filesystem::temp_directory_path()/
        ("phase13_test_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(dir);
    try {
        constexpr std::size_t frames=48000;
        std::array<std::vector<float>,2> samples={std::vector<float>(frames),std::vector<float>(frames)};
        for (std::size_t i=0;i<frames;++i) {
            const float tone=0.2f*std::sin(2.0*3.141592653589793*437.3*i/48000.0);
            const float click=i==12000 || i==24000 || i==36000 ? 0.7f : 0.0f;
            samples[0][i]=tone+click;
            samples[1][i]=0.8f*tone+click;
        }
        const float* inputPointers[]={samples[0].data(),samples[1].data()};
        const auto input=dir/"input.wav", baseline=dir/"baseline.wav";
        {
            ts::WavStreamWriter writer(input,48000,2,frames);
            writer.write(inputPointers,frames);
            writer.finish();
        }
        ts::StretchConfig config;
        config.sampleRate=48000;
        config.channels=2;
        config.timeRatio=2;
        config.enableMultiResolution=true;
        config.qualityMode=ts::QualityMode::Experimental;
        config.enablePhaseLocking=true;
        config.enableTransientHandling=true;
        config.enableAdaptiveTimeMapping=true;
        config.enablePreciseTransientAnchoring=true;
        config.enableStereoCoherence=true;
        const auto baselineResult=ts::ChunkedTimeStretchEngine(config).processWav(input,baseline,8192);
        ts::Phase13StreamingEngine engine(config);
        std::array<ts::Phase13Result,2> results;
        for (std::size_t trial=0;trial<2;++trial) {
            const auto output=dir/(trial==0 ? "stream8192.wav" : "stream16384.wav");
            ts::WavStreamWriter writer(output,48000,2,frames*2);
            results[trial]=engine.processFile(input,[&](const float* const* data,std::size_t count) {
                writer.write(data,count);
            },trial==0 ? 8192 : 16384);
            writer.finish();
            require(identical(baseline,output),"Phase 13 differs from offline chunked reference");
            require(results[trial].processing.outputFrames==frames*2,"Wrong output length");
            require(results[trial].processing.timeMapHash==baselineResult.timeMapHash,"TimeMap changed");
        }
        require(results[0].stages.fft==results[1].stages.fft,"FFT depends on output block");
        require(results[0].stages.phase==results[1].stages.phase,"Phase depends on output block");
        require(results[0].stages.ifft==results[1].stages.ifft,"IFFT depends on output block");
        require(results[0].stages.ola==results[1].stages.ola,"OLA depends on output block");
        require(results[0].stages.lowFir==results[1].stages.lowFir,"LP250 depends on output block");
        require(results[0].stages.highFir==results[1].stages.highFir,"LP3500 depends on output block");
        require(results[0].stages.fir==results[1].stages.fir,"FIR depends on output block");
        config.timeRatio=1.0;
        try {
            ts::Phase13StreamingEngine invalid(config);
            throw std::runtime_error("Incorrectly accepted non-0.50 speed");
        } catch (const std::invalid_argument&) {}
        std::filesystem::remove_all(dir);
        std::cout << "Phase 13: offline reference and two output block sizes match exactly\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << " (files: " << dir << ")\n";
        return 1;
    }
}
