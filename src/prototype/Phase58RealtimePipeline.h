#pragma once
#include "prototype/Phase57ProgressiveSynthesis.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include "prototype/Phase58FixRealtimeWorker.h"
#include "prototype/Phase59Control.h"
#include <string>

namespace ts::prototype::phase58 {
enum class WorkerScheduling {Standard,AudioWorkgroup};
enum class LifecycleState {Unstarted,Starting,Running,Stopping,Finalized};
enum class LifecycleTestPoint {WorkerExit,BeforeJoin,Joining,JoinedBeforeFinalize,BeforeFinalPublish};
// Explicit normal-thread verification only. Never called by pullAudio or while
// holding the pipeline data mutex; WorkerExit runs after DSP policy restoration.
// The host must keep context alive through stop/destruction. Empty in apps.
struct LifecycleTestHooks {
    void* context=nullptr;
    void(*event)(void*,LifecycleTestPoint,std::uint64_t session)noexcept=nullptr;
    unsigned failStartBeforeWorker=0; // 1 analysis, 2 DSP, 3 sampler, 0 disabled
};
struct Configuration {
    std::uint32_t speedMicros=500000;
    bool candidate=true,verifyPcm=true,recordWorkerProfile=false;
    bool detailedDiagnostics=false;
    bool sampleDspThread=false;
    bool residentInput=false;
    bool dynamicTransitions=false; // Phase59 explicit research opt-in only.
    WorkerScheduling scheduling=WorkerScheduling::Standard;
    std::size_t diagnosticEventLimit=262144;
    std::size_t analysisChunk=32768;
    std::size_t sourceSnapshotBytes=512ULL*1024*1024;
    // Deterministic fault/stall controls, never implicit environment variables.
    double analysisDelayMs=0,dspDelayMs=0;
    std::atomic<bool>* holdDspAfterReadyForTest=nullptr; // normal-policy deterministic supply test only
    std::size_t publicationLimitForTest=0;
    unsigned transitionFailureForTest=0; // 0 none, 1 processing, 2 allocation.
    unsigned promotionFailureOnAttemptForTest=0; // Explicit pre-promotion fault, max 2.
    std::array<std::pair<std::size_t,std::size_t>,4> phaseProbeWindows{};
    std::size_t phaseProbeWindowCount=0; // Detailed phase substages, at most 4 windows.
    bool seekCheckpoints=true; // Phase61, exact resident fixed-state cache, max 2.
    bool fastLocalSeek=false; // Explicit factory only; Exact remains the default.
    std::size_t localPrerollInputFrames=0;
    std::size_t loopEndInputFrame=0; // Phase62 bounded exact epoch; 0 disables.
    bool reusableLoop=false;
    std::size_t loopBeginInputFrame=0;
    bool localPublicationFade=true; // Legacy experiment; Interactive mixes at output.
    LifecycleTestHooks lifecycleTestHooks{};
};
struct RenderResult {std::size_t wanted=0,received=0,outputBefore=0,fifoBefore=0;};
struct FifoCursors {std::uint64_t read=0,write=0;};
struct ExecutionOwnerCounts {std::uint64_t alive=0,peak=0;};
struct PositionSample {std::uint64_t session=0,mapVersion=0;std::size_t output=0,input=0;double atS=0;};
struct LoopPcmDescriptor {std::uint64_t cycle=0;std::array<float,2> first{},last{};};
enum class LoopTransitionState {Idle,Requested,Applying,Committed,Cancelled,Rejected};
struct LoopTransitionSnapshot {
    LoopTransitionState state=LoopTransitionState::Idle;
    std::uint64_t cycle=0,mapVersion=0,operationID=0;
    std::size_t localStart=0,localEnd=0,cumulativeStart=0,cumulativeEnd=0,generatedAtCommit=0,publishedAtCommit=0;
};
struct LoopReuseDiagnostics {
    bool enabled=false;
    std::uint64_t cyclesPrepared=0,seedRestores=0,cacheReadFrames=0,coldDiscardedFrames=0,warmDiscardedFrames=0;
    std::size_t cacheBytes=0,seedOutput=0,mapBuilds=0,workerCreations=0;
    std::uint64_t fftPlanCreations=0,warmFftPlanCreations=0,seedClones=0;
    double mapS=0,dspConstructS=0,coldPrefixS=0,coldCpuS=0,warmCpuS=0,seedCloneS=0,restoreS=0;
    double analysisWaitS=0,mapCpuS=0,coldPrefixCpuS=0,joinS=0;
};
struct Diagnostics {
    std::uint64_t session=0,analysisThread=0,dspThread=0,snapshotVersion=0;
    std::size_t inputFrames=0,receivedInput=0,generated=0,published=0,consumed=0,outputFrames=0;
    std::size_t inputAtFirstPcm=0,inputAtReady=0,nonEosPublished=0;
    std::size_t sourceSnapshotBytes=0;
    std::size_t residentInputBytes=0,borrowedSnapshotOwners=0;
    bool dynamicTransitions=false;
    std::size_t transitionOperations=0,transitionMapOwners=0,transitionHistory=0,transitionMapPeakBytes=0;
    std::size_t transitionPlanAttempts=0,transitionStaleReplans=0,transitionAnalysisDeferrals=0;
    double transitionPlanCpuS=0,transitionPlanWallS=0;
    double residentReadyS=-1;
    bool renderingRequested=false;
    bool inputSamplesPrevalidated=false;
    RealtimeWorkerMetrics scheduling;
    std::uint64_t realtimeNewCalls=0;
    bool realtimeAllocationsMeasured=false;
    std::size_t fifoHighWater=0,snapshotPeakBytes=0,snapshotCopyBytes=0;
    std::uint64_t missingFrames=0,missingCalls=0,maxConsecutiveMissing=0,rejectedWrites=0,analysisWaits=0;
    double verifiedS=-1,identifiedS=-1,analysisStartS=-1,firstEventS=-1,firstMapS=-1;
    double firstGeneratedS=-1,firstPublishedS=-1,readyS=-1,analysisDoneS=-1;
    double analysisCpuS=0,dspCpuS=0,maxDspWallS=0,analysisWaitS=0,backpressureWaitS=0;
    double dspWorkerCpuS=0,maxDspCpuS=0,maxPublicationGapS=0;
    double maxDspValidationWallS=0,maxDspValidationCpuS=0;
    double analysisWorkerCpuS=0;
    std::size_t workerProfileRecords=0,workerProfileDropped=0;
    std::size_t detailRecords=0,detailDropped=0;
    std::uint64_t dspNewCalls=0;
    bool dspAllocationsMeasured=false;
    unsigned analysisQosClass=0,dspQosClass=0;
    int analysisQosRelativePriority=0,dspQosRelativePriority=0;
    bool analysisQosQueried=false,dspQosQueried=false;
    std::size_t threadSamples=0,threadSamplesDropped=0,threadSampleErrors=0;
    bool threadSamplingRequested=false;
    double samplerCpuS=0;
    bool analysisQos=false,dspQos=false,analysisDone=false,dspDone=false,cancelled=false,failed=false;
    std::string inputSha256,pcmSha256,error;
    // Phase61: an input lease survives render epochs. Positions are absolute
    // output coordinates; generated includes the exact discarded prefix.
    std::uint64_t inputGeneration=0;
    std::size_t outputStartFrame=0,discardedFrames=0;
    bool reusedInput=false,reusedAnalysis=false;
    std::size_t sourceHashPasses=0,sourceSnapshotCreations=0,residentLockCalls=0;
    bool checkpointUsed=false;
    std::size_t checkpointStartFrame=0,checkpointResidentStates=0,checkpointBuilds=0;
    bool fastLocalSeek=false;
    std::size_t localSeedInput=0,localBeginOutput=0,localPrerollInputFrames=0;
    double localInitializeS=0;
    LifecycleState lifecycle=LifecycleState::Unstarted;
    // Acquired only after ALL joins AND finalizeTransition/cancelOperations.
    // Until true, mailbox owner/vector record counts are unmeasured placeholders,
    // not measured zeros. Other fields use atomics, immutable data or data locks.
    bool finalDataAvailable=false;
    LoopReuseDiagnostics loopReuse;
};
struct WorkerRecord {
    std::size_t outputStart=0,outputEnd=0,fifoBefore=0,fifoAfter=0,receivedInput=0;
    std::uint64_t snapshotVersion=0;bool finalSnapshot=false;
    double startedS=0,publishedS=0,wallS=0,cpuS=0,publicationGapS=0;
    Phase36StreamingSpeedEngine::WorkProfile work{};
    bool realtime=false;
    std::uint64_t dynamicMapVersion=0;
    RealtimeIntervalTiming intervalTiming{};
};
struct DetailEvent {
    std::size_t stage=0,scope=0;bool begin=false;
    double atS=0,cpuS=0;
    std::uint64_t newCalls=0;
};
struct ThreadSample {
    double beforeS=0,afterS=0;
    std::uint64_t stageBefore=0,stageAfter=0,userNs=0,systemNs=0;
    int result=0,state=-1,policy=-1,currentPriority=-1,basePriority=-1,maxPriority=-1;
};
// Independent fixed-speed experimental path. No product API or default route.
// One serialized normal owner performs start/stop/destruction (including failure
// cleanup); these must not overlap. Diagnostic snapshots may run concurrently
// with that owner's start/stop, with object lifetime retained by the caller.
// Export copies require finalDataAvailable; EOS/dspDone alone is insufficient.
// One control producer and one audio consumer. Only pullAudio is callback-safe.
class RealtimePipeline {
    struct Impl;std::unique_ptr<Impl> impl_;
public:
    RealtimePipeline(const std::filesystem::path&,Configuration={});
    ~RealtimePipeline();
    // Counts whole pipeline lifetimes, including unstarted preparations and
    // joined owners awaiting destruction. Immutable DSP save areas do not run.
    static ExecutionOwnerCounts executionOwnerCounts()noexcept;
    void start();
    void setPublicationLimitForTest(std::size_t); // before start; Standard worker only
    bool waitUntilReady(std::chrono::milliseconds);
    // Normal owner only. Arm before starting output; disarm after quiescence.
    bool setRealtimeRendering(bool,std::chrono::milliseconds timeout=std::chrono::seconds(1));
    void stop(); // Consumer must be quiescent before stop/destruction.
    RenderResult pullAudio(float*const*,std::size_t)noexcept;
    bool peekAudioFrame(std::size_t offset,std::array<float,2>&)const noexcept; // same audio consumer, no cursor advance
    FifoCursors diagnosticFifoCursors()const noexcept; // Separate atomic loads, diagnostic use only.
    std::optional<PositionSample> positionSample()const noexcept; // Paired normal-worker sample.
    // Normal owner, after callback quiescence and rendering disarm. No wait.
    // Null until the analysis owner has acknowledged the DSP committed map.
    // Unconsumed seeks retain the exact requested input frame (no round trip).
    std::optional<PositionSample> stoppedPosition()const;
    bool finished()const noexcept;
    bool drained()const noexcept;
    bool failed()const noexcept;
    phase59::RequestReceipt requestSpeed(std::uint32_t targetMicros,std::size_t logicalPresented,
        std::uint64_t expectedSession=0,std::uint64_t expectedInputGeneration=0);
    std::vector<phase59::SpeedOperation> speedOperations()const; // Normal control thread only.
    TimeMap dynamicTimeMap()const; // Joined workers only, normal diagnostic copy.
    std::size_t available()const noexcept;
    std::uint32_t sampleRate()const noexcept;
    std::size_t channels()const noexcept;
    std::size_t inputFrames()const noexcept;
    // Normal owner only. Shares protected bytes/FD and immutable analysis;
    // creates only fresh DSP/FIFO/transition state. Caller starts the result.
    std::unique_ptr<RealtimePipeline> createSeek(std::size_t inputFrame,std::uint32_t speedMicros)const;
    std::unique_ptr<RealtimePipeline> createFastLocalSeek(std::size_t inputFrame,std::uint32_t speedMicros,std::size_t prerollInputFrames=0)const;
    std::unique_ptr<RealtimePipeline> createInteractiveSeek(std::size_t inputFrame,std::uint32_t speedMicros,std::size_t prerollInputFrames=0)const;
    // Phase62: exact DSP, finite FIFO, shared input/analysis; no whole-song PCM cache.
    std::unique_ptr<RealtimePipeline> createLoopSeek(std::size_t start,std::size_t end,std::uint32_t speed)const;
    void enableLoopReuse(std::size_t rangeStartInputFrame); // before start; same immutable program only
    void setLoopSupplyLimitForTest(std::size_t frames); // before start; finite producer ceiling >= Ready lead
    bool loopReuseEnabled()const noexcept;
    std::size_t loopOutputStartFrame()const noexcept;
    std::uint64_t loopReadCycle()const noexcept;
    // Only after the replacement fixed A->B owner is Ready. The current
    // producer retains its complete DSP and pending PCM at the frontier.
    // This owner ends at the committed dynamic B; caller retains replacement
    // through the boundary once cancellation returns false.
    phase59::RequestReceipt requestLoopTransition(std::uint32_t,std::size_t logicalPresented,std::atomic<std::uint64_t>* callbackOperation=nullptr);
    LoopTransitionSnapshot loopTransition()const noexcept;
    bool cancelLoopTransition()noexcept;
    std::optional<LoopPcmDescriptor> loopPcmDescriptor(std::uint64_t cycle)noexcept; // audio consumer only
    std::array<float,2> loopFirstSample()const noexcept; // immutable after Ready; no ownership operation
    std::size_t loopOutputEndFrame()const noexcept; // valid after Ready
    std::size_t fixedOutputFrameForInput(std::size_t)const; // final analysis; rejects dynamic plans
    bool finalAnalysisAvailable()const noexcept;
    // Normal owner only. Fade on DSP publication, then wait for its absolute
    // end to be consumed. Cancelling restores gain through another 5ms ramp.
    void requestRetireFade(bool);
    bool retireFadeDrained()const noexcept;
    std::size_t outputStartFrame()const noexcept;
    std::uint64_t inputGeneration()const noexcept;
    double elapsedSeconds()const noexcept;
    Diagnostics diagnostics()const; // Control thread, never callback.
    std::vector<WorkerRecord> workerRecords()const; // Joined workers only.
    std::vector<DetailEvent> detailEvents()const; // Joined workers only.
    std::vector<ThreadSample> threadSamples()const; // Joined workers only.
private:
    explicit RealtimePipeline(std::unique_ptr<Impl>);
};
}
