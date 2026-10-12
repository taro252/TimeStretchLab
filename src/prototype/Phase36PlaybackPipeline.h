#pragma once
#include "dsp/Phase14PlaybackPipeline.h"
#include "prototype/Phase35TimeMap.h"
#include "prototype/Phase36StreamingSpeedEngine.h"
#include <array>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <mutex>
#include <thread>
#include <vector>

namespace ts::prototype {

enum class Phase36RequestState : std::uint8_t {
    Idle, Submitting, Requested, Applied, Rejected, Cancelled
};
enum class Phase36RequestResult : std::uint8_t {
    Accepted, Busy, Duplicate, Stopped, Invalid, LimitReached
};
struct Phase36PlanMetric {
    Phase35Plan plan;
    Phase35Speed from{},target{};
    std::uint64_t generation=0,requestNs=0,planNs=0;
    std::size_t requestedOutput=0,requestedInput=0,planningFence=0;
    std::size_t prepared=0,published=0,firstUnprocessedInput=0;
    std::array<std::size_t,3> firstUnprocessedResolutionInputs{};
    std::array<std::size_t,3> lastProcessedResolutionInputs{};
    std::array<std::size_t,3> finalizedOla{};
    std::array<std::size_t,2> firstUnprocessedFirSources{};
    std::size_t firstDensityChangedInput=0;
    std::size_t timeMapBytes=0;
    double planMilliseconds=0;
};
struct Phase36Snapshot {
    Phase36RequestState state=Phase36RequestState::Idle;
    Phase35Outcome planOutcome=Phase35Outcome::NoSafeInterval;
    Phase35Speed initial{},from{},target{},currentAudible{};
    std::uint64_t generation=0,requestNs=0,acceptedNs=0,workerSeenNs=0,planNs=0;
    std::size_t requestedOutput=0,requestedInput=0,produced=0,presented=0;
    std::size_t preparedAtPlan=0,publishedAtPlan=0,fifoAtPlan=0;
    std::size_t processedInputAtPlan=0,planningFence=0;
    std::size_t appliedOutput=0,completionOutput=0,outputLength=0;
    std::size_t fifoHighWater=0;
    std::uint64_t underrunFrames=0,rejectedWrites=0;
    double maxWorkerChunkSeconds=0,planMilliseconds=0;
    std::size_t completedChanges=0;
};
struct Phase36RealtimeMarkers {
    std::size_t outputLength=0,appliedOutput=0,completionOutput=0;
    std::uint64_t generation=0;
};

// Worker owns the complete DSP and TimeMap. The render thread only reads a
// preallocated SPSC FIFO. Speed requests are passed with lock-free atomics.
class Phase36PlaybackPipeline {
public:
    Phase36PlaybackPipeline(const std::filesystem::path& input,Phase35Speed initial,
        std::size_t fifoFrames=16384,std::size_t blockFrames=2048,
        std::size_t leadFrames=12288);
    ~Phase36PlaybackPipeline();
    void start();
    void stop(); // The audio consumer must first be quiescent.
    Phase36RequestResult requestSpeed(Phase35Speed target,
        std::size_t presentedOutputFrame) noexcept;
    std::size_t pullAudio(float* const* output,std::size_t frames) noexcept;
    bool waitForPrefill(std::size_t frames,std::chrono::milliseconds timeout);
    bool finished() const noexcept { return finished_.load(std::memory_order_acquire); }
    bool drained() const noexcept { return finished() && fifo_.available()==0; }
    std::size_t available() const noexcept { return fifo_.available(); }
    Phase36Snapshot snapshot() const noexcept;
    Phase36RealtimeMarkers realtimeMarkers() const noexcept;
    std::vector<Phase36PlanMetric> planMetrics() const;
    double workerChunkP95Seconds() const;
    Phase13StageDigests stageDigests() const;
    void rethrowWorkerError() const;
    std::uint32_t sampleRate() const noexcept { return sampleRate_; }
    std::size_t channels() const noexcept { return channels_; }
    std::size_t inputFrames() const noexcept { return analysis_.inputFrames(); }
private:
    std::filesystem::path file_;
    const std::uint32_t sampleRate_;
    const std::size_t channels_,blockFrames_,leadFrames_;
    const Phase35Speed initial_;
    Phase13TransientAnalysis analysis_;
    Phase14AudioFifo fifo_;
    std::thread worker_;
    std::atomic<bool> stop_{false},finished_{false},started_{false};
    std::atomic<Phase36RequestState> state_{Phase36RequestState::Idle};
    std::atomic<Phase35Outcome> planOutcome_{Phase35Outcome::NoSafeInterval};
    std::atomic<std::uint32_t> fromMicros_{0},targetMicros_{0},currentTailMicros_{0};
    std::atomic<std::uint64_t> generation_{0},requestNs_{0},acceptedNs_{0};
    std::atomic<std::uint64_t> workerSeenNs_{0},planNs_{0};
    std::atomic<std::size_t> requestedOutput_{0},requestedInput_{0};
    std::atomic<std::size_t> produced_{0},presented_{0},outputLength_{0};
    std::atomic<std::size_t> preparedAtPlan_{0},publishedAtPlan_{0},fifoAtPlan_{0};
    std::atomic<std::size_t> processedInputAtPlan_{0},planningFence_{0};
    std::atomic<std::size_t> appliedOutput_{0},completionOutput_{0};
    std::atomic<std::uint64_t> underrunFrames_{0};
    std::atomic<double> maxWorkerChunkSeconds_{0},planMilliseconds_{0};
    mutable std::mutex historyMutex_;
    std::vector<Phase36PlanMetric> plans_;
    std::vector<double> workerChunkSeconds_;
    std::atomic<std::size_t> planCount_{0};
    std::atomic<std::uint64_t> appliedGeneration_{0};
    std::exception_ptr error_;
    Phase13StageDigests stageDigests_{}; // Written once before finished_.
};
}
