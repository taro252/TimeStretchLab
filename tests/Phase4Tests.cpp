#include "dsp/FFTAccelerate.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
constexpr int rate = 44100;
constexpr double kPi = std::numbers::pi;
void check(bool pass, const char* message) { if (!pass) throw std::runtime_error(message); }
using Audio = std::vector<std::vector<float>>;
ts::StretchConfig config(double speed, bool coherence, int channels = 2) {
    ts::StretchConfig c;
    c.channels = channels; c.timeRatio = 1 / speed; c.enablePhaseLocking = true;
    c.enableTransientHandling = true; c.enableAdaptiveTimeMapping = true;
    c.enablePreciseTransientAnchoring = true; c.enableStereoCoherence = coherence;
    return c;
}
double maxDifference(const Audio& a, const Audio& b) {
    check(a.size() == b.size(), "Channel mismatch");
    double difference = 0;
    for (std::size_t c = 0; c < a.size(); ++c) {
        check(a[c].size() == b[c].size(), "Length mismatch");
        for (std::size_t i = 0; i < a[c].size(); ++i)
            difference = std::max(difference, std::abs(double(a[c][i]) - b[c][i]));
    }
    return difference;
}
struct Metrics { double sideMid = 0, correlation = 0; };
Metrics metrics(const Audio& x) {
    double ll = 0, rr = 0, lr = 0, mid = 0, side = 0;
    for (std::size_t i = 0; i < x[0].size(); ++i) {
        const double l = x[0][i], r = x[1][i];
        ll += l*l; rr += r*r; lr += l*r;
        mid += (l+r)*(l+r); side += (l-r)*(l-r);
    }
    return {std::sqrt(side / (mid + 1e-30)), lr / std::sqrt(ll*rr + 1e-30)};
}
struct Spectral { double ipd = 0, ild = 0; };
Spectral spectral(const Audio& x, std::size_t start) {
    ts::FFTAccelerate fft(8192);
    std::vector<float> frame(8192);
    std::vector<std::complex<float>> left(4097), right(4097);
    for (int channel = 0; channel < 2; ++channel) {
        for (std::size_t i = 0; i < frame.size(); ++i)
            frame[i] = x[channel][start+i] * float(0.5-0.5*std::cos(2*kPi*i/frame.size()));
        fft.forward(frame.data(), (channel == 0 ? left : right).data());
    }
    const auto bin = std::size_t(std::llround(440.0 * 8192 / rate));
    return {std::remainder(double(std::arg(right[bin]))-std::arg(left[bin]), 2*kPi),
            20*std::log10((std::abs(left[bin])+1e-12)/(std::abs(right[bin])+1e-12))};
}
Audio sine(double phase, double rightAmplitude = 1) {
    Audio x(2, std::vector<float>(rate * 3));
    for (std::size_t i = 0; i < x[0].size(); ++i) {
        x[0][i] = float(0.5*std::sin(2*kPi*440*i/rate));
        x[1][i] = float(0.5*rightAmplitude*std::sin(2*kPi*440*i/rate+phase));
    }
    return x;
}
void testSine(double speed, double phase, double amplitude) {
    const auto input = sine(phase, amplitude);
    ts::TimeStretchEngine old(config(speed, false)), newer(config(speed, true));
    const auto oldOutput = old.processOffline(input), output = newer.processOffline(input);
    check(output[0].size() == std::size_t(std::llround(input[0].size()/speed)), "Duration mismatch");
    const auto before = spectral(input, rate);
    const auto independent = spectral(oldOutput, std::size_t(std::llround(rate/speed)));
    const auto after = spectral(output, std::size_t(std::llround(rate/speed)));
    const auto ipdError = std::abs(std::remainder(after.ipd-before.ipd, 2*kPi));
    const auto ildError = std::abs(after.ild-before.ild);
    check(ipdError < 0.15, "Known phase difference was not retained");
    check(ildError < 0.4, "Amplitude panning changed");
    check(std::isfinite(newer.lastAverageCoherenceWeight()), "Non-finite coherence weight");
    if (phase == 0 && amplitude == 1) check(metrics(output).sideMid < 1e-5, "Identical stereo split");
    std::cout << "sine speed=" << speed << " input_ipd_deg=" << before.ipd*180/kPi
              << " phase37_ipd_deg=" << independent.ipd*180/kPi
              << " phase4_ipd_deg=" << after.ipd*180/kPi
              << " ipd_error_deg=" << ipdError*180/kPi
              << " ild_error_db=" << ildError
              << " average_weight=" << newer.lastAverageCoherenceWeight() << '\n';
}
void testNoise(double speed) {
    std::mt19937 generator(1234);
    std::normal_distribution<float> noise(0.0f, 0.12f);
    Audio input(2, std::vector<float>(rate*3));
    for (auto& channel : input) for (auto& sample : channel) sample = noise(generator);
    ts::TimeStretchEngine engine(config(speed, true));
    const auto output = engine.processOffline(input);
    const auto m = metrics(output);
    check(m.sideMid > 0.6, "Decorrelated noise was collapsed toward mono");
    check(std::abs(m.correlation) < 0.4, "Noise channels became correlated");
    check(engine.lastAverageCoherenceWeight() < 0.1, "Noise coherence weight too high");
    std::cout << "noise speed=" << speed << " side_mid=" << m.sideMid
              << " correlation=" << m.correlation
              << " average_weight=" << engine.lastAverageCoherenceWeight() << '\n';
}
void testReverb(double speed) {
    auto input = sine(0, 1);
    // Dry center plus distinct delayed decays in the two channels.
    for (std::size_t i = rate/3; i < input[0].size(); ++i) {
        input[0][i] += 0.15f * std::sin(2*kPi*611*(i-rate/3)/rate);
        input[1][i] += 0.15f * std::sin(2*kPi*677*(i-rate/3)/rate);
    }
    ts::TimeStretchEngine baseline(config(speed, false)), engine(config(speed, true));
    const auto a = baseline.processOffline(input), b = engine.processOffline(input);
    const auto ma = metrics(a), mb = metrics(b);
    check(mb.sideMid > 0.5*ma.sideMid, "Stereo ambience was suppressed");
    check(mb.sideMid < 1.5*ma.sideMid, "Stereo ambience widened excessively");
    std::cout << "reverb speed=" << speed << " phase37_side_mid=" << ma.sideMid
              << " phase4_side_mid=" << mb.sideMid << '\n';
}
void testTransientTiming(double speed) {
    Audio input(2, std::vector<float>(rate*5));
    for (int n = 0; n < 8; ++n) {
        input[0][rate+n*rate/2] = 0.8f;
        input[1][rate+n*rate/2] = 0.4f;
    }
    ts::TimeStretchEngine baseline(config(speed, false)), engine(config(speed, true));
    const auto a = baseline.processOffline(input), b = engine.processOffline(input);
    check(engine.lastAnchoredEventCount() == baseline.lastAnchoredEventCount() &&
          engine.lastAnchoredEventCount() == 8, "Transient anchors changed");
    check(engine.lastAnchorMaxErrorSamples() == baseline.lastAnchorMaxErrorSamples(),
          "Transient positions changed");
    double maxPeakOffset = 0;
    for (int n = 0; n < 8; ++n) {
        const auto center = std::size_t(std::llround((rate+n*rate/2)/speed));
        const auto peak = [&](const Audio& x) {
            std::size_t where = center;
            for (std::size_t i = center-300; i <= center+300; ++i)
                if (std::abs(x[0][i]) > std::abs(x[0][where])) where = i;
            return where;
        };
        maxPeakOffset = std::max(maxPeakOffset,
            std::abs(double(peak(a))-double(peak(b))));
    }
    check(maxPeakOffset <= 1, "Transient peak timing changed");
    std::cout << "click speed=" << speed << " anchored=" << engine.lastAnchoredEventCount()
              << " max_peak_offset_samples=" << maxPeakOffset << '\n';
}
}
int main() {
    try {
        std::cout << std::fixed << std::setprecision(6);
        check(!ts::StretchConfig{}.enableStereoCoherence, "Coherence must default OFF");
        for (double speed : {0.75, 0.5}) {
            auto stereo = sine(kPi/4);
            ts::TimeStretchEngine baseline(config(speed, false));
            check(maxDifference(baseline.processOffline(stereo), baseline.processOffline(stereo)) == 0,
                  "Phase 3.7 OFF regression");
            testSine(speed, 0, 1);
            testSine(speed, kPi/4, 1);
            testSine(speed, 0, 0.5);
            testNoise(speed);
            testReverb(speed);
            testTransientTiming(speed);
            ts::StretchConfig monoConfig = config(speed, true, 1);
            auto mono = sine(0)[0];
            ts::TimeStretchEngine monoOn(monoConfig);
            monoConfig.enableStereoCoherence = false;
            ts::TimeStretchEngine monoOff(monoConfig);
            check(maxDifference(monoOn.processOffline({mono}), monoOff.processOffline({mono})) == 0,
                  "Mono was not bypassed");
        }
        std::cout << "PASS: Phase 4 tests\n";
    } catch (const std::exception& e) {
        std::cerr << "FAIL: " << e.what() << '\n'; return 1;
    }
}
