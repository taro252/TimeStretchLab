#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>

namespace ts {
struct ProcessorStatistics {
    std::uint64_t inputUnderrunCalls=0;
    std::uint64_t outputUnderrunFrames=0;
    std::uint64_t inputOverrunFrames=0;
    std::uint64_t inputHighWaterFrames=0;
    std::uint64_t outputHighWaterFrames=0;
    std::uint64_t processingNanoseconds=0;
    std::uint64_t workerCalls=0;
    std::uint64_t resetCount=0;
};

struct ProcessorLatency {
    std::size_t lowHalfWindow=4096;
    std::size_t midHalfWindow=2048;
    std::size_t crossoverHalfFilter=1024;
    std::size_t crossoverBlock=2048;
    std::size_t fifoSafety=4096;
    std::size_t transientLookahead=0; // Not implemented in the live path.
    std::size_t startupInputFrames=0;
};

// Planar float, single-producer input / single-consumer output. The worker
// exclusively calls process(). reset()/prepare() require all three threads to
// be quiescent. The live path uses the existing Low+Mid vocoder and LP250 but
// has a linear time map; offline transient preprocessing remains separate.
class TimeStretchProcessor {
public:
    TimeStretchProcessor();
    ~TimeStretchProcessor();
    TimeStretchProcessor(const TimeStretchProcessor&)=delete;
    TimeStretchProcessor& operator=(const TimeStretchProcessor&)=delete;
    void prepare(double sampleRate,int channels,std::size_t maxBlockSize);
    void reset() noexcept;
    void setSpeed(double speed);
    double targetSpeed() const noexcept;
    double currentSpeed() const noexcept;
    std::size_t pushInput(const float* const* input,std::size_t frames) noexcept;
    std::size_t availableInputCapacity() const noexcept;
    // DSP-worker only. Never call from an audio render callback.
    std::size_t process(std::size_t maxOutputFrames) noexcept;
    std::size_t availableOutputFrames() const noexcept;
    // Copies available frames and fills a shortage with silence.
    std::size_t pullOutput(float* const* output,std::size_t frames) noexcept;
    void signalEndOfInput() noexcept;
    bool drained() const noexcept;
    bool faulted() const noexcept;
    ProcessorStatistics statistics() const noexcept;
    ProcessorLatency latency() const noexcept;
    std::size_t inputFifoCapacity() const noexcept;
    std::size_t outputFifoCapacity() const noexcept;
    std::size_t workingMemoryBytes() const noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
