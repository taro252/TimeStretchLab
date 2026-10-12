#include "prototype/Phase35TransitionEngine.h"
#include "audio/WavStream.h"
#include "dsp/MultiResolutionCrossover.h"
#include "dsp/PartialTracker.h"
#include "dsp/PeriodicResynchronizer.h"
#include "dsp/RingOverlapAdd.h"
#include "prototype/Phase35PhaseVocoder.h"
#include "dsp/StreamingCrossover.h"
#include "prototype/Phase35StereoPhaseCoherence.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <memory>
#include <stdexcept>

namespace ts {
using prototype::Phase35PhaseVocoder;
using prototype::Phase35StereoPhaseCoherence;
namespace {
constexpr std::size_t cacheSize = 65536;

struct Detection {
    TimeMap map;
    std::vector<bool> resets;
    std::vector<float> strengths;
    std::size_t transientCount = 0, eventCount = 0, anchoredCount = 0;
    long long anchorError = 0;
};

Detection detect(const std::filesystem::path& path, const StretchConfig& config,
                 std::size_t length, std::size_t channels) {
    Detection result;
    const std::size_t fftSize = 4096, hop = 1024, padding = fftSize/2;
    const auto frameCount = (length+padding+hop-1)/hop+1;
    result.resets.resize(frameCount);
    result.strengths.resize(frameCount);
    WavStreamReader reader(path);
    STFT stft(fftSize);
    std::vector<float> frame(fftSize), combined(fftSize/2+1);
    std::vector<std::complex<float>> spectrum(fftSize/2+1);
    std::unique_ptr<TransientDetector> detector;
    std::unique_ptr<TransientEventMap> events;
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
        result.transientCount=detector->transientCount();
        if (config.enableAdaptiveTimeMapping) {
            EventMapConfig settings;
            settings.minimumDistanceFrames=config.eventMinimumDistanceFrames;
            settings.decayMergeFrames=config.eventDecayMergeFrames;
            settings.preRollFrames=config.eventPreRollFrames;
            settings.postRollFrames=config.enableSelectivePhaseReset
                ? config.eventAttackPostRollFrames : config.eventPostRollFrames;
            settings.preserveAttackRegion=config.enableSelectivePhaseReset;
            events=std::make_unique<TransientEventMap>(detector->frames(),active,hop,
                                                       config.timeRatio,settings);
            if (config.enableSelectivePhaseReset || config.enablePreciseTransientAnchoring) {
                AnchorLocatorConfig anchorSettings;
                if (config.enablePreciseTransientAnchoring) {
                    anchorSettings.minimumPeakToRunnerUp=3.0;
                    anchorSettings.requireInteriorPeak=true;
                }
                const auto anchors=TransientAnchorLocator::locate(length,channels,
                    [&](std::size_t channel,std::size_t sample) {
                        return reader.sample(channel,sample);
                    },events->events(),hop,anchorSettings);
                std::vector<double> offsets(anchors.size());
                for (std::size_t i=0; i<anchors.size(); ++i) {
                    offsets[i]=anchors[i].sampleOffset;
                    if (anchors[i].confident) ++result.anchoredCount;
                }
                events->refineAnchors(offsets);
            }
            result.eventCount=events->events().size();
            for (const auto& event: events->events())
                result.anchorError=std::max(result.anchorError,
                    std::llabs(events->starts()[event.peakFrame]-
                               events->idealStartAt(event.peakFrame)));
        }
    }
    std::vector<long long> starts(frameCount);
    for (std::size_t i=0; i<frameCount; ++i) {
        starts[i]=events ? events->starts()[i]
            : std::llround(i*hop*config.timeRatio);
        result.resets[i]=events ? events->resetAt(i)
            : (detector && detector->resetAt(i));
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
                     bool mid, std::size_t outputLength,
                     const std::vector<std::pair<std::size_t,bool>>& modeChanges,
                     std::ostream* frameTrace)
        : reader_(path), config_(config), detection_(detection), mid_(mid),
          fftSize_(fftSize), hop_(hop), padding_(fftSize/2),
          length_(reader_.frames()), outputLength_(outputLength),
          frameTrace_(frameTrace), stft_(fftSize),
          coherence_(fftSize,config.sampleRate,config.stereoCoherenceStrength,
                     config.lowFrequencyCoherenceStrength), sharedPeaks_(fftSize),
          frame_(fftSize), synthesized_(fftSize),
          inputSpectra_(reader_.channels(),std::vector<std::complex<float>>(fftSize/2+1)),
          outputSpectra_(reader_.channels(),std::vector<std::complex<float>>(fftSize/2+1)),
          combined_(fftSize/2+1), cache_(cacheSize) {
        if (frameTrace_) frameTrace_->precision(10);
        std::size_t position=0;
        while (true) {
            positions_.push_back(position);
            if (position>=length_+padding_) break;
            bool half=config.timeRatio>2.0;
            for (const auto& change:modeChanges) {
                if (change.first>position) break;
                half=change.second;
            }
            position+=half ? static_cast<std::size_t>(hop_/2) : static_cast<std::size_t>(hop_);
        }
        frameCount_=positions_.size();
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
        // The frozen Mid reset vector is indexed at 1024 input samples.
        // At the research half-hop, map the same immutable events to the
        // additional Mid frames instead of indexing the old vector directly.
        if (true) {
            resets_.resize(frameCount_);
            strengths_.resize(frameCount_);
            for (const auto& event: detection_.map.events()) {
                const auto inputSample=event.peakFrame*
                    static_cast<std::size_t>(detection_.map.sourceHop());
                auto found=std::lower_bound(positions_.begin(),positions_.end(),inputSample);
                if (found==positions_.end()) --found;
                if (found!=positions_.begin() &&
                    inputSample-*(found-1)<*found-inputSample) --found;
                if (mid_ && *found!=inputSample)
                    throw std::runtime_error("Mid transient reset frame skipped by variable hop");
                const auto mapped=static_cast<std::size_t>(found-positions_.begin());
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
        const auto start=positions_[frameIndex];
        for (std::size_t i=0; i<fftSize_; ++i) {
            const auto padded=start+i;
            frame_[i]=padded>=padding_ && padded-padding_<length_
                ? reader_.sample(channel,padded-padding_) : 0.0f;
        }
        stft_.analyze(frame_.data(),inputSpectra_[channel].data());
    }
    long long startAt(std::size_t frameIndex) const {
        return std::llround(detection_.map.outputPositionForInputSample(
            double(positions_[frameIndex])));
    }
    int analysisDistance() const {
        return nextFrame_ ? static_cast<int>(positions_[nextFrame_]-positions_[nextFrame_-1]) : hop_;
    }
    void processFrame() {
        const auto start=startAt(nextFrame_);
        const double delta=nextFrame_==0 ? 0.0 : double(start-previousStart_);
        if (nextFrame_ && (delta<=0 || delta>=double(fftSize_)))
            throw std::runtime_error("Unsafe variable synthesis hop");
        const bool reset=resets_[nextFrame_];
        const float strength=strengths_[nextFrame_];
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
            decision=resynchronizer_->consider(nextFrame_,start,positions_[nextFrame_],
                detection_.resets,sharedPeaks_,reader_,olas_);
            if (decision.applied) {
                for (std::size_t c=0;c<reader_.channels();++c) {
                    for (std::size_t i=0;i<fftSize_;++i) {
                        const auto inputSample=static_cast<long long>(positions_[nextFrame_])+
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
                diagnostics_ << nextFrame_ << ',' << positions_[nextFrame_] << ',' << start << ','
                    << int(decision.scheduled) << ',' << int(decision.applied) << ','
                    << decision.offsetSamples << ',' << decision.correlation << ','
                    << decision.tonality << ',' << int(decision.transientSuppressed) << '\n';
        }
        if (shared) {
            const auto* owners=config_.enablePhaseLocking ? &sharedPeaks_.ownerPeak() : nullptr;
            for (std::size_t c=0; c<2; ++c)
                vocoders_[c].process(inputSpectra_[c].data(),outputSpectra_[c].data(),
                    delta,reset,config_.enableSelectivePhaseReset,strength,owners,analysisDistance());
            if (decision.applied) for (std::size_t c=0;c<2;++c)
                vocoders_[c].resynchronize(inputSpectra_[c].data(),alignedSpectra_[c].data(),
                                          outputSpectra_[c].data(),owners);
            if (config_.enableStereoCoherence)
                coherence_.process(inputSpectra_[0].data(),inputSpectra_[1].data(),
                    outputSpectra_[0].data(),outputSpectra_[1].data(),
                    vocoders_[0],vocoders_[1],sharedPeaks_.ownerPeak());
        } else {
            for (std::size_t c=0; c<reader_.channels(); ++c) {
                if (tracker_) sharedPeaks_.analyzePeaks(inputSpectra_[c].data(),combined_.size());
                vocoders_[c].process(inputSpectra_[c].data(),outputSpectra_[c].data(),
                    delta,reset,config_.enableSelectivePhaseReset,strength,
                    (tracker_ || resynchronizer_) ? &sharedPeaks_.ownerPeak() : nullptr,
                    analysisDistance());
                if (decision.applied)
                    vocoders_[c].resynchronize(inputSpectra_[c].data(),alignedSpectra_[c].data(),
                        outputSpectra_[c].data(),&sharedPeaks_.ownerPeak());
            }
        }
        for (std::size_t c=0; c<reader_.channels(); ++c) {
            stft_.synthesize(outputSpectra_[c].data(),synthesized_.data());
            olas_[c].add(synthesized_.data(),stft_.window().data(),fftSize_,start);
        }
        if (frameTrace_ && nextFrame_) {
            const auto begin=inputSpectra_[0].begin()+1;
            const auto end=inputSpectra_[0].end()-1;
            const auto peak=std::max_element(begin,end,[](const auto& left,const auto& right) {
                return std::norm(left)<std::norm(right);
            });
            const auto bin=static_cast<std::size_t>(peak-inputSpectra_[0].begin());
            *frameTrace_ << fftSize_ << ',' << nextFrame_ << ','
                << positions_[nextFrame_] << ',' << analysisDistance() << ',' << start << ','
                << start-previousStart_ << ',' << int(reset) << ',' << bin << ','
                << std::arg(inputSpectra_[0][bin]) << ','
                << std::arg(outputSpectra_[0][bin]) << ',' << std::abs(*peak) << '\n';
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
        }
        ++produced_;
    }
    WavStreamReader reader_;
    const StretchConfig& config_;
    const Detection& detection_;
    bool mid_;
    std::size_t fftSize_,hop_,padding_,length_,outputLength_,frameCount_=0;
    std::vector<std::size_t> positions_;
    std::ostream* frameTrace_;
    STFT stft_;
    Phase35StereoPhaseCoherence coherence_;
    PhaseLocker sharedPeaks_;
    std::unique_ptr<PartialTracker> tracker_;
    std::unique_ptr<PeriodicResynchronizer> resynchronizer_;
    std::ofstream diagnostics_;
    std::vector<Phase35PhaseVocoder> vocoders_;
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
};
}

Phase35TransitionEngine::Phase35TransitionEngine(StretchConfig config):config_(std::move(config)) {
    if (config_.fftSize!=4096 || config_.analysisHop!=1024)
        throw std::invalid_argument("Chunked processing requires 4096/1024 mid-resolution settings");
    if (config_.enablePartialTracking || config_.enablePVSOLA)
        throw std::invalid_argument("Phase 35 supports frozen Experimental 3500 only");
    TimeStretchEngine validate(config_);
}
ChunkedResult Phase35TransitionEngine::processWav(const std::filesystem::path& input,
    const std::filesystem::path& output,const TimeMap& map,
    const std::vector<std::pair<std::size_t,bool>>& modeChanges,
    std::size_t outputFrames,std::size_t chunkSize,std::ostream* frameTrace) {
    constexpr auto requestedMode=std::optional<AblationMode>{AblationMode::Full};
    const auto mode=requestedMode.value_or(!config_.enableMultiResolution ||
        config_.qualityMode==QualityMode::Normal ? AblationMode::MidOnly :
        config_.qualityMode==QualityMode::Experimental ? AblationMode::Full : AblationMode::LowMid);
    if (chunkSize<8192 || chunkSize>65536)
        throw std::invalid_argument("Chunk size must be 8192..65536");
    WavStreamReader reader(input);
    if (reader.channels()!=static_cast<std::size_t>(config_.channels) ||
        reader.sampleRate()!=config_.sampleRate)
        throw std::invalid_argument("WAV metadata differs from configuration");
    ChunkedResult result;
    result.inputFrames=reader.frames();
    if (map.empty() || map.sourceHop()!=1024 || outputFrames==0)
        throw std::invalid_argument("Invalid Phase 35 timeline");
    result.outputFrames=outputFrames;
    result.chunkSize=chunkSize;
    WavStreamWriter writer(output,reader.sampleRate(),reader.channels(),result.outputFrames);
    std::vector<std::vector<float>> chunk(reader.channels(),std::vector<float>(chunkSize));
    std::vector<const float*> pointers(reader.channels());
    for (std::size_t c=0; c<reader.channels(); ++c) pointers[c]=chunk[c].data();
    if (reader.frames()==0) {
        for (std::size_t start=0; start<result.outputFrames; start+=chunkSize) {
            const auto count=std::min(chunkSize,result.outputFrames-start);
            for (std::size_t i=0; i<count; ++i) for (std::size_t c=0; c<reader.channels(); ++c) {
                const auto value=reader.sample(c,start+i);
                chunk[c][i]=value;
                result.peak=std::max(result.peak,std::abs(value));
            }
            writer.write(pointers.data(),count);
        }
        writer.finish();
        return result;
    }
    auto detection=detect(input,config_,reader.frames(),reader.channels());
    detection.map=map;
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
    // Independent B experiment: below 0.50x double the STFT frame density
    // at every resolution. The frozen 0.50x+ branch keeps its exact settings.
    resolution[1]=std::make_unique<ResolutionStream>(input,config_,4096,
        1024,detection,true,result.outputFrames,modeChanges,frameTrace);
    if (mode!=AblationMode::MidOnly)
        resolution[0]=std::make_unique<ResolutionStream>(input,config_,8192,
            2048,detection,false,result.outputFrames,modeChanges,frameTrace);
    if (mode==AblationMode::Full)
        resolution[2]=std::make_unique<ResolutionStream>(input,config_,1024,
            256,detection,false,result.outputFrames,modeChanges,frameTrace);
    for (const auto& item: resolution) if (item) result.olaRingSamples+=item->olaSize()*reader.channels();
    std::unique_ptr<MultiResolutionCrossover> filters;
    std::vector<std::unique_ptr<StreamingCrossoverChannel>> crossovers;
    std::vector<std::unique_ptr<StreamingFIR>> lowFilters;
    if (mode!=AblationMode::MidOnly) {
        filters=std::make_unique<MultiResolutionCrossover>(config_.sampleRate,
            config_.lowCrossoverHz,config_.highCrossoverHz);
        for (std::size_t c=0; c<reader.channels(); ++c) {
            if (mode==AblationMode::Full)
                crossovers.emplace_back(std::make_unique<StreamingCrossoverChannel>(*filters,result.outputFrames));
            else
                lowFilters.emplace_back(std::make_unique<StreamingFIR>(filters->lowFilter(),result.outputFrames));
        }
        result.firRingSamples=(mode==AblationMode::Full ? crossovers[0]->ringSize()
            : lowFilters[0]->ringSize())*reader.channels();
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
            } else value=crossovers[c]->next(start+i,[&](std::size_t r,std::size_t n) {
                return resolution[r]->get(c,n);
            });
            chunk[c][i]=value;
            result.peak=std::max(result.peak,std::abs(value));
        }
        writer.write(pointers.data(),count);
    }
    writer.finish();
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
    return result;
}
}
