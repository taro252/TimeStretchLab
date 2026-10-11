#include "prototype/Phase23VariableSpeedEngine.h"
// Frozen Phase 13 synthesis order, copied into an independent prototype so
// the production fixed-speed engine and its Golden output remain untouched.
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

#include "dsp/TransientEventMap.h"

namespace ts::prototype {
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

Detection makeDetection(const Phase13TransientAnalysis& analysis,
                        const StretchConfig& config,const TimeMap& map) {
    Detection result;
    TransientEventMap events(analysis.detectorFrames(),analysis.activeFrameCount(),
                             1024,config.timeRatio,EventMapConfig{},analysis.events());
    std::vector<double> offsets;
    offsets.reserve(analysis.anchors().size());
    for (const auto& anchor:analysis.anchors()) {
        offsets.push_back(anchor.sampleOffset);
        if (anchor.confident) ++result.anchoredCount;
    }
    events.refineAnchors(offsets);
    if (events.starts().size()!=map.starts().size())
        throw std::invalid_argument("Phase 23 TimeMap size differs from analyzed frames");
    result.map=map;
    result.resets.resize(events.starts().size());
    result.strengths.resize(events.starts().size());
    result.transientCount=analysis.transientCount();
    result.eventCount=events.events().size();
    for (std::size_t i=0;i<events.starts().size();++i) {
        result.resets[i]=events.resetAt(i);
        result.strengths[i]=events.resetStrengthAt(i);
    }
    for (const auto& event:events.events())
        result.anchorError=std::max(result.anchorError,
            std::llabs(events.starts()[event.peakFrame]-
                       events.idealStartAt(event.peakFrame)));
    return result;
}
class ResolutionStream {
public:
    ResolutionStream(const std::filesystem::path& path, const StretchConfig& config,
                     int fftSize, int hop, const Detection& detection,
                     bool mid, std::size_t outputLength, Phase13StageDigests& digests,
                     std::size_t resolutionIndex,std::ostream* stageTrace,
                     std::size_t probeInputSample)
        : reader_(path), config_(config), detection_(detection), mid_(mid),
          fftSize_(fftSize), hop_(hop), padding_(fftSize/2),
          length_(reader_.frames()), outputLength_(outputLength),
          frameCount_((length_+padding_+hop_-1)/hop_+1),
          digests_(digests), resolutionIndex_(resolutionIndex),
          stageTrace_(stageTrace), probeInputSample_(probeInputSample), stft_(fftSize),
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
        if (stageTrace_ && std::llabs(static_cast<long long>(nextFrame_*hop_)-
                                      static_cast<long long>(probeInputSample_))<=65536)
            *stageTrace_<<"frame,"<<resolutionIndex_<<','<<nextFrame_<<','
                        <<nextFrame_*hop_<<','<<start<<','
                        <<digests_.fft[resolutionIndex_]<<','
                        <<digests_.phase[resolutionIndex_]<<','
                        <<digests_.ifft[resolutionIndex_]<<','
                        <<digests_.ola[resolutionIndex_]<<",,,\n";
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
    std::ostream* stageTrace_;
    std::size_t probeInputSample_;
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

Phase23VariableSpeedEngine::Phase23VariableSpeedEngine(StretchConfig config)
    : config_(std::move(config)) {
    // This validates the same frozen Experimental 3500 configuration as Phase 13.
    Phase13StreamingEngine validated(config_);
}

Phase13Result Phase23VariableSpeedEngine::process(
    const std::filesystem::path& input,const Phase13TransientAnalysis& analysis,
    const TimeMap& map,std::size_t outputFrames,const OutputSink& sink,
    std::size_t chunkSize,std::ostream* stageTrace,
    std::size_t probeInputSample) {
    if (!sink || map.empty() || map.sourceHop()!=1024 ||
        chunkSize<8192 || chunkSize>65536)
        throw std::invalid_argument("Invalid Phase 23 process request");
    WavStreamReader reader(input);
    if (reader.frames()!=analysis.inputFrames() ||
        reader.channels()!=static_cast<std::size_t>(config_.channels) ||
        reader.sampleRate()!=config_.sampleRate)
        throw std::invalid_argument("Analyzed WAV metadata differs from Phase 23 input");
    if (reader.frames()==0 || outputFrames==0)
        throw std::invalid_argument("Phase 23 requires nonempty audio");
    const auto detection=makeDetection(analysis,config_,map);
    Phase13Result phase13;
    for (auto* group:{&phase13.stages.fft,&phase13.stages.phase,
                     &phase13.stages.ifft,&phase13.stages.ola}) group->fill(hashSeed);
    phase13.stages.lowFir=hashSeed;
    phase13.stages.highFir=hashSeed;
    phase13.stages.fir=hashSeed;
    auto& result=phase13.processing;
    result.inputFrames=reader.frames();
    result.outputFrames=outputFrames;
    result.chunkSize=chunkSize;
    result.timeMapHash=hashSeed;
    for (const auto start:map.starts()) {
        result.timeMapHash^=static_cast<std::uint64_t>(start);
        result.timeMapHash*=1099511628211ULL;
    }
    result.transientCount=detection.transientCount;
    result.eventCount=detection.eventCount;
    result.anchoredEventCount=detection.anchoredCount;
    result.maxAnchorErrorSamples=detection.anchorError;

    // One instance per resolution persists across the whole input. The
    // crossover filters likewise retain their overlap and FFT block position.
    std::array<std::unique_ptr<ResolutionStream>,3> resolution;
    resolution[1]=std::make_unique<ResolutionStream>(input,config_,4096,1024,
        detection,true,outputFrames,phase13.stages,1,stageTrace,probeInputSample);
    resolution[0]=std::make_unique<ResolutionStream>(input,config_,8192,2048,
        detection,false,outputFrames,phase13.stages,0,stageTrace,probeInputSample);
    resolution[2]=std::make_unique<ResolutionStream>(input,config_,1024,256,
        detection,false,outputFrames,phase13.stages,2,stageTrace,probeInputSample);
    for (const auto& item:resolution)
        result.olaRingSamples+=item->olaSize()*reader.channels();
    MultiResolutionCrossover filters(config_.sampleRate,config_.lowCrossoverHz,
                                     config_.highCrossoverHz);
    std::vector<std::unique_ptr<StreamingFIR>> lowFilters,highFilters;
    for (std::size_t c=0;c<reader.channels();++c) {
        lowFilters.emplace_back(std::make_unique<StreamingFIR>(filters.lowFilter(),outputFrames));
        highFilters.emplace_back(std::make_unique<StreamingFIR>(filters.highFilter(),outputFrames));
    }
    result.firRingSamples=(lowFilters[0]->ringSize()+highFilters[0]->ringSize())*
        reader.channels();
    std::vector<std::vector<float>> chunk(reader.channels(),std::vector<float>(chunkSize));
    std::vector<const float*> pointers(reader.channels());
    for (std::size_t c=0;c<reader.channels();++c) pointers[c]=chunk[c].data();
    for (std::size_t start=0;start<outputFrames;start+=chunkSize) {
        const auto count=std::min(chunkSize,outputFrames-start);
        for (std::size_t i=0;i<count;++i) for (std::size_t c=0;c<reader.channels();++c) {
            const auto high=resolution[2]->get(c,start+i);
            const auto lowFiltered=lowFilters[c]->next(start+i,[&](std::size_t n) {
                return resolution[0]->get(c,n)-resolution[1]->get(c,n);
            });
            const auto highFiltered=highFilters[c]->next(start+i,[&](std::size_t n) {
                return resolution[1]->get(c,n)-resolution[2]->get(c,n);
            });
            hashFloat(phase13.stages.lowFir,lowFiltered);
            hashFloat(phase13.stages.highFir,highFiltered);
            float value=high;
            value+=lowFiltered;
            value+=highFiltered;
            chunk[c][i]=value;
            hashFloat(phase13.stages.fir,value);
            result.peak=std::max(result.peak,std::abs(value));
            if (stageTrace && c+1==reader.channels() && (start+i)%256==0 &&
                std::llabs(static_cast<long long>(start+i)-
                           std::llround(map.outputPositionForInputSample(
                               double(probeInputSample))))<=131072)
                *stageTrace<<"fir,-1,-1,-1,"<<start+i<<",,,,,"
                           <<phase13.stages.lowFir<<','<<phase13.stages.highFir<<','
                           <<phase13.stages.fir<<'\n';
        }
        sink(pointers.data(),count);
    }
    result.averageCoherenceWeight=resolution[1]->averageCoherenceWeight();
    return phase13;
}
}
