#include "prototype/Phase36StreamingSpeedEngine.h"
// Phase 23 synthesis order, copied so fixed-speed/Golden paths remain frozen.
#include "audio/WavStream.h"
#include "dsp/MultiResolutionCrossover.h"
#include "dsp/PartialTracker.h"
#include "dsp/PeriodicResynchronizer.h"
#include "dsp/RingOverlapAdd.h"
#include "dsp/FFTAccelerate.h"
#include "prototype/Phase35PhaseVocoder.h"
#include "prototype/Phase35StereoPhaseCoherence.h"
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
#include <chrono>
#include <ctime>

#include "dsp/TransientEventMap.h"

namespace ts::prototype {
namespace {
using ts::prototype::Phase35PhaseVocoder;
using ts::prototype::Phase35StereoPhaseCoherence;
constexpr std::size_t cacheSize = 65536;
constexpr std::uint64_t hashSeed = 14695981039346656037ULL;
using WorkProfile=Phase36StreamingSpeedEngine::WorkProfile;
double threadCpuNow() {
    timespec value{};
    clock_gettime(CLOCK_THREAD_CPUTIME_ID,&value);
    return double(value.tv_sec)+double(value.tv_nsec)*1e-9;
}
struct StageClock {
    WorkProfile* profile;
    std::size_t stage;
    std::chrono::steady_clock::time_point wall;
    double cpu;
    bool finished=false;
    StageClock(WorkProfile* target,std::size_t index)
        : profile(target),stage(index),wall(target ? std::chrono::steady_clock::now() :
          std::chrono::steady_clock::time_point{}),cpu(target ? threadCpuNow() : 0) {}
    void finish() {
        if (!profile || finished) return;
        finished=true;
        auto& item=profile->stages[stage];
        item.wallSeconds+=std::chrono::duration<double>(
            std::chrono::steady_clock::now()-wall).count();
        item.threadCpuSeconds+=threadCpuNow()-cpu;
    }
    ~StageClock() { finish(); }
};
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

// Phase 5.3 FFT convolution with a worker-only mutable end boundary. The
// response, block order and accumulation order are identical to StreamingFIR.
class LiveStreamingFIR {
public:
    LiveStreamingFIR(const MultiResolutionCrossover::Filter& filter,std::size_t length,
                     WorkProfile* profile)
        : taps_(filter.taps),center_(filter.taps/2),
          blockLength_(4096-filter.taps+1),length_(length),
          response_(filter.response),spectrum_(2049),block_(4096),
          transformed_(4096),accum_(16384),profile_(profile) {}
    void setOutputLength(std::size_t length) {
        if (length==length_) return;
        if (length<base_ || length<nextBlock_)
            throw std::logic_error("Live FIR end already synthesized");
        length_=length;
    }
    std::size_t ringSize() const { return accum_.size(); }
    std::size_t firstUnprocessedSourceSample() const { return nextBlock_; }
    template<class Source> float next(std::size_t index,Source&& source) {
        if (index!=base_) throw std::logic_error("Non-sequential FIR retrieval");
        while (nextBlock_<length_ && nextBlock_<=index+center_) {
            std::fill(block_.begin(),block_.end(),0.0f);
            const auto count=std::min(blockLength_,length_-nextBlock_);
            for (std::size_t i=0;i<count;++i) block_[i]=source(nextBlock_+i);
            {
                StageClock measure(profile_,4);
                fft_.forward(block_.data(),spectrum_.data());
                for (std::size_t k=0;k<spectrum_.size();++k) spectrum_[k]*=response_[k];
                fft_.inverse(spectrum_.data(),transformed_.data());
            }
            const auto valid=count+taps_-1;
            for (std::size_t i=0;i<valid;++i) {
                const auto target=static_cast<long long>(nextBlock_+i)-
                    static_cast<long long>(center_);
                if (target<0 || static_cast<std::size_t>(target)>=length_) continue;
                const auto position=static_cast<std::size_t>(target);
                if (position<base_ || position>=base_+accum_.size())
                    throw std::out_of_range("FIR ring capacity exceeded");
                accum_[position%accum_.size()]+=transformed_[i];
            }
            nextBlock_+=blockLength_;
        }
        const auto slot=index%accum_.size();
        const float value=accum_[slot];
        accum_[slot]=0;
        ++base_;
        return value;
    }
private:
    FFTAccelerate fft_{4096};
    std::size_t taps_,center_,blockLength_,length_,nextBlock_=0,base_=0;
    std::vector<std::complex<float>> response_,spectrum_;
    std::vector<float> block_,transformed_,accum_;
    WorkProfile* profile_;
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
        throw std::invalid_argument("Phase 24 TimeMap size differs from analyzed frames");
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
                     bool mid, std::size_t outputLength,
                     const std::vector<std::pair<std::size_t,bool>>& modeChanges,
                     Phase13StageDigests& digests,
                     std::size_t resolutionIndex,std::ostream* stageTrace,
                     std::size_t probeInputSample,WorkProfile* profile)
        : reader_(path), config_(config), detection_(detection), mid_(mid),
          fftSize_(fftSize), hop_(hop), padding_(fftSize/2),
          length_(reader_.frames()), outputLength_(outputLength),
          modeChanges_(modeChanges),
          digests_(digests), resolutionIndex_(resolutionIndex),
          stageTrace_(stageTrace), probeInputSample_(probeInputSample), stft_(fftSize),
          coherence_(fftSize,config.sampleRate,config.stereoCoherenceStrength,
                     config.lowFrequencyCoherenceStrength), sharedPeaks_(fftSize),
          frame_(fftSize), synthesized_(fftSize),profile_(profile),
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

    }

    void setOutputLength(std::size_t length) { outputLength_=length; }
    std::size_t firstUnprocessedInputSample() const { return position_; }
    std::size_t lastProcessedInputSample() const { return lastProcessed_; }
    std::size_t finalizedOlaSample() const { return olas_[0].nextAbsoluteSample(); }
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
        (void)frameIndex;
        const auto start=position_;
        { StageClock measure(profile_,0);
        for (std::size_t i=0; i<fftSize_; ++i) {
            const auto padded=start+i;
            frame_[i]=padded>=padding_ && padded-padding_<length_
                ? reader_.sample(channel,padded-padding_) : 0.0f;
        } }
        { StageClock measure(profile_,1);
          stft_.analyze(frame_.data(),inputSpectra_[channel].data()); }
        hashSpectrum(digests_.fft[resolutionIndex_], inputSpectra_[channel]);
    }
    long long startAt(std::size_t frameIndex) const {
        (void)frameIndex;
        return std::llround(detection_.map.outputPositionForInputSample(double(position_)));
    }
    std::size_t nextInputPosition() const {
        bool half=config_.timeRatio>2.0;
        for (const auto& change:modeChanges_) {
            if (change.first>position_) break;
            half=change.second;
        }
        return position_+(half ? hop_/2 : hop_);
    }
    void processFrame() {
        const auto start=startAt(nextFrame_);
        const double delta=nextFrame_==0 ? 0.0 : double(start-previousStart_);
        if (nextFrame_ && (delta<=0 || delta>=double(fftSize_)))
            throw std::runtime_error("Unsafe variable synthesis hop");
        bool reset=false;
        float strength=0;
        const auto following=nextInputPosition();
        const auto midpoint=position_+(following-position_)/2;
        while (nextEvent_<detection_.map.events().size()) {
            const auto& event=detection_.map.events()[nextEvent_];
            // Phase 35 uses a strict '<' comparison for the previous frame;
            // an event exactly halfway between two frames belongs to the
            // following frame.
            if (event.peakFrame*1024>=midpoint) break;
            reset=true;
            strength=std::max(strength,event.strength);
            ++nextEvent_;
        }
        const int actualAnalysisHop=nextFrame_ ?
            static_cast<int>(position_-lastProcessed_) : hop_;
        for (std::size_t c=0; c<reader_.channels(); ++c) analyze(c,nextFrame_);
        StageClock phaseMeasure(profile_,2);
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
            decision=resynchronizer_->consider(nextFrame_,start,position_,
                detection_.resets,sharedPeaks_,reader_,olas_);
            if (decision.applied) {
                for (std::size_t c=0;c<reader_.channels();++c) {
                    for (std::size_t i=0;i<fftSize_;++i) {
                        const auto inputSample=static_cast<long long>(position_)+
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
                diagnostics_ << nextFrame_ << ',' << position_ << ',' << start << ','
                    << int(decision.scheduled) << ',' << int(decision.applied) << ','
                    << decision.offsetSamples << ',' << decision.correlation << ','
                    << decision.tonality << ',' << int(decision.transientSuppressed) << '\n';
        }
        if (shared) {
            const auto* owners=config_.enablePhaseLocking ? &sharedPeaks_.ownerPeak() : nullptr;
            for (std::size_t c=0; c<2; ++c)
                vocoders_[c].process(inputSpectra_[c].data(),outputSpectra_[c].data(),
                    delta,reset,config_.enableSelectivePhaseReset,strength,owners,actualAnalysisHop);
            if (decision.applied) for (std::size_t c=0;c<2;++c)
                vocoders_[c].resynchronize(inputSpectra_[c].data(),alignedSpectra_[c].data(),
                                          outputSpectra_[c].data(),owners);
            if (tracker_) throw std::logic_error("Partial tracking is outside Phase 36 scope");
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
                    actualAnalysisHop);
                if (decision.applied)
                    vocoders_[c].resynchronize(inputSpectra_[c].data(),alignedSpectra_[c].data(),
                        outputSpectra_[c].data(),&sharedPeaks_.ownerPeak());
                if (tracker_) throw std::logic_error("Partial tracking is outside Phase 36 scope");
            }
        }
        phaseMeasure.finish();
        for (std::size_t c=0; c<reader_.channels(); ++c) {
            StageClock synthesisMeasure(profile_,3);
            hashSpectrum(digests_.phase[resolutionIndex_], outputSpectra_[c]);
            stft_.synthesize(outputSpectra_[c].data(),synthesized_.data());
            for (const auto sample : synthesized_) hashFloat(digests_.ifft[resolutionIndex_], sample);
            olas_[c].add(synthesized_.data(),stft_.window().data(),fftSize_,start);
        }
        if (stageTrace_ && std::llabs(static_cast<long long>(position_)-
                                      static_cast<long long>(probeInputSample_))<=65536)
            *stageTrace_<<"frame,"<<resolutionIndex_<<','<<nextFrame_<<','
                        <<position_<<','<<start<<','
                        <<digests_.fft[resolutionIndex_]<<','
                        <<digests_.phase[resolutionIndex_]<<','
                        <<digests_.ifft[resolutionIndex_]<<','
                        <<digests_.ola[resolutionIndex_]<<",,,\n";
        previousStart_=start;
        if (position_>=length_+padding_) done_=true;
        lastProcessed_=position_;
        position_=following;
        ++nextFrame_;
    }
    void produce() {
        const auto absolute=produced_+padding_;
        while (!done_ &&
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
    std::size_t fftSize_,hop_,padding_,length_,outputLength_;
    const std::vector<std::pair<std::size_t,bool>>& modeChanges_;
    Phase13StageDigests& digests_;
    std::size_t resolutionIndex_;
    std::ostream* stageTrace_;
    std::size_t probeInputSample_;
    STFT stft_;
    Phase35StereoPhaseCoherence coherence_;
    PhaseLocker sharedPeaks_;
    std::unique_ptr<PartialTracker> tracker_;
    std::unique_ptr<PeriodicResynchronizer> resynchronizer_;
    std::ofstream diagnostics_;
    std::vector<Phase35PhaseVocoder> vocoders_;
    std::vector<RingOverlapAdd> olas_;
    std::vector<float> frame_,synthesized_;
    WorkProfile* profile_;
    std::vector<std::vector<std::complex<float>>> inputSpectra_,outputSpectra_;
    std::vector<std::vector<std::complex<float>>> alignedSpectra_;
    std::vector<std::complex<float>> combined_;
    std::vector<std::array<float,2>> cache_;
    std::size_t nextFrame_=0,produced_=0,position_=0,lastProcessed_=0,nextEvent_=0;
    bool done_=false;
    long long previousStart_=0;
};
}

Phase36StreamingSpeedEngine::Phase36StreamingSpeedEngine(StretchConfig config)
    : config_(std::move(config)) {
    // Phase 13 analysis is speed independent; its validator covers the
    // frozen 0.50x branch while this isolated prototype permits 0.40x.
    auto validation=config_;
    validation.timeRatio=2.0;
    Phase13StreamingEngine validated(validation);
    if (config_.enablePartialTracking || config_.enablePVSOLA)
        throw std::invalid_argument("Phase 36 supports Experimental 3500 only");
}

Phase13Result Phase36StreamingSpeedEngine::process(
    const std::filesystem::path& input,const Phase13TransientAnalysis& analysis,
    TimeMap map,std::size_t outputFrames,std::size_t chunkSize,
    const PreparedSink& preparedSink,const UpdateHook& update,
    std::vector<std::pair<std::size_t,bool>> modeChanges,
    const ProfileHook& profileHook,std::ostream* componentCsv,
    std::size_t probeFirst,std::size_t probeLast) {
    std::ostream* stageTrace=nullptr;
    std::size_t probeInputSample=0;
    if (!preparedSink || map.empty() || map.sourceHop()!=1024 ||
        chunkSize<1024 || chunkSize>65536)
        throw std::invalid_argument("Invalid Phase 24 process request");
    WavStreamReader reader(input);
    if (reader.frames()!=analysis.inputFrames() ||
        reader.channels()!=static_cast<std::size_t>(config_.channels) ||
        reader.sampleRate()!=config_.sampleRate)
        throw std::invalid_argument("Analyzed WAV metadata differs from Phase 24 input");
    if (reader.frames()==0 || outputFrames==0)
        throw std::invalid_argument("Phase 24 requires nonempty audio");
    auto detection=makeDetection(analysis,config_,map);
    WorkProfile workProfile;
    WorkProfile* profile=profileHook ? &workProfile : nullptr;
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
        detection,true,outputFrames,modeChanges,phase13.stages,1,stageTrace,probeInputSample,profile);
    resolution[0]=std::make_unique<ResolutionStream>(input,config_,8192,2048,
        detection,false,outputFrames,modeChanges,phase13.stages,0,stageTrace,probeInputSample,profile);
    resolution[2]=std::make_unique<ResolutionStream>(input,config_,1024,256,
        detection,false,outputFrames,modeChanges,phase13.stages,2,stageTrace,probeInputSample,profile);
    for (const auto& item:resolution)
        result.olaRingSamples+=item->olaSize()*reader.channels();
    MultiResolutionCrossover filters(config_.sampleRate,config_.lowCrossoverHz,
                                     config_.highCrossoverHz);
    std::vector<std::unique_ptr<LiveStreamingFIR>> lowFilters,highFilters;
    for (std::size_t c=0;c<reader.channels();++c) {
        lowFilters.emplace_back(std::make_unique<LiveStreamingFIR>(filters.lowFilter(),outputFrames,profile));
        highFilters.emplace_back(std::make_unique<LiveStreamingFIR>(filters.highFilter(),outputFrames,profile));
    }
    result.firRingSamples=(lowFilters[0]->ringSize()+highFilters[0]->ringSize())*
        reader.channels();
    std::vector<std::vector<float>> chunk(reader.channels(),std::vector<float>(chunkSize));
    std::vector<const float*> pointers(reader.channels());
    for (std::size_t c=0;c<reader.channels();++c) pointers[c]=chunk[c].data();
    for (std::size_t start=0;start<outputFrames;start+=chunkSize) {
        if (profile) workProfile={};
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
            if (componentCsv && start+i>=probeFirst && start+i<probeLast)
                *componentCsv<<start+i<<','<<c<<','
                    <<resolution[0]->get(c,start+i)<<','
                    <<resolution[1]->get(c,start+i)<<','<<high<<','
                    <<lowFiltered<<','<<highFiltered<<','<<value<<'\n';
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
        const auto poll=[&] {
            if (!update || start+count>=outputFrames) return;
            {
                Frontier frontier;
                frontier.preparedOutput=start+count;
                for (std::size_t r=0;r<3;++r) {
                    frontier.nextInput[r]=resolution[r]->firstUnprocessedInputSample();
                    frontier.lastProcessedInput[r]=resolution[r]->lastProcessedInputSample();
                    frontier.finalizedOla[r]=resolution[r]->finalizedOlaSample();
                }
                frontier.firstUnprocessedFirSource={
                    lowFilters[0]->firstUnprocessedSourceSample(),
                    highFilters[0]->firstUnprocessedSourceSample()};
                update(frontier,detection.map,outputFrames,modeChanges);
            }
            if (outputFrames<start+count || outputFrames>
                static_cast<std::size_t>(std::ceil(reader.frames()*2.5))+2)
                throw std::runtime_error("Invalid live output length");
            for (auto& item:resolution) item->setOutputLength(outputFrames);
            for (auto& item:lowFilters) item->setOutputLength(outputFrames);
            for (auto& item:highFilters) item->setOutputLength(outputFrames);
        };
        preparedSink(pointers.data(),count,poll);
        if (profile) profileHook(start,workProfile);
    }
    result.outputFrames=outputFrames;
    result.timeMapHash=hashSeed;
    for (const auto value:detection.map.starts()) {
        result.timeMapHash^=static_cast<std::uint64_t>(value);
        result.timeMapHash*=1099511628211ULL;
    }
    result.averageCoherenceWeight=resolution[1]->averageCoherenceWeight();
    return phase13;
}
}
