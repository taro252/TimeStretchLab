#include "dsp/Phase14PlaybackPipeline.h"
#include <algorithm>
#include <cstring>
#include <stdexcept>

namespace ts {
namespace {
using Clock = std::chrono::steady_clock;
struct Stopped {};
static_assert(std::atomic<std::uint64_t>::is_always_lock_free);
static_assert(std::atomic<std::size_t>::is_always_lock_free);
}

Phase14AudioFifo::Phase14AudioFifo(std::size_t channels, std::size_t capacityFrames)
    : data_(channels, std::vector<float>(capacityFrames)), capacity_(capacityFrames) {
    if (channels<1 || channels>2 || capacityFrames<8192)
        throw std::invalid_argument("Phase 14 FIFO configuration");
}

std::size_t Phase14AudioFifo::available() const noexcept {
    // Observe the consumer's released index before the producer's released
    // index: a third (control) thread must not combine a newer read with an
    // older write and underflow the unsigned subtraction.
    const auto r=readIndex_.load(std::memory_order_acquire);
    const auto w=writeIndex_.load(std::memory_order_acquire);
    return static_cast<std::size_t>(w-r);
}

std::size_t Phase14AudioFifo::free() const noexcept {
    const auto r=readIndex_.load(std::memory_order_acquire);
    const auto w=writeIndex_.load(std::memory_order_relaxed);
    return capacity_-static_cast<std::size_t>(w-r);
}

std::size_t Phase14AudioFifo::read(float* const* output, std::size_t frames) noexcept {
    const auto r=readIndex_.load(std::memory_order_relaxed);
    const auto w=writeIndex_.load(std::memory_order_acquire);
    const auto count=std::min(frames,static_cast<std::size_t>(w-r));
    const auto first=std::min(count,capacity_-static_cast<std::size_t>(r%capacity_));
    for (std::size_t c=0; c<data_.size(); ++c) {
        std::memcpy(output[c],data_[c].data()+r%capacity_,first*sizeof(float));
        if (count>first) std::memcpy(output[c]+first,data_[c].data(),(count-first)*sizeof(float));
        std::fill_n(output[c]+count,frames-count,0.0f);
    }
    readIndex_.store(r+count,std::memory_order_release);
    return count;
}

bool Phase14AudioFifo::write(const float* const* input, std::size_t frames) noexcept {
    const auto w=writeIndex_.load(std::memory_order_relaxed);
    const auto r=readIndex_.load(std::memory_order_acquire);
    if (frames>capacity_-static_cast<std::size_t>(w-r)) {
        rejectedWrites_.fetch_add(1,std::memory_order_relaxed);
        return false;
    }
    const auto first=std::min(frames,capacity_-static_cast<std::size_t>(w%capacity_));
    for (std::size_t c=0; c<data_.size(); ++c) {
        std::memcpy(data_[c].data()+w%capacity_,input[c],first*sizeof(float));
        if (frames>first) std::memcpy(data_[c].data(),input[c]+first,(frames-first)*sizeof(float));
    }
    writeIndex_.store(w+frames,std::memory_order_release);
    const auto level=static_cast<std::size_t>(w+frames-r);
    auto previous=highWater_.load(std::memory_order_relaxed);
    while (previous<level && !highWater_.compare_exchange_weak(previous,level,std::memory_order_relaxed)) {}
    return true;
}

void Phase14AudioFifo::clearQuiescent() noexcept {
    readIndex_.store(0,std::memory_order_relaxed);
    writeIndex_.store(0,std::memory_order_relaxed);
    highWater_.store(0,std::memory_order_relaxed);
    rejectedWrites_.store(0,std::memory_order_relaxed);
}

Phase14PlaybackPipeline::Phase14PlaybackPipeline(StretchConfig config, std::size_t fifoFrames,
                                                 std::size_t workerBlockFrames)
    : engine_(config), fifo_(config.channels,fifoFrames),
      workerBlockFrames_(workerBlockFrames) {
    if (workerBlockFrames<8192 || workerBlockFrames>65536 || workerBlockFrames>fifoFrames)
        throw std::invalid_argument("Phase 14 worker block/FIFO size");
}

Phase14PlaybackPipeline::~Phase14PlaybackPipeline() { stop(); }

void Phase14PlaybackPipeline::prepare(const std::filesystem::path& knownFile) {
    if (worker_.joinable()) throw std::logic_error("Stop before prepare");
    const auto start=Clock::now();
    prepared_=engine_.analyzeFile(knownFile);
    analysisSeconds_=std::chrono::duration<double>(Clock::now()-start).count();
}

void Phase14PlaybackPipeline::start() {
    if (worker_.joinable()) throw std::logic_error("Already started");
    if (prepared_.outputFrames()==0) throw std::logic_error("Prepare a nonempty file first");
    fifo_.clearQuiescent();
    underrunCalls_.store(0);
    underrunFrames_.store(0);
    producedFrames_.store(0);
    dspSeconds_.store(0);
    dspActiveSeconds_.store(0);
    maxWorkerChunkSeconds_.store(0);
    workerError_=nullptr;
    stopRequested_.store(false,std::memory_order_release);
    workerFinished_.store(false,std::memory_order_release);
    worker_=std::thread([this] {
        const auto begin=Clock::now();
        auto chunkStart=begin;
        double active=0;
        try {
            engine_.processPrepared(prepared_,[&](const float* const* data,std::size_t frames) {
                const auto now=Clock::now();
                const auto seconds=std::chrono::duration<double>(now-chunkStart).count();
                active+=seconds;
                maxWorkerChunkSeconds_.store(std::max(maxWorkerChunkSeconds_.load(),seconds));
                while (!stopRequested_.load(std::memory_order_acquire) && fifo_.free()<frames)
                    std::this_thread::sleep_for(std::chrono::microseconds(100));
                if (stopRequested_.load(std::memory_order_acquire)) throw Stopped{};
                if (!fifo_.write(data,frames)) throw std::runtime_error("FIFO producer overrun");
                producedFrames_.fetch_add(frames,std::memory_order_relaxed);
                chunkStart=Clock::now();
            },workerBlockFrames_);
        } catch (const Stopped&) {
        } catch (...) { workerError_=std::current_exception(); }
        dspSeconds_.store(std::chrono::duration<double>(Clock::now()-begin).count());
        dspActiveSeconds_.store(active);
        workerFinished_.store(true,std::memory_order_release);
    });
}

void Phase14PlaybackPipeline::stop() {
    stopRequested_.store(true,std::memory_order_release);
    if (worker_.joinable()) worker_.join();
    workerFinished_.store(true,std::memory_order_release);
}

std::size_t Phase14PlaybackPipeline::pullAudio(float* const* output,std::size_t frames) noexcept {
    const auto count=fifo_.read(output,frames);
    if (count<frames) {
        underrunCalls_.fetch_add(1,std::memory_order_relaxed);
        underrunFrames_.fetch_add(frames-count,std::memory_order_relaxed);
    }
    return count;
}

bool Phase14PlaybackPipeline::waitForPrefill(std::size_t frames,std::chrono::milliseconds timeout) {
    const auto start=Clock::now();
    while (availableOutputFrames()<frames && !workerFinished()) {
        if (Clock::now()-start>=timeout) return false;
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    prefillSeconds_=std::chrono::duration<double>(Clock::now()-start).count();
    return availableOutputFrames()>=frames;
}

void Phase14PlaybackPipeline::rethrowWorkerError() const {
    if (!workerFinished()) return;
    if (workerError_) std::rethrow_exception(workerError_);
}

Phase14Statistics Phase14PlaybackPipeline::statistics() const noexcept {
    return {analysisSeconds_,dspSeconds_.load(),dspActiveSeconds_.load(),prefillSeconds_,maxWorkerChunkSeconds_.load(),
            fifo_.highWater(),fifo_.rejectedWrites(),underrunCalls_.load(),
            underrunFrames_.load(),producedFrames_.load()};
}

} // namespace ts
