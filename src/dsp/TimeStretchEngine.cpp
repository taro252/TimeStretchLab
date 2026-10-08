#include "dsp/TimeStretchEngine.h"
#include "dsp/StereoPhaseCoherence.h"
#include "dsp/MultiResolutionCrossover.h"
#include "dsp/PartialTracker.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <numbers>
#include <stdexcept>

namespace ts {
TimeStretchEngine::TimeStretchEngine(const StretchConfig& config)
    : config_(config), stft_(config.fftSize), frame_(config.fftSize), synthesized_(config.fftSize),
      spectrum_(config.fftSize / 2 + 1), stretchedSpectrum_(config.fftSize / 2 + 1) {
    if ((config.sampleRate != 44100 && config.sampleRate != 48000) ||
        (config.channels != 1 && config.channels != 2) ||
        config.analysisHop < 1 || config.analysisHop > config.fftSize / 2 ||
        !std::isfinite(config.timeRatio) || config.timeRatio <= 0 ||
        (config.enableMultiResolution && (config.fftSize != 4096 || config.analysisHop != 1024)) ||
        (config.enableAdaptiveTimeMapping && !config.enableTransientHandling) ||
        (config.enableSelectivePhaseReset && !config.enableAdaptiveTimeMapping) ||
        (config.enablePreciseTransientAnchoring && !config.enableAdaptiveTimeMapping) ||
        (config.enableSelectivePhaseReset && config.enablePreciseTransientAnchoring) ||
        (config.enablePartialTracking && (!config.enablePhaseLocking || config.fftSize!=4096 ||
                                          config.analysisHop!=1024)) ||
        (config.enablePVSOLA && (!config.enablePhaseLocking || config.enablePartialTracking ||
                                 !config.enableTransientHandling ||
                                 !config.enableAdaptiveTimeMapping ||
                                 !config.enablePreciseTransientAnchoring ||
                                 (config.channels==2 && !config.enableStereoCoherence) ||
                                 !config.enableMultiResolution ||
                                 config.qualityMode!=QualityMode::High ||
                                 config.fftSize!=4096 || config.analysisHop!=1024)) ||
        !std::isfinite(config.pvsolaIntervalMs) || config.pvsolaIntervalMs<50 ||
        config.pvsolaIntervalMs>500 || !std::isfinite(config.pvsolaSearchMs) ||
        config.pvsolaSearchMs<1 || config.pvsolaSearchMs>20 ||
        !std::isfinite(config.pvsolaMinimumCorrelation) ||
        config.pvsolaMinimumCorrelation<0 || config.pvsolaMinimumCorrelation>1 ||
        !std::isfinite(config.stereoCoherenceStrength) ||
        config.stereoCoherenceStrength < 0 || config.stereoCoherenceStrength > 1 ||
        !std::isfinite(config.lowFrequencyCoherenceStrength) ||
        config.lowFrequencyCoherenceStrength < 0 || config.lowFrequencyCoherenceStrength > 1)
        throw std::invalid_argument("Invalid configuration or unsupported later-phase feature enabled");
    if (!std::isfinite(config.lowCrossoverHz) || config.lowCrossoverHz < 100 ||
        config.lowCrossoverHz > 1000)
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
    lastAnchoredEventCount_ = 0;
    lastAnchors_.clear();
    lastAverageCoherenceWeight_ = 0;
    lastCrossoverWorkingMemoryBytes_ = 0;
    lastTimeMap_ = TimeMap{};
}
void TimeStretchEngine::setTimeRatio(double ratio) {
    if (!std::isfinite(ratio) || ratio <= 0) throw std::invalid_argument("Invalid time ratio");
    config_.timeRatio = ratio;
    reset();
}
std::vector<std::vector<float>> TimeStretchEngine::processOffline(
    const std::vector<std::vector<float>>& input) {
    if (config_.enablePVSOLA)
        throw std::invalid_argument("PVSOLA prototype requires chunked processing");
    if (config_.enableMultiResolution && config_.qualityMode!=QualityMode::Normal)
        return processMultiResolution(input);
    return processSingleResolution(input, nullptr);
}
std::vector<std::vector<float>> TimeStretchEngine::processMultiResolution(
    const std::vector<std::vector<float>>& input) {
    if (config_.timeRatio == 1.0) return processSingleResolution(input, nullptr);
    StretchConfig midConfig = config_;
    midConfig.enableMultiResolution = false;
    TimeStretchEngine midEngine(midConfig);
    auto mid = midEngine.processSingleResolution(input, nullptr);
    const TimeMap& shared = midEngine.lastTimeMap_;
    StretchConfig lowConfig = midConfig, highConfig = midConfig;
    lowConfig.fftSize = 8192; lowConfig.analysisHop = 2048;
    lowConfig.enablePartialTracking = false;
    highConfig.enablePartialTracking = false;
    lowConfig.enablePVSOLA = false;
    highConfig.enablePVSOLA = false;
    // A single mid-resolution detector decides all events and timing. The
    // satellite engines only sample this shared timeline at their frame times.
    lowConfig.debugCsvDirectory.clear();
    highConfig.debugCsvDirectory.clear();
    TimeStretchEngine lowEngine(lowConfig);
    auto low = lowEngine.processSingleResolution(input, &shared);
    MultiResolutionCrossover crossover(config_.sampleRate,config_.lowCrossoverHz);
    std::vector<std::vector<float>> result(input.size());
    if (config_.qualityMode==QualityMode::Experimental) {
        highConfig.fftSize = 1024; highConfig.analysisHop = 256;
        TimeStretchEngine highEngine(highConfig);
        auto high = highEngine.processSingleResolution(input, &shared);
        for (std::size_t c = 0; c < input.size(); ++c)
            crossover.combine(low[c], mid[c], high[c], result[c]);
    } else {
        for (std::size_t c = 0; c < input.size(); ++c)
            crossover.combineLowMid(low[c],mid[c],result[c]);
    }
    lastCrossoverWorkingMemoryBytes_ = crossover.workingMemoryBytes();
    lastTimeMap_ = shared;
    lastTransientCount_ = midEngine.lastTransientCount_;
    lastEventCount_ = midEngine.lastEventCount_;
    lastEvents_ = midEngine.lastEvents_;
    lastAnchors_ = midEngine.lastAnchors_;
    lastAnchoredEventCount_ = midEngine.lastAnchoredEventCount_;
    lastAnchorMaxErrorSamples_ = midEngine.lastAnchorMaxErrorSamples_;
    lastAverageCoherenceWeight_ = midEngine.lastAverageCoherenceWeight_;
    return result;
}
std::vector<std::vector<float>> TimeStretchEngine::processSingleResolution(
    const std::vector<std::vector<float>>& input, const TimeMap* sharedMap) {
    lastTransientCount_ = 0;
    lastEventCount_ = 0;
    lastEvents_.clear();
    lastAnchorMaxErrorSamples_ = 0;
    lastAnchoredEventCount_ = 0;
    lastAnchors_.clear();
    lastAverageCoherenceWeight_ = 0;
    lastCrossoverWorkingMemoryBytes_ = 0;
    lastTimeMap_ = TimeMap{};
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
    std::vector<bool> sharedResets(frameCount, false);
    std::vector<float> sharedStrengths(frameCount, 0.0f);
    if (sharedMap) {
        lastEvents_ = sharedMap->events();
        lastEventCount_ = lastEvents_.size();
        for (const auto& event : lastEvents_) {
            const auto inputSample = event.peakFrame *
                static_cast<std::size_t>(sharedMap->sourceHop());
            const auto mappedFrame = std::min(frameCount-1,
                static_cast<std::size_t>(std::llround(double(inputSample)/hop)));
            sharedResets[mappedFrame] = true;
            sharedStrengths[mappedFrame] = std::max(sharedStrengths[mappedFrame], event.strength);
        }
    }
    auto fillFrame = [&](std::size_t channel, std::size_t analysisStart) {
        for (std::size_t i = 0; i < fftSize; ++i) {
            const auto padded = analysisStart + i;
            frame_[i] = padded >= padding && padded - padding < length
                ? input[channel][padded - padding] : 0.0f;
        }
    };
    std::unique_ptr<TransientDetector> detector;
    std::unique_ptr<TransientEventMap> eventMap;
    if (config_.enableTransientHandling && !sharedMap) {
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
            if (config_.enableSelectivePhaseReset || config_.enablePreciseTransientAnchoring) {
                std::vector<double> offsets(eventMap->events().size());
                AnchorLocatorConfig anchorConfig;
                if (config_.enablePreciseTransientAnchoring) {
                    anchorConfig.minimumPeakToRunnerUp = 3.0;
                    anchorConfig.requireInteriorPeak = true;
                }
                lastAnchors_ = TransientAnchorLocator::locate(
                    input, eventMap->events(), hop, anchorConfig);
                for (std::size_t id = 0; id < lastAnchors_.size(); ++id) {
                    offsets[id] = lastAnchors_[id].sampleOffset;
                    if (lastAnchors_[id].confident) ++lastAnchoredEventCount_;
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
    std::vector<long long> timelineStarts(frameCount);
    for (std::size_t frameIndex = 0; frameIndex < frameCount; ++frameIndex)
        timelineStarts[frameIndex] = sharedMap
            ? std::llround(sharedMap->outputPositionForInputSample(frameIndex * double(hop)))
            : (eventMap ? eventMap->starts()[frameIndex]
                        : std::llround(frameIndex * synthesisHop()));
    lastTimeMap_ = TimeMap(config_.analysisHop, std::move(timelineStarts), lastEvents_);
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
    if (eventMap && config_.enablePreciseTransientAnchoring && !config_.debugCsvDirectory.empty()) {
        std::ofstream csv(std::filesystem::path(config_.debugCsvDirectory) / "anchors.csv");
        if (!csv) throw std::runtime_error("Cannot create anchor debug CSV");
        csv << "eventId,frame,sampleOffset,absoluteInputSample,crestFactor,confident,idealFrameStart,actualFrameStart\n";
        for (std::size_t id = 0; id < lastAnchors_.size(); ++id) {
            const auto& anchor = lastAnchors_[id];
            csv << id << ',' << anchor.frame << ',' << anchor.sampleOffset << ','
                << anchor.absoluteInputSample << ',' << anchor.crestFactor << ','
                << anchor.confident << ',' << eventMap->idealStartAt(anchor.frame) << ','
                << eventMap->starts()[anchor.frame] << '\n';
        }
    }
    if (input.size() == 2 && (config_.enableStereoCoherence || config_.enablePartialTracking)) {
        for (auto& vocoder : vocoders_) vocoder.reset();
        StereoPhaseCoherence coherence(fftSize, config_.sampleRate,
            config_.stereoCoherenceStrength, config_.lowFrequencyCoherenceStrength);
        PhaseLocker sharedPeaks(fftSize);
        std::unique_ptr<PartialTracker> tracker;
        if (config_.enablePartialTracking)
            tracker=std::make_unique<PartialTracker>(fftSize,config_.analysisHop,
                                                     config_.sampleRate,2);
        const auto bins = fftSize / 2 + 1;
        std::vector<std::complex<float>> leftInput(bins), rightInput(bins),
            leftOutput(bins), rightOutput(bins), combined(bins);
        std::vector<double> independentIpd;
        OverlapAdd leftOla(capacity), rightOla(capacity);
        std::ofstream coherenceCsv;
        if (!config_.debugCsvDirectory.empty()) {
            coherenceCsv.open(std::filesystem::path(config_.debugCsvDirectory) / "stereo_coherence.csv");
            if (!coherenceCsv) throw std::runtime_error("Cannot create stereo coherence CSV");
            coherenceCsv << "frame,bin,magL,magR,midMagnitude,sideMagnitude,inputIPD,independentOutputIPD,finalOutputIPD,coherenceWeight,ILD\n";
            independentIpd.resize(bins);
        }
        long long previousStart = 0;
        for (std::size_t frameIndex = 0; frameIndex < frameCount; ++frameIndex) {
            const auto analysisStart = frameIndex * hop;
            fillFrame(0, analysisStart);
            stft_.analyze(frame_.data(), leftInput.data());
            fillFrame(1, analysisStart);
            stft_.analyze(frame_.data(), rightInput.data());
            for (std::size_t k = 0; k < bins; ++k)
                combined[k] = {std::hypot(std::abs(leftInput[k]), std::abs(rightInput[k])), 0};
            sharedPeaks.analyzePeaks(combined.data(), bins);
            const auto start = lastTimeMap_.outputPositionForInputSample(frameIndex * double(hop));
            const double delta = frameIndex == 0 ? 0.0 : start - previousStart;
            const bool resetPhase = sharedMap ? sharedResets[frameIndex] :
                (eventMap ? eventMap->resetAt(frameIndex)
                          : (detector && detector->resetAt(frameIndex)));
            const float strength = sharedMap ? sharedStrengths[frameIndex] :
                (eventMap ? eventMap->resetStrengthAt(frameIndex) : 0.0f);
            const auto* owners = config_.enablePhaseLocking ? &sharedPeaks.ownerPeak() : nullptr;
            vocoders_[0].process(leftInput.data(), leftOutput.data(), delta, resetPhase,
                                 config_.enableSelectivePhaseReset, strength, owners);
            vocoders_[1].process(rightInput.data(), rightOutput.data(), delta, resetPhase,
                                 config_.enableSelectivePhaseReset, strength, owners);
            if (tracker) tracker->process(sharedPeaks,
                {leftInput.data(),rightInput.data()},
                {leftOutput.data(),rightOutput.data()},
                {&vocoders_[0],&vocoders_[1]},delta,resetPhase);
            // CSV diagnostics need the independent phase before coherence changes it.
            if (coherenceCsv.is_open()) {
                for (std::size_t k = 1; k + 1 < bins; ++k)
                    independentIpd[k] = std::remainder(double(std::arg(rightOutput[k])) -
                        std::arg(leftOutput[k]), 2.0 * std::numbers::pi);
            }
            if (config_.enableStereoCoherence)
                coherence.process(leftInput.data(), rightInput.data(), leftOutput.data(),
                                  rightOutput.data(), vocoders_[0], vocoders_[1],
                                  sharedPeaks.ownerPeak());
            if (tracker) tracker->synchronize({leftOutput.data(),rightOutput.data()});
            if (coherenceCsv.is_open()) {
                for (std::size_t k = 1; k + 1 < bins; ++k) {
                    const double ml = std::abs(leftInput[k]), mr = std::abs(rightInput[k]);
                    if (std::max(ml, mr) < 1e-5) continue;
                    coherenceCsv << frameIndex << ',' << k << ',' << ml << ',' << mr << ','
                        << 0.5 * std::abs(leftInput[k] + rightInput[k]) << ','
                        << 0.5 * std::abs(leftInput[k] - rightInput[k]) << ','
                        << std::remainder(double(std::arg(rightInput[k])) - std::arg(leftInput[k]),
                                          2.0 * std::numbers::pi) << ',' << independentIpd[k] << ','
                        << std::remainder(double(std::arg(rightOutput[k])) - std::arg(leftOutput[k]),
                                          2.0 * std::numbers::pi) << ',' << coherence.weights()[k] << ','
                        << 20 * std::log10((ml + 1e-12) / (mr + 1e-12)) << '\n';
                }
            }
            stft_.synthesize(leftOutput.data(), synthesized_.data());
            leftOla.add(synthesized_.data(), stft_.window().data(), fftSize, start);
            stft_.synthesize(rightOutput.data(), synthesized_.data());
            rightOla.add(synthesized_.data(), stft_.window().data(), fftSize, start);
            previousStart = start;
        }
        result[0] = leftOla.finish(outputLength, padding);
        result[1] = rightOla.finish(outputLength, padding);
        lastAverageCoherenceWeight_ = coherence.averageWeight();
        return result;
    }
    for (std::size_t c = 0; c < input.size(); ++c) {
        vocoders_[c].reset();
        std::unique_ptr<PartialTracker> tracker;
        if (config_.enablePartialTracking)
            tracker=std::make_unique<PartialTracker>(fftSize,config_.analysisHop,
                                                     config_.sampleRate,1);
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
            const auto start = lastTimeMap_.outputPositionForInputSample(frameIndex * double(hop));
            const double delta = frameIndex == 0 ? 0.0 : (start - previousStart);
            const bool resetPhase=sharedMap ? sharedResets[frameIndex] :
                (eventMap ? eventMap->resetAt(frameIndex)
                          : (detector && detector->resetAt(frameIndex)));
            vocoders_[c].process(spectrum_.data(), stretchedSpectrum_.data(), delta,
                                 resetPhase,
                                 config_.enableSelectivePhaseReset,
                                 sharedMap ? sharedStrengths[frameIndex] :
                                   (eventMap ? eventMap->resetStrengthAt(frameIndex) : 0.0f));
            if (tracker) {
                tracker->process(vocoders_[c].phaseLocker(),
                    {spectrum_.data(),nullptr},{stretchedSpectrum_.data(),nullptr},
                    {&vocoders_[c],nullptr},delta,resetPhase);
                tracker->synchronize({stretchedSpectrum_.data(),nullptr});
            }
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
