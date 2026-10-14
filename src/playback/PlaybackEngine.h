#pragma once
#include "prototype/Phase39PlaybackPipeline.h"
#include <deque>
#include <optional>
#include <mutex>
#include <memory>
#include <atomic>
#include <thread>

namespace ts::playback {
enum class Preset { Candidate, Baseline };
enum class PlaybackState { Empty, Preparing, Ready, Playing, Paused, Stopped, Draining, Ended, Failed };
enum class StopReason { None, User, EndOfStream, RouteChanged, WorkerError };
enum class SpeedStatus { Pending, Submitted, Applied, Completed, Replaced, Duplicate, Rejected, Cancelled, Configured };
enum class TimeMapMode { ProtectedC, OutputTimeL2 };
struct DspOptions {
    TimeMapMode timeMapMode=TimeMapMode::OutputTimeL2;
    bool preciseBoundaryL1=true,safeDensity=true,inheritedQos=true;
    std::size_t fifoFrames=16384,leadFrames=16384,blockFrames=2048;
};
struct Configuration {
    Preset preset=Preset::Candidate;
    double initialSpeed=.50;
    bool detailedDiagnostics=false,verifyRawPcm=false;
    // Explicit verification hooks, disabled in ordinary application use.
    prototype::Phase52WorkerOptions verificationHooks{};
    static Configuration candidate(double speed=.50){Configuration c;c.initialSpeed=speed;return c;}
    static Configuration baseline(double speed=.50){auto c=candidate(speed);c.preset=Preset::Baseline;return c;}
    std::size_t fifoFrames() const{return 16384;}
    std::size_t leadFrames() const{return preset==Preset::Candidate?16384:12288;}
    std::size_t blockFrames() const{return 2048;}
    DspOptions dspOptions() const{return {preset==Preset::Candidate?TimeMapMode::OutputTimeL2:TimeMapMode::ProtectedC,
        preset==Preset::Candidate,true,true,fifoFrames(),leadFrames(),blockFrames()};}
};
struct SpeedOperation {
    std::uint64_t id=0,session=0,generation=0,observedNs=0,sentNs=0,completedNs=0;
    double target=0;
    SpeedStatus status=SpeedStatus::Pending;
    prototype::Phase39Outcome outcome=prototype::Phase39Outcome::Applied;
    std::size_t applyOutput=0,completeOutput=0;
};
struct Position {std::uint64_t outputFrame=0,inputFrame=0;double inputSeconds=0,outputSeconds=0;};
struct StateSnapshot {
    PlaybackState state=PlaybackState::Empty;
    StopReason reason=StopReason::None;
    std::uint64_t session=0,missingFrames=0;
    double requestedSpeed=0,appliedTargetSpeed=0;
    std::optional<SpeedOperation> pending,active,lastResult;
};
struct Diagnostics {
    std::uint64_t session=0,renderCalls=0,producedFrames=0,consumedFrames=0,presentedFrames=0,missingFrames=0,underrunCalls=0;
    std::uint64_t maxContinuousMissingFrames=0,firstUnderrunNs=0,lastUnderrunNs=0,eventOverwrites=0,concurrentRenders=0;
    std::size_t fifoAvailable=0,fifoHighWater=0,outputLength=0;
    std::uint64_t rejectedWrites=0,operationHistoryDrops=0;
    double maxWorkerWallSeconds=0,maxWorkerCpuSeconds=0;
    StopReason reason=StopReason::None;
    std::string error;
};
struct UnderrunEvent {std::uint64_t timestampNs=0,outputFrame=0,requested=0,received=0,available=0,generation=0;};
struct RenderResult {std::size_t received=0,wanted=0,fifoBefore=0;std::uint64_t outputBefore=0,generation=0,lastPublicationNs=0;};

// Control APIs may lock, allocate, read files and wait: use an app work queue.
// Only renderAudio() may be called from an audio render callback.
// One planar-float consumer, arbitrary block sizes. No Apple audio API here.
class PlaybackEngine {
public:
    PlaybackEngine();
    ~PlaybackEngine();
    PlaybackEngine(const PlaybackEngine&)=delete;
    bool prepare(const std::filesystem::path& input,Configuration config=Configuration::candidate());
    bool play(); bool pause(); bool resume(); void stop(StopReason reason=StopReason::User);
    std::uint64_t setSpeed(double speed);
    PlaybackState getPlaybackState() const noexcept{return state_.load();}
    double getRequestedSpeed() const noexcept{return requested_.load()/1000000.;}
    double getAppliedTargetSpeed() const noexcept{return applied_.load()/1000000.;}
    std::optional<SpeedOperation> getPendingSpeedChange() const;
    std::optional<SpeedOperation> getActiveSpeedChange() const;
    Position getCurrentPlaybackPosition() const;
    Diagnostics getPlaybackDiagnostics() const;
    std::vector<SpeedOperation> operationHistory() const;
    std::vector<UnderrunEvent> underrunEvents() const; // Paused/stopped/ended only.
    std::vector<prototype::Phase39PlanMetric> plans() const; // Worker finished/joined only.
    std::vector<prototype::Phase39BlockProfile> workerProfiles() const;
    std::string rawPcmSha() const;
    std::uint32_t sampleRate() const noexcept{return rate_.load();}
    std::size_t channels() const noexcept{return channels_.load();}
    Configuration configuration() const;
    StateSnapshot getStateSnapshot() const;
    RenderResult renderAudio(float* const* output,std::size_t frames,std::uint64_t timestampNs) noexcept;
private:
    void inhibitRender();void prepareLocked();void tick();void record(const SpeedOperation&);
    void cancelCommands();void failLocked(const std::string&);
    mutable std::mutex mutex_;
    std::filesystem::path input_;Configuration config_;
    std::unique_ptr<prototype::Phase39PlaybackPipeline> pipeline_;
    std::atomic<prototype::Phase39PlaybackPipeline*> renderPipeline_{nullptr};
    std::atomic<bool> renderEnabled_{false},exitControl_{false};
    std::atomic<unsigned> inRender_{0};std::atomic_flag renderBusy_=ATOMIC_FLAG_INIT;
    std::thread control_;
    std::atomic<PlaybackState> state_{PlaybackState::Empty};
    std::atomic<std::uint32_t> requested_{500000},applied_{500000},rate_{0};
    std::atomic<std::size_t> channels_{0};
    std::optional<SpeedOperation> pending_,active_;
    std::deque<SpeedOperation> history_;
    std::uint64_t nextOperation_=0,session_=0,historyDrops_=0;
    StopReason reason_=StopReason::None;std::string error_;
    std::atomic<std::uint64_t> calls_{0},consumed_{0},presented_{0},missing_{0},underruns_{0},continuous_{0},maxContinuous_{0};
    std::atomic<std::uint64_t> firstMissing_{0},lastMissing_{0},eventSequence_{0},concurrent_{0};
    std::array<UnderrunEvent,2048> events_{};
};
const char* name(PlaybackState);const char* name(SpeedStatus);const char* name(StopReason);
}
