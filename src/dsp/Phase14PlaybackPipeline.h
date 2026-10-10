#pragma once

#include "dsp/Phase13StreamingEngine.h"
#include <atomic>
#include <chrono>
#include <filesystem>
#include <functional>
#include <memory>
#include <thread>
#include <vector>

namespace ts {
struct SeekSuperseded {};
class VerifiedPcmCache;

// One DSP producer and one audio consumer. Storage is allocated before start().
// Neither read() nor write() allocates, waits, locks, or performs I/O.
class Phase14AudioFifo {
public:
    Phase14AudioFifo(std::size_t channels, std::size_t capacityFrames);
    std::size_t available() const noexcept;
    std::size_t free() const noexcept;
    std::size_t channels() const noexcept { return data_.size(); }
    std::size_t capacity() const noexcept { return capacity_; }
    std::size_t read(float* const* output, std::size_t frames) noexcept;
    bool write(const float* const* input, std::size_t frames) noexcept;
    void clearQuiescent() noexcept;
    std::size_t highWater() const noexcept { return highWater_.load(std::memory_order_relaxed); }
    std::uint64_t rejectedWrites() const noexcept { return rejectedWrites_.load(std::memory_order_relaxed); }
private:
    std::vector<std::vector<float>> data_;
    const std::size_t capacity_;
    alignas(64) std::atomic<std::uint64_t> readIndex_{0};
    alignas(64) std::atomic<std::uint64_t> writeIndex_{0};
    std::atomic<std::size_t> highWater_{0};
    std::atomic<std::uint64_t> rejectedWrites_{0};
};

struct Phase14Statistics {
    double analysisSeconds = 0;
    double dspSeconds = 0;
    double dspActiveSeconds = 0;
    double prefillSeconds = 0;
    double maxWorkerChunkSeconds = 0;
    std::size_t fifoHighWaterFrames = 0;
    std::uint64_t fifoRejectedWrites = 0;
    std::uint64_t underrunCalls = 0;
    std::uint64_t underrunFrames = 0;
    std::size_t producedFrames = 0;
};

// Control thread: prepare/start/stop. Worker: Phase 13 processPrepared.
// Audio thread: pullAudio() only. Stop/restart requires the consumer to be idle.
class Phase14PlaybackPipeline {
public:
    Phase14PlaybackPipeline(StretchConfig config, std::size_t fifoFrames = 131072,
                            std::size_t workerBlockFrames = 8192);
    ~Phase14PlaybackPipeline();
    Phase14PlaybackPipeline(const Phase14PlaybackPipeline&) = delete;
    Phase14PlaybackPipeline& operator=(const Phase14PlaybackPipeline&) = delete;

    void prepare(const std::filesystem::path& knownFile);
    void start();
    // Phase 16 control-thread seek. The audio consumer must be stopped and
    // quiescent before this call. Replays from sample zero, discards only raw
    // output before outputFrame, then prefills the existing FIFO.
    void startAtOutputFrame(std::size_t outputFrame,std::size_t prefillFrames,
                            std::chrono::milliseconds timeout,
                            const std::function<bool()>& superseded={});
    // Phase 18 control thread: verified raw PCM cache feeds the same FIFO.
    // File reads and planar conversion run exclusively on the worker.
    void startFromCache(const std::filesystem::path& cacheFile,std::size_t outputFrame,
                        std::size_t prefillFrames,std::chrono::milliseconds timeout,
                        const std::function<bool()>& superseded={});
    void startFromVerifiedCache(std::shared_ptr<const VerifiedPcmCache> cache,
                        std::size_t outputFrame,std::size_t prefillFrames,
                        std::chrono::milliseconds timeout,
                        const std::function<bool()>& superseded={});
    void stop();
    // A real callback calls only this method. Missing frames are filled with zero.
    std::size_t pullAudio(float* const* output, std::size_t frames) noexcept;
    std::size_t availableOutputFrames() const noexcept { return fifo_.available(); }
    bool workerFinished() const noexcept { return workerFinished_.load(std::memory_order_acquire); }
    bool drained() const noexcept { return workerFinished() && fifo_.available()==0; }
    std::size_t outputFrames() const noexcept { return prepared_.outputFrames(); }
    std::size_t inputFrames() const noexcept { return prepared_.inputFrames(); }
    std::size_t outputFrameForInputFrame(std::size_t inputFrame) const {
        return prepared_.outputFrameForInputFrame(inputFrame);
    }
    bool waitForPrefill(std::size_t frames, std::chrono::milliseconds timeout);
    void rethrowWorkerError() const;
    Phase14Statistics statistics() const noexcept;
private:
    Phase13StreamingEngine engine_;
    Phase13PreparedFile prepared_;
    Phase14AudioFifo fifo_;
    const std::size_t workerBlockFrames_;
    const std::uint32_t sourceRate_;
    std::thread worker_;
    std::atomic<bool> stopRequested_{false}, workerFinished_{false};
    std::atomic<std::uint64_t> underrunCalls_{0}, underrunFrames_{0};
    std::atomic<std::size_t> producedFrames_{0};
    std::atomic<double> dspSeconds_{0}, maxWorkerChunkSeconds_{0};
    std::atomic<double> dspActiveSeconds_{0};
    double analysisSeconds_ = 0, prefillSeconds_ = 0;
    std::exception_ptr workerError_;
};

} // namespace ts
