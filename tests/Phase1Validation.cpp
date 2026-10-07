#include "dsp/FFTAccelerate.h"
#include "dsp/OverlapAdd.h"
#include "dsp/PhaseVocoder.h"
#include "dsp/STFT.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
constexpr int rate = 44100;
constexpr std::size_t fftSize = 4096, hop = 1024;

void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
double maxError(const std::vector<float>& a, const std::vector<float>& b) {
    check(a.size() == b.size(), "Comparison length mismatch");
    double error = 0;
    for (std::size_t i = 0; i < a.size(); ++i)
        error = std::max(error, std::abs(double(a[i]) - b[i]));
    return error;
}
std::vector<float> arbitrarySignal(std::size_t count) {
    std::vector<float> signal(count);
    std::uint32_t state = 0x12345678;
    for (std::size_t i = 0; i < count; ++i) {
        state = state * 1664525u + 1013904223u;
        const double noise = double(state >> 8) / double(1u << 24) - 0.5;
        signal[i] = float(0.3 * noise + 0.4 * std::sin(2 * std::numbers::pi * 437.3 * i / rate));
    }
    return signal;
}
double fftRoundTrip() {
    ts::FFTAccelerate fft(fftSize);
    const auto input = arbitrarySignal(fftSize);
    std::vector<std::complex<float>> spectrum(fftSize / 2 + 1);
    std::vector<float> output(fftSize);
    fft.forward(input.data(), spectrum.data());
    fft.inverse(spectrum.data(), output.data());
    const auto error = maxError(input, output);
    check(error < 1e-5, "FFT/IFFT scaling or reconstruction failed");
    return error;
}
double stftReconstruction() {
    const auto input = arbitrarySignal(2 * rate);
    ts::STFT stft(fftSize);
    const auto padding = fftSize / 2;
    ts::OverlapAdd ola(input.size() + 4 * fftSize);
    std::vector<float> frame(fftSize), synthesized(fftSize);
    std::vector<std::complex<float>> spectrum(fftSize / 2 + 1);
    // This path deliberately calls STFT and OLA directly: no engine unity bypass.
    const auto frameCount = (input.size() + padding + hop - 1) / hop + 1;
    for (std::size_t frameIndex = 0; frameIndex < frameCount; ++frameIndex) {
        const auto start = frameIndex * hop;
        for (std::size_t i = 0; i < fftSize; ++i) {
            const auto padded = start + i;
            frame[i] = padded >= padding && padded - padding < input.size()
                ? input[padded - padding] : 0.0f;
        }
        stft.analyze(frame.data(), spectrum.data());
        stft.synthesize(spectrum.data(), synthesized.data());
        ola.add(synthesized.data(), stft.window().data(), fftSize, start);
    }
    const auto output = ola.finish(input.size(), padding);
    const auto error = maxError(input, output);
    check(error < 1e-5, "STFT/OLA window normalization failed");
    return error;
}
double measuredFrequency(const std::vector<float>& input, double nearHz) {
    // Hann-weighted DFT search around the expected pitch; 0.02 Hz grid is
    // finer than a single FFT bin and does not depend on the engine's FFT.
    constexpr std::size_t length = 2 * rate;
    check(input.size() >= length, "Frequency test signal too short");
    const auto start = (input.size() - length) / 2;
    double bestHz = 0, bestPower = -1;
    for (int step = -50; step <= 50; ++step) {
        const double hz = nearHz + step * 0.02;
        double re = 0, im = 0;
        for (std::size_t i = 0; i < length; ++i) {
            const double window = 0.5 - 0.5 * std::cos(2 * std::numbers::pi * i / length);
            const double angle = 2 * std::numbers::pi * hz * i / rate;
            re += input[start + i] * window * std::cos(angle);
            im -= input[start + i] * window * std::sin(angle);
        }
        const double power = re * re + im * im;
        if (power > bestPower) { bestPower = power; bestHz = hz; }
    }
    return bestHz;
}
ts::StretchConfig configFor(int channels, double speed) {
    ts::StretchConfig config;
    config.sampleRate = rate;
    config.channels = channels;
    config.timeRatio = 1.0 / speed;
    return config;
}
void offBinSine() {
    constexpr double frequency = 437.3;
    std::vector<float> sine(5 * rate);
    for (std::size_t i = 0; i < sine.size(); ++i)
        sine[i] = float(0.5 * std::sin(2 * std::numbers::pi * frequency * i / rate));
    for (double speed : {0.75, 0.5}) {
        auto output = ts::TimeStretchEngine(configFor(1, speed)).processOffline({sine})[0];
        check(std::all_of(output.begin(), output.end(), [](float value) { return std::isfinite(value); }),
              "Non-finite off-bin sine output");
        const auto hz = measuredFrequency(output, frequency);
        check(std::abs(hz - frequency) < 0.5, "Off-bin sine pitch drift");
        std::cout << "off_bin speed=" << speed << " dominant_hz=" << hz << '\n';
    }
}
void longDuration() {
    // Sparse 300-second artificial input still runs the full DSP path.
    std::vector<std::vector<float>> input(1, std::vector<float>(300 * rate));
    input[0][rate] = 0.1f;
    for (double speed : {0.75, 0.5}) {
        auto output = ts::TimeStretchEngine(configFor(1, speed)).processOffline(input);
        check(std::all_of(output[0].begin(), output[0].end(), [](float value) { return std::isfinite(value); }),
              "Non-finite long-duration output");
        const auto expected = static_cast<std::size_t>(std::llround(double(input[0].size()) / speed));
        const auto difference = static_cast<long long>(output[0].size()) - static_cast<long long>(expected);
        check(std::abs(difference) < static_cast<long long>(hop), "Long duration error");
        std::cout << "duration speed=" << speed << " samples=" << output[0].size()
                  << " expected=" << expected << " difference=" << difference << '\n';
    }
}
void thresholdReentry() {
    constexpr std::size_t bin = 41;
    std::vector<std::complex<float>> input(fftSize / 2 + 1), output(fftSize / 2 + 1);
    for (double speed : {0.75, 0.5}) {
        ts::PhaseVocoder vocoder(fftSize, hop);
        auto step = [&](float magnitude, float phase) {
            input[bin] = std::polar(magnitude, phase);
            vocoder.process(input.data(), output.data(), hop / speed);
            const auto value = output[bin];
            check(std::isfinite(value.real()) && std::isfinite(value.imag()), "Non-finite threshold output");
            check(std::abs(value) < 3e-7, "Threshold output magnitude exploded");
            return value;
        };
        step(2e-7f, 0.3f);
        for (int frame = 0; frame < 4; ++frame)
            check(step(5e-8f, float(0.6 * frame)) == std::complex<float>(0, 0), "Subthreshold output not muted");
        const auto recovered = step(2e-7f, 1.2f);
        const auto phaseError = std::remainder(std::arg(recovered) - 1.2, 2 * std::numbers::pi);
        check(std::abs(phaseError) < 1e-5, "Threshold re-entry phase jump");
    }
    std::cout << "threshold_reentry finite=yes excessive_magnitude=no phase_jump=no\n";
}
void silenceAndStereo() {
    for (int channels : {1, 2}) for (double speed : {0.75, 0.5}) {
        std::vector<std::vector<float>> silence(channels, std::vector<float>(rate));
        auto output = ts::TimeStretchEngine(configFor(channels, speed)).processOffline(silence);
        for (const auto& channel : output)
            check(std::all_of(channel.begin(), channel.end(), [](float value) {
                return std::isfinite(value) && value == 0.0f;
            }), "Silence produced NaN/Inf or noise");
    }
    std::cout << "silence mono_stereo speeds=0.75,0.50 finite=yes noise=no\n";

    for (double speed : {0.75, 0.5}) {
        std::vector<std::vector<float>> stereo(2, std::vector<float>(5 * rate));
        for (std::size_t i = 0; i < stereo[0].size(); ++i) {
            const double phase = 2 * std::numbers::pi * 440 * i / rate;
            stereo[0][i] = float(0.5 * std::sin(phase));
            stereo[1][i] = float(0.5 * std::sin(phase + 0.7));
        }
        const auto output = ts::TimeStretchEngine(configFor(2, speed)).processOffline(stereo);
        for (const auto& channel : output)
            check(std::all_of(channel.begin(), channel.end(), [](float value) { return std::isfinite(value); }),
                  "Non-finite stereo output");
        double minRatio = 10, maxRatio = 0;
        for (std::size_t start = rate; start + rate <= output[0].size() - rate; start += rate) {
            double left = 0, right = 0;
            for (std::size_t i = start; i < start + rate; ++i) {
                left += double(output[0][i]) * output[0][i];
                right += double(output[1][i]) * output[1][i];
            }
            const double ratio = std::sqrt(left / right);
            minRatio = std::min(minRatio, ratio);
            maxRatio = std::max(maxRatio, ratio);
        }
        check(minRatio > 0.9 && maxRatio < 1.1, "Stereo channel amplitude imbalance");
        check(maxRatio - minRatio < 0.1, "Stereo channel amplitude fluctuated");
        std::cout << "stereo speed=" << speed << " min_lr_rms_ratio=" << minRatio
                  << " max_lr_rms_ratio=" << maxRatio << '\n';
    }
}
void defaults() {
    const ts::StretchConfig config;
    check(!config.enablePhaseLocking && !config.enableTransientHandling && !config.enableMultiResolution,
          "Phase 1 advanced features must default off");
    std::cout << "advanced_feature_defaults=off\n";
}
}

int main() {
    try {
        std::cout << std::fixed << std::setprecision(8);
        defaults();
        std::cout << "fft_round_trip_max_error=" << fftRoundTrip() << '\n';
        std::cout << "stft_ola_max_error=" << stftReconstruction() << '\n';
        offBinSine();
        thresholdReentry();
        silenceAndStereo();
        longDuration();
        std::cout << "PASS: all Phase 1 validation checks\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
