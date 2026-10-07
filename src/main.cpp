#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void usage() {
    std::cerr << "Usage: timestretch input.wav output.wav --speed 0.5 "
                 "[--fft-size 4096] [--analysis-hop 1024] "
                 "[--phase-locking on|off] [--transient on|off] [--debug-csv directory]\n"
                 "[--transient-sensitivity 3] [--transient-history 12] "
                 "[--transient-cooldown 2] [--transient-lookback 1]\n"
                 "Multiresolution supports only off.\n";
}
double number(const char* text, const std::string& option) {
    std::size_t used = 0;
    const auto value = std::stod(text, &used);
    if (used != std::string(text).size() || !std::isfinite(value))
        throw std::invalid_argument("Invalid " + option);
    return value;
}
}
int main(int argc, char** argv) {
    if (argc < 4) { usage(); return 2; }
    try {
        double speed = -1;
        int fftSize = 4096, analysisHop = 1024;
        bool phaseLocking = false;
        bool transientHandling = false;
        float transientSensitivity = 3.0f;
        int transientHistory = 12, transientCooldown = 2, transientLookback = 1;
        std::string debugCsvDirectory;
        bool hopSpecified = false;
        for (int i = 3; i < argc; i += 2) {
            if (i + 1 >= argc) throw std::invalid_argument("Option needs a value");
            const std::string key = argv[i], value = argv[i + 1];
            if (key == "--speed") speed = number(argv[i + 1], key);
            else if (key == "--fft-size") fftSize = static_cast<int>(number(argv[i + 1], key));
            else if (key == "--analysis-hop") {
                analysisHop = static_cast<int>(number(argv[i + 1], key)); hopSpecified = true;
            } else if (key == "--phase-locking") {
                if (value != "on" && value != "off") throw std::invalid_argument("--phase-locking expects on/off");
                phaseLocking = value == "on";
            } else if (key == "--transient") {
                if (value != "on" && value != "off") throw std::invalid_argument("--transient expects on/off");
                transientHandling = value == "on";
            } else if (key == "--transient-sensitivity") {
                transientSensitivity = static_cast<float>(number(argv[i + 1], key));
            } else if (key == "--transient-history") {
                transientHistory = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--transient-cooldown") {
                transientCooldown = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--transient-lookback") {
                transientLookback = static_cast<int>(number(argv[i + 1], key));
            } else if (key == "--debug-csv") {
                debugCsvDirectory = value;
            } else if (key == "--multiresolution") {
                if (value != "off") throw std::invalid_argument(key + " is unavailable");
            } else throw std::invalid_argument("Unknown/unsupported Phase 1 option: " + key);
        }
        if (!(speed > 0 && speed <= 1.25)) throw std::invalid_argument("Speed must be > 0 and <= 1.25");
        if (!hopSpecified) analysisHop = fftSize / 4;
        const auto input = ts::WavReader::read(argv[1]);
        ts::StretchConfig config;
        config.sampleRate = input.sampleRate;
        config.channels = static_cast<int>(input.channels.size());
        config.timeRatio = 1.0 / speed;
        config.fftSize = fftSize;
        config.analysisHop = analysisHop;
        config.enablePhaseLocking = phaseLocking;
        config.enableTransientHandling = transientHandling;
        config.transientSensitivity = transientSensitivity;
        config.transientHistoryFrames = transientHistory;
        config.transientCooldownFrames = transientCooldown;
        config.transientLookbackFrames = transientLookback;
        config.debugCsvDirectory = debugCsvDirectory;
        ts::TimeStretchEngine engine(config);
        const auto start = std::chrono::steady_clock::now();
        const auto output = engine.processOffline(input.channels);
        const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        ts::WavWriter::write(argv[2], {input.sampleRate, output});
        float peak = 0;
        for (const auto& channel : output) for (float sample : channel)
            peak = std::max(peak, std::abs(sample));
        std::cout << "FFT=" << fftSize << " Ha=" << analysisHop
                  << " Hs=" << engine.synthesisHop() << " speed=" << speed
                  << " phase_locking=" << (phaseLocking ? "on" : "off")
                  << " transient=" << (transientHandling ? "on" : "off")
                  << " transient_count=" << engine.lastTransientCount()
                  << " input_frames=" << input.channels.front().size()
                  << " output_frames=" << output.front().size()
                  << " processing_seconds=" << elapsed << " peak=" << peak << '\n';
        if (peak > 1.0f) std::cerr << "Warning: output peak exceeds 1.0 (no normalization applied)\n";
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n'; usage(); return 1;
    }
}
