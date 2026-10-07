#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/PhaseLocker.h"
#include "dsp/PhaseVocoder.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstdint>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr double pi = std::numbers::pi;
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
double maxError(const std::vector<float>& a, const std::vector<float>& b) {
    check(a.size() == b.size(), "Baseline length differs");
    double error = 0;
    for (std::size_t i = 0; i < a.size(); ++i)
        error = std::max(error, std::abs(double(a[i]) - b[i]));
    return error;
}
double rms(const std::vector<float>& x) {
    double sum = 0;
    for (float value : x) sum += double(value) * value;
    return std::sqrt(sum / x.size());
}
double maxAdjacentChange(const std::vector<float>& x) {
    double maximum = 0;
    for (std::size_t i = 1; i < x.size(); ++i)
        maximum = std::max(maximum, std::abs(double(x[i]) - x[i - 1]));
    return maximum;
}
double dominantFrequency(const std::vector<float>& x, int rate, double center) {
    const auto length = std::size_t(2 * rate), start = (x.size() - length) / 2;
    double best = 0, power = -1;
    for (int step = -50; step <= 50; ++step) {
        const double frequency = center + step * 0.02;
        double re = 0, im = 0;
        for (std::size_t i = 0; i < length; ++i) {
            const double window = 0.5 - 0.5 * std::cos(2 * pi * i / length);
            const double angle = 2 * pi * frequency * i / rate;
            re += x[start + i] * window * std::cos(angle);
            im -= x[start + i] * window * std::sin(angle);
        }
        if (const double candidate = re * re + im * im; candidate > power) {
            power = candidate; best = frequency;
        }
    }
    return best;
}
double toneAmplitude(const std::vector<float>& x, int rate, double frequency) {
    const auto length = std::size_t(2 * rate), start = (x.size() - length) / 2;
    double re = 0, im = 0;
    for (std::size_t i = 0; i < length; ++i) {
        const double angle = 2 * pi * frequency * i / rate;
        re += x[start + i] * std::cos(angle);
        im -= x[start + i] * std::sin(angle);
    }
    return 2 * std::hypot(re, im) / length;
}
double rmsRange(const std::vector<float>& x, int rate) {
    double minimum = 1e9, maximum = 0;
    for (std::size_t start = rate; start + rate < x.size(); start += rate) {
        double sum = 0;
        for (std::size_t i = start; i < start + rate; ++i) sum += double(x[i]) * x[i];
        const double value = std::sqrt(sum / rate);
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
    }
    return maximum / minimum;
}
double movingEnvelopeRange(const std::vector<float>& x, int rate) {
    const auto block = std::size_t(rate / 50); // 20 ms windows expose fast modulation.
    const auto margin = std::size_t(rate * 0.3);
    double minimum = 1e9, maximum = 0;
    for (std::size_t start = margin; start + block + margin < x.size(); start += block) {
        double sum = 0;
        for (std::size_t i = start; i < start + block; ++i) sum += double(x[i]) * x[i];
        const double value = std::sqrt(sum / block);
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
    }
    return maximum / minimum;
}
void unitPeakMap() {
    constexpr std::size_t size = 128;
    ts::PhaseLocker locker(size);
    std::vector<std::complex<float>> spectrum(size / 2 + 1), output(size / 2 + 1);
    locker.analyzePeaks(spectrum.data(), spectrum.size());
    check(locker.peaks().empty(), "Silent spectrum produced a peak");
    spectrum[20] = std::polar(10.0f, 0.3f);
    spectrum[19] = std::polar(2.0f, 0.1f);
    spectrum[21] = std::polar(3.0f, 0.8f);
    spectrum[30] = std::polar(8.0f, -0.2f);
    spectrum[29] = std::polar(2.0f, 0.4f);
    spectrum[31] = std::polar(2.0f, -0.4f);
    spectrum[40] = std::polar(0.005f, 0.5f); // Below the -60 dB relative cutoff.
    locker.analyzePeaks(spectrum.data(), spectrum.size());
    check(locker.peaks().size() == 2, "Peak threshold/local maximum failed");
    check(locker.peaks()[0].bin == 20 && locker.peaks()[1].bin == 30,
          "Peak order failed");
    check(locker.ownerPeak()[25] == 20 && locker.ownerPeak()[26] == 30,
          "Midpoint owner region failed");
    std::vector<double> propagated(size / 2 + 1);
    propagated[20] = 1.4; propagated[30] = -1.1;
    output[20] = std::polar(10.0f, 1.4f);
    output[30] = std::polar(8.0f, -1.1f);
    locker.lock(propagated, output.data());
    check(std::abs(std::remainder(std::arg(output[21]) - (1.4 + 0.8 - 0.3), 2 * pi)) < 1e-6,
          "Identity phase relation failed");
    check(std::abs(std::arg(output[20]) - 1.4) < 1e-6, "Peak anchor changed");
    check(std::abs(std::remainder(propagated[21] - std::arg(output[21]), 2 * pi)) < 1e-6,
          "Locked phase was not committed to synthesis state");
    check(std::abs(propagated[20] - 1.4) < 1e-12, "Peak synthesis state changed");
    check(std::abs(std::abs(output[40]) - 0.005f) < 1e-6f,
          "Non-peak bin magnitude was not preserved");

    std::fill(spectrum.begin(), spectrum.end(), std::complex<float>(0, 0));
    // A Gaussian in log magnitude has its exact parabola apex at bin 40.3.
    for (int k = 39; k <= 41; ++k)
        spectrum[k] = {float(std::exp(-0.8 * (k - 40.3) * (k - 40.3))), 0};
    locker.analyzePeaks(spectrum.data(), spectrum.size());
    check(locker.peaks().size() == 1 && std::abs(locker.peaks()[0].position - 40.3f) < 0.01f,
          "Log-parabolic sub-bin interpolation failed");
    std::cout << "peak_map=pass midpoint=pass interpolation=" << locker.peaks()[0].position << '\n';
}
void movingPeakState() {
    constexpr std::size_t size = 128;
    constexpr int hop = 32, bin = 21;
    constexpr double synthesisHop = 64;
    ts::PhaseVocoder vocoder(size, hop, true);
    std::vector<std::complex<float>> spectrum(size / 2 + 1), output(size / 2 + 1);
    auto frame = [&](float magnitude20, float phase20, float magnitude21, float phase21) {
        std::fill(spectrum.begin(), spectrum.end(), std::complex<float>(0, 0));
        spectrum[20] = std::polar(magnitude20, phase20);
        spectrum[21] = std::polar(magnitude21, phase21);
        vocoder.process(spectrum.data(), output.data(), synthesisHop);
        return double(std::arg(output[bin]));
    };
    frame(10.0f, 0.3f, 2.0f, 0.8f);
    const double lockedPrevious = frame(10.0f, 0.4f, 2.0f, 1.0f);
    check(vocoder.phaseLocker().ownerPeak()[bin] == 20, "Setup bin was not locked to peak 20");
    const double current = frame(2.0f, 0.6f, 10.0f, 1.3f);
    check(vocoder.phaseLocker().ownerPeak()[bin] == bin, "Moving bin did not become a peak");
    const double omega = 2 * pi * bin / size;
    const double residual = std::remainder(1.3 - 1.0 - omega * hop, 2 * pi);
    const double expected = std::remainder(lockedPrevious + (omega + residual / hop) * synthesisHop, 2 * pi);
    check(std::abs(std::remainder(current - expected, 2 * pi)) < 1e-5,
          "New peak propagated from stale, pre-lock synthesis phase");
    std::cout << "moving_peak_state=pass\n";
}
ts::StretchConfig config(int rate, double speed, bool locking) {
    ts::StretchConfig c;
    c.sampleRate = rate; c.channels = 1; c.timeRatio = 1 / speed;
    c.enablePhaseLocking = locking;
    return c;
}
void phase1Baseline(const std::filesystem::path& baseline) {
    const auto input = ts::WavReader::read(baseline / "input_sine.wav");
    for (const auto [speed, label] : {std::pair{0.75, "075"}, {0.5, "050"}}) {
        const auto expected = ts::WavReader::read(baseline / (std::string("sine_") + label + ".wav"));
        const auto actual = ts::TimeStretchEngine(config(44100, speed, false)).processOffline(input.channels);
        const auto error = maxError(actual[0], expected.channels[0]);
        check(error < 1e-7, "Phase-locking OFF differs from saved Phase 1 result");
        std::cout << "phase1_baseline speed=" << speed << " max_error=" << error << '\n';
    }
}
void silentFallback() {
    for (int channels : {1, 2}) for (double speed : {0.75, 0.5}) {
        auto c = config(44100, speed, true);
        c.channels = channels;
        std::vector<std::vector<float>> input(channels, std::vector<float>(44100, 0.0f));
        auto output = ts::TimeStretchEngine(c).processOffline(input);
        for (const auto& channel : output)
            check(std::all_of(channel.begin(), channel.end(), [](float sample) {
                return std::isfinite(sample) && sample == 0.0f;
            }), "Phase locking silence fallback failed");
    }
    std::cout << "silent_fallback mono_stereo=pass\n";
}
std::vector<float> sine(int rate, double frequency, double duration) {
    std::vector<float> signal(std::size_t(std::llround(rate * duration)));
    for (std::size_t i = 0; i < signal.size(); ++i)
        signal[i] = float(0.5 * std::sin(2 * pi * frequency * i / rate));
    return signal;
}
std::vector<float> harmonics(int rate) {
    constexpr double amplitudes[] = {1.0, 0.8, 0.6, 0.5, 0.4, 0.3};
    std::vector<float> signal(10 * rate);
    for (std::size_t i = 0; i < signal.size(); ++i) {
        double sample = 0;
        for (int harmonic = 1; harmonic <= 6; ++harmonic)
            sample += amplitudes[harmonic - 1] * std::sin(2 * pi * 110 * harmonic * i / rate);
        signal[i] = float(0.15 * sample);
    }
    return signal;
}
std::vector<float> moving(int rate) {
    std::vector<float> signal(10 * rate);
    double phase = 0;
    for (std::size_t i = 0; i < signal.size(); ++i) {
        const double frequency = 400 + 100 * double(i) / signal.size();
        signal[i] = float(0.5 * std::sin(phase));
        phase += 2 * pi * frequency / rate;
    }
    return signal;
}
std::vector<float> nearby(int rate) {
    std::vector<float> signal(10 * rate);
    for (std::size_t i = 0; i < signal.size(); ++i)
        signal[i] = float(0.25 * (std::sin(2 * pi * 440 * i / rate) +
                                   std::sin(2 * pi * 470 * i / rate)));
    return signal;
}
std::vector<float> noise(int rate) {
    std::vector<float> signal(10 * rate);
    std::uint32_t state = 123456789;
    for (auto& sample : signal) {
        state = state * 1664525u + 1013904223u;
        sample = float(0.2 * (double(state >> 8) / double(1u << 24) - 0.5));
    }
    return signal;
}
void compareSignal(const std::string& name, const std::vector<float>& input,
                   int rate, const std::filesystem::path& outputDir) {
    if (!outputDir.empty()) ts::WavWriter::write(outputDir / (name + "_input.wav"), {std::uint32_t(rate), {input}});
    for (double speed : {0.75, 0.5}) {
        std::vector<float> previous;
        for (bool locking : {false, true}) {
            const auto start = std::chrono::steady_clock::now();
            const auto output = ts::TimeStretchEngine(config(rate, speed, locking)).processOffline({input})[0];
            const auto processing = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
            check(std::all_of(output.begin(), output.end(), [](float x) { return std::isfinite(x); }),
                  "Non-finite artificial signal output");
            const auto maxLevel = *std::max_element(output.begin(), output.end(),
                [](float a, float b) { return std::abs(a) < std::abs(b); });
            check(std::abs(maxLevel) < 3.0f, "Excessive artificial signal output level");
            const std::string label = speed == 0.75 ? "075" : "050";
            if (!outputDir.empty())
                ts::WavWriter::write(outputDir / (name + "_" + label + (locking ? "_on.wav" : "_off.wav")),
                                     {std::uint32_t(rate), {output}});
            std::cout << name << " speed=" << speed << " locking=" << (locking ? "on" : "off")
                      << " rms=" << rms(output) << " peak=" << std::abs(maxLevel)
                      << " max_adjacent_change=" << maxAdjacentChange(output)
                      << " process_s=" << processing;
            if (name == "sine") {
                const double frequency = dominantFrequency(output, rate, 437.3);
                check(std::abs(frequency - 437.3) <= 0.5, "Off-bin sine pitch changed");
                if (locking) check(std::abs(rms(output) - 0.5 / std::sqrt(2.0)) < 0.02,
                                   "Phase locking degraded single sine level");
                std::cout << " dominant_hz=" << frequency;
            }
            if (name == "harmonic") {
                std::cout << " harmonic_amplitudes=";
                for (int harmonic = 1; harmonic <= 6; ++harmonic)
                    std::cout << (harmonic == 1 ? "" : "/") << toneAmplitude(output, rate, 110 * harmonic);
            }
            if (name == "nearby")
                std::cout << " amplitudes_440_470=" << toneAmplitude(output, rate, 440)
                          << '/' << toneAmplitude(output, rate, 470);
            if (name == "moving" && locking) {
                check(maxAdjacentChange(output) < 0.15, "Moving peak caused a large sample jump");
                const auto modulation = movingEnvelopeRange(output, rate);
                check(modulation < 1.05, "Moving peak caused strong periodic level modulation");
                std::cout << " moving_20ms_rms_range=" << modulation;
            }
            if (name == "noise") {
                const auto variation = rmsRange(output, rate);
                check(variation < 3.0, "Noise level became unstable");
                std::cout << " one_second_rms_range=" << variation;
            }
            if (locking) std::cout << " on_off_max_difference=" << maxError(output, previous);
            std::cout << '\n';
            if (!locking) previous = output;
        }
    }
}
}

int main(int argc, char** argv) {
    try {
        check(argc >= 2, "Phase 1 baseline directory required");
        const std::filesystem::path outputDir = argc >= 3 ? argv[2] : "";
        if (!outputDir.empty()) std::filesystem::create_directories(outputDir);
        std::cout << std::fixed << std::setprecision(6);
        unitPeakMap();
        movingPeakState();
        phase1Baseline(argv[1]);
        silentFallback();
        compareSignal("sine", sine(48000, 437.3, 10), 48000, outputDir);
        compareSignal("harmonic", harmonics(44100), 44100, outputDir);
        compareSignal("moving", moving(44100), 44100, outputDir);
        compareSignal("nearby", nearby(44100), 44100, outputDir);
        compareSignal("noise", noise(44100), 44100, outputDir);
        std::cout << "PASS: Phase 2 peak locking tests\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n'; return 1;
    }
}
