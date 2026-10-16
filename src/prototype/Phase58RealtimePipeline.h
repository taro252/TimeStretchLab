#pragma once
#include "prototype/Phase57ProgressiveSynthesis.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include "prototype/Phase58FixRealtimeWorker.h"
#include "prototype/Phase59Control.h"
#include <string>

namespace ts::prototype::phase58 {
enum class WorkerScheduling {Standard,AudioWorkgroup};
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
    unsigned transitionFailureForTest=0; // 0 none, 1 processing, 2 allocation.
    unsigned promotionFailureOnAttemptForTest=0; // Explicit pre-promotion fault, max 2.
    std::array<std::pair<std::size_t,std::size_t>,4> phaseProbeWindows{};
    std::size_t phaseProbeWindowCount=0; // Detailed phase substages, at most 4 windows.
};
struct RenderResult {std::size_t wanted=0,received=0,outputBefore=0,fifoBefore=0;};
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
// One control producer and one audio consumer. Only pullAudio is callback-safe.
class RealtimePipeline {
    struct Impl;std::unique_ptr<Impl> impl_;
public:
    RealtimePipeline(const std::filesystem::path&,Configuration={});
    ~RealtimePipeline();
    void start();
    bool waitUntilReady(std::chrono::milliseconds);
    // Normal owner only. Arm before starting output; disarm after quiescence.
    bool setRealtimeRendering(bool,std::chrono::milliseconds timeout=std::chrono::seconds(1));
    void stop(); // Consumer must be quiescent before stop/destruction.
    RenderResult pullAudio(float*const*,std::size_t)noexcept;
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
    double elapsedSeconds()const noexcept;
    Diagnostics diagnostics()const; // Control thread, never callback.
    std::vector<WorkerRecord> workerRecords()const; // Joined workers only.
    std::vector<DetailEvent> detailEvents()const; // Joined workers only.
    std::vector<ThreadSample> threadSamples()const; // Joined workers only.
};
}
