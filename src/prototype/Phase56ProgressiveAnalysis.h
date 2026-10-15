#pragma once
#include "prototype/Phase56ImmutableSeries.h"
#include "prototype/Phase56ReferenceData.h"
#include "dsp/TransientAnchor.h"
#include <atomic>
#include <functional>
#include <optional>
namespace ts::prototype::phase56 {
// Experimental arithmetic counterpart. Existing one-shot finalize is untouched.
class IncrementalDetector {
    TransientConfig config_;long long lastDetected_=-3;std::size_t classified_=0,count_=0;
    std::vector<TransientFrame> frames_;std::vector<bool> active_;
    std::vector<double> history_,deviations_;
    void classify(std::size_t i);
public:
    void push(TransientFrame raw,bool active);
    void finish();
    std::size_t stableCount()const{return classified_>1?classified_-1:0;}
    std::size_t transientCount()const{return count_;}
    const std::vector<TransientFrame>& frames()const{return frames_;}
};
class IncrementalEvents {
    std::optional<TransientEvent> open_;double peakFlux_=0,peakEnergy_=0;std::size_t next_=0;
public:
    using Closed=std::function<void(const TransientEvent&)>;
    // Returns true only if a provisional peak changed (including a new event).
    bool push(std::size_t i,const TransientFrame&,const Closed&);
    void finish(const Closed&);
    const std::optional<TransientEvent>& pending()const{return open_;}
};
class MapPrefixBuilder {
    std::array<double,maxMaps> position_{},ratios_{};double previousOffset_=0;
    std::vector<double> stretchWeights_,compressWeights_;
    std::size_t boundary_=0,events_=0,intervalWork_=0;
    std::vector<std::uint32_t> speedMicros_;
    void segment(std::size_t end,double offset,bool tail);
public:
    std::array<std::vector<long long>,maxMaps> nodes;
    explicit MapPrefixBuilder(std::vector<std::uint32_t> requested=percentSpeedMicros());
    const auto& speedMicros()const{return speedMicros_;}
    void close(const TransientEvent&,const TransientAnchor&);
    void finish(std::size_t featureCount);
    std::size_t intervalWork()const{return intervalWork_;}
    std::size_t memoryBytes()const{std::size_t n=(stretchWeights_.capacity()+compressWeights_.capacity())*sizeof(double);for(const auto& v:nodes)n+=v.capacity()*sizeof(long long);return n;}
};
enum class AnalysisError {None,InvalidInput,Allocation,Processing,InputRead,InputChanged};
struct AnalysisSnapshot {
    std::uint64_t inputGeneration=0;
    std::size_t speedCount=0;
    std::array<std::uint32_t,maxMaps> speedMicros{};
    std::size_t receivedInputFrames=0,featureThrough=0,detectorThrough=0;
    std::size_t closedEventCount=0,closedAnchorCount=0,mapThroughNode=0;
    std::size_t activeFrameCount=0,transientCount=0;
    bool isFinal=false,isCancelled=false,hasError=false;
    AnalysisError error=AnalysisError::None;
    ImmutableSeries<TransientFrame> detector;
    ImmutableSeries<TransientEvent> events;
    ImmutableSeries<TransientAnchor> anchors;
    std::array<ImmutableSeries<long long>,maxMaps> maps;
    const ImmutableSeries<long long>& mapForSpeed(std::uint32_t micros)const{
        for(std::size_t i=0;i<speedCount;++i)if(speedMicros[i]==micros)return maps[i];
        throw std::out_of_range("Speed not requested for this session");
    }
};
struct AnalysisLimits {
    std::size_t maxInputFrames=48000ULL*600,snapshotBytes=64*1024*1024;
};
struct AnalysisStatistics {
    std::size_t fftFrames=0,mapIntervalWork=0,pcmCopyBytes=0,snapshotCopyBytes=0;
    std::size_t snapshotLiveBytes=0,snapshotPeakBytes=0,workingBytes=0;
};
// One producer; any number of snapshot readers. cancel() may be called by
// another thread. No method is an audio-callback API; no cache registration.
class ProgressiveAnalysisSession {
    struct Impl;std::unique_ptr<Impl> impl_;
public:
    ProgressiveAnalysisSession(std::uint32_t rate,std::size_t channels,std::uint64_t generation,AnalysisLimits={},std::vector<std::uint32_t> requestedSpeeds=percentSpeedMicros());
    ~ProgressiveAnalysisSession();
    void appendInput(std::uint64_t generation,std::size_t offset,const float*const* input,std::size_t frames);
    void advanceAnalysis();
    // Optional hook is solely for deterministic commit-boundary fault tests.
    void finishInput(std::uint64_t generation,const std::function<void()>& beforeCommit={});
    void failInput(std::uint64_t generation,AnalysisError);
    void cancel()noexcept;
    std::shared_ptr<const AnalysisSnapshot> getSnapshot()const;
    AnalysisStatistics statistics()const;
};
}
