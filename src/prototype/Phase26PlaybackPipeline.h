#pragma once
#include "dsp/Phase14PlaybackPipeline.h"
#include "prototype/Phase26BidirectionalTimeMap.h"
#include "prototype/Phase24StreamingSpeedEngine.h"
#include <atomic>
#include <chrono>
#include <filesystem>
#include <mutex>
#include <thread>
#include <vector>

namespace ts::prototype {

enum class Phase26RequestState : std::uint8_t {
    Idle, Submitting, Requested, Applied, Rejected, Cancelled
};
enum class Phase26RequestResult : std::uint8_t {
    Accepted, Busy, Duplicate, Stopped, LimitReached
};
enum class Phase26AudibleStage : std::uint8_t {
    Stable, Accepted, AwaitingSafeRegion, AwaitingPlayback,
    Transitioning, Complete, Rejected, Cancelled
};
struct Phase26PlanMetric {
    BidirectionalPlan plan;
    std::size_t requestedOutput=0,requestedInput=0,planningFence=0;
    double planMilliseconds=0;
};
struct Phase26Snapshot {
    Phase26RequestState state=Phase26RequestState::Idle;
    Phase26AudibleStage audibleStage=Phase26AudibleStage::Stable;
    BidirectionalOutcome planOutcome=BidirectionalOutcome::NoSafeInterval;
    PlaybackSpeed initial=PlaybackSpeed::Half,from=PlaybackSpeed::Half;
    PlaybackSpeed target=PlaybackSpeed::Half,currentAudible=PlaybackSpeed::Half;
    std::uint64_t generation=0,requestNs=0,acceptedNs=0,workerSeenNs=0,planNs=0;
    std::size_t requestedOutput=0,requestedInput=0,produced=0,presented=0;
    std::size_t preparedAtPlan=0,publishedAtPlan=0,fifoAtPlan=0;
    std::size_t processedInputAtPlan=0,preparedFence=0,processedInputFence=0;
    std::size_t planningFence=0,appliedOutput=0,completionOutput=0,outputLength=0;
    std::size_t fifoHighWater=0;
    std::uint64_t underrunFrames=0,rejectedWrites=0;
    double maxWorkerChunkSeconds=0,planMilliseconds=0;
    std::size_t completedChanges=0;
};
struct Phase26RealtimeMarkers {
    std::size_t outputLength=0,appliedOutput=0,completionOutput=0;
    std::uint64_t generation=0;
};

// Independent BCD worker. One producer owns the complete TimeMap, phase,
// OLA and FIR history. The consumer uses only the preallocated raw FIFO.
class Phase26PlaybackPipeline {
public:
    Phase26PlaybackPipeline(const std::filesystem::path& input,PlaybackSpeed initial,
        std::size_t fifoFrames=16384,std::size_t blockFrames=2048,
        std::size_t leadFrames=12288,bool pollWhileBlocked=true);
    ~Phase26PlaybackPipeline();
    void start();
    void stop(); // Audio consumer must first be quiescent.
    Phase26RequestResult requestSpeed(PlaybackSpeed target,
        std::size_t presentedOutputFrame) noexcept;
    std::size_t pullAudio(float* const* output,std::size_t frames) noexcept;
    bool waitForPrefill(std::size_t frames,std::chrono::milliseconds timeout);
    bool finished() const noexcept { return finished_.load(std::memory_order_acquire); }
    bool drained() const noexcept { return finished() && fifo_.available()==0; }
    std::size_t available() const noexcept { return fifo_.available(); }
    Phase26Snapshot snapshot() const noexcept;
    Phase26RealtimeMarkers realtimeMarkers() const noexcept;
    std::vector<BidirectionalPlan> history() const;
    std::vector<Phase26PlanMetric> planMetrics() const;
    void rethrowWorkerError() const;
    std::uint32_t sampleRate() const noexcept { return sampleRate_; }
    std::size_t channels() const noexcept { return channels_; }
    std::size_t inputFrames() const noexcept { return analysis_.inputFrames(); }
private:
    std::filesystem::path file_;
    const std::uint32_t sampleRate_;
    const std::size_t channels_,blockFrames_,leadFrames_;
    const PlaybackSpeed initial_;
    const bool pollWhileBlocked_;
    Phase13TransientAnalysis analysis_;
    Phase14AudioFifo fifo_;
    std::thread worker_;
    std::atomic<bool> stop_{false},finished_{false},started_{false};
    std::atomic<Phase26RequestState> state_{Phase26RequestState::Idle};
    std::atomic<BidirectionalOutcome> planOutcome_{BidirectionalOutcome::NoSafeInterval};
    std::atomic<PlaybackSpeed> from_{PlaybackSpeed::Half},target_{PlaybackSpeed::Half},
        currentTail_{PlaybackSpeed::Half};
    std::atomic<std::uint64_t> generation_{0},requestNs_{0},acceptedNs_{0};
    std::atomic<std::uint64_t> workerSeenNs_{0},planNs_{0};
    std::atomic<std::size_t> requestedOutput_{0},requestedInput_{0};
    std::atomic<std::size_t> produced_{0},presented_{0},outputLength_{0};
    std::atomic<std::size_t> preparedAtPlan_{0},publishedAtPlan_{0},fifoAtPlan_{0};
    std::atomic<std::size_t> processedInputAtPlan_{0},preparedFence_{0};
    std::atomic<std::size_t> processedInputFence_{0},planningFence_{0};
    std::atomic<std::size_t> appliedOutput_{0},completionOutput_{0};
    std::atomic<std::uint64_t> underrunFrames_{0};
    std::atomic<double> maxWorkerChunkSeconds_{0},planMilliseconds_{0};
    mutable std::mutex historyMutex_;
    std::vector<Phase26PlanMetric> plans_;
    std::atomic<std::size_t> planCount_{0};
    std::atomic<std::uint64_t> appliedGeneration_{0};
    std::exception_ptr error_;
};
}
