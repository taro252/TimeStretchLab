#pragma once
#include "prototype/Phase39PlaybackPipeline.h"
#include "playback/PlaybackAnalysisCache.h"
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
    // Keep the Phase 53 aggregate prefix source-compatible.
    // Explicit verification hooks, disabled in ordinary application use.
    prototype::Phase52WorkerOptions verificationHooks{};
    bool reuseAnalysis=true;
    std::shared_ptr<PlaybackAnalysisCache> analysisCache; // null selects shared 32 MiB cache.
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
enum class SeekStatus { Pending, Preparing, Completed, Replaced, Cancelled, Rejected, Failed };
struct SeekSnapshot {
    std::uint64_t id=0,session=0,requestedInputFrame=0,outputFrame=0,observedNs=0,readyNs=0;
    double initialSpeed=0;
    std::uint32_t replans=0;
    std::uint64_t activeId=0,pendingId=0;
    SeekStatus status=SeekStatus::Rejected;
    std::string reason;
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
    // Raw output chunks prepared by DSP, including a pending unpublished chunk.
    std::uint64_t generatedFrames=0;
    // producedFrames is the legacy name for FIFO-published frames.
    std::uint64_t session=0,renderCalls=0,producedFrames=0,consumedFrames=0,presentedFrames=0,missingFrames=0,underrunCalls=0;
    std::uint64_t maxContinuousMissingFrames=0,firstUnderrunNs=0,lastUnderrunNs=0,eventOverwrites=0,concurrentRenders=0;
    std::size_t fifoAvailable=0,fifoHighWater=0,outputLength=0,outputStartFrame=0,inputFrames=0;
    std::uint64_t rejectedWrites=0,operationHistoryDrops=0,lifetimeMissingFrames=0,lifetimeUnderrunCalls=0;
    double maxWorkerWallSeconds=0,maxWorkerCpuSeconds=0;
    StopReason reason=StopReason::None;
    std::string error;
};
struct SegmentEvidence {
    std::uint64_t session=0;
    std::size_t outputStart=0,publishedEnd=0,consumedEnd=0,outputLength=0;
    std::uint32_t sampleRate=0;std::size_t channels=0;
    double initialSpeed=0;Preset preset=Preset::Candidate;
    std::uint64_t missingFrames=0;
    std::string rawPcmSha256,contentSha256,workerError;
    std::vector<prototype::Phase39PlanMetric> plans;
    std::vector<prototype::Phase39BlockProfile> workerProfiles; // Explicit detailed diagnostics only.
};
struct UnderrunEvent {std::uint64_t timestampNs=0,outputFrame=0,requested=0,received=0,available=0,generation=0;};
struct RenderResult {std::size_t received=0,wanted=0,fifoBefore=0;std::uint64_t outputBefore=0,generation=0,lastPublicationNs=0;std::uint64_t session=0;
    std::uint64_t fifoReadBefore=0,fifoReadAfter=0,fifoWriteBefore=0,fifoWriteAfter=0;};

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
    std::uint64_t seekToInputSeconds(double seconds);
    std::uint64_t seekToInputFrame(std::uint64_t frame);
    SeekSnapshot getSeekSnapshot() const;
    std::vector<SeekSnapshot> seekHistory() const;
    std::vector<SegmentEvidence> closedSegmentEvidence() const; // Up to 16, control-side only.
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
    StartupDiagnostics getStartupDiagnostics() const;
    StateSnapshot getStateSnapshot() const;
    RenderResult renderAudio(float* const* output,std::size_t frames,std::uint64_t timestampNs) noexcept;
private:
    void inhibitRender();void prepareLocked(std::optional<std::size_t> startInput=std::nullopt);void tick();void record(const SpeedOperation&);
    void performSeek(std::unique_lock<std::mutex>&);
    void refreshActiveSpeed();
    void cancelSeeks();void recordSeek(const SeekSnapshot&);
    struct RenderCounters;
    void resetSession(std::size_t outputStart,std::shared_ptr<RenderCounters> ready={});
    void cancelCommands();void failLocked(const std::string&);
    mutable std::mutex mutex_;
    std::filesystem::path input_;Configuration config_;
    std::shared_ptr<const AnalysisLease> analysisLease_;
    std::shared_ptr<PlaybackAnalysisCache> uncached_=std::make_shared<PlaybackAnalysisCache>(0);
    StartupDiagnostics startup_;
    std::optional<SeekSnapshot> pendingSeek_,activeSeek_;
    SeekSnapshot seekSnapshot_;std::deque<SeekSnapshot> seekHistory_;
    std::deque<SegmentEvidence> closedSegments_;
    std::uint64_t nextSeek_=0;std::atomic<std::uint64_t> seekVersion_{0};
    bool sessionStarted_=false;std::optional<std::size_t> segmentInput_;
    std::unique_ptr<prototype::Phase39PlaybackPipeline> pipeline_;
    std::shared_ptr<RenderCounters> renderCounters_;
    std::atomic<RenderCounters*> renderCountersPtr_{nullptr};
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
    std::atomic<std::uint64_t> lifetimeMissing_{0},lifetimeUnderruns_{0};
};
const char* name(SeekStatus);const char* name(PlaybackState);const char* name(SpeedStatus);const char* name(StopReason);
}
