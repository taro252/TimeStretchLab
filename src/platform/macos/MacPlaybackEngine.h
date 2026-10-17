#pragma once
#include "playback/PlaybackEngine.h"
#include <memory>
namespace ts::playback {
struct RenderAllocationHooks {void(*enter)()noexcept=nullptr;void(*leave)()noexcept=nullptr;std::uint64_t(*count)()noexcept=nullptr;};
struct MacOptions {float playbackGain=.5f;bool recordCallbacks=false;RenderAllocationHooks allocationHooks{};std::uint32_t seekFadeFrames=64;};
struct MacDiagnostics {
    unsigned deviceId=0,deviceChannels=0,deviceBufferFrames=0;
    double deviceRate=0,devicePresentationLatencyMs=0,sourcePresentationLatencyMs=0;
    std::uint64_t callbackCalls=0,maxCallbackNs=0,deadlineMisses=0,formatErrors=0,callbackRecordsDropped=0;
    std::uint64_t hostMissing=0,hostBackwards=0,hostCadenceErrors=0,sampleErrors=0,halWindowMisses=0;
    std::uint64_t routeChanges=0,callbackCppAllocations=0;
    std::uint64_t bridgeSteadyNs=0,bridgeMachNs=0,bridgeUncertaintyNs=0;
    std::uint64_t lastPcmTargetEndNs=0,outputStoppedMachNs=0;
    bool allocationMeasured=false;
    StageTiming avConstruction,avStart;
    std::uint64_t prepareCalledSteadyNs=0,playCalledSteadyNs=0,firstPcmMachNs=0;
    std::string error;
};
namespace detail {
// Read-only export policy. Lifecycle transitions belong to the adapter monitor.
constexpr bool callbackHistoryReadable(PlaybackState state,bool active,unsigned inRender) noexcept {
    return state!=PlaybackState::Draining && !active && inRender==0;
}
}
struct MacCallbackRecord {
    std::uint64_t sequence=0,epoch=0,startNs=0,endNs=0,ioEndNs=0,hostNs=0;
    double sampleTime=0;
    std::uint32_t timestampFlags=0,requested=0;
    RenderResult raw{};
    std::uint64_t hostTicks=0;
    double rateScalar=0;
};
// All lifecycle calls belong on an application control/work queue, never render.
class MacPlaybackEngine {
public:
    MacPlaybackEngine();~MacPlaybackEngine();
    bool prepare(const std::filesystem::path&,Configuration=Configuration::candidate(),MacOptions={});
    bool play();bool pause();bool resume();void stop();
    std::uint64_t setSpeed(double speed);
    std::uint64_t seekToInputSeconds(double seconds);std::uint64_t seekToInputFrame(std::uint64_t frame);
    SeekSnapshot getSeekSnapshot()const;std::vector<SeekSnapshot> seekHistory()const;
    std::vector<SegmentEvidence> closedSegmentEvidence()const;
    PlaybackState getPlaybackState() const noexcept;
    double getRequestedSpeed()const;double getAppliedTargetSpeed()const;
    Position getCurrentPlaybackPosition()const;
    std::optional<SpeedOperation> getPendingSpeedChange()const;
    std::optional<SpeedOperation> getActiveSpeedChange()const;
    StateSnapshot getStateSnapshot()const;
    Diagnostics getPlaybackDiagnostics()const;
    MacDiagnostics getNativeDiagnostics()const;
    StartupDiagnostics getStartupDiagnostics()const;
    // Throws logic_error while rendering/draining; never stops audio output.
    std::vector<MacCallbackRecord> callbackRecords()const;
    std::vector<SpeedOperation> operationHistory()const;
    std::vector<prototype::Phase39PlanMetric> plans()const;
    std::vector<prototype::Phase39BlockProfile> workerProfiles()const;
    std::string rawPcmSha()const;
    std::uint32_t sampleRate()const;std::size_t channels()const;
    void simulateDeviceChangeForTest();
private:struct Impl;std::unique_ptr<Impl> impl_;
};
}
