#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include "dsp/FFTAccelerate.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <bit>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <numbers>
#include <complex>
#include <cstdint>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
void run(double speed, int channels, std::size_t chunkSize) {
    constexpr std::size_t rate=44100, length=rate*2;
    ts::AudioBuffer input;
    input.sampleRate=rate;
    input.channels.assign(channels,std::vector<float>(length));
    std::mt19937 generator(42);
    std::uniform_real_distribution<float> noise(-0.15f,0.15f);
    for (std::size_t i=0; i<length; ++i) {
        const float sine=0.25f*std::sin(2*std::numbers::pi*437.3*i/rate);
        const bool burst=(i>=chunkSize-16 && i<chunkSize+16) ||
                         (i>=2*chunkSize-16 && i<2*chunkSize+16);
        const float transient=i==chunkSize-1 || i==chunkSize ||
                              i==2*chunkSize-1 || i==2*chunkSize ? 0.4f : 0.0f;
        float drum=0;
        for (const auto onset: {chunkSize+1,2*chunkSize-1}) {
            if (i>=onset && i-onset<rate/10) {
                const auto offset=i-onset;
                drum+=0.28f*std::exp(-double(offset)/750.0)*
                    std::sin(2*std::numbers::pi*85.0*offset/rate);
            }
        }
        for (int c=0; c<channels; ++c)
            input.channels[c][i]=(sine+transient+drum+(burst?noise(generator):0.0f))*(c?0.7f:1.0f);
    }
    const auto base=std::filesystem::temp_directory_path()/
        ("phase51_"+std::to_string(channels)+"_"+std::to_string(chunkSize)+"_"+
         std::to_string(int(speed*100)));
    const auto inputPath=base.string()+"_input.wav", outputPath=base.string()+"_output.wav";
    ts::WavWriter::write(inputPath,input);
    ts::StretchConfig config;
    config.sampleRate=rate; config.channels=channels; config.timeRatio=1/speed;
    config.enablePhaseLocking=true;
    config.enableTransientHandling=true;
    config.enableAdaptiveTimeMapping=true;
    config.enablePreciseTransientAnchoring=true;
    config.enableStereoCoherence=true;
    config.enableMultiResolution=true;
    ts::TimeStretchEngine baseline(config);
    const auto expected=baseline.processOffline(input.channels);
    ts::ChunkedTimeStretchEngine streaming(config);
    const auto stats=streaming.processWav(inputPath,outputPath,chunkSize);
    const auto actual=ts::WavReader::read(outputPath);
    if (stats.outputFrames!=expected[0].size() || actual.channels.size()!=expected.size())
        throw std::runtime_error("Chunked output length/channel mismatch");
    double maximum=0, boundaryMaximum=0;
    for (std::size_t c=0; c<expected.size(); ++c) for (std::size_t i=0; i<expected[c].size(); ++i) {
        const auto difference=std::abs(double(expected[c][i])-actual.channels[c][i]);
        maximum=std::max(maximum,difference);
        if (i%chunkSize<64 || i%chunkSize>=chunkSize-64)
            boundaryMaximum=std::max(boundaryMaximum,difference);
        if (!std::isfinite(actual.channels[c][i])) throw std::runtime_error("Nonfinite output");
    }
    std::cout << "speed=" << speed << " channels=" << channels << " chunk=" << chunkSize
              << " max_difference=" << maximum << " boundary_difference=" << boundaryMaximum
              << " output_frames=" << stats.outputFrames << '\n';
    if (maximum>=1e-5 || boundaryMaximum>=1e-5)
        throw std::runtime_error("Phase 5 sample regression exceeded tolerance");
    std::filesystem::remove(inputPath);
    std::filesystem::remove(outputPath);
}
void silence(double speed,int channels) {
    constexpr std::size_t rate=44100;
    const auto base=std::filesystem::temp_directory_path()/
        ("phase51_silence_"+std::to_string(channels)+"_"+std::to_string(int(speed*100)));
    const auto inputPath=base.string()+"_input.wav",outputPath=base.string()+"_output.wav";
    ts::WavWriter::write(inputPath,{rate,
        std::vector<std::vector<float>>(channels,std::vector<float>(rate))});
    ts::StretchConfig config;
    config.sampleRate=rate; config.channels=channels; config.timeRatio=1/speed;
    config.enablePhaseLocking=true; config.enableTransientHandling=true;
    config.enableAdaptiveTimeMapping=true; config.enablePreciseTransientAnchoring=true;
    config.enableStereoCoherence=true; config.enableMultiResolution=true;
    const auto stats=ts::ChunkedTimeStretchEngine(config).processWav(inputPath,outputPath);
    const auto output=ts::WavReader::read(outputPath);
    if (output.channels[0].size()!=stats.outputFrames) throw std::runtime_error("Silence length");
    for (const auto& channel:output.channels) for (const auto value:channel)
        if (value!=0 || !std::isfinite(value)) throw std::runtime_error("Silence noise or nonfinite");
    std::filesystem::remove(inputPath);
    std::filesystem::remove(outputPath);
}
void fftRepeatability() {
    constexpr std::size_t size=1024;
    std::vector<float> signal(size);
    for (std::size_t i=0;i<size;++i)
        signal[i]=std::sin(2*std::numbers::pi*437.3*i/44100.0);
    std::vector<std::complex<float>> reference(size/2+1),current(size/2+1);
    for (int repetition=0;repetition<48;++repetition) {
        std::vector<char> perturb(113*repetition);
        ts::FFTAccelerate fft(size);
        fft.forward(signal.data(),current.data());
        if (repetition==0) reference=current;
        else for (std::size_t k=0;k<current.size();++k) {
            if (std::bit_cast<std::uint32_t>(reference[k].real())!=
                    std::bit_cast<std::uint32_t>(current[k].real()) ||
                std::bit_cast<std::uint32_t>(reference[k].imag())!=
                    std::bit_cast<std::uint32_t>(current[k].imag()))
                throw std::runtime_error("FFT result depends on workspace placement");
        }
    }
}
}
int main() {
    try {
        fftRepeatability();
        for (double speed: {0.75,0.5}) {
            run(speed,1,8192);
            run(speed,2,16384);
        }
        run(0.5,2,65536);
        for (double speed:{0.75,0.5}) for (int channels:{1,2}) silence(speed,channels);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
