#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <stdexcept>

namespace ts {
TimeStretchEngine::TimeStretchEngine(const StretchConfig& config)
    : config_(config), stft_(config.fftSize), frame_(config.fftSize), synthesized_(config.fftSize),
      spectrum_(config.fftSize / 2 + 1), stretchedSpectrum_(config.fftSize / 2 + 1) {
    if ((config.sampleRate != 44100 && config.sampleRate != 48000) ||
        (config.channels != 1 && config.channels != 2) ||
        config.analysisHop < 1 || config.analysisHop > config.fftSize / 2 ||
        !std::isfinite(config.timeRatio) || config.timeRatio <= 0 ||
        config.enableMultiResolution ||
        (config.enableAdaptiveTimeMapping && !config.enableTransientHandling) ||
        (config.enableSelectivePhaseReset && !config.enableAdaptiveTimeMapping))
        throw std::invalid_argument("Invalid configuration or unsupported later-phase feature enabled");
    for (int c = 0; c < config.channels; ++c)
        vocoders_.emplace_back(config.fftSize, config.analysisHop,
                               config.enablePhaseLocking, config.sampleRate);
}
void TimeStretchEngine::reset() {
    for (auto& vocoder : vocoders_) vocoder.reset();
    lastTransientCount_ = 0;
    lastEventCount_ = 0;
    lastEvents_.clear();
    lastAnchorMaxErrorSamples_ = 0;
}
void TimeStretchEngine::setTimeRatio(double ratio) {
    if (!std::isfinite(ratio) || ratio <= 0) throw std::invalid_argument("Invalid time ratio");
    config_.timeRatio = ratio;
    reset();
}
std::vector<std::vector<float>> TimeStretchEngine::processOffline(const std::vector<std::vector<float>>& input) {
    lastTransientCount_ = 0;
    lastEventCount_ = 0;
    lastEvents_.clear();
    lastAnchorMaxErrorSamples_ = 0;
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
    auto fillFrame = [&](std::size_t channel, std::size_t analysisStart) {
        for (std::size_t i = 0; i < fftSize; ++i) {
            const auto padded = analysisStart + i;
            frame_[i] = padded >= padding && padded - padding < length
                ? input[channel][padded - padding] : 0.0f;
        }
    };
    std::unique_ptr<TransientDetector> detector;
    std::unique_ptr<TransientEventMap> eventMap;
    if (config_.enableTransientHandling) {
        TransientConfig transientConfig;
        transientConfig.sensitivity = config_.transientSensitivity;
        transientConfig.minimumFlux = config_.transientMinimumFlux;
        transientConfig.resetStrengthThreshold = config_.transientStrengthThreshold;
        transientConfig.historyFrames = config_.transientHistoryFrames;
        transientConfig.cooldownFrames = config_.transientCooldownFrames;
        transientConfig.lookbackFrames = config_.transientLookbackFrames;
        detector = std::make_unique<TransientDetector>(fftSize / 2 + 1, transientConfig);
        std::vector<float> combined(fftSize / 2 + 1);
        for (std::size_t frameIndex = 0; frameIndex < frameCount; ++frameIndex) {
            std::fill(combined.begin(), combined.end(), 0.0f);
            const auto analysisStart = frameIndex * hop;
            for (std::size_t c = 0; c < input.size(); ++c) {
                fillFrame(c, analysisStart);
                stft_.analyze(frame_.data(), spectrum_.data());
                for (std::size_t k = 0; k < combined.size(); ++k)
                    combined[k] += std::norm(spectrum_[k]);
            }
            for (auto& value : combined) value = std::sqrt(value);
            detector->pushMagnitudes(combined.data());
        }
        const auto activeFrameCount = length + padding >= fftSize
            ? (length + padding - fftSize) / hop + 1 : 0;
        detector->finalize(activeFrameCount);
        lastTransientCount_ = detector->transientCount();
        if (config_.enableAdaptiveTimeMapping) {
            EventMapConfig mapConfig;
            mapConfig.minimumDistanceFrames = config_.eventMinimumDistanceFrames;
            mapConfig.decayMergeFrames = config_.eventDecayMergeFrames;
            mapConfig.preRollFrames = config_.eventPreRollFrames;
            mapConfig.postRollFrames = config_.enableSelectivePhaseReset
                ? config_.eventAttackPostRollFrames : config_.eventPostRollFrames;
            mapConfig.preserveAttackRegion = config_.enableSelectivePhaseReset;
            eventMap = std::make_unique<TransientEventMap>(
                detector->frames(), activeFrameCount, config_.analysisHop, config_.timeRatio, mapConfig);
            if (config_.enableSelectivePhaseReset) {
                std::vector<double> offsets(eventMap->events().size());
                for (std::size_t id = 0; id < eventMap->events().size(); ++id) {
                    const auto center = eventMap->events()[id].peakFrame * hop;
                    const auto lo = center > hop ? center - hop : 0;
                    const auto hi = std::min(length, center + 2 * hop);
                    double energy = 0, peakEnergy = 0;
                    std::size_t peakSample = center;
                    for (auto sample = lo; sample < hi; ++sample) {
                        double sampleEnergy = 0;
                        for (const auto& channel : input)
                            sampleEnergy += double(channel[sample]) * channel[sample];
                        energy += sampleEnergy;
                        if (sampleEnergy > peakEnergy) {
                            peakEnergy = sampleEnergy;
                            peakSample = sample;
                        }
                    }
                    // A sparse click has a very high crest factor. Use its
                    // true input sample to avoid frame-grid timing error;
                    // tonal/drum material keeps the spectral event anchor.
                    if (hi > lo && peakEnergy > 0 &&
                        std::sqrt(peakEnergy / (energy / (hi - lo))) >= 20.0)
                        offsets[id] = static_cast<double>(peakSample) - center;
                }
                eventMap->refineAnchors(offsets);
            }
            lastEventCount_ = eventMap->events().size();
            lastEvents_ = eventMap->events();
            for (const auto& event : lastEvents_)
                lastAnchorMaxErrorSamples_ = std::max(lastAnchorMaxErrorSamples_,
                    std::llabs(eventMap->starts()[event.peakFrame] -
                               eventMap->idealStartAt(event.peakFrame)));
        }
    }
    if (!config_.debugCsvDirectory.empty())
        std::filesystem::create_directories(config_.debugCsvDirectory);
    if (detector && !config_.debugCsvDirectory.empty()) {
        const auto path = std::filesystem::path(config_.debugCsvDirectory) / "transients.csv";
        std::ofstream csv(path);
        if (!csv) throw std::runtime_error("Cannot create transient debug CSV");
        csv << "frameIndex,spectralFlux,logEnergy,threshold,transientStrength,transientDetected,resetApplied,sharedChannels\n";
        const auto& frames = detector->frames();
        for (std::size_t i = 0; i < frames.size(); ++i)
            csv << i << ',' << frames[i].spectralFlux << ',' << frames[i].logEnergy << ','
                << frames[i].threshold << ','
                << frames[i].strength << ',' << frames[i].detected << ','
                << frames[i].resetApplied << ',' << input.size() << '\n';
    }
    if (eventMap && !config_.debugCsvDirectory.empty()) {
        std::ofstream csv(std::filesystem::path(config_.debugCsvDirectory) / "event_map.csv");
        if (!csv) throw std::runtime_error("Cannot create event map debug CSV");
        csv << "frameIndex,flux,threshold,eventId,eventStrength,isTransientRegion,localTimeRatio,synthesisStart,resetApplied,sharedChannels\n";
        const auto& frames = detector->frames();
        for (std::size_t i = 0; i < frames.size(); ++i)
            csv << i << ',' << frames[i].spectralFlux << ',' << frames[i].threshold << ','
                << eventMap->eventIdAt(i) << ',' << eventMap->eventStrengthAt(i) << ','
                << eventMap->isTransientRegion(i) << ',' << eventMap->localRatios()[i] << ','
                << eventMap->starts()[i] << ',' << eventMap->resetAt(i) << ',' << input.size() << '\n';
    }
    if (eventMap && config_.enableSelectivePhaseReset && !config_.debugCsvDirectory.empty()) {
        std::ofstream csv(std::filesystem::path(config_.debugCsvDirectory) / "events.csv");
        if (!csv) throw std::runtime_error("Cannot create event debug CSV");
        csv << "eventId,onsetFrame,peakFrame,attackEndFrame,endFrame,strength,idealStart,actualStart,errorSamples\n";
        for (std::size_t id = 0; id < eventMap->events().size(); ++id) {
            const auto& event = eventMap->events()[id];
            const auto ideal = eventMap->idealStartAt(event.peakFrame);
            const auto actual = eventMap->starts()[event.peakFrame];
            csv << id << ',' << event.onsetFrame << ',' << event.peakFrame << ','
                << event.attackEndFrame << ',' << event.endFrame << ',' << event.strength
                << ',' << ideal << ',' << actual << ',' << actual - ideal << '\n';
        }
    }
    for (std::size_t c = 0; c < input.size(); ++c) {
        vocoders_[c].reset();
        std::ofstream framesCsv, peaksCsv;
        if (!config_.debugCsvDirectory.empty() && config_.enablePhaseLocking) {
            const auto base = std::filesystem::path(config_.debugCsvDirectory);
            framesCsv.open(base / ("frames_ch" + std::to_string(c) + ".csv"));
            peaksCsv.open(base / ("peaks_ch" + std::to_string(c) + ".csv"));
            if (!framesCsv || !peaksCsv) throw std::runtime_error("Cannot create debug CSV");
            framesCsv << "frameIndex,peakCount\n";
            peaksCsv << "frameIndex,peakBin,interpolatedPeakPosition,peakFrequencyHz,peakMagnitude\n";
        }
        OverlapAdd ola(capacity);
        long long previousStart = 0;
        for (std::size_t frameIndex = 0; frameIndex < frameCount; ++frameIndex) {
            const auto analysisStart = frameIndex * hop;
            // Zero padding lets the first and final real samples receive full window coverage.
            fillFrame(c, analysisStart);
            stft_.analyze(frame_.data(), spectrum_.data());
            // Round absolute positions, never a repeatedly rounded hop.
            const auto start = eventMap ? eventMap->starts()[frameIndex]
                                        : std::llround(frameIndex * synthesisHop());
            const double delta = frameIndex == 0 ? 0.0 : (start - previousStart);
            vocoders_[c].process(spectrum_.data(), stretchedSpectrum_.data(), delta,
                                 eventMap ? eventMap->resetAt(frameIndex)
                                          : (detector && detector->resetAt(frameIndex)),
                                 config_.enableSelectivePhaseReset,
                                 eventMap ? eventMap->resetStrengthAt(frameIndex) : 0.0f);
            if (framesCsv) {
                const auto& peaks = vocoders_[c].phaseLocker().peaks();
                framesCsv << frameIndex << ',' << peaks.size() << '\n';
                for (const auto& peak : peaks)
                    peaksCsv << frameIndex << ',' << peak.bin << ',' << peak.position << ','
                             << peak.position * config_.sampleRate / config_.fftSize << ','
                             << peak.magnitude << '\n';
            }
            stft_.synthesize(stretchedSpectrum_.data(), synthesized_.data());
            ola.add(synthesized_.data(), stft_.window().data(), fftSize, start);
            previousStart = start;
        }
        result[c] = ola.finish(outputLength, padding);
    }
    return result;
}
}
