#include "audio/WavWriter.h"
#include "dsp/TimeStretchEngine.h"
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
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
std::vector<float> signal(const std::string& name) {
    std::vector<float> x(5 * rate);
    if (name == "click") for (int n = 0; n < 8; ++n) x[rate + n * rate / 2] = 0.8f;
    if (name == "sine") for (std::size_t i = 0; i < x.size(); ++i)
        x[i] = float(0.5 * std::sin(2 * pi * 440 * i / rate));
    if (name == "drum") {
        unsigned state = 12345;
        for (std::size_t i = 0; i < x.size(); ++i)
            x[i] = float(0.08 * std::sin(2 * pi * 110 * i / rate));
        for (int n = 0; n < rate / 2; ++n) {
            state = state * 1664525u + 1013904223u;
            const double t = double(n) / rate;
            const double noise = t < 0.025 ? 0.2 * (double(state >> 8) / (1u << 24) - 0.5) : 0;
            x[rate + n] += float(noise + 0.5 * std::exp(-15 * t) * std::sin(2 * pi * 100 * t));
        }
    }
    return x;
}
ts::StretchConfig config(double speed, bool precise, int channels = 1,
                         const std::filesystem::path& debug = {}) {
    ts::StretchConfig c;
    c.sampleRate = rate; c.channels = channels; c.timeRatio = 1.0 / speed;
    c.enablePhaseLocking = true;
    c.enableTransientHandling = true;
    c.enableAdaptiveTimeMapping = true;
    c.enablePreciseTransientAnchoring = precise;
    c.debugCsvDirectory = debug.string();
    return c;
}
double maxDifference(const std::vector<float>& left, const std::vector<float>& right) {
    check(left.size() == right.size(), "Duration changed");
    double value = 0;
    for (std::size_t i = 0; i < left.size(); ++i)
        value = std::max(value, std::abs(double(left[i]) - right[i]));
    return value;
}
struct Attack { double peakTime = 0, widthMs = 0; };
Attack attack(const std::vector<float>& x, double expected) {
    const long long center = std::llround(expected * rate);
    const auto lo = static_cast<std::size_t>(std::max(0LL, center - rate * 12 / 100));
    const auto hi = std::min(x.size(), static_cast<std::size_t>(center + rate * 12 / 100));
    std::size_t peakAt = lo;
    for (auto i = lo; i < hi; ++i)
        if (std::abs(x[i]) > std::abs(x[peakAt])) peakAt = i;
    Attack result;
    result.peakTime = double(peakAt) / rate;
    for (auto i = lo; i < hi; ++i)
        if (std::abs(x[i]) >= std::abs(x[peakAt]) * 0.1) result.widthMs += 1000.0 / rate;
    return result;
}
void compare(const std::string& name, double speed, const std::filesystem::path& dir) {
    const auto input = signal(name);
    const auto label = speed == 0.75 ? "075" : "050";
    ts::TimeStretchEngine phase35(config(speed, false));
    ts::TimeStretchEngine phase37off(config(speed, false));
    ts::TimeStretchEngine phase37(config(speed, true,
        1, name == "click" ? dir / "click_debug" : std::filesystem::path{}));
    const auto baseline = phase35.processOffline({input})[0];
    const auto disabled = phase37off.processOffline({input})[0];
    const auto output = phase37.processOffline({input})[0];
    check(maxDifference(baseline, disabled) == 0, "Anchoring OFF differs from Phase 3.5");
    check(output.size() == std::size_t(std::llround(input.size() / speed)), "Wrong duration");
    check(std::all_of(output.begin(), output.end(), [](float x) { return std::isfinite(x); }),
          "Non-finite output");
    check(phase37.lastAnchorMaxErrorSamples() <= 1, "Precise event anchor moved");
    ts::WavWriter::write(dir / (name + "_" + label + "_phase35.wav"), {rate, {baseline}});
    ts::WavWriter::write(dir / (name + "_" + label + "_phase37.wav"), {rate, {output}});
    std::cout << name << " speed=" << speed << " events=" << phase37.lastEventCount()
              << " anchored=" << phase37.lastAnchoredEventCount()
              << " off_max_difference=0 on_max_difference=" << maxDifference(baseline, output);
    if (name == "click") {
        check(phase37.lastEventCount() == 8 && phase37.lastAnchoredEventCount() == 8,
              "A clear click was not anchored");
        double maximum = 0;
        for (int n = 1; n < 8; ++n) {
            const auto before = attack(output, (1.0 + (n - 1) * 0.5) / speed).peakTime;
            const auto after = attack(output, (1.0 + n * 0.5) / speed).peakTime;
            maximum = std::max(maximum, std::abs((after - before) - 0.5 / speed));
        }
        std::cout << " max_interval_error_ms=" << maximum * 1000;
        check(maximum <= 0.003, "Click interval error exceeds 3 ms");
    }
    if (name == "drum") {
        const auto before = attack(baseline, 1.0 / speed);
        const auto after = attack(output, 1.0 / speed);
        std::cout << " phase35_width_ms=" << before.widthMs
                  << " phase37_width_ms=" << after.widthMs;
        check(phase37.lastEventCount() == 1, "Drum event was split");
        check(after.widthMs <= before.widthMs + 0.5, "Drum attack width worsened");
    }
    if (name == "sine") {
        check(phase37.lastEventCount() == 0 && baseline == output,
              "Tonal signal changed without an event");
    }
    std::cout << '\n';
}
void stereo(const std::filesystem::path& dir) {
    const auto left = signal("click");
    auto right = left;
    for (auto& sample : right) sample *= 0.5f;
    ts::TimeStretchEngine engine(config(0.5, true, 2, dir / "stereo_debug"));
    const auto output = engine.processOffline({left, right});
    check(engine.lastAnchoredEventCount() == 8, "Stereo click anchors differ");
    double error = 0;
    for (std::size_t i = 0; i < output[0].size(); ++i)
        error = std::max(error, std::abs(double(output[0][i]) * 0.5 - output[1][i]));
    check(error < 1e-5, "Stereo channels used different timing");
    std::cout << "stereo_click max_channel_error=" << error << '\n';
}
}
int main(int argc, char** argv) {
    try {
        check(argc == 2, "Output directory required");
        const std::filesystem::path dir = argv[1];
        std::filesystem::create_directories(dir);
        std::cout << std::fixed << std::setprecision(6);
        for (double speed : {0.75, 0.5})
            for (const std::string name : {"click", "drum", "sine"}) compare(name, speed, dir);
        stereo(dir);
        std::cout << "PASS: Phase 3.7 tests\n";
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n'; return 1;
    }
}
