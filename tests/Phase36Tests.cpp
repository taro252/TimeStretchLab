#include "audio/WavWriter.h"
#include "dsp/TimeStretchEngine.h"
#include "dsp/PhaseVocoder.h"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
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
    if (name == "impulse") x[rate] = 0.8f;
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
ts::StretchConfig config(double speed, int phase, const std::filesystem::path& debug = {}) {
    ts::StretchConfig c;
    c.sampleRate = rate; c.channels = 1; c.timeRatio = 1.0 / speed;
    c.enablePhaseLocking = true;
    c.enableTransientHandling = phase >= 3;
    c.enableAdaptiveTimeMapping = phase >= 35;
    c.enableSelectivePhaseReset = phase >= 36;
    c.debugCsvDirectory = debug.string();
    return c;
}
struct Attack { double peak = 0, time = 0, widthMs = 0, pre = 0, post = 0; };
Attack attack(const std::vector<float>& x, double expectedTime) {
    const long long center = std::llround(expectedTime * rate);
    const auto lo = static_cast<std::size_t>(std::max(0LL, center - rate * 12 / 100));
    const auto hi = std::min(x.size(), static_cast<std::size_t>(center + rate * 12 / 100));
    std::size_t peakAt = lo;
    for (std::size_t i = lo; i < hi; ++i)
        if (std::abs(x[i]) > std::abs(x[peakAt])) peakAt = i;
    Attack result;
    result.peak = std::abs(x[peakAt]); result.time = double(peakAt) / rate;
    for (std::size_t i = lo; i < hi; ++i) {
        if (std::abs(x[i]) >= 0.1 * result.peak) result.widthMs += 1000.0 / rate;
        if (i < static_cast<std::size_t>(center)) result.pre += double(x[i]) * x[i];
        else result.post += double(x[i]) * x[i];
    }
    return result;
}
double maxDifference(const std::vector<float>& left, const std::vector<float>& right) {
    check(left.size() == right.size(), "Regression duration changed");
    double maximum = 0;
    for (std::size_t i = 0; i < left.size(); ++i)
        maximum = std::max(maximum, std::abs(double(left[i]) - right[i]));
    return maximum;
}
void waveformCsv(const std::filesystem::path& path, const std::vector<float>& input,
                 const std::vector<float>& p2, const std::vector<float>& p35,
                 const std::vector<float>& p36, double speed) {
    std::ofstream csv(path);
    check(bool(csv), "Cannot write waveform CSV");
    csv << "offsetMs,input,phase2,phase35,phase36\n";
    const long long inCenter = rate, outCenter = std::llround(rate / speed);
    for (int n = -rate * 15 / 100; n <= rate * 15 / 100; ++n)
        csv << 1000.0 * n / rate << ',' << input[inCenter + n] << ','
            << p2[outCenter + n] << ',' << p35[outCenter + n] << ','
            << p36[outCenter + n] << '\n';
}
void compare(const std::string& name, double speed, const std::filesystem::path& dir) {
    const auto input = signal(name);
    const auto label = speed == 0.75 ? "075" : "050";
    std::vector<std::vector<float>> outputs;
    std::size_t eventCount = 0;
    long long anchorError = 0;
    std::vector<ts::TransientEvent> events;
    for (int phase : {2, 35, 36}) {
        auto c = config(speed, phase, phase == 36 ? dir / (name + "_" + label + "_debug") : "");
        ts::TimeStretchEngine engine(c);
        auto output = engine.processOffline({input})[0];
        check(output.size() == std::size_t(std::llround(input.size() / speed)), "Duration changed");
        check(std::all_of(output.begin(), output.end(), [](float x) { return std::isfinite(x); }),
              "Non-finite output");
        if (phase == 36) {
            eventCount = engine.lastEventCount();
            events = engine.lastEvents();
            anchorError = engine.lastAnchorMaxErrorSamples();
        }
        ts::WavWriter::write(dir / (name + "_" + label + "_phase" + std::to_string(phase) + ".wav"),
                             {rate, {output}});
        outputs.push_back(std::move(output));
    }
    check(anchorError <= 1, "Event synthesis anchor moved");
    if (name == "drum") {
        check(eventCount == 1, "Drum attack event was split");
        check(events[0].attackEndFrame > events[0].peakFrame,
              "Drum early decay was not protected");
        waveformCsv(dir / ("drum_" + std::string(label) + "_waveform.csv"), input,
                    outputs[0], outputs[1], outputs[2], speed);
    }
    if (name == "impulse") {
        check(eventCount == 1, "Impulse event missing");
        check(events[0].attackEndFrame <= events[0].peakFrame + 2,
              "Impulse protected region was too long");
    }
    if (name == "click") check(eventCount == 8, "Click event count differs from eight");
    if (name == "sine") {
        check(eventCount == 0 && outputs[1] == outputs[2], "Tonal-only regression");
    }
    std::cout << name << " speed=" << speed << " events=" << eventCount
              << " anchor_error_samples=" << anchorError;
    if (name != "sine") for (std::size_t index = 0; index < outputs.size(); ++index) {
        const auto a = attack(outputs[index], 1.0 / speed);
        std::cout << " phase" << (index == 0 ? 2 : index == 1 ? 35 : 36)
                  << "_width_ms=" << a.widthMs << "_peak=" << a.peak
                  << "_peak_time=" << a.time << "_pre=" << a.pre << "_post=" << a.post;
    }
    if (name == "click") {
        double maximum = 0;
        for (int n = 1; n < 8; ++n) {
            const auto left = attack(outputs[2], (1.0 + (n - 1) * 0.5) / speed).time;
            const auto right = attack(outputs[2], (1.0 + n * 0.5) / speed).time;
            maximum = std::max(maximum, std::abs((right - left) - 0.5 / speed));
        }
        std::cout << " max_click_interval_error_ms=" << maximum * 1000;
    }
    std::cout << '\n';
}
void regress(double speed) {
    const auto input = signal("drum");
    auto c35 = config(speed, 35), c36off = config(speed, 36);
    c36off.enableSelectivePhaseReset = false;
    const auto baseline = ts::TimeStretchEngine(c35).processOffline({input})[0];
    const auto disabled = ts::TimeStretchEngine(c36off).processOffline({input})[0];
    check(maxDifference(baseline, disabled) == 0, "Phase 3.6 OFF differs from Phase 3.5");
    auto c35off = config(speed, 35);
    c35off.enableAdaptiveTimeMapping = false;
    const auto phase3 = ts::TimeStretchEngine(config(speed, 3)).processOffline({input})[0];
    const auto phase35off = ts::TimeStretchEngine(c35off).processOffline({input})[0];
    check(maxDifference(phase3, phase35off) == 0, "Phase 3.5 OFF differs from Phase 3");
    auto transientOff = config(speed, 36);
    transientOff.enableSelectivePhaseReset = false;
    transientOff.enableAdaptiveTimeMapping = false;
    transientOff.enableTransientHandling = false;
    const auto phase2 = ts::TimeStretchEngine(config(speed, 2)).processOffline({input})[0];
    const auto phase2Regression = ts::TimeStretchEngine(transientOff).processOffline({input})[0];
    check(maxDifference(phase2, phase2Regression) == 0, "Transient OFF differs from Phase 2");
    std::cout << "regression speed=" << speed
              << " phase36_off_max_error=0 phase35_off_max_error=0 transient_off_max_error=0\n";
}
void selectiveResetUnit() {
    constexpr int fftSize = 4096;
    std::vector<std::complex<float>> first(fftSize / 2 + 1), second(first.size());
    std::vector<std::complex<float>> normal(first.size()), soft(first.size());
    first[10] = std::polar(1.0f, 0.0f); second[10] = std::polar(1.0f, 2.0f);
    first[100] = std::polar(0.1f, 0.0f); second[100] = std::polar(1.0f, 2.0f);
    ts::PhaseVocoder reference(fftSize, 1024, false, rate);
    ts::PhaseVocoder selective(fftSize, 1024, false, rate);
    reference.process(first.data(), normal.data(), 0);
    selective.process(first.data(), soft.data(), 0);
    reference.process(second.data(), normal.data(), 2048);
    selective.process(second.data(), soft.data(), 2048, true, true, 1.0f);
    const auto phaseDistance = [](double left, double right) {
        return std::abs(std::remainder(left - right, 2 * pi));
    };
    const auto lowShift = phaseDistance(std::arg(soft[10]), std::arg(normal[10]));
    const auto highShift = phaseDistance(std::arg(soft[100]), std::arg(normal[100]));
    check(lowShift < 1e-6 && lowShift < highShift,
          "Steady low-frequency bin was reset");
    check(phaseDistance(std::arg(soft[100]), 2.0) <
              phaseDistance(std::arg(normal[100]), 2.0),
          "Rising high-frequency bin was not pulled toward analysis phase");
    std::cout << "selective_reset_unit=pass low_shift_rad=" << lowShift
              << " high_shift_rad=" << highShift << '\n';
}
}
int main(int argc, char** argv) {
    try {
        check(argc == 2, "Output directory required");
        const std::filesystem::path dir = argv[1];
        std::filesystem::create_directories(dir);
        std::cout << std::fixed << std::setprecision(6);
        selectiveResetUnit();
        for (double speed : {0.75, 0.5}) {
            regress(speed);
            for (const std::string name : {"impulse", "click", "drum", "sine"})
                compare(name, speed, dir);
        }
        std::cout << "PASS: Phase 3.6 tests\n";
    } catch (const std::exception& e) {
        std::cerr << "FAIL: " << e.what() << '\n'; return 1;
    }
}
