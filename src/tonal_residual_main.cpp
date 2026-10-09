#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/TonalResidualEngine.h"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc,char** argv) {
    if (argc!=5 && argc!=7) {
        std::cerr << "Usage: tonal_residual_stretch input.wav output.wav --speed 0.75 "
                     "[--diagnostics directory]\n";
        return 2;
    }
    try {
        double speed=0;
        std::filesystem::path diagnostics;
        for (int i=3;i<argc;i+=2) {
            const std::string option=argv[i];
            if (option=="--speed") {
                std::size_t used=0;
                speed=std::stod(argv[i+1],&used);
                if (used!=std::string(argv[i+1]).size())
                    throw std::invalid_argument("Invalid speed");
            } else if (option=="--diagnostics") diagnostics=argv[i+1];
            else throw std::invalid_argument("Unknown option: "+option);
        }
        if (!std::isfinite(speed) || speed<=0 || speed>2)
            throw std::invalid_argument("Invalid speed");
        const auto audio=ts::WavReader::read(argv[1]);
        if (audio.channels.size()!=1)
            throw std::invalid_argument("Phase 9C prototype requires mono input");
        ts::SinusoidalResidualConfig config;
        config.sampleRate=audio.sampleRate;
        config.timeRatio=1/speed;
        if (!diagnostics.empty()) std::filesystem::create_directories(diagnostics);
        const auto start=std::chrono::steady_clock::now();
        ts::TonalResidualEngine engine(config);
        const auto result=engine.processMono(audio.channels[0],
            diagnostics.empty()?std::filesystem::path{}:diagnostics/"tracks.csv");
        const double seconds=std::chrono::duration<double>(
            std::chrono::steady_clock::now()-start).count();
        ts::WavWriter::write(argv[2],{audio.sampleRate,{result.output}});
        if (!diagnostics.empty()) {
            const auto save=[&](const char* name,const std::vector<float>& samples) {
                ts::WavWriter::write(diagnostics/name,{audio.sampleRate,{samples}});
            };
            save("primary.wav",result.primary);
            save("tonal_input.wav",result.tonalInput);
            save("noise_input.wav",result.noiseInput);
            save("tonal_output.wav",result.tonalOutput);
            save("noise_output.wav",result.noiseOutput);
            save("primary_and_tonal.wav",result.primaryAndTonal);
        }
        std::cout << "inputFrames=" << audio.channels[0].size()
                  << " outputFrames=" << result.output.size()
                  << " meanTonalMask=" << result.meanTonalMask
                  << " trackBirths=" << result.primaryStats.trackBirths
                  << " trackDeaths=" << result.primaryStats.trackDeaths
                  << " medianLifetimeSeconds=" << result.primaryStats.medianTrackLifetimeSeconds
                  << " processingSeconds=" << seconds << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
