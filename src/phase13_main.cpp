#include "audio/WavStream.h"
#include "dsp/Phase13StreamingEngine.h"
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc, char** argv) {
    if (argc != 3 && argc != 4) {
        std::cerr << "Usage: phase13_stream input.wav output.wav [block-frames:8192..65536]\n";
        return 2;
    }
    try {
        const std::size_t block = argc == 4 ? std::stoul(argv[3]) : 16384;
        const ts::WavStreamReader input(argv[1]);
        ts::StretchConfig config;
        config.sampleRate = input.sampleRate();
        config.channels = static_cast<int>(input.channels());
        config.timeRatio = 2.0;
        config.enableMultiResolution = true;
        config.qualityMode = ts::QualityMode::Experimental;
        config.enablePhaseLocking = true;
        config.enableTransientHandling = true;
        config.enableAdaptiveTimeMapping = true;
        config.enablePreciseTransientAnchoring = true;
        config.enableStereoCoherence = true;
        ts::WavStreamWriter writer(argv[2],input.sampleRate(),input.channels(),input.frames()*2);
        ts::Phase13StreamingEngine engine(config);
        const auto result = engine.processFile(argv[1], [&](const float* const* data, std::size_t count) {
            writer.write(data,count);
        },block);
        writer.finish();
        std::cout << "input_frames=" << result.processing.inputFrames << '\n'
                  << "output_frames=" << result.processing.outputFrames << '\n'
                  << "time_map_hash=" << result.processing.timeMapHash << '\n'
                  << "peak=" << result.processing.peak << '\n';
        constexpr const char* names[] = {"low","mid","high"};
        for (std::size_t i=0; i<3; ++i)
            std::cout << names[i] << "_fft=" << result.stages.fft[i] << '\n'
                      << names[i] << "_phase=" << result.stages.phase[i] << '\n'
                      << names[i] << "_ifft=" << result.stages.ifft[i] << '\n'
                      << names[i] << "_ola=" << result.stages.ola[i] << '\n';
        std::cout << "low_fir=" << result.stages.lowFir << '\n'
                  << "high_fir=" << result.stages.highFir << '\n'
                  << "fir_output=" << result.stages.fir << '\n';
    } catch (const std::exception& error) {
        std::cerr << "Phase 13: " << error.what() << '\n';
        return 1;
    }
}
