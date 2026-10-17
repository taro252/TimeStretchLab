#pragma once
#include "playback/ProgressiveContract.h"
#include "platform/macos/MacPlaybackEngine.h"
#include "prototype/Phase58RealtimePipeline.h"

namespace ts::playback {
struct ProgressiveOptions {
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
    bool seekCheckpoints=true;
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
struct ProgressiveStateSnapshot {
    progressive::State state=progressive::State::Empty;
    StopReason reason=StopReason::None;
    std::uint64_t preparation=0,session=0,inputGeneration=0;
    double requestedSpeed=1,appliedTargetSpeed=1;
    std::optional<prototype::phase59::SpeedOperation> pending,active,lastResult;
    std::string error;
    std::uint64_t renderEpoch=0;
};
struct ProgressiveDiagnostics {
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
};
struct ProgressiveNativeDiagnostics : MacDiagnostics {
    std::uint64_t invalidSampleTimeCalls=0,invalidRateScalarCalls=0;
};
struct ProgressiveClosedEpoch {
    std::uint64_t renderEpoch=0;
    prototype::phase58::Diagnostics pipeline;
    std::vector<prototype::phase59::SpeedOperation> operations;
    std::size_t droppedOperations=0;
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
    bool prepare(const std::filesystem::path&,ProgressiveOptions={});
    bool play();bool pause();bool resume();void stop();
    prototype::phase59::RequestReceipt setSpeed(double,std::uint64_t expectedSession=0,std::uint64_t expectedInputGeneration=0,std::uint64_t expectedRenderEpoch=0);
    progressive::SeekReceipt requestSeekToInputFrame(std::uint64_t,std::uint64_t expectedInputGeneration=0,std::uint64_t expectedRenderEpoch=0);
    progressive::SeekReceipt requestSeekToInputSeconds(double,std::uint64_t expectedInputGeneration=0,std::uint64_t expectedRenderEpoch=0);
    progressive::SeekSnapshot getSeekSnapshot()const;
    std::vector<progressive::SeekOperation> seekHistory()const;
    std::vector<ProgressiveClosedEpoch> closedEpochs()const;
    // v1 compatibility: false while the public seek capability gate is closed.
    // v2 clients use requestSeek* and distinguish acceptance from completion.
    bool seekToInputSeconds(double) noexcept;
    progressive::State getPlaybackState()const noexcept;
    ProgressiveStateSnapshot getStateSnapshot()const;
    ProgressivePosition getCurrentPlaybackPosition()const;
    ProgressiveDiagnostics getPlaybackDiagnostics()const;
    ProgressiveNativeDiagnostics getNativeDiagnostics()const;
    std::vector<MacCallbackRecord> callbackRecords()const; // only after quiescence
    std::vector<prototype::phase59::SpeedOperation> operationHistory()const;
    TimeMap finalTimeMap()const; // stopped/ended, valid completed analysis only
    void simulateDeviceChangeForTest(); // follows the same safe-stop path
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
