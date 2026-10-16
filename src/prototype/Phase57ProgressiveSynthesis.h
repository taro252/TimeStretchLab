#pragma once
#include "prototype/Phase56ProgressiveAnalysis.h"
#include "prototype/Phase36StreamingSpeedEngine.h"
#include <functional>
#include <span>
namespace ts::prototype::phase59 {struct DynamicMap;}
namespace ts::prototype::phase57 {
enum class SynthesisState {Produced,NeedsMoreInput,NeedsMoreAnalysis,Finished,Cancelled,Failed};
struct SynthesisFrontier {
    std::uint64_t generation=0;
    std::size_t receivedInput=0,detectorThrough=0,closedEvents=0,mapThroughNode=0;
    std::array<std::size_t,3> nextInput{},lastInput{},readableInputThrough{},olaThrough{};
    std::array<std::size_t,2> firSourceThrough{},firThrough{};
    std::size_t generated=0,published=0,outputFrames=0;
    SynthesisState state=SynthesisState::NeedsMoreAnalysis;
};
// One producer. Snapshot ownership is bounded to the newest lease; PCM is
// borrowed only for the duration of the sink. No audio-callback API.
class ProgressiveSynthesisEngine {
    struct Impl;std::unique_ptr<Impl> impl_;
public:
    using Sink=std::function<void(std::uint64_t,std::size_t,const float*const*,std::size_t)>;
    ProgressiveSynthesisEngine(const std::filesystem::path& pinnedInput,std::uint32_t speedMicros,
        std::uint64_t generation,std::function<void()> validateInput={},std::size_t memoryBudget=16*1024*1024,
        std::span<const unsigned char> pinnedBytes={});
    ~ProgressiveSynthesisEngine();
    // Phase58: optional fixed PlaybackEngine output-length contract. Must be
    // selected before the first snapshot; the Phase57 default is unchanged.
    void setDeclaredFinalOutputFrames(std::size_t);
    void enableWorkProfiling(); // Producer only, before first snapshot.
    void setWorkObserver(Phase36StreamingSpeedEngine::WorkProfile::Observer,void*);
    Phase36StreamingSpeedEngine::WorkProfile workProfile()const;
    void supplySnapshot(std::shared_ptr<const phase56::AnalysisSnapshot>);
    // Experimental realtime reader: an external mailbox must pin this immutable
    // view through the next supply call or engine destruction. No ownership ops.
    void supplyBorrowedSnapshot(const phase56::AnalysisSnapshot*);
    // Phase59 independent research path; opt in before the first snapshot.
    void enableDynamicTransitions();
    // Caller pins both old and proposed immutable views during this bounded
    // validation. A false return leaves every DSP state and view unchanged.
    bool trySupplyBorrowedDynamicMap(const phase59::DynamicMap*) noexcept;
    Phase36StreamingSpeedEngine::Frontier dspFrontier()const;
    SynthesisState advance(const Sink&); // at most one 2048-frame output block
    void cancel()noexcept; // thread-safe request; completed EOS stays completed
    void fail();
    SynthesisFrontier frontier()const; // producer or quiescent caller only
    std::size_t stateBytesEstimate()const;
    void injectFailureForTest();
};
}
