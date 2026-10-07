#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace ts {
TimeStretchEngine::TimeStretchEngine(const StretchConfig& config)
    : config_(config), stft_(config.fftSize), frame_(config.fftSize), synthesized_(config.fftSize),
      spectrum_(config.fftSize / 2 + 1), stretchedSpectrum_(config.fftSize / 2 + 1) {
    if ((config.sampleRate != 44100 && config.sampleRate != 48000) ||
        (config.channels != 1 && config.channels != 2) ||
        config.analysisHop < 1 || config.analysisHop > config.fftSize / 2 ||
        !std::isfinite(config.timeRatio) || config.timeRatio <= 0 ||
        config.enablePhaseLocking || config.enableTransientHandling || config.enableMultiResolution)
        throw std::invalid_argument("Invalid Phase 1 configuration or later-phase feature enabled");
    for (int c = 0; c < config.channels; ++c)
        vocoders_.emplace_back(config.fftSize, config.analysisHop);
}
void TimeStretchEngine::reset() { for (auto& vocoder : vocoders_) vocoder.reset(); }
void TimeStretchEngine::setTimeRatio(double ratio) {
    if (!std::isfinite(ratio) || ratio <= 0) throw std::invalid_argument("Invalid time ratio");
    config_.timeRatio = ratio;
    reset();
}
std::vector<std::vector<float>> TimeStretchEngine::processOffline(const std::vector<std::vector<float>>& input) {
    if (input.size() != static_cast<std::size_t>(config_.channels))
        throw std::invalid_argument("Input channel count differs from configuration");
    const auto length = input.front().size();
    for (const auto& channel : input) {
        if (channel.size() != length) throw std::invalid_argument("Input channel lengths differ");
        for (float value : channel) if (!std::isfinite(value))
            throw std::invalid_argument("Non-finite input sample");
    }
    if (length == 0) return std::vector<std::vector<float>>(input.size());
    // Unity bypass keeps the original samples and level exactly intact.
    if (config_.timeRatio == 1.0) return input;
    const double target = std::round(length * config_.timeRatio);
    if (target > static_cast<double>(std::numeric_limits<std::size_t>::max() / 2))
        throw std::length_error("Output too large");
    const auto outputLength = static_cast<std::size_t>(target);
    const auto padding = static_cast<std::size_t>(config_.fftSize / 2);
    const auto fftSize = static_cast<std::size_t>(config_.fftSize);
    const auto hop = static_cast<std::size_t>(config_.analysisHop);
    const auto capacity = outputLength + fftSize * 3 +
        static_cast<std::size_t>(std::ceil(synthesisHop())) + padding;
    std::vector<std::vector<float>> result(input.size());
    const auto frameCount = (length + padding + hop - 1) / hop + 1;
    for (std::size_t c = 0; c < input.size(); ++c) {
        vocoders_[c].reset();
        OverlapAdd ola(capacity);
        long long previousStart = 0;
        for (std::size_t frameIndex = 0; frameIndex < frameCount; ++frameIndex) {
            const auto analysisStart = frameIndex * hop;
            // Zero padding lets the first and final real samples receive full window coverage.
            for (std::size_t i = 0; i < fftSize; ++i) {
                const auto padded = analysisStart + i;
                frame_[i] = padded >= padding && padded - padding < length
                    ? input[c][padded - padding] : 0.0f;
            }
            stft_.analyze(frame_.data(), spectrum_.data());
            // Round absolute positions, never a repeatedly rounded hop.
            const auto start = std::llround(frameIndex * synthesisHop());
            const double delta = frameIndex == 0 ? 0.0 : (start - previousStart);
            vocoders_[c].process(spectrum_.data(), stretchedSpectrum_.data(), delta);
            stft_.synthesize(stretchedSpectrum_.data(), synthesized_.data());
            ola.add(synthesized_.data(), stft_.window().data(), fftSize, start);
            previousStart = start;
        }
        result[c] = ola.finish(outputLength, padding);
    }
    return result;
}
}
