#pragma once
#include <span>
#include "playback/ProgressiveContract.h"
#include "playback/ProgressiveLoopContract.h"
#include "platform/macos/MacPlaybackEngine.h"
#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase46HostClock.h"

namespace ts::playback {
struct ProgressiveOutputSpan {
    std::uint64_t newEpoch=0,oldEpoch=0,callbackFrame=0;
    std::size_t newOutputOffset=0,oldOutputOffset=0,newReceivedFrames=0,oldReceivedFrames=0;
    std::size_t frames=0,mixedFrames=0,transitionOffset=0,transitionLength=0;
    std::size_t oldMissingFrames=0,newMissingFrames=0,outputAffectedFrames=0;
    std::size_t failurePaddingFrames=0,failurePaddingOffset=0;
    bool unrenderedFailure=false;
    bool periodicBoundary=false,correctionHead=false,correctionTail=false;
    std::size_t boundaryFrames=0,periodFrames=0,periodOffset=0;
    std::array<float,2> boundaryLast{},boundaryFirst{};
    // Entry mixing may straddle B. Period corrections precede the entry mix.
    bool correctionBeforeMix=false,oldPeriodicBoundary=false,oldCorrectionHead=false,oldCorrectionTail=false;
    std::size_t oldBoundaryFrames=0,oldPeriodFrames=0,oldPeriodOffset=0;
    std::array<float,2> oldBoundaryLast{},oldBoundaryFirst{};
};
inline constexpr std::size_t progressiveMaximumSpans=32;
struct ProgressiveCallbackRecord {
    MacCallbackRecord callback;
    std::uint64_t renderEpoch=0,speedRequestID=0,routeChanges=0;
    std::uint32_t machNumer=1,machDenom=1,previousFrames=0;
    double sourceRate=0,deviceRate=0;
    std::array<ProgressiveOutputSpan,progressiveMaximumSpans> spans{};
    std::size_t spanCount=0,oldMissingFrames=0,newMissingFrames=0;
    std::size_t outputAffectedFrames=0,failurePaddingFrames=0,pauseSilenceFrames=0;
    prototype::Phase46HostClock::Evidence clock;
};
enum class ProgressiveControlTestPoint {SeekPreparationStarted,SwitchStartedOrDone,RetiringOld,RetiringPreparation,RestartWait,SeekCleanupWait,SeekCleanupComplete,RestartLaunch,AcquiringResources,PauseObserved,SwitchPublished,SpeedReplacementDecision,LoopJobDispatch,NextPreparationDeadline,PartialMixReplaceDecision,PartialMixClearDecision,PartialMixStopDecision,ClearCancellationDecision,LoopJobSelected,InputPreparationJoinWait,ReadyBeforeConfigure};
// Explicit normal-thread tests only; empty in ordinary apps. Hooks must not call
// engine APIs. Replacement/clear/partial-mix decisions and SeekCleanupComplete
// hold the engine mutex and must not wait for callers of engine APIs. Worker
// gates, including LoopJobSelected, run outside it. Never called by the callback.
struct ProgressiveControlTestHooks {
    void* context=nullptr;
    void(*event)(void*,ProgressiveControlTestPoint)noexcept=nullptr;
};
// Normal destructor thread only, after all joins/retirement. The sink must own
// copied values, outlive the engine, and never call back into the engine.
struct FinalLoopSpeedAudit {
    std::span<const progressive::LoopSpeedOperation> operations;
    std::uint64_t sequence=0;
    bool workersJoined=false,retirementComplete=false;
};
struct FinalOperationAudit;
struct EpochOperationAudit;
struct ProgressiveOptions {
    // Concrete product configuration. Pending methods remain disabled; research
    // access needs an explicit per-method Research policy. App F acceptance is
    // separate from the engine's compiled per-method approval table.
    static ProgressiveOptions macOSProduct(){ProgressiveOptions o;o.featurePolicy=progressive::FeaturePolicyOptions{};return o;}
    Preset preset=Preset::Candidate;
    double initialSpeed=1.00;
    std::uint64_t memoryReservationBudget=1024ULL*1024*1024;
    std::chrono::milliseconds prepareTimeout{120000};
    std::size_t callbackRecordLimit=0; // opt-in, at most 262144; pre-touched.
    // Optional host-owned raw PCM observer, before fixed output gain 0.5.
    // Borrowed only during this call. Must be bounded, noexcept, allocation-free,
    // lock-free and I/O-free. No library verification PCM or global new hooks.
    void* observerContext=nullptr;
    void(*observeRawPcm)(void*,const float*const*,std::size_t frames,std::size_t outputOffset)noexcept=nullptr;
    // Phase61 observer uses the same callback restrictions and explicit identity.
    void(*observeEpochPcm)(void*,const float*const*,std::size_t frames,std::size_t outputOffset,
        std::uint64_t inputGeneration,std::uint64_t renderEpoch,std::uint64_t session)noexcept=nullptr;
    RenderAllocationHooks allocationHooks{}; // explicit verification host only
    bool allowExperimentalLoops=false; // legacy explicit research opt-in
    // Explicit v3 settings override legacy booleans. Same resolved value controls
    // reservation, owner budgets, finite observations, admission and diagnostics.
    std::optional<progressive::FeaturePolicyOptions> featurePolicy;
    bool seekCheckpoints=true;
    bool measureControlCosts=false; // disabled in ordinary apps; normal-thread counters
    // 内部DSP hash。OFFでmonoの全体CPU増加を実測したため既存ONを維持する。
    // 詳細profileとは独立し、入力SHAと最終PCM照合も省略しない。
    bool recordStageDigests=true;
    // Research opt-in only: long impulse-train quality is NOT approved.
    bool allowUnvalidatedFastLocalSeek=false;
    // Post-mix output is NOT one epoch's raw suffix. Called before gain 0.5.
    // first mixedFrames use both epochs; remaining frames use newEpoch alone.
    // Same callback restrictions as observeEpochPcm. Optional bounded observer.
    void(*observeOutputPcm)(void*,const float*const*,const ProgressiveOutputSpan&)noexcept=nullptr;
    unsigned seekFailureForTest=0; // explicit verification only: 1 before promotion, 2 before publication
    std::size_t loopSupplyFramesForTest=0; // explicit worker supply ceiling; no callback test gate
    std::size_t loopSpeedOperationLimitForTest=4096,stoppedSpeedOperationLimitForTest=4096; // admission only; may reduce, never raise
    prototype::phase58::LifecycleTestHooks pipelineLifecycleTestHooks{};
    ProgressiveControlTestHooks controlTestHooks{};
    prototype::phase58::ControlTestHooks pipelineControlTestHooks{};
    void* finalLoopSpeedAuditContext=nullptr;
    bool(*receiveFinalLoopSpeedAudit)(void*,const FinalLoopSpeedAudit&)noexcept=nullptr;
    void* finalOperationAuditContext=nullptr;
    bool(*receiveFinalOperationAudit)(void*,const FinalOperationAudit&)noexcept=nullptr;
    // Normal thread only, after this owner joins and releases callback refs.
    // Must copy before returning; no engine re-entry. false is audited.
    void* finalEpochAuditContext=nullptr;
    bool(*receiveFinalEpochAudit)(void*,const EpochOperationAudit&)noexcept=nullptr;
};
struct ProgressivePosition {
    std::uint64_t session=0,outputFrame=0;
    double outputSeconds=0;
    // A paired control-worker sample, or the exact unconsumed seek target.
    // Never an extrapolated playback position.
    std::optional<std::uint64_t> inputFrame,sampledOutputFrame;
    std::optional<double> inputSeconds;
    std::uint64_t inputGeneration=0,renderEpoch=0;
};
// Separate from Phase59 Completed (which requires actual audio consumption).
// IDs use the high bit and remain stable across session/render epoch switches.
enum class StoppedSpeedState {Preparing,ReadyForResume,Replaced,Cancelled,Failed};
inline const char* name(StoppedSpeedState state)noexcept {
    switch(state){
    case StoppedSpeedState::Preparing:return "Preparing";
    case StoppedSpeedState::ReadyForResume:return "ReadyForResume";
    case StoppedSpeedState::Replaced:return "Replaced";
    case StoppedSpeedState::Cancelled:return "Cancelled";
    case StoppedSpeedState::Failed:return "Failed";
    }return "Failed";
}
struct StoppedSpeedOperation {
    std::uint64_t id=0,inputGeneration=0,sourceSession=0,sourceRenderEpoch=0;
    std::uint64_t mapVersion=0,consumedOutputFrame=0,resumeInputFrame=0;
    std::uint64_t session=0,renderEpoch=0,outputStartFrame=0;
    std::uint64_t acceptedNs=0,readyNs=0;
    std::uint64_t loopID=0,cycle=0,preparationVersion=0,discardedForStoppedSpeedFrames=0;
    std::uint32_t speedMicros=1000000;
    StoppedSpeedState state=StoppedSpeedState::Preparing;
    bool positionCaptured=false,outputStarted=false;
    progressive::SeekMode mode=progressive::SeekMode::Exact;
    std::string reason;
};
// Borrowed only for this normal destructor-thread call, after ALL joins.
// Copy before returning; retain app engine/prepare UUIDs beside engineSerial.
// Ordinary speed history is delivered by receiveFinalEpochAudit before the
// bounded closed-history view is trimmed. Keep external UUIDs beside both.
struct FinalOperationAudit {
    std::uint64_t engineSerial=0,preparation=0;
    std::span<const progressive::SeekOperation> seeks;
    std::span<const StoppedSpeedOperation> stoppedSpeeds;
    std::span<const progressive::LoopSpeedOperation> loopSpeeds;
    std::span<const progressive::LoopPreparationOperation> loopPreparations;
    bool workersJoined=false,retirementComplete=false;
    std::uint64_t epochAuditCalls=0,epochAuditRejected=0;
    bool epochAuditConfigured=false;
};
struct EpochOperationAudit {
    std::uint64_t engineSerial=0,preparation=0,sequence=0,renderEpoch=0,session=0,inputGeneration=0;
    std::span<const prototype::phase59::SpeedOperation> ordinarySpeeds;
    bool preparedOnly=false,workersJoined=false,callbackReleased=false;
};
struct ProgressiveStateSnapshot {
    progressive::AvailabilityReason failureCode=progressive::AvailabilityReason::Available;
    progressive::State state=progressive::State::Empty;
    StopReason reason=StopReason::None;
    std::uint64_t preparation=0,session=0,inputGeneration=0;
    double requestedSpeed=1,appliedTargetSpeed=1;
    std::optional<prototype::phase59::SpeedOperation> pending,active,lastResult;
    std::string error;
    std::uint64_t renderEpoch=0;
    std::optional<StoppedSpeedOperation> stoppedSpeed;
    bool resumePending=false; // accepted intent; Playing means output actually started
};
struct ProgressiveDiagnostics {
    unsigned contractVersion=progressive::contractVersion;
    std::uint64_t engineSerial=0;
    bool epochAuditConfigured=false;
    std::uint64_t epochAuditCalls=0,epochAuditRejected=0;
    progressive::EffectiveFeatures features;
    bool controlCostsMeasured=false;
    ControlCostValue monitorCost,syncLoopSpeedCost;
    std::uint64_t seekDispatchWakes=0;
    std::uint64_t seekTimingVisits=0,seekTimingLatches=0; // engine寿命、履歴全走査なし
    std::string engineKind="Experimental Progressive Phase61",timeStretchLabSha;
    std::uint64_t preparation=0,session=0,inputGeneration=0;
    std::uint64_t generatedFrames=0,publishedFrames=0,consumedFrames=0,presentedFrames=0;
    // presentedFrames is the input-lifetime requested count (v1 semantics).
    // This field is the current render epoch's absolute logical coordinate.
    std::uint64_t currentEpochPresentedFrame=0;
    std::uint64_t missingFrames=0,underrunCalls=0,maxConsecutiveMissingFrames=0,rejectedWrites=0;
    std::uint32_t sourceSampleRate=0;
    std::size_t channels=0,inputFrames=0,residentInputBytes=0,temporarySourceBytes=0,reservationBytes=0;
    double requestedSpeed=1,appliedTargetSpeed=1,processCpuS=0;
    std::optional<double> dspWorkerCpuS; // final after worker join
    std::uint64_t rssBytes=0,peakRssBytes=0;
    double acceptedToReadyS=-1,constructorS=-1;
    prototype::phase58::Diagnostics pipeline;
    bool fifoSupplyFailed=false;
    // Unmeasured is null, never a fabricated zero or PASS.
    std::optional<bool> pcmCorrect,overallAudioQuality;
    std::optional<std::uint64_t> callbackCppNew,osPageFaults;
    std::string error;
    std::uint64_t renderEpoch=0;
    std::uint64_t workerDeadlineMisses=0,workerNewCalls=0,workgroupErrors=0;
    // Normal-thread snapshot with the same finalDataAvailable rule as pipeline.
    // Present while an old epoch is retained during join/post-processing.
    std::optional<prototype::phase58::Diagnostics> retiringPipeline;
    std::uint64_t archivedEpochCount=0,archivedPreparedEpochCount=0; // input lifetime, not the history limit
};
struct ProgressiveNativeDiagnostics : MacDiagnostics {
    std::uint64_t invalidSampleTimeCalls=0,invalidRateScalarCalls=0;
};
struct ProgressiveClosedEpoch {
    std::uint64_t renderEpoch=0;
    prototype::phase58::Diagnostics pipeline;
    std::vector<prototype::phase59::SpeedOperation> operations;
    std::size_t droppedOperations=0;
    bool preparedOnly=false; // cancelled/failed preparation; epoch=0 if never assigned
};
struct LoopSpeedPcmEvidence {
    progressive::LoopSpeedOperation operation;
    prototype::phase58::LoopTransitionSnapshot commit;
    TimeMap map; // product evidence, independently re-planned by the validation host
};
// Create, operate, query, stop and destroy on one serial application work queue.
// prepare is Accepted, not Ready. Poll state/snapshot on that queue.
// play after Stopped/Ended starts a fresh async preparation and auto-plays only
// after Ready + successful Workgroup promotion. Return true is acceptance.
// No public method may be called by an audio render callback or a main UI thread.
class ProgressiveMacPlaybackEngine {
public:
    ProgressiveMacPlaybackEngine();
    ~ProgressiveMacPlaybackEngine();
    ProgressiveMacPlaybackEngine(const ProgressiveMacPlaybackEngine&)=delete;
    ProgressiveMacPlaybackEngine& operator=(const ProgressiveMacPlaybackEngine&)=delete;
    static progressive::Capabilities capabilities() noexcept {return {};}
    progressive::SeekAvailability seekAvailability()const;
    progressive::LoopAvailability loopAvailability()const;
    // A/B confirmed, no position change. At most one preparation; explicit
    // user operations preempt it. Ready is visible only after owner retirement.
    progressive::LoopReceipt requestLoopPreparation(std::uint64_t a,std::uint64_t b,progressive::LoopContext);
    void cancelLoopPreparation();
    progressive::LoopPreparationSnapshot loopPreparationSnapshot()const;
    progressive::HistoryUsage historyUsage()const;
    std::vector<progressive::LoopPreparationOperation> loopPreparationHistory()const;
    progressive::LoopReceipt requestLoopRange(std::uint64_t startFrame,std::uint64_t endFrameExclusive,progressive::LoopContext,progressive::LoopOptions={});
    // Clear matches loopID + input/session; epoch may have advanced automatically.
    progressive::LoopReceipt requestClearLoop(std::uint64_t loopID,progressive::LoopContext);
    progressive::LoopSpeedReceipt requestLoopSpeed(double,progressive::LoopContext); // explicit busy/stale reasons
    progressive::LoopSnapshot getLoopSnapshot()const;
    std::vector<progressive::LoopBoundaryEvent> loopHistory()const; // last 64; cycles unbounded
    std::vector<progressive::LoopSpeedOperation> loopSpeedHistory()const; // engine lifetime, at most 4096 Accepted IDs
    std::optional<progressive::LoopSpeedOperation> loopSpeedOperation(std::uint64_t id)const;
    std::optional<LoopSpeedPcmEvidence> loopSpeedPcmEvidence(std::uint64_t id)const; // while current/retiring owner is retained; null is not PASS
    bool prepare(const std::filesystem::path&,ProgressiveOptions={},progressive::ContractV4Tag={});
    // play/resume true means accepted. During stopped preparation output starts
    // asynchronously only after the latest epoch is committed. pause also cancels
    // an accepted resume while still Ready/Paused. Poll state + resumePending.
    bool play();bool pause();bool resume();void stop();
    prototype::phase59::RequestReceipt setSpeed(double,std::uint64_t expectedSession=0,std::uint64_t expectedInputGeneration=0,std::uint64_t expectedRenderEpoch=0);
    progressive::SeekReceipt requestSeekToInputFrame(std::uint64_t,std::uint64_t expectedInputGeneration=0,std::uint64_t expectedRenderEpoch=0);
    progressive::SeekReceipt requestSeekToInputSeconds(double,std::uint64_t expectedInputGeneration=0,std::uint64_t expectedRenderEpoch=0);
    // Explicit experimental local phase origin. Exact APIs above are unchanged.
    // Interactive output transition. Default 500ms; legacy research 1000/2000ms
    // arguments remain accepted. The session-aware API below always uses 500ms.
    progressive::SeekReceipt requestFastLocalSeekToInputFrame(std::uint64_t,std::uint64_t expectedInputGeneration=0,std::uint64_t expectedRenderEpoch=0,std::uint32_t prerollMillis=500);
    progressive::SeekReceipt requestFastLocalSeekToInputSeconds(double,std::uint64_t expectedInputGeneration=0,std::uint64_t expectedRenderEpoch=0,std::uint32_t prerollMillis=500);
    // Session-aware development API. All three identities are required/nonzero.
    progressive::SeekReceipt requestInteractiveSeekToInputFrame(std::uint64_t,std::uint64_t inputGeneration,std::uint64_t renderEpoch,std::uint64_t session);
    progressive::SeekReceipt requestInteractiveSeekToInputSeconds(double,std::uint64_t inputGeneration,std::uint64_t renderEpoch,std::uint64_t session);
    progressive::SeekSnapshot getSeekSnapshot()const;
    std::vector<progressive::SeekOperation> seekHistory()const;
    std::vector<ProgressiveClosedEpoch> closedEpochs()const;
    // v1 compatibility: static seek=true requires BOTH Exact and Interactive approval.
    // v2 clients use requestSeek* and distinguish acceptance from completion.
    bool seekToInputSeconds(double) noexcept;
    progressive::State getPlaybackState()const noexcept;
    ProgressiveStateSnapshot getStateSnapshot()const;
    ProgressivePosition getCurrentPlaybackPosition()const;
    ProgressiveDiagnostics getPlaybackDiagnostics()const;
    ProgressiveNativeDiagnostics getNativeDiagnostics()const;
    std::vector<MacCallbackRecord> callbackRecords()const; // only after quiescence
    std::vector<ProgressiveCallbackRecord> loopClockAnomalyRecords()const; // first anomaly: 16 before, 16 after
    std::vector<ProgressiveCallbackRecord> loopCallbackRecords()const; // last 256 callbacks, including all bounded spans
    std::vector<StoppedSpeedOperation> stoppedSpeedHistory()const; // engine lifetime, bounded 4096
    std::vector<prototype::phase59::SpeedOperation> operationHistory()const;
    TimeMap finalTimeMap()const; // stopped/ended, valid completed analysis only
    void simulateDeviceChangeForTest(); // follows the same safe-stop path
private:
    prototype::phase59::RequestReceipt setSpeedImpl(double,std::uint64_t,std::uint64_t,std::uint64_t,std::string*,progressive::LoopSpeedReceiptCode* =nullptr);
    progressive::SeekReceipt requestSeekFrame(std::uint64_t,std::uint64_t,std::uint64_t,progressive::SeekMode,std::uint32_t,std::uint64_t expectedSession=0);
    progressive::SeekReceipt requestSeekSeconds(double,std::uint64_t,std::uint64_t,progressive::SeekMode,std::uint32_t,std::uint64_t expectedSession=0);
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
