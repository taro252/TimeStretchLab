#pragma once
#include "prototype/Phase57ProgressiveSynthesis.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include <string>

namespace ts::prototype::phase58 {
struct Configuration {
    std::uint32_t speedMicros=500000;
    bool candidate=true,verifyPcm=true,recordWorkerProfile=false;
    std::size_t analysisChunk=32768;
    std::size_t sourceSnapshotBytes=512ULL*1024*1024;
    // Deterministic fault/stall controls, never implicit environment variables.
    double analysisDelayMs=0,dspDelayMs=0;
};
struct RenderResult {std::size_t wanted=0,received=0,outputBefore=0,fifoBefore=0;};
struct Diagnostics {
    std::uint64_t session=0,analysisThread=0,dspThread=0,snapshotVersion=0;
    std::size_t inputFrames=0,receivedInput=0,generated=0,published=0,consumed=0,outputFrames=0;
    std::size_t inputAtFirstPcm=0,inputAtReady=0,nonEosPublished=0;
    std::size_t sourceSnapshotBytes=0;
    std::size_t fifoHighWater=0,snapshotPeakBytes=0,snapshotCopyBytes=0;
    std::uint64_t missingFrames=0,missingCalls=0,maxConsecutiveMissing=0,rejectedWrites=0,analysisWaits=0;
    double verifiedS=-1,identifiedS=-1,analysisStartS=-1,firstEventS=-1,firstMapS=-1;
    double firstGeneratedS=-1,firstPublishedS=-1,readyS=-1,analysisDoneS=-1;
    double analysisCpuS=0,dspCpuS=0,maxDspWallS=0,analysisWaitS=0,backpressureWaitS=0;
    double dspWorkerCpuS=0,maxDspCpuS=0,maxPublicationGapS=0;
    double maxDspValidationWallS=0,maxDspValidationCpuS=0;
    double analysisWorkerCpuS=0;
    std::size_t workerProfileRecords=0,workerProfileDropped=0;
    bool analysisQos=false,dspQos=false,analysisDone=false,dspDone=false,cancelled=false,failed=false;
    std::string inputSha256,pcmSha256,error;
};
struct WorkerRecord {
    std::size_t outputStart=0,outputEnd=0,fifoBefore=0,fifoAfter=0,receivedInput=0;
    std::uint64_t snapshotVersion=0;bool finalSnapshot=false;
    double startedS=0,publishedS=0,wallS=0,cpuS=0,publicationGapS=0;
    Phase36StreamingSpeedEngine::WorkProfile work{};
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
    void stop(); // Consumer must be quiescent before stop/destruction.
    RenderResult pullAudio(float*const*,std::size_t)noexcept;
    bool finished()const noexcept;
    bool drained()const noexcept;
    bool failed()const noexcept;
    std::size_t available()const noexcept;
    std::uint32_t sampleRate()const noexcept;
    std::size_t channels()const noexcept;
    std::size_t inputFrames()const noexcept;
    double elapsedSeconds()const noexcept;
    Diagnostics diagnostics()const; // Control thread, never callback.
    std::vector<WorkerRecord> workerRecords()const; // Joined workers only.
};
}
