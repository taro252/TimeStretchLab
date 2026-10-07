#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/FFTAccelerate.h"
#include "dsp/PhaseVocoder.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
double rms(const std::vector<float>& x) {
    double sum = 0;
    for (float sample : x) sum += double(sample) * sample;
    return std::sqrt(sum / x.size());
}
double dominantFrequency(const std::vector<float>& x, double rate) {
    // Independent measurement: scan the central two seconds with a Hann-weighted DFT.
    const std::size_t count = static_cast<std::size_t>(2 * rate);
    const std::size_t start = (x.size() - count) / 2;
    double bestFrequency = 0, bestPower = -1;
    for (double hz = 435; hz <= 445; hz += 0.1) {
        double re = 0, im = 0;
        for (std::size_t n = 0; n < count; ++n) {
            const double w = 0.5 - 0.5 * std::cos(2 * std::numbers::pi * n / count);
            const double angle = 2 * std::numbers::pi * hz * n / rate;
            re += x[start + n] * w * std::cos(angle);
            im -= x[start + n] * w * std::sin(angle);
        }
        const double power = re * re + im * im;
        if (power > bestPower) { bestPower = power; bestFrequency = hz; }
    }
    return bestFrequency;
}
void testThresholdCrossing() {
    // One spectral bin represents a low-amplitude sinusoid whose amplitude
    // falls below the tracking threshold for two frames, then returns.
    constexpr std::size_t size = 4096, bin = 41;
    std::vector<std::complex<float>> input(size / 2 + 1), output(size / 2 + 1);
    for (double synthesisHop : {1024.0 / 0.75, 2048.0}) {
        ts::PhaseVocoder vocoder(size, 1024);
        auto step = [&](float magnitude, float phase) {
            input[bin] = std::polar(magnitude, phase);
            vocoder.process(input.data(), output.data(), synthesisHop);
            return output[bin];
        };
        step(2e-7f, 0.3f);
        require(step(5e-8f, 0.7f) == std::complex<float>(0, 0), "Subthreshold bin was not muted");
        require(step(5e-8f, -0.8f) == std::complex<float>(0, 0), "Subthreshold bin was not muted");
        const auto resumed = step(2e-7f, 1.2f);
        // At a fresh onset the output phase must match the input phase. A stale
        // previous phase would create an unrelated jump here.
        const auto phaseError = std::remainder(std::arg(resumed) - 1.2, 2 * std::numbers::pi);
        require(std::abs(phaseError) < 1e-5, "Phase jump after threshold crossing");
        require(std::abs(std::abs(resumed) - 2e-7f) < 1e-12, "Recovered sinusoid amplitude changed");
    }
}
}
int main(int argc, char** argv) {
    try {
        testThresholdCrossing();
        const auto resultDir = argc > 1 ? std::filesystem::path(argv[1]) : std::filesystem::path();
        if (!resultDir.empty()) std::filesystem::create_directories(resultDir);
        constexpr int rate = 44100;
        constexpr std::size_t samples = 5 * rate;
        std::vector<float> sine(samples), impulse(samples, 0.0f), silence(samples, 0.0f);
        for (std::size_t i = 0; i < samples; ++i)
            sine[i] = 0.5f * std::sin(2 * std::numbers::pi * 440 * i / rate);
        impulse[rate] = 0.8f;

        ts::FFTAccelerate fft(4096);
        std::vector<float> original(4096), reconstructed(4096);
        for (std::size_t i = 0; i < original.size(); ++i)
            original[i] = std::sin(2 * std::numbers::pi * 440 * i / rate);
        std::vector<std::complex<float>> bins(2049);
        fft.forward(original.data(), bins.data());
        fft.inverse(bins.data(), reconstructed.data());
        double fftError = 0;
        for (std::size_t i = 0; i < original.size(); ++i)
            fftError = std::max(fftError, std::abs(double(original[i] - reconstructed[i])));
        require(fftError < 1e-5, "FFT round trip error");

        if (!resultDir.empty()) {
            ts::WavWriter::write(resultDir / "input_sine.wav", {rate, {sine}});
            auto readback = ts::WavReader::read(resultDir / "input_sine.wav");
            require(readback.channels[0] == sine, "WAV float32 round trip");
        }

        std::ofstream metrics;
        if (!resultDir.empty()) metrics.open(resultDir / "metrics.txt");
        for (double speed : {1.0, 0.75, 0.5}) {
            ts::StretchConfig config;
            config.sampleRate = rate; config.channels = 1; config.timeRatio = 1.0 / speed;
            ts::TimeStretchEngine engine(config);
            const auto start = std::chrono::steady_clock::now();
            auto output = engine.processOffline({sine})[0];
            const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
            const auto expected = static_cast<std::size_t>(std::llround(samples / speed));
            require(std::abs(static_cast<long long>(output.size()) - static_cast<long long>(expected)) < config.analysisHop,
                    "Duration error exceeds one analysis hop");
            require(std::all_of(output.begin(), output.end(), [](float x) { return std::isfinite(x); }),
                    "Non-finite sine output");
            const auto pitch = dominantFrequency(output, rate);
            require(std::abs(pitch - 440) <= 1, "440 Hz pitch drift");
            if (speed == 1.0) {
                double maxError = 0;
                for (std::size_t i = 0; i < samples; ++i)
                    maxError = std::max(maxError, std::abs(double(output[i] - sine[i])));
                require(maxError == 0 && std::abs(rms(output) / rms(sine) - 1) < 1e-6,
                        "Unity output changed volume or samples");
            }
            const auto label = speed == 1.0 ? "100" : speed == 0.75 ? "075" : "050";
            if (!resultDir.empty()) ts::WavWriter::write(resultDir / (std::string("sine_") + label + ".wav"), {rate, {output}});
            auto& stream = resultDir.empty() ? std::cout : metrics;
            stream << std::fixed << std::setprecision(4) << "sine speed=" << speed
                   << " frames=" << output.size() << " duration_s=" << double(output.size()) / rate
                   << " dominant_hz=" << pitch << " rms=" << rms(output)
                   << " processing_s=" << elapsed << '\n';

            auto impulseOutput = engine.processOffline({impulse})[0];
            require(impulseOutput.size() == expected, "Impulse duration mismatch");
            require(std::all_of(impulseOutput.begin(), impulseOutput.end(), [](float x) { return std::isfinite(x); }),
                    "Non-finite impulse output");
            if (!resultDir.empty()) ts::WavWriter::write(resultDir / (std::string("impulse_") + label + ".wav"), {rate, {impulseOutput}});
        }
        ts::StretchConfig config;
        config.channels = 1; config.timeRatio = 2;
        auto zeros = ts::TimeStretchEngine(config).processOffline({silence})[0];
        require(std::all_of(zeros.begin(), zeros.end(), [](float x) { return std::isfinite(x) && x == 0.0f; }),
                "Silence became non-finite or nonzero");
        std::cout << "PASS: FFT, WAV, 440 Hz pitch, duration, unity, impulse, silence, threshold crossing\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n'; return 1;
    }
}
