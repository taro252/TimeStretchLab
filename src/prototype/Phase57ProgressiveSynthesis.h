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
struct LocalSeekStart {
    std::size_t requestedInput=0,requestedOutput=0,seedInput=0,beginOutput=0;
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
    // Stream readers duplicate the FD without reopening a pathname; caller keeps
    // ownership. Optional resident bytes are borrowed and must outlive the engine.
    ProgressiveSynthesisEngine(int pinnedFd,std::uint32_t speedMicros,
        std::uint64_t generation,std::function<void()> validateInput={},std::size_t memoryBudget=16*1024*1024,
        std::span<const unsigned char> pinnedBytes={});
    ~ProgressiveSynthesisEngine();
    // Phase58: optional fixed PlaybackEngine output-length contract. Must be
    // selected before the first snapshot; the Phase57 default is unchanged.
    void setDeclaredFinalOutputFrames(std::size_t);
    void enableWorkProfiling(); // Producer only, before first snapshot.
    void setWorkObserver(Phase36StreamingSpeedEngine::WorkProfile::Observer,void*);
    void setWorkObserverActive(bool) noexcept; // DSP owner, between advance calls.
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
    // Phase61: exclusive normal owner, final fixed map, same resident input.
    // Returns null when this state cannot be checkpointed exactly. No audio or
    // realtime callback may call this allocating deep copy.
    std::unique_ptr<ProgressiveSynthesisEngine> cloneFixedCheckpoint(int pinnedFd,
        std::span<const unsigned char> sameResidentBytes,std::function<void()> validateInput={})const;
    // A clone adopts the new epoch's same final fixed map before producing PCM.
    void prepareCheckpointForEpoch();
    // Persistent fixed-loop producer only. Same final snapshot object, resident
    // identity, speed/configuration; restores into existing FFT/work buffers.
    // No callback API. Rejects dynamic history and foreign checkpoint lineage.
    bool restoreFixedLoopCheckpoint(const ProgressiveSynthesisEngine&);
    bool captureFixedLoopCheckpoint(ProgressiveSynthesisEngine& preparedSlot)const;
    // Experimental local phase origin, NOT Exact Seek. Final fixed analysis/map
    // must already be supplied; call once, before advance, on the normal owner.
    // Returned absolute output prefix is synthesized then discarded by caller.
    LocalSeekStart initializeFastLocal(std::size_t inputFrame,std::size_t prerollInputFrames);
    void injectFailureForTest();
};
}
