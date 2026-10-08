#include "audio/WavReader.h"
#include "dsp/FFTAccelerate.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
double percentile(std::vector<double>& values, double fraction) {
    if (values.empty()) return 0;
    std::sort(values.begin(), values.end());
    return values[std::min(values.size() - 1,
        static_cast<std::size_t>(fraction * (values.size() - 1)))];
}
}
int main(int argc, char** argv) {
    if (argc < 2) { std::cerr << "Usage: bass_pitch_metrics file.wav ...\n"; return 2; }
    try {
        constexpr std::size_t fftSize = 8192;
        ts::FFTAccelerate fft(fftSize);
        std::vector<float> frame(fftSize);
        std::vector<std::complex<float>> spectrum(fftSize / 2 + 1);
        std::cout << std::fixed << std::setprecision(3);
        for (int file = 1; file < argc; ++file) {
            const auto audio = ts::WavReader::read(argv[file]);
            const auto length = audio.channels.front().size();
            const auto hop = static_cast<std::size_t>(audio.sampleRate / 10);
            const auto minBin = static_cast<std::size_t>(std::ceil(45.0 * fftSize / audio.sampleRate));
            const auto maxBin = static_cast<std::size_t>(std::floor(240.0 * fftSize / audio.sampleRate));
            std::vector<double> frequencies, steps;
            double previous = 0;
            for (std::size_t start = 0; start + fftSize <= length; start += hop) {
                double energy = 0;
                for (std::size_t i = 0; i < fftSize; ++i) {
                    double sample = 0;
                    for (const auto& channel : audio.channels) sample += channel[start + i];
                    sample /= audio.channels.size();
                    energy += sample * sample;
                    frame[i] = static_cast<float>(sample *
                        (0.5 - 0.5 * std::cos(2 * std::numbers::pi * i / fftSize)));
                }
                if (energy / fftSize < 0.0001) { previous = 0; continue; }
                fft.forward(frame.data(), spectrum.data());
                std::size_t peak = minBin;
                double bandSum = 0;
                for (auto bin = minBin; bin <= maxBin; ++bin) {
                    const double magnitude = std::abs(spectrum[bin]);
                    bandSum += magnitude;
                    if (magnitude > std::abs(spectrum[peak])) peak = bin;
                }
                if (std::abs(spectrum[peak]) * (maxBin - minBin + 1) < bandSum * 3) {
                    previous = 0; continue;
                }
                const double a = std::log(std::abs(spectrum[peak - 1]) + 1e-12);
                const double b = std::log(std::abs(spectrum[peak]) + 1e-12);
                const double c = std::log(std::abs(spectrum[peak + 1]) + 1e-12);
                const double denominator = a - 2 * b + c;
                const double offset = std::abs(denominator) > 1e-12
                    ? std::clamp(0.5 * (a - c) / denominator, -0.5, 0.5) : 0;
                const double frequency = (peak + offset) * audio.sampleRate / fftSize;
                frequencies.push_back(frequency);
                if (previous > 0) {
                    const double cents = std::abs(1200 * std::log2(frequency / previous));
                    if (cents < 100) steps.push_back(cents);
                }
                previous = frequency;
            }
            std::cout << "file=" << argv[file] << " voiced_frames=" << frequencies.size()
                      << " stable_pairs=" << steps.size()
                      << " median_frequency_hz=" << percentile(frequencies, 0.5)
                      << " median_step_cents=" << percentile(steps, 0.5)
                      << " p90_step_cents=" << percentile(steps, 0.9) << '\n';
        }
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << '\n'; return 1;
    }
}
