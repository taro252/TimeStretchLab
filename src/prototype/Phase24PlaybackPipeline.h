#pragma once
#include "dsp/Phase14PlaybackPipeline.h"
#include "prototype/Phase22VariableTimeMap.h"
#include "prototype/Phase24StreamingSpeedEngine.h"
#include <atomic>
#include <chrono>
#include <filesystem>
#include <thread>

namespace ts::prototype {

enum class SpeedRequestState : int { Idle, Submitting, Requested, Applied, Rejected };
struct Phase24Snapshot {
    SpeedRequestState requestState=SpeedRequestState::Idle;
    std::size_t requestedOutput=0,requestedInput=0,publishedAtRequest=0,planningFence=0;
    std::size_t appliedInput=0,appliedOutput=0,completionOutput=0;
    std::size_t produced=0,presented=0,outputLength=0,firstUnprocessedInput=0;
    std::size_t fifoHighWater=0;
    std::uint64_t underrunFrames=0,rejectedWrites=0;
    std::size_t preparedAtPlan=0,fifoAtPlan=0,firstInputAtPlan=0;
    std::size_t preparedFence=0,processedInputFence=0;
    std::uint64_t requestTimestampNs=0,acceptedTimestampNs=0;
    std::uint64_t workerSeenTimestampNs=0,planTimestampNs=0;
    double maxWorkerChunkSeconds=0;
};
struct Phase24RealtimeMarkers {
    std::size_t outputLength=0,appliedOutput=0,completionOutput=0;
};

// Known-file, one-way 0.50 -> 0.75 player. Control submits one request;
// DSP worker alone owns the mutable TimeMap and all synthesis state.
class Phase24PlaybackPipeline {
public:
    // Zero leadLimitFrames preserves the Phase 24 FIFO behavior. Phase 25
    // experiments choose a lower limit and optionally poll while blocked.
    Phase24PlaybackPipeline(const std::filesystem::path& file,
        std::size_t fifoFrames=32768,std::size_t blockFrames=8192,
        std::size_t leadLimitFrames=0,bool pollWhileBlocked=false);
    ~Phase24PlaybackPipeline();
    void start();
    void stop(); // Consumer must already be quiescent.
    bool requestThreeQuarter(std::size_t presentedOutputFrame) noexcept;
    std::size_t pullAudio(float* const* output,std::size_t frames) noexcept;
    bool waitForPrefill(std::size_t frames,std::chrono::milliseconds timeout);
    bool finished() const noexcept { return finished_.load(std::memory_order_acquire); }
    bool drained() const noexcept { return finished() && fifo_.available()==0; }
    std::size_t available() const noexcept { return fifo_.available(); }
    Phase24Snapshot snapshot() const noexcept;
    Phase24RealtimeMarkers realtimeMarkers() const noexcept;
    void rethrowWorkerError() const;
    std::uint32_t sampleRate() const noexcept { return sampleRate_; }
    std::size_t channels() const noexcept { return channels_; }
    std::size_t inputFrames() const noexcept { return analysis_.inputFrames(); }
private:
    std::filesystem::path file_;
    const std::uint32_t sampleRate_;
    const std::size_t channels_,blockFrames_,leadLimitFrames_;
    const bool pollWhileBlocked_;
    Phase13TransientAnalysis analysis_;
    Phase14AudioFifo fifo_;
    std::thread worker_;
    std::atomic<bool> stop_{false},finished_{false};
    std::atomic<SpeedRequestState> requestState_{SpeedRequestState::Idle};
    std::atomic<std::size_t> requestedOutput_{0},requestedInput_{0},publishedAtRequest_{0};
    std::atomic<std::size_t> planningFence_{0},appliedInput_{0},appliedOutput_{0};
    std::atomic<std::size_t> completionOutput_{0},produced_{0},presented_{0};
    std::atomic<std::size_t> outputLength_{0},firstUnprocessedInput_{0};
    std::atomic<std::size_t> preparedAtPlan_{0},fifoAtPlan_{0};
    std::atomic<std::size_t> firstInputAtPlan_{0};
    std::atomic<std::size_t> preparedFence_{0},processedInputFence_{0};
    std::atomic<std::uint64_t> underrunFrames_{0};
    std::atomic<std::uint64_t> requestTimestampNs_{0},acceptedTimestampNs_{0};
    std::atomic<std::uint64_t> workerSeenTimestampNs_{0},planTimestampNs_{0};
    std::atomic<double> maxWorkerChunkSeconds_{0};
    std::exception_ptr error_;
};
}
