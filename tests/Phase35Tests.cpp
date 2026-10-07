#include "audio/WavWriter.h"
#include "dsp/TimeStretchEngine.h"
#include "dsp/TransientEventMap.h"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr int rate = 44100;
constexpr double pi = std::numbers::pi;
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
std::vector<float> makeSignal(const std::string& name) {
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
    c.debugCsvDirectory = debug.string();
    return c;
}
struct Attack { double peak = 0, position = 0, widthMs = 0, preEnergy = 0, postEnergy = 0; };
double largestStepOutsideAttack(const std::vector<float>& x, double expected) {
    const auto center = std::llround(expected * rate);
    const auto exclusion = std::llround(0.25 * rate);
    double largest = 0;
    for (std::size_t i = 1; i < x.size(); ++i)
        if (std::abs(static_cast<long long>(i) - center) > exclusion)
            largest = std::max(largest, std::abs(double(x[i]) - x[i - 1]));
    return largest;
}
Attack attack(const std::vector<float>& x, double expected) {
    const long long center = std::llround(expected * rate);
    const auto lo = static_cast<std::size_t>(std::max(0LL, center - rate * 12 / 100));
    const auto hi = std::min(x.size(), static_cast<std::size_t>(center + rate * 12 / 100));
    std::size_t peakAt = lo;
    for (std::size_t i = lo; i < hi; ++i)
        if (std::abs(x[i]) > std::abs(x[peakAt])) peakAt = i;
    Attack result;
    result.peak = std::abs(x[peakAt]); result.position = double(peakAt) / rate;
    for (std::size_t i = lo; i < hi; ++i) {
        if (std::abs(x[i]) >= result.peak * 0.1) result.widthMs += 1000.0 / rate;
        if (i < static_cast<std::size_t>(center)) result.preEnergy += double(x[i]) * x[i];
        else result.postEnergy += double(x[i]) * x[i];
    }
    return result;
}
void checkMap() {
    std::vector<ts::TransientFrame> frames(100);
    frames[20].spectralFlux = 0.8; frames[20].threshold = 0.1;
    frames[20].strength = 1; frames[20].logEnergy = 100;
    frames[20].previousLogEnergy = 10;
    frames[26].spectralFlux = 0.2; frames[26].threshold = 0.1;
    frames[26].strength = 1; frames[26].logEnergy = 10;
    frames[26].previousLogEnergy = 5;
    ts::TransientEventMap map(frames, 100, 1024, 2);
    check(map.events().size() == 1 && map.events()[0].peakFrame == 20,
          "Decaying aftershock was not merged into one event");
    check(map.resetAt(20) && !map.resetAt(26), "Event has duplicate phase resets");
    check(std::abs(map.starts()[20] - 20 * 2048LL) <= 1,
          "Event beat position drifted from global tempo");
    check(map.starts()[22] - map.starts()[20] < 2 * 1024 * 1.2,
          "First two attack hops were stretched too far");
    check(std::abs(map.starts().back() - std::llround(99 * 2048.0)) <= 1,
          "Adaptive timeline does not conserve global duration");
    double high = 0;
    for (double ratio : map.localRatios()) high = std::max(high, ratio);
    check(map.localRatios()[20] <= 1.000001 && high <= 3.000001,
          "Local ratio escaped transient/compensation bounds");
}
void stereoShared(const std::filesystem::path& dir) {
    const auto left = makeSignal("click");
    auto right = left;
    for (auto& value : right) value *= 0.5f;
    auto c = config(0.5, 35, dir / "stereo_debug");
    c.channels = 2;
    ts::TimeStretchEngine engine(c);
    const auto output = engine.processOffline({left, right});
    check(engine.lastEventCount() == 8, "Stereo event count differs from click count");
    double maxChannelError = 0;
    for (std::size_t i = 0; i < output[0].size(); ++i)
        maxChannelError = std::max(maxChannelError,
                                   std::abs(double(output[0][i]) * 0.5 - output[1][i]));
    check(maxChannelError < 1e-5, "Stereo channels used different event maps");
    std::ifstream csv(dir / "stereo_debug/event_map.csv");
    std::string header;
    std::getline(csv, header);
    check(header.find("sharedChannels") != std::string::npos,
          "Shared stereo decision missing from debug CSV");
    std::cout << "stereo_shared events=" << engine.lastEventCount()
              << " max_channel_error=" << maxChannelError << '\n';
}
void waveformCsv(const std::filesystem::path& path, const std::vector<float>& input,
                 const std::vector<float>& p2, const std::vector<float>& p3,
                 const std::vector<float>& p35, double speed) {
    std::ofstream csv(path);
    check(bool(csv), "Cannot write waveform CSV");
    csv << "offsetMs,input,phase2,phase3,phase35\n";
    const long long inCenter = rate, outCenter = std::llround(rate / speed);
    const int radius = rate * 15 / 100;
    for (int n = -radius; n <= radius; ++n) {
        csv << 1000.0 * n / rate << ',' << input[inCenter + n] << ','
            << p2[outCenter + n] << ',' << p3[outCenter + n] << ','
            << p35[outCenter + n] << '\n';
    }
}
void compare(const std::string& name, double speed, const std::filesystem::path& dir) {
    const auto input = makeSignal(name);
    const auto label = speed == 0.75 ? "075" : "050";
    std::vector<std::vector<float>> outputs;
    std::size_t events = 0;
    for (int phase : {2, 3, 35}) {
        auto c = config(speed, phase, phase == 35 && name == "drum" ? dir / "drum_debug" : "");
        ts::TimeStretchEngine engine(c);
        auto output = engine.processOffline({input})[0];
        check(output.size() == std::size_t(std::llround(input.size() / speed)), "Wrong duration");
        check(std::all_of(output.begin(), output.end(), [](float v) { return std::isfinite(v); }),
              "Non-finite Phase 3.5 output");
        if (phase == 35) events = engine.lastEventCount();
        ts::WavWriter::write(dir / (name + "_" + label + "_phase" + std::to_string(phase) + ".wav"),
                             {rate, {output}});
        outputs.push_back(std::move(output));
    }
    if (name == "drum") {
        check(events == 1, "One physical drum attack must produce one event");
        waveformCsv(dir / ("drum_" + std::string(label) + "_waveform.csv"), input,
                    outputs[0], outputs[1], outputs[2], speed);
        const auto strayStep = largestStepOutsideAttack(outputs[2], 1.0 / speed);
        std::cout << "drum speed=" << speed << " largest_step_outside_attack=" << strayStep << '\n';
        check(strayStep < 0.15, "Extra click outside the drum attack");
    }
    if (name == "sine") {
        check(events == 0, "Steady sine produced an event");
        check(outputs[1] == outputs[2], "No-event mapping changed a steady sine");
    }
    if (name == "impulse") check(events == 1, "Impulse event count differs from one");
    if (name == "click") check(events == 8, "Click train event count differs from eight");
    std::cout << name << " speed=" << speed << " events=" << events;
    if (name != "sine") for (std::size_t i = 0; i < outputs.size(); ++i) {
        const auto a = attack(outputs[i], 1.0 / speed);
        std::cout << " phase" << (i == 2 ? 35 : int(i) + 2) << "_width_ms=" << a.widthMs
                  << "_peak=" << a.peak << "_position=" << a.position
                  << "_pre=" << a.preEnergy << "_post=" << a.postEnergy;
    }
    if (name == "click") {
        double maxIntervalError = 0;
        for (int n = 1; n < 8; ++n) {
            const auto left = attack(outputs[2], (1.0 + (n - 1) * 0.5) / speed).position;
            const auto right = attack(outputs[2], (1.0 + n * 0.5) / speed).position;
            maxIntervalError = std::max(maxIntervalError, std::abs((right - left) - 0.5 / speed));
        }
        std::cout << " max_interval_error_s=" << maxIntervalError;
        check(maxIntervalError < 0.05, "Click interval drift exceeded 50 ms");
    }
    std::cout << '\n';
}
}
int main(int argc, char** argv) {
    try {
        check(argc == 2, "Output directory required");
        const std::filesystem::path dir = argv[1];
        std::filesystem::create_directories(dir);
        checkMap();
        for (const std::string name : {"impulse", "click", "drum", "sine"})
            for (double speed : {0.75, 0.5}) compare(name, speed, dir);
        stereoShared(dir);
        std::cout << "PASS: Phase 3.5 tests\n";
    } catch (const std::exception& e) {
        std::cerr << "FAIL: " << e.what() << '\n'; return 1;
    }
}
