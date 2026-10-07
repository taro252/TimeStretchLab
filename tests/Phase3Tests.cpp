#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include "dsp/TimeStretchEngine.h"
#include "dsp/TransientDetector.h"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr int rate = 44100;
constexpr double pi = std::numbers::pi;
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
double maxError(const std::vector<float>& a, const std::vector<float>& b) {
    check(a.size() == b.size(), "Output length differs");
    double error = 0;
    for (std::size_t i = 0; i < a.size(); ++i)
        error = std::max(error, std::abs(double(a[i]) - b[i]));
    return error;
}
double rms(const std::vector<float>& x) {
    double sum = 0;
    for (float sample : x) sum += double(sample) * sample;
    return std::sqrt(sum / x.size());
}
struct Attack {
    double peak = 0;
    double peakTime = 0;
    double widthMs = 0;
    double preEnergy = 0;
    double postEnergy = 0;
};
Attack attackAround(const std::vector<float>& x, double expectedTime, int sampleRate) {
    const auto center = static_cast<long long>(std::llround(expectedTime * sampleRate));
    const auto radius = static_cast<long long>(sampleRate * 0.12);
    const auto lo = static_cast<std::size_t>(std::max(0LL, center - radius));
    const auto hi = std::min(x.size(), static_cast<std::size_t>(center + radius));
    std::size_t peakIndex = lo;
    for (std::size_t i = lo; i < hi; ++i)
        if (std::abs(x[i]) > std::abs(x[peakIndex])) peakIndex = i;
    const double peak = std::abs(x[peakIndex]);
    std::size_t above = 0;
    double pre = 0, post = 0;
    for (std::size_t i = lo; i < hi; ++i) {
        if (std::abs(x[i]) >= 0.1 * peak) ++above;
        if (i < static_cast<std::size_t>(center)) pre += double(x[i]) * x[i];
        else post += double(x[i]) * x[i];
    }
    return {peak, double(peakIndex) / sampleRate, 1000.0 * above / sampleRate, pre, post};
}
void detectorUnit() {
    ts::TransientConfig config;
    ts::TransientDetector detector(65, config);
    std::vector<float> magnitudes(65, 1.0f);
    for (int frame = 0; frame < 30; ++frame) {
        const float level = frame == 8 ? 8.0f : (frame == 9 ? 8.0f : 1.0f);
        std::fill(magnitudes.begin(), magnitudes.end(), level);
        detector.pushMagnitudes(magnitudes.data());
    }
    detector.finalize();
    check(detector.transientCount() == 1, "Adaptive detector missed or duplicated synthetic onset");
    check(detector.frames()[8].detected && detector.resetAt(7), "Lookback did not mark preceding frame");
    check(!detector.resetAt(8), "Reset applied to the wrong frame");
    detector.reset();
    check(detector.frames().empty() && detector.transientCount() == 0, "Detector reset failed");
    std::cout << "detector_unit=pass lookback=1 cooldown=2\n";
}
ts::StretchConfig config(double speed, bool transient, int channels = 1) {
    ts::StretchConfig c;
    c.sampleRate = rate; c.channels = channels; c.timeRatio = 1.0 / speed;
    c.enablePhaseLocking = true;
    c.enableTransientHandling = transient;
    return c;
}
void phase2Regression(const std::filesystem::path& baseline) {
    const auto input = ts::WavReader::read(baseline / "sine_input.wav");
    for (const auto [speed, label] : {std::pair{0.75, "075"}, {0.5, "050"}}) {
        auto c = config(speed, false);
        c.sampleRate = 48000;
        const auto output = ts::TimeStretchEngine(c).processOffline(input.channels)[0];
        const auto expected = ts::WavReader::read(baseline / (std::string("sine_") + label + "_on.wav"));
        const auto error = maxError(output, expected.channels[0]);
        check(error < 1e-7, "Phase 3 OFF changed Phase 2 output");
        std::cout << "phase2_regression speed=" << speed << " max_error=" << error << '\n';
    }
}
std::vector<float> impulse() {
    std::vector<float> signal(5 * rate);
    signal[rate] = 0.8f;
    return signal;
}
std::vector<float> clicks() {
    std::vector<float> signal(5 * rate);
    for (int i = 0; i < 8; ++i) signal[rate + i * rate / 2] = 0.8f;
    return signal;
}
std::vector<float> drum() {
    std::vector<float> signal(5 * rate);
    unsigned state = 12345;
    // An ongoing tone makes phase history nontrivial when the drum attack arrives.
    for (std::size_t i = 0; i < signal.size(); ++i)
        signal[i] = float(0.08 * std::sin(2 * pi * 110 * i / rate));
    for (int n = 0; n < rate / 2; ++n) {
        state = state * 1664525u + 1013904223u;
        const double time = double(n) / rate;
        const double noise = time < 0.025 ? 0.2 * (double(state >> 8) / (1u << 24) - 0.5) : 0;
        signal[rate + n] += float(noise + 0.5 * std::exp(-15 * time) * std::sin(2 * pi * 100 * time));
    }
    return signal;
}
std::vector<float> sine(bool amplitudeRamp) {
    std::vector<float> signal(5 * rate);
    for (std::size_t i = 0; i < signal.size(); ++i) {
        const double amplitude = amplitudeRamp ? 0.2 + 0.3 * double(i) / signal.size() : 0.5;
        signal[i] = float(amplitude * std::sin(2 * pi * 440 * i / rate));
    }
    return signal;
}
void compare(const std::string& name, const std::vector<float>& input,
             const std::filesystem::path& outputDir) {
    if (!outputDir.empty()) ts::WavWriter::write(outputDir / (name + "_input.wav"), {rate, {input}});
    for (double speed : {0.75, 0.5}) {
        std::vector<float> previous;
        for (bool transient : {false, true}) {
            ts::TimeStretchEngine engine(config(speed, transient));
            const auto output = engine.processOffline({input})[0];
            check(output.size() == std::size_t(std::llround(input.size() / speed)), "Duration changed");
            check(std::all_of(output.begin(), output.end(), [](float x) { return std::isfinite(x); }),
                  "Non-finite Phase 3 output");
            const auto label = speed == 0.75 ? "075" : "050";
            if (!outputDir.empty())
                ts::WavWriter::write(outputDir / (name + "_" + label + (transient ? "_on.wav" : "_off.wav")),
                                     {rate, {output}});
            std::cout << name << " speed=" << speed << " transient=" << (transient ? "on" : "off")
                      << " count=" << engine.lastTransientCount() << " rms=" << rms(output);
            if (name == "impulse" || name == "click" || name == "drum") {
                const auto attack = attackAround(output, 1.0 / speed, rate);
                std::cout << " attack_peak=" << attack.peak << " attack_time=" << attack.peakTime
                          << " width_ms=" << attack.widthMs << " pre_energy=" << attack.preEnergy
                          << " post_energy=" << attack.postEnergy;
            }
            if (name == "click") {
                double largestIntervalError = 0;
                auto previousTime = attackAround(output, 1.0 / speed, rate).peakTime;
                for (int click = 1; click < 8; ++click) {
                    const auto time = attackAround(output, (1.0 + 0.5 * click) / speed, rate).peakTime;
                    largestIntervalError = std::max(largestIntervalError,
                        std::abs((time - previousTime) - 0.5 / speed));
                    previousTime = time;
                }
                check(largestIntervalError < 0.05, "Click spacing changed unexpectedly");
                std::cout << " max_interval_error_s=" << largestIntervalError;
            }
            if (transient) {
                if (name == "sine" || name == "slow_am")
                    check(engine.lastTransientCount() == 0, "Tonal input caused a phase reset");
                if (name == "impulse" || name == "click" || name == "drum")
                    check(engine.lastTransientCount() > 0, "Attack was not detected");
                std::cout << " on_off_max_difference=" << maxError(output, previous);
            } else previous = output;
            std::cout << '\n';
        }
    }
}
void stereoShared(const std::filesystem::path& outputDir) {
    std::vector<std::vector<float>> input(2, std::vector<float>(5 * rate));
    input[0][rate] = 0.8f;
    input[1][rate] = 0.4f;
    auto c = config(0.5, true, 2);
    if (!outputDir.empty()) c.debugCsvDirectory = (outputDir / "stereo_debug").string();
    ts::TimeStretchEngine engine(c);
    const auto output = engine.processOffline(input);
    check(engine.lastTransientCount() > 0, "Stereo attack not detected");
    check(std::all_of(output[0].begin(), output[0].end(), [](float x) { return std::isfinite(x); }) &&
          std::all_of(output[1].begin(), output[1].end(), [](float x) { return std::isfinite(x); }),
          "Non-finite stereo transient output");
    std::cout << "stereo_shared count=" << engine.lastTransientCount() << '\n';
}
}
int main(int argc, char** argv) {
    try {
        check(argc >= 2, "Phase 2 baseline directory required");
        const std::filesystem::path outputDir = argc >= 3 ? argv[2] : "";
        if (!outputDir.empty()) std::filesystem::create_directories(outputDir);
        std::cout << std::fixed << std::setprecision(6);
        detectorUnit();
        phase2Regression(argv[1]);
        compare("impulse", impulse(), outputDir);
        compare("click", clicks(), outputDir);
        compare("drum", drum(), outputDir);
        compare("sine", sine(false), outputDir);
        compare("slow_am", sine(true), outputDir);
        stereoShared(outputDir);
        std::cout << "PASS: Phase 3 tests\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n'; return 1;
    }
}
