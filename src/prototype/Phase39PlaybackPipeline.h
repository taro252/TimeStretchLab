#pragma once
#include "dsp/Phase14PlaybackPipeline.h"
#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase36StreamingSpeedEngine.h"
#include <array>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <mutex>
#include <thread>
#include <vector>

namespace ts::prototype {

enum class Phase39RequestState : std::uint8_t {
    Idle, Submitting, Requested, Applied, Rejected, Cancelled
};
enum class Phase39RequestResult : std::uint8_t {
    Accepted, Busy, Duplicate, Stopped, Invalid, LimitReached
};
enum class Phase39DensityDiagnostic : std::uint8_t {
    Immediate, HoldInitial, AfterRamp
};
struct Phase39PlanMetric {
    Phase39Plan plan;
    Phase39Speed from{},target{};
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
struct Phase39Snapshot {
    Phase39RequestState state=Phase39RequestState::Idle;
    Phase39Outcome planOutcome=Phase39Outcome::NoSafeInterval;
    Phase39Speed initial{},from{},target{},currentAudible{};
    std::uint64_t generation=0,requestNs=0,acceptedNs=0,workerSeenNs=0,planNs=0;
    std::size_t requestedOutput=0,requestedInput=0,produced=0,presented=0;
    std::size_t preparedAtPlan=0,publishedAtPlan=0,fifoAtPlan=0;
    std::size_t processedInputAtPlan=0,planningFence=0;
    std::size_t appliedOutput=0,completionOutput=0,outputLength=0;
    std::size_t fifoHighWater=0;
    std::uint64_t underrunFrames=0,rejectedWrites=0;
    double maxWorkerChunkSeconds=0,planMilliseconds=0,planCpuMilliseconds=0;
    double maxWorkerCpuSeconds=0,maxFifoWaitSeconds=0,maxFifoWriteSeconds=0;
    double maxHistoryMutexWaitSeconds=0;
    std::uint64_t fifoWaitNanoseconds=0,workerChunksOver100Ms=0;
    std::size_t completedChanges=0;
};
struct Phase39RealtimeMarkers {
    std::size_t outputLength=0,appliedOutput=0,completionOutput=0;
    std::uint64_t generation=0;
};
struct Phase39BlockProfile {
    std::size_t outputStart=0;
    double chunkWallSeconds=0,chunkCpuSeconds=0,fifoWaitSeconds=0;
    std::uint64_t cppNewCalls=0;
    Phase36StreamingSpeedEngine::WorkProfile work{};
};

// Worker owns the complete DSP and TimeMap. The render thread only reads a
// preallocated SPSC FIFO. Speed requests are passed with lock-free atomics.
class Phase39PlaybackPipeline {
public:
    Phase39PlaybackPipeline(const std::filesystem::path& input,Phase39Speed initial,
        std::size_t fifoFrames=16384,std::size_t blockFrames=2048,
        std::size_t leadFrames=12288,
        Phase39Planning planning=Phase39Planning::A,
        Phase39DensityDiagnostic densityDiagnostic=Phase39DensityDiagnostic::Immediate,
        bool enableProfile=false,
        std::filesystem::path componentCsv={},std::size_t probeFirst=0,
        std::size_t probeLast=0,
        std::function<std::uint64_t()> allocationCounter={});
    ~Phase39PlaybackPipeline();
    void start();
    void stop(); // The audio consumer must first be quiescent.
    Phase39RequestResult requestSpeed(Phase39Speed target,
        std::size_t presentedOutputFrame) noexcept;
    std::size_t pullAudio(float* const* output,std::size_t frames) noexcept;
    bool waitForPrefill(std::size_t frames,std::chrono::milliseconds timeout);
    bool finished() const noexcept { return finished_.load(std::memory_order_acquire); }
    bool drained() const noexcept { return finished() && fifo_.available()==0; }
    std::size_t available() const noexcept { return fifo_.available(); }
    Phase39Snapshot snapshot() const noexcept;
    Phase39RealtimeMarkers realtimeMarkers() const noexcept;
    std::vector<Phase39PlanMetric> planMetrics() const;
    std::vector<Phase39BlockProfile> slowestBlocks() const;
    double workerChunkP95Seconds() const;
    double workerChunkP99Seconds() const;
    Phase13StageDigests stageDigests() const;
    void rethrowWorkerError() const;
    std::uint32_t sampleRate() const noexcept { return sampleRate_; }
    std::size_t channels() const noexcept { return channels_; }
    std::size_t inputFrames() const noexcept { return analysis_.inputFrames(); }
private:
    std::filesystem::path file_;
    const std::uint32_t sampleRate_;
    const std::size_t channels_,blockFrames_,leadFrames_;
    const Phase39Speed initial_;
    const Phase39Planning planning_;
    const Phase39DensityDiagnostic densityDiagnostic_;
    const bool enableProfile_;
    const std::filesystem::path componentCsv_;
    const std::size_t probeFirst_,probeLast_;
    const std::function<std::uint64_t()> allocationCounter_;
    Phase13TransientAnalysis analysis_;
    Phase14AudioFifo fifo_;
    std::thread worker_;
    std::atomic<bool> stop_{false},finished_{false},started_{false};
    std::atomic<Phase39RequestState> state_{Phase39RequestState::Idle};
    std::atomic<Phase39Outcome> planOutcome_{Phase39Outcome::NoSafeInterval};
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
    std::atomic<double> planCpuMilliseconds_{0};
    std::atomic<double> maxWorkerCpuSeconds_{0},maxFifoWaitSeconds_{0};
    std::atomic<double> maxFifoWriteSeconds_{0},maxHistoryMutexWaitSeconds_{0};
    std::atomic<std::uint64_t> fifoWaitNanoseconds_{0},workerChunksOver100Ms_{0};
    mutable std::mutex historyMutex_;
    std::vector<Phase39PlanMetric> plans_;
    std::vector<double> workerChunkSeconds_;
    std::vector<Phase39BlockProfile> slowestBlocks_; // Worker-only until finished.
    std::atomic<std::size_t> planCount_{0};
    std::atomic<std::uint64_t> appliedGeneration_{0};
    std::exception_ptr error_;
    Phase13StageDigests stageDigests_{}; // Written once before finished_.
};
}
