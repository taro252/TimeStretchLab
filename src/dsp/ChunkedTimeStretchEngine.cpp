#include "dsp/ChunkedTimeStretchEngine.h"
#include "audio/WavStream.h"
#include "dsp/MultiResolutionCrossover.h"
#include "dsp/RingOverlapAdd.h"
#include "dsp/StreamingCrossover.h"
#include "dsp/StereoPhaseCoherence.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdlib>
#include <limits>
#include <memory>
#include <stdexcept>

namespace ts {
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
                     bool mid, std::size_t outputLength)
        : reader_(path), config_(config), detection_(detection), mid_(mid),
          fftSize_(fftSize), hop_(hop), padding_(fftSize/2),
          length_(reader_.frames()), outputLength_(outputLength),
          frameCount_((length_+padding_+hop_-1)/hop_+1), stft_(fftSize),
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
private:
    void analyze(std::size_t channel,std::size_t frameIndex) {
        const auto start=frameIndex*hop_;
        for (std::size_t i=0; i<fftSize_; ++i) {
            const auto padded=start+i;
            frame_[i]=padded>=padding_ && padded-padding_<length_
                ? reader_.sample(channel,padded-padding_) : 0.0f;
        }
        stft_.analyze(frame_.data(),inputSpectra_[channel].data());
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
        if (config_.enableStereoCoherence && reader_.channels()==2) {
            for (std::size_t k=0; k<combined_.size(); ++k)
                combined_[k]={std::hypot(std::abs(inputSpectra_[0][k]),
                                         std::abs(inputSpectra_[1][k])),0};
            sharedPeaks_.analyzePeaks(combined_.data(),combined_.size());
            const auto* owners=config_.enablePhaseLocking ? &sharedPeaks_.ownerPeak() : nullptr;
            for (std::size_t c=0; c<2; ++c)
                vocoders_[c].process(inputSpectra_[c].data(),outputSpectra_[c].data(),
                    delta,reset,config_.enableSelectivePhaseReset,strength,owners);
            coherence_.process(inputSpectra_[0].data(),inputSpectra_[1].data(),
                outputSpectra_[0].data(),outputSpectra_[1].data(),
                vocoders_[0],vocoders_[1],sharedPeaks_.ownerPeak());
        } else {
            for (std::size_t c=0; c<reader_.channels(); ++c)
                vocoders_[c].process(inputSpectra_[c].data(),outputSpectra_[c].data(),
                    delta,reset,config_.enableSelectivePhaseReset,strength);
        }
        for (std::size_t c=0; c<reader_.channels(); ++c) {
            stft_.synthesize(outputSpectra_[c].data(),synthesized_.data());
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
        }
        ++produced_;
    }
    WavStreamReader reader_;
    const StretchConfig& config_;
    const Detection& detection_;
    bool mid_;
    std::size_t fftSize_,hop_,padding_,length_,outputLength_,frameCount_;
    STFT stft_;
    StereoPhaseCoherence coherence_;
    PhaseLocker sharedPeaks_;
    std::vector<PhaseVocoder> vocoders_;
    std::vector<RingOverlapAdd> olas_;
    std::vector<float> frame_,synthesized_;
    std::vector<std::vector<std::complex<float>>> inputSpectra_,outputSpectra_;
    std::vector<std::complex<float>> combined_;
    std::vector<std::array<float,2>> cache_;
    std::vector<bool> resets_;
    std::vector<float> strengths_;
    std::size_t nextFrame_=0,produced_=0;
    long long previousStart_=0;
};
}

ChunkedTimeStretchEngine::ChunkedTimeStretchEngine(StretchConfig config):config_(std::move(config)) {
    if (!config_.enableMultiResolution || config_.fftSize!=4096 || config_.analysisHop!=1024)
        throw std::invalid_argument("Chunked processing requires Phase 5 multiresolution settings");
    TimeStretchEngine validate(config_);
}
ChunkedResult ChunkedTimeStretchEngine::processWav(const std::filesystem::path& input,
    const std::filesystem::path& output,std::size_t chunkSize) {
    if (chunkSize<8192 || chunkSize>65536)
        throw std::invalid_argument("Chunk size must be 8192..65536");
    WavStreamReader reader(input);
    if (reader.channels()!=static_cast<std::size_t>(config_.channels) ||
        reader.sampleRate()!=config_.sampleRate)
        throw std::invalid_argument("WAV metadata differs from configuration");
    ChunkedResult result;
    result.inputFrames=reader.frames();
    const auto target=std::round(reader.frames()*config_.timeRatio);
    if (!std::isfinite(target) || target>double(std::numeric_limits<std::size_t>::max()/2))
        throw std::length_error("Output too large");
    result.outputFrames=static_cast<std::size_t>(target);
    result.chunkSize=chunkSize;
    WavStreamWriter writer(output,reader.sampleRate(),reader.channels(),result.outputFrames);
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
            writer.write(pointers.data(),count);
        }
        writer.finish();
        return result;
    }
    const auto detection=detect(input,config_,reader.frames(),reader.channels());
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
    resolution[0]=std::make_unique<ResolutionStream>(input,config_,8192,2048,detection,false,result.outputFrames);
    resolution[1]=std::make_unique<ResolutionStream>(input,config_,4096,1024,detection,true,result.outputFrames);
    resolution[2]=std::make_unique<ResolutionStream>(input,config_,1024,256,detection,false,result.outputFrames);
    for (const auto& item: resolution) result.olaRingSamples+=item->olaSize()*reader.channels();
    MultiResolutionCrossover filters(config_.sampleRate);
    std::vector<std::unique_ptr<StreamingCrossoverChannel>> crossovers;
    for (std::size_t c=0; c<reader.channels(); ++c)
        crossovers.emplace_back(std::make_unique<StreamingCrossoverChannel>(filters,result.outputFrames));
    result.firRingSamples=crossovers[0]->ringSize()*reader.channels();
    for (std::size_t start=0; start<result.outputFrames; start+=chunkSize) {
        const auto count=std::min(chunkSize,result.outputFrames-start);
        for (std::size_t i=0; i<count; ++i) for (std::size_t c=0; c<reader.channels(); ++c) {
            const auto value=crossovers[c]->next(start+i,[&](std::size_t r,std::size_t n) {
                return resolution[r]->get(c,n);
            });
            chunk[c][i]=value;
            result.peak=std::max(result.peak,std::abs(value));
        }
        writer.write(pointers.data(),count);
    }
    writer.finish();
    result.averageCoherenceWeight=resolution[1]->averageCoherenceWeight();
    return result;
}
}
