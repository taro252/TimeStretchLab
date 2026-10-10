#include "dsp/Phase13StreamingEngine.h"
// Frozen Phase 5.3 processing order copied from ChunkedTimeStretchEngine.
// Kept independent so Phase 13 diagnostics cannot change the offline reference.
#include "audio/WavStream.h"
#include "dsp/MultiResolutionCrossover.h"
#include "dsp/PartialTracker.h"
#include "dsp/PeriodicResynchronizer.h"
#include "dsp/RingOverlapAdd.h"
#include "dsp/StreamingCrossover.h"
#include "dsp/StereoPhaseCoherence.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <memory>
#include <cstring>
#include <stdexcept>

namespace ts {
struct Phase13TransientData {
    std::filesystem::path input;
    std::size_t inputFrames=0, channels=0, frameCount=0, activeFrames=0;
    std::uint32_t sampleRate=0;
    std::size_t transientCount=0;
    std::vector<TransientFrame> detectorFrames;
    std::vector<TransientEvent> events;
    std::vector<TransientAnchor> anchors;
};
namespace {
constexpr std::size_t cacheSize = 65536;
constexpr std::uint64_t hashSeed = 14695981039346656037ULL;
void hashFloat(std::uint64_t& hash, float value) {
    std::uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    hash ^= bits;
    hash *= 1099511628211ULL;
}
void hashSpectrum(std::uint64_t& hash, const std::vector<std::complex<float>>& values) {
    for (const auto& value : values) {
        hashFloat(hash, value.real());
        hashFloat(hash, value.imag());
    }
}

struct Detection {
    TimeMap map;
    std::vector<bool> resets;
    std::vector<float> strengths;
    std::size_t transientCount = 0, eventCount = 0, anchoredCount = 0;
    long long anchorError = 0;
};

EventMapConfig eventSettings(const StretchConfig& config) {
    EventMapConfig settings;
    settings.minimumDistanceFrames=config.eventMinimumDistanceFrames;
    settings.decayMergeFrames=config.eventDecayMergeFrames;
    settings.preRollFrames=config.eventPreRollFrames;
    settings.postRollFrames=config.enableSelectivePhaseReset
        ? config.eventAttackPostRollFrames : config.eventPostRollFrames;
    settings.preserveAttackRegion=config.enableSelectivePhaseReset;
    return settings;
}
Phase13TransientData analyzeInputEvents(const std::filesystem::path& path,
    const StretchConfig& config, std::size_t length, std::size_t channels) {
    Phase13TransientData analysis;
    analysis.input=path;
    analysis.inputFrames=length;
    analysis.channels=channels;
    analysis.sampleRate=config.sampleRate;
    const std::size_t fftSize = 4096, hop = 1024, padding = fftSize/2;
    const auto frameCount = (length+padding+hop-1)/hop+1;
    analysis.frameCount=frameCount;
    WavStreamReader reader(path);
    STFT stft(fftSize);
    std::vector<float> frame(fftSize), combined(fftSize/2+1);
    std::vector<std::complex<float>> spectrum(fftSize/2+1);
    std::unique_ptr<TransientDetector> detector;
    if (config.enableTransientHandling) {
        TransientConfig settings;
        settings.sensitivity = config.transientSensitivity;
        settings.minimumFlux = config.transientMinimumFlux;
        settings.resetStrengthThreshold = config.transientStrengthThreshold;
        settings.historyFrames = config.transientHistoryFrames;
        settings.cooldownFrames = config.transientCooldownFrames;
        settings.lookbackFrames = config.transientLookbackFrames;
        detector = std::make_unique<TransientDetector>(fftSize/2+1, settings);
        for (std::size_t frameIndex=0; frameIndex<frameCount; ++frameIndex) {
            std::fill(combined.begin(), combined.end(), 0.0f);
            const auto start=frameIndex*hop;
            for (std::size_t channel=0; channel<channels; ++channel) {
                for (std::size_t i=0; i<fftSize; ++i) {
                    const auto padded=start+i;
                    frame[i]=padded>=padding && padded-padding<length
                        ? reader.sample(channel,padded-padding) : 0.0f;
                }
                stft.analyze(frame.data(),spectrum.data());
                for (std::size_t k=0; k<combined.size(); ++k)
                    combined[k]+=std::norm(spectrum[k]);
            }
            for (auto& value: combined) value=std::sqrt(value);
            detector->pushMagnitudes(combined.data());
        }
        const auto active=length+padding>=fftSize
            ? (length+padding-fftSize)/hop+1 : 0;
        detector->finalize(active);
        analysis.transientCount=detector->transientCount();
        analysis.activeFrames=active;
        analysis.detectorFrames=detector->frames();
        if (config.enableAdaptiveTimeMapping) {
            analysis.events=TransientEventMap::consolidateEvents(
                analysis.detectorFrames,active,eventSettings(config));
            if (config.enableSelectivePhaseReset || config.enablePreciseTransientAnchoring) {
                AnchorLocatorConfig anchorSettings;
                if (config.enablePreciseTransientAnchoring) {
                    anchorSettings.minimumPeakToRunnerUp=3.0;
                    anchorSettings.requireInteriorPeak=true;
                }
                analysis.anchors=TransientAnchorLocator::locate(length,channels,
                    [&](std::size_t channel,std::size_t sample) {
                        return reader.sample(channel,sample);
                    },analysis.events,hop,anchorSettings);
            }
        }
    }
    return analysis;
}
Detection buildDetection(const Phase13TransientData& analysis,
    const StretchConfig& config) {
    Detection result;
    const std::size_t hop=1024, frameCount=analysis.frameCount;
    result.resets.resize(frameCount);
    result.strengths.resize(frameCount);
    result.transientCount=analysis.transientCount;
    std::unique_ptr<TransientEventMap> events;
    if (config.enableAdaptiveTimeMapping && config.enableTransientHandling) {
        events=std::make_unique<TransientEventMap>(analysis.detectorFrames,
            analysis.activeFrames,hop,config.timeRatio,eventSettings(config),analysis.events);
        if (config.enableSelectivePhaseReset || config.enablePreciseTransientAnchoring) {
            std::vector<double> offsets(analysis.anchors.size());
            for (std::size_t i=0; i<analysis.anchors.size(); ++i) {
                offsets[i]=analysis.anchors[i].sampleOffset;
                if (analysis.anchors[i].confident) ++result.anchoredCount;
            }
            events->refineAnchors(offsets);
        }
        result.eventCount=events->events().size();
        for (const auto& event: events->events())
            result.anchorError=std::max(result.anchorError,
                std::llabs(events->starts()[event.peakFrame]-
                           events->idealStartAt(event.peakFrame)));
    }
    std::vector<long long> starts(frameCount);
    for (std::size_t i=0; i<frameCount; ++i) {
        starts[i]=events ? events->starts()[i]
            : std::llround(i*hop*config.timeRatio);
        result.resets[i]=events ? events->resetAt(i) : false;
        result.strengths[i]=events ? events->resetStrengthAt(i) : 0.0f;
    }
    result.map=TimeMap(hop,std::move(starts),events ? events->events()
                                                     : std::vector<TransientEvent>{});
    return result;
}

class ResolutionStream {
public:
    ResolutionStream(const std::filesystem::path& path, const StretchConfig& config,
                     int fftSize, int hop, const Detection& detection,
                     bool mid, std::size_t outputLength, Phase13StageDigests& digests, std::size_t resolutionIndex)
        : reader_(path), config_(config), detection_(detection), mid_(mid),
          fftSize_(fftSize), hop_(hop), padding_(fftSize/2),
          length_(reader_.frames()), outputLength_(outputLength),
          frameCount_((length_+padding_+hop_-1)/hop_+1),
          digests_(digests), resolutionIndex_(resolutionIndex), stft_(fftSize),
          coherence_(fftSize,config.sampleRate,config.stereoCoherenceStrength,
                     config.lowFrequencyCoherenceStrength), sharedPeaks_(fftSize),
          frame_(fftSize), synthesized_(fftSize),
          inputSpectra_(reader_.channels(),std::vector<std::complex<float>>(fftSize/2+1)),
          outputSpectra_(reader_.channels(),std::vector<std::complex<float>>(fftSize/2+1)),
          combined_(fftSize/2+1), cache_(cacheSize) {
        for (std::size_t c=0; c<reader_.channels(); ++c) {
            vocoders_.emplace_back(fftSize,hop,config.enablePhaseLocking,config.sampleRate);
            olas_.emplace_back(fftSize*4);
        }
        if (mid_ && config_.enablePartialTracking)
            tracker_=std::make_unique<PartialTracker>(fftSize_,hop_,config.sampleRate,
                                                      static_cast<int>(reader_.channels()));
        if (mid_ && config_.enablePVSOLA) {
            resynchronizer_=std::make_unique<PeriodicResynchronizer>(config_,fftSize_,hop_);
            alignedSpectra_.resize(reader_.channels(),
                                   std::vector<std::complex<float>>(fftSize_/2+1));
            if (!config_.debugCsvDirectory.empty()) {
                std::filesystem::create_directories(config_.debugCsvDirectory);
                diagnostics_.open(std::filesystem::path(config_.debugCsvDirectory)/"pvsola_resync.csv");
                if (!diagnostics_) throw std::runtime_error("Cannot create PVSOLA diagnostics");
                diagnostics_ << "frame,inputSample,outputSample,scheduledResync,resyncApplied,searchOffsetSamples,"
                                "correlation,tonality,transientSuppressed\n";
            }
        }
        if (!mid_) {
            resets_.resize(frameCount_);
            strengths_.resize(frameCount_);
            for (const auto& event: detection_.map.events()) {
                const auto inputSample=event.peakFrame*
                    static_cast<std::size_t>(detection_.map.sourceHop());
                const auto mapped=std::min(frameCount_-1,
                    static_cast<std::size_t>(std::llround(double(inputSample)/hop_)));
                resets_[mapped]=true;
                strengths_[mapped]=std::max(strengths_[mapped],event.strength);
            }
        }
    }

    float get(std::size_t channel,std::size_t index) {
        if (index>=outputLength_) throw std::out_of_range("Resolution output index");
        while (produced_<=index) produce();
        if (index+cacheSize<produced_) throw std::out_of_range("Resolution cache expired");
        return cache_[index%cacheSize][channel];
    }
    double averageCoherenceWeight() const { return coherence_.averageWeight(); }
    std::size_t olaSize() const { return olas_.empty()?0:olas_[0].capacity(); }
    const PartialTracker* tracker() const { return tracker_.get(); }
    const PeriodicResynchronizer* resynchronizer() const { return resynchronizer_.get(); }
private:
    void analyze(std::size_t channel,std::size_t frameIndex) {
        const auto start=frameIndex*hop_;
        for (std::size_t i=0; i<fftSize_; ++i) {
            const auto padded=start+i;
            frame_[i]=padded>=padding_ && padded-padding_<length_
                ? reader_.sample(channel,padded-padding_) : 0.0f;
        }
        stft_.analyze(frame_.data(),inputSpectra_[channel].data());
        hashSpectrum(digests_.fft[resolutionIndex_], inputSpectra_[channel]);
    }
    long long startAt(std::size_t frameIndex) const {
        return std::llround(detection_.map.outputPositionForInputSample(
            frameIndex*double(hop_)));
    }
    void processFrame() {
        const auto start=startAt(nextFrame_);
        const double delta=nextFrame_==0 ? 0.0 : double(start-previousStart_);
        const bool reset=mid_ ? detection_.resets[nextFrame_] : resets_[nextFrame_];
        const float strength=mid_ ? detection_.strengths[nextFrame_] : strengths_[nextFrame_];
        for (std::size_t c=0; c<reader_.channels(); ++c) analyze(c,nextFrame_);
        const bool shared=reader_.channels()==2 &&
            (config_.enableStereoCoherence || tracker_ || resynchronizer_);
        if (shared) {
            for (std::size_t k=0; k<combined_.size(); ++k)
                combined_[k]={std::hypot(std::abs(inputSpectra_[0][k]),
                                         std::abs(inputSpectra_[1][k])),0};
            sharedPeaks_.analyzePeaks(combined_.data(),combined_.size());
        } else if (resynchronizer_)
            sharedPeaks_.analyzePeaks(inputSpectra_[0].data(),combined_.size());
        ResyncDecision decision;
        if (resynchronizer_) {
            decision=resynchronizer_->consider(nextFrame_,start,nextFrame_*hop_,
                detection_.resets,sharedPeaks_,reader_,olas_);
            if (decision.applied) {
                for (std::size_t c=0;c<reader_.channels();++c) {
                    for (std::size_t i=0;i<fftSize_;++i) {
                        const auto inputSample=static_cast<long long>(nextFrame_*hop_)+
                            decision.offsetSamples+static_cast<long long>(i)-
                            static_cast<long long>(padding_);
                        frame_[i]=inputSample>=0 &&
                            inputSample<static_cast<long long>(length_)
                            ? reader_.sample(c,static_cast<std::size_t>(inputSample)) : 0;
                    }
                    stft_.analyze(frame_.data(),alignedSpectra_[c].data());
                }
            }
            if (diagnostics_)
                diagnostics_ << nextFrame_ << ',' << nextFrame_*hop_ << ',' << start << ','
                    << int(decision.scheduled) << ',' << int(decision.applied) << ','
                    << decision.offsetSamples << ',' << decision.correlation << ','
                    << decision.tonality << ',' << int(decision.transientSuppressed) << '\n';
        }
        if (shared) {
            const auto* owners=config_.enablePhaseLocking ? &sharedPeaks_.ownerPeak() : nullptr;
            for (std::size_t c=0; c<2; ++c)
                vocoders_[c].process(inputSpectra_[c].data(),outputSpectra_[c].data(),
                    delta,reset,config_.enableSelectivePhaseReset,strength,owners,pendingAnalysisHop_);
            if (decision.applied) for (std::size_t c=0;c<2;++c)
                vocoders_[c].resynchronize(inputSpectra_[c].data(),alignedSpectra_[c].data(),
                                          outputSpectra_[c].data(),owners);
            if (tracker_) tracker_->process(sharedPeaks_,
                {inputSpectra_[0].data(),inputSpectra_[1].data()},
                {outputSpectra_[0].data(),outputSpectra_[1].data()},
                {&vocoders_[0],&vocoders_[1]},delta,reset);
            if (config_.enableStereoCoherence)
                coherence_.process(inputSpectra_[0].data(),inputSpectra_[1].data(),
                    outputSpectra_[0].data(),outputSpectra_[1].data(),
                    vocoders_[0],vocoders_[1],sharedPeaks_.ownerPeak());
            if (tracker_) tracker_->synchronize({outputSpectra_[0].data(),outputSpectra_[1].data()});
        } else {
            for (std::size_t c=0; c<reader_.channels(); ++c) {
                if (tracker_) sharedPeaks_.analyzePeaks(inputSpectra_[c].data(),combined_.size());
                vocoders_[c].process(inputSpectra_[c].data(),outputSpectra_[c].data(),
                    delta,reset,config_.enableSelectivePhaseReset,strength,
                    (tracker_ || resynchronizer_) ? &sharedPeaks_.ownerPeak() : nullptr,
                    pendingAnalysisHop_);
                if (decision.applied)
                    vocoders_[c].resynchronize(inputSpectra_[c].data(),alignedSpectra_[c].data(),
                        outputSpectra_[c].data(),&sharedPeaks_.ownerPeak());
                if (tracker_) {
                    tracker_->process(sharedPeaks_,{inputSpectra_[c].data(),nullptr},
                        {outputSpectra_[c].data(),nullptr},{&vocoders_[c],nullptr},delta,reset);
                    tracker_->synchronize({outputSpectra_[c].data(),nullptr});
                }
            }
        }
        pendingAnalysisHop_=decision.applied ? hop_-decision.offsetSamples : 0;
        for (std::size_t c=0; c<reader_.channels(); ++c) {
            hashSpectrum(digests_.phase[resolutionIndex_], outputSpectra_[c]);
            stft_.synthesize(outputSpectra_[c].data(),synthesized_.data());
            for (const auto sample : synthesized_) hashFloat(digests_.ifft[resolutionIndex_], sample);
            olas_[c].add(synthesized_.data(),stft_.window().data(),fftSize_,start);
        }
        previousStart_=start;
        ++nextFrame_;
    }
    void produce() {
        const auto absolute=produced_+padding_;
        while (nextFrame_<frameCount_ &&
               static_cast<long long>(startAt(nextFrame_))<=static_cast<long long>(absolute))
            processFrame();
        for (std::size_t c=0; c<reader_.channels(); ++c) {
            while (olas_[c].nextAbsoluteSample()<absolute) olas_[c].pop();
            cache_[produced_%cacheSize][c]=olas_[c].pop();
            hashFloat(digests_.ola[resolutionIndex_], cache_[produced_%cacheSize][c]);
        }
        ++produced_;
    }
    WavStreamReader reader_;
    const StretchConfig& config_;
    const Detection& detection_;
    bool mid_;
    std::size_t fftSize_,hop_,padding_,length_,outputLength_,frameCount_;
    Phase13StageDigests& digests_;
    std::size_t resolutionIndex_;
    STFT stft_;
    StereoPhaseCoherence coherence_;
    PhaseLocker sharedPeaks_;
    std::unique_ptr<PartialTracker> tracker_;
    std::unique_ptr<PeriodicResynchronizer> resynchronizer_;
    std::ofstream diagnostics_;
    std::vector<PhaseVocoder> vocoders_;
    std::vector<RingOverlapAdd> olas_;
    std::vector<float> frame_,synthesized_;
    std::vector<std::vector<std::complex<float>>> inputSpectra_,outputSpectra_;
    std::vector<std::vector<std::complex<float>>> alignedSpectra_;
    std::vector<std::complex<float>> combined_;
    std::vector<std::array<float,2>> cache_;
    std::vector<bool> resets_;
    std::vector<float> strengths_;
    std::size_t nextFrame_=0,produced_=0;
    long long previousStart_=0;
    int pendingAnalysisHop_=0;
};
}

struct Phase13PreparedFile::Impl {
    std::filesystem::path input;
    std::size_t inputFrames=0, outputFrames=0, channels=0;
    std::uint32_t sampleRate=0;
    double timeRatio=0;
    std::shared_ptr<const Phase13TransientData> analysis;
    Detection detection;
};

std::size_t Phase13TransientAnalysis::inputFrames() const {
    return impl_ ? impl_->inputFrames : 0;
}
std::size_t Phase13TransientAnalysis::transientCount() const {
    return impl_ ? impl_->transientCount : 0;
}
const std::vector<TransientEvent>& Phase13TransientAnalysis::events() const {
    if (!impl_) throw std::logic_error("Transient analysis is empty");
    return impl_->events;
}
const std::vector<TransientAnchor>& Phase13TransientAnalysis::anchors() const {
    if (!impl_) throw std::logic_error("Transient analysis is empty");
    return impl_->anchors;
}
const std::vector<TransientFrame>& Phase13TransientAnalysis::detectorFrames() const {
    if (!impl_) throw std::logic_error("Transient analysis is empty");
    return impl_->detectorFrames;
}
std::size_t Phase13TransientAnalysis::activeFrameCount() const {
    return impl_ ? impl_->activeFrames : 0;
}

std::size_t Phase13PreparedFile::inputFrames() const {
    return impl_ ? impl_->inputFrames : 0;
}
std::size_t Phase13PreparedFile::outputFrames() const {
    return impl_ ? impl_->outputFrames : 0;
}
std::size_t Phase13PreparedFile::outputFrameForInputFrame(std::size_t inputFrame) const {
    if (!impl_ || inputFrame>impl_->inputFrames)
        throw std::out_of_range("Input frame outside analyzed file");
    if (inputFrame==impl_->inputFrames) return impl_->outputFrames;
    const auto mapped=impl_->detection.map.outputPositionForInputSample(double(inputFrame));
    return static_cast<std::size_t>(std::clamp(std::llround(mapped),0LL,
        static_cast<long long>(impl_->outputFrames-1)));
}

Phase13StreamingEngine::Phase13StreamingEngine(StretchConfig config):config_(std::move(config)) {
    if (config_.fftSize!=4096 || config_.analysisHop!=1024)
        throw std::invalid_argument("Chunked processing requires 4096/1024 mid-resolution settings");
    if ((config_.timeRatio != 2.0 && config_.timeRatio != 4.0/3.0) ||
        config_.qualityMode != QualityMode::Experimental ||
        !config_.enableMultiResolution || !config_.enablePhaseLocking ||
        !config_.enableTransientHandling || !config_.enableAdaptiveTimeMapping ||
        !config_.enablePreciseTransientAnchoring || !config_.enableStereoCoherence ||
        config_.enableSelectivePhaseReset || config_.enablePartialTracking ||
        config_.enablePVSOLA || config_.lowCrossoverHz != 250.0 ||
        config_.highCrossoverHz != 3500.0 ||
        config_.stereoCoherenceStrength != 1.0f ||
        config_.lowFrequencyCoherenceStrength != 0.5f ||
        config_.transientSensitivity != 3.0f ||
        config_.transientMinimumFlux != 0.02f ||
        config_.transientStrengthThreshold != 0.25f ||
        config_.transientHistoryFrames != 12 ||
        config_.transientCooldownFrames != 2 ||
        config_.transientLookbackFrames != 1 ||
        config_.eventMinimumDistanceFrames != 4 ||
        config_.eventDecayMergeFrames != 12 ||
        config_.eventPreRollFrames != 2 ||
        config_.eventPostRollFrames != 5)
        throw std::invalid_argument("Phase 13 requires the frozen Experimental 3500 fixed-speed settings");
    TimeStretchEngine validate(config_);
}
Phase13PreparedFile Phase13StreamingEngine::analyzeFile(const std::filesystem::path& input) const {
    return prepareWithAnalysis(analyzeTransientEvents(input));
}
Phase13TransientAnalysis Phase13StreamingEngine::analyzeTransientEvents(
    const std::filesystem::path& input) const {
    WavStreamReader reader(input);
    if (reader.channels()!=static_cast<std::size_t>(config_.channels) ||
        reader.sampleRate()!=config_.sampleRate)
        throw std::invalid_argument("WAV metadata differs from configuration");
    auto data=std::make_shared<Phase13TransientData>();
    if (reader.frames()!=0)
        *data=analyzeInputEvents(input,config_,reader.frames(),reader.channels());
    else {
        data->input=input;
        data->channels=reader.channels();
        data->sampleRate=reader.sampleRate();
    }
    Phase13TransientAnalysis analysis;
    analysis.impl_=std::move(data);
    return analysis;
}
Phase13PreparedFile Phase13StreamingEngine::prepareWithAnalysis(
    const Phase13TransientAnalysis& analysis) const {
    if (!analysis.impl_) throw std::invalid_argument("Transient analysis is empty");
    const auto& data=*analysis.impl_;
    if (data.channels!=static_cast<std::size_t>(config_.channels) ||
        data.sampleRate!=config_.sampleRate)
        throw std::invalid_argument("Transient analysis metadata differs from configuration");
    const auto target=std::round(data.inputFrames*config_.timeRatio);
    if (!std::isfinite(target) || target>double(std::numeric_limits<std::size_t>::max()/2))
        throw std::length_error("Output too large");
    auto plan=std::make_shared<Phase13PreparedFile::Impl>();
    plan->input=data.input;
    plan->inputFrames=data.inputFrames;
    plan->outputFrames=static_cast<std::size_t>(target);
    plan->channels=data.channels;
    plan->sampleRate=data.sampleRate;
    plan->timeRatio=config_.timeRatio;
    plan->analysis=analysis.impl_;
    if (data.inputFrames!=0)
        plan->detection=buildDetection(data,config_);
    Phase13PreparedFile prepared;
    prepared.impl_=std::move(plan);
    return prepared;
}
Phase13Result Phase13StreamingEngine::processFile(const std::filesystem::path& input,
    const OutputSink& sink, std::size_t chunkSize) {
    return processPrepared(analyzeFile(input),sink,chunkSize);
}
Phase13Result Phase13StreamingEngine::processPrepared(const Phase13PreparedFile& prepared,
    const OutputSink& sink, std::size_t chunkSize) {
    if (!prepared.impl_) throw std::invalid_argument("Phase 13 file has not been analyzed");
    if (prepared.impl_->timeRatio!=config_.timeRatio)
        throw std::invalid_argument("Prepared TimeMap belongs to another fixed speed");
    if (!sink) throw std::invalid_argument("Phase 13 output sink is required");
    constexpr auto mode = AblationMode::Full;
    Phase13Result phase13;
    for (auto* group : {&phase13.stages.fft, &phase13.stages.phase,
                        &phase13.stages.ifft, &phase13.stages.ola})
        group->fill(hashSeed);
    phase13.stages.lowFir = hashSeed;
    phase13.stages.highFir = hashSeed;
    phase13.stages.fir = hashSeed;
    if (chunkSize<8192 || chunkSize>65536)
        throw std::invalid_argument("Chunk size must be 8192..65536");
    const auto& input=prepared.impl_->input;
    WavStreamReader reader(input);
    if (reader.channels()!=prepared.impl_->channels ||
        reader.sampleRate()!=prepared.impl_->sampleRate ||
        reader.frames()!=prepared.impl_->inputFrames ||
        reader.channels()!=static_cast<std::size_t>(config_.channels) ||
        reader.sampleRate()!=config_.sampleRate)
        throw std::invalid_argument("Analyzed WAV metadata differs from input/configuration");
    auto& result = phase13.processing;
    result.inputFrames=reader.frames();
    const auto target=std::round(reader.frames()*config_.timeRatio);
    if (!std::isfinite(target) || target>double(std::numeric_limits<std::size_t>::max()/2))
        throw std::length_error("Output too large");
    result.outputFrames=static_cast<std::size_t>(target);
    result.chunkSize=chunkSize;
    std::vector<std::vector<float>> chunk(reader.channels(),std::vector<float>(chunkSize));
    std::vector<const float*> pointers(reader.channels());
    for (std::size_t c=0; c<reader.channels(); ++c) pointers[c]=chunk[c].data();
    if (reader.frames()==0 || config_.timeRatio==1.0) {
        for (std::size_t start=0; start<result.outputFrames; start+=chunkSize) {
            const auto count=std::min(chunkSize,result.outputFrames-start);
            for (std::size_t i=0; i<count; ++i) for (std::size_t c=0; c<reader.channels(); ++c) {
                const auto value=reader.sample(c,start+i);
                chunk[c][i]=value;
                result.peak=std::max(result.peak,std::abs(value));
            }
            sink(pointers.data(),count);
        }
        return phase13;
    }
    const auto& detection=prepared.impl_->detection;
    result.timeMapHash=14695981039346656037ULL;
    for (const auto start: detection.map.starts()) {
        result.timeMapHash^=static_cast<std::uint64_t>(start);
        result.timeMapHash*=1099511628211ULL;
    }
    result.transientCount=detection.transientCount;
    result.eventCount=detection.eventCount;
    result.anchoredEventCount=detection.anchoredCount;
    result.maxAnchorErrorSamples=detection.anchorError;
    std::array<std::unique_ptr<ResolutionStream>,3> resolution;
    resolution[1]=std::make_unique<ResolutionStream>(input,config_,4096,1024,detection,true,result.outputFrames,phase13.stages,1);
    if (mode!=AblationMode::MidOnly)
        resolution[0]=std::make_unique<ResolutionStream>(input,config_,8192,2048,detection,false,result.outputFrames,phase13.stages,0);
    if (mode==AblationMode::Full)
        resolution[2]=std::make_unique<ResolutionStream>(input,config_,1024,256,detection,false,result.outputFrames,phase13.stages,2);
    for (const auto& item: resolution) if (item) result.olaRingSamples+=item->olaSize()*reader.channels();
    std::unique_ptr<MultiResolutionCrossover> filters;
    std::vector<std::unique_ptr<StreamingFIR>> lowFilters;
    std::vector<std::unique_ptr<StreamingFIR>> highFilters;
    if (mode!=AblationMode::MidOnly) {
        filters=std::make_unique<MultiResolutionCrossover>(config_.sampleRate,
            config_.lowCrossoverHz,config_.highCrossoverHz);
        for (std::size_t c=0; c<reader.channels(); ++c) {
            lowFilters.emplace_back(std::make_unique<StreamingFIR>(filters->lowFilter(),result.outputFrames));
            if (mode==AblationMode::Full)
                highFilters.emplace_back(std::make_unique<StreamingFIR>(filters->highFilter(),result.outputFrames));
        }
        result.firRingSamples=(lowFilters[0]->ringSize()+
            (highFilters.empty() ? 0 : highFilters[0]->ringSize()))*reader.channels();
    }
    for (std::size_t start=0; start<result.outputFrames; start+=chunkSize) {
        const auto count=std::min(chunkSize,result.outputFrames-start);
        for (std::size_t i=0; i<count; ++i) for (std::size_t c=0; c<reader.channels(); ++c) {
            float value;
            if (mode==AblationMode::MidOnly) value=resolution[1]->get(c,start+i);
            else if (mode==AblationMode::LowMid) {
                const auto mid=resolution[1]->get(c,start+i);
                value=mid+lowFilters[c]->next(start+i,[&](std::size_t n) {
                    return resolution[0]->get(c,n)-resolution[1]->get(c,n);
                });
            } else {
                const auto high=resolution[2]->get(c,start+i);
                const auto lowFiltered=lowFilters[c]->next(start+i,[&](std::size_t n) {
                    return resolution[0]->get(c,n)-resolution[1]->get(c,n);
                });
                const auto highFiltered=highFilters[c]->next(start+i,[&](std::size_t n) {
                    return resolution[1]->get(c,n)-resolution[2]->get(c,n);
                });
                hashFloat(phase13.stages.lowFir,lowFiltered);
                hashFloat(phase13.stages.highFir,highFiltered);
                value=high;
                value+=lowFiltered;
                value+=highFiltered;
            }
            chunk[c][i]=value;
            hashFloat(phase13.stages.fir, value);
            result.peak=std::max(result.peak,std::abs(value));
        }
        sink(pointers.data(),count);
    }
    result.averageCoherenceWeight=resolution[1]->averageCoherenceWeight();
    if (const auto* tracker=resolution[1]->tracker()) {
        const auto& stats=tracker->stats();
        result.trackablePeakFrames=stats.trackablePeakFrames;
        result.matchedPeakFrames=stats.matchedPeakFrames;
        result.appliedPeakFrames=stats.appliedPeakFrames;
        result.trackSwitches=stats.trackSwitches;
        result.averageTrackLifetimeFrames=tracker->averageLifetimeFrames();
        result.averageTrackCount=tracker->averageTrackCount();
        result.peakPhaseDiscontinuityMean=stats.phaseDiscontinuityCount ?
            stats.phaseDiscontinuitySum/stats.phaseDiscontinuityCount : 0;
        result.peakPhaseDiscontinuityMax=stats.phaseDiscontinuityMax;
    }
    if (const auto* resync=resolution[1]->resynchronizer()) {
        const auto& stats=resync->stats();
        result.resyncScheduled=stats.scheduled;
        result.resyncApplied=stats.applied;
        result.resyncTransientSuppressed=stats.transientSuppressed;
        result.averageResyncCorrelation=stats.applied ? stats.correlationSum/stats.applied : 0;
        result.averageResyncOffsetSamples=stats.applied ?
            stats.absoluteOffsetSum/stats.applied : 0;
    }
    return phase13;
}
}
