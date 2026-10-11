#include "prototype/Phase24PlaybackPipeline.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace ts::prototype {
namespace {
using Clock=std::chrono::steady_clock;
struct Stopped {};
static_assert(std::atomic<std::size_t>::is_always_lock_free);
std::uint64_t nowNs() {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        Clock::now().time_since_epoch()).count());
}
StretchConfig frozen(const std::filesystem::path& file) {
    WavStreamReader reader(file);
    StretchConfig config;
    config.sampleRate=reader.sampleRate();
    config.channels=static_cast<int>(reader.channels());
    config.timeRatio=2.0;
    config.enableMultiResolution=true;
    config.qualityMode=QualityMode::Experimental;
    config.enablePhaseLocking=true;
    config.enableTransientHandling=true;
    config.enableAdaptiveTimeMapping=true;
    config.enablePreciseTransientAnchoring=true;
    config.enableStereoCoherence=true;
    return config;
}
std::size_t inverseInput(const TimeMap& map,std::size_t output) {
    const auto& starts=map.starts();
    auto it=std::upper_bound(starts.begin(),starts.end(),
                             static_cast<long long>(output));
    if (it==starts.begin()) return 0;
    const auto index=std::min<std::size_t>(it-starts.begin()-1,starts.size()-2);
    const auto span=starts[index+1]-starts[index];
    const auto fraction=span>0 ? std::clamp(
        (double(output)-starts[index])/double(span),0.0,1.0) : 0.0;
    return static_cast<std::size_t>(std::llround((index+fraction)*map.sourceHop()));
}
}

Phase24PlaybackPipeline::Phase24PlaybackPipeline(const std::filesystem::path& file,
    std::size_t fifoFrames,std::size_t blockFrames,
    std::size_t leadLimitFrames,bool pollWhileBlocked)
    : file_(file),sampleRate_(WavStreamReader(file).sampleRate()),
      channels_(WavStreamReader(file).channels()),blockFrames_(blockFrames),
      leadLimitFrames_(leadLimitFrames ? leadLimitFrames : fifoFrames),
      pollWhileBlocked_(pollWhileBlocked),
      analysis_(Phase13StreamingEngine(frozen(file)).analyzeTransientEvents(file)),
      fifo_(channels_,fifoFrames) {
    if (blockFrames<1024 || blockFrames>65536 || blockFrames>fifoFrames ||
        leadLimitFrames_<blockFrames || leadLimitFrames_>fifoFrames)
        throw std::invalid_argument("Phase 24 block/FIFO size");
}
Phase24PlaybackPipeline::~Phase24PlaybackPipeline() { stop(); }
void Phase24PlaybackPipeline::start() {
    if (worker_.joinable()) throw std::logic_error("Phase 24 already started");
    fifo_.clearQuiescent();
    stop_.store(false,std::memory_order_release);
    finished_.store(false,std::memory_order_release);
    requestState_.store(SpeedRequestState::Idle,std::memory_order_release);
    requestedOutput_=0;requestedInput_=0;publishedAtRequest_=0;planningFence_=0;
    appliedInput_=0;appliedOutput_=0;completionOutput_=0;
    produced_=0;presented_=0;underrunFrames_=0;maxWorkerChunkSeconds_=0;
    firstUnprocessedInput_=0;preparedAtPlan_=0;fifoAtPlan_=0;firstInputAtPlan_=0;
    preparedFence_=0;processedInputFence_=0;
    requestTimestampNs_=0;acceptedTimestampNs_=0;
    workerSeenTimestampNs_=0;planTimestampNs_=0;error_=nullptr;
    outputLength_=static_cast<std::size_t>(std::llround(analysis_.inputFrames()*2.0));
    worker_=std::thread([this] {
        try {
            VariableTimeMap timeline(analysis_,sampleRate_);
            Phase24StreamingSpeedEngine engine(frozen(file_));
            auto previous=Clock::now();
            const auto publish=[&](const float* const* data,std::size_t frames,
                                   const std::function<void()>& poll) {
                    const auto now=Clock::now();
                    const auto seconds=std::chrono::duration<double>(now-previous).count();
                    auto old=maxWorkerChunkSeconds_.load();
                    while (old<seconds && !maxWorkerChunkSeconds_.compare_exchange_weak(old,seconds)) {}
                    while (!stop_.load(std::memory_order_acquire) &&
                           (fifo_.free()<frames || fifo_.available()+frames>leadLimitFrames_)) {
                        if (pollWhileBlocked_) poll();
                        std::this_thread::sleep_for(std::chrono::microseconds(100));
                    }
                    if (stop_.load(std::memory_order_acquire)) throw Stopped{};
                    if (pollWhileBlocked_) poll();
                    if (!fifo_.write(data,frames)) throw std::runtime_error("Phase 24 FIFO overflow");
                    produced_.fetch_add(frames,std::memory_order_release);
                    previous=Clock::now();
            };
            const auto plan=[&](std::size_t committed,std::size_t firstInput,TimeMap& map,
                    std::size_t& length) {
                    firstUnprocessedInput_.store(firstInput,std::memory_order_release);
                    if (requestState_.load(std::memory_order_acquire)!=SpeedRequestState::Requested)
                        return;
                    workerSeenTimestampNs_.store(nowNs(),std::memory_order_relaxed);
                    const auto asked=requestedOutput_.load(std::memory_order_relaxed);
                    publishedAtRequest_.store(pollWhileBlocked_ ? produced_.load(
                        std::memory_order_acquire) : committed,std::memory_order_relaxed);
                    preparedAtPlan_.store(committed,std::memory_order_relaxed);
                    fifoAtPlan_.store(fifo_.available(),std::memory_order_relaxed);
                    firstInputAtPlan_.store(firstInput,std::memory_order_relaxed);
                    const auto protectedInput=std::min(analysis_.inputFrames(),firstInput+1024);
                    const auto inputFence=static_cast<std::size_t>(std::ceil(
                        map.outputPositionForInputSample(double(protectedInput))));
                    const auto preparedFence=committed+8192;
                    preparedFence_.store(preparedFence,std::memory_order_relaxed);
                    processedInputFence_.store(inputFence,std::memory_order_relaxed);
                    const auto fence=std::max(preparedFence,inputFence);
                    planningFence_.store(fence,std::memory_order_relaxed);
                    const auto requestInput=inverseInput(timeline.fixedHalf(),asked);
                    requestedInput_.store(requestInput,std::memory_order_relaxed);
                    const auto plan=timeline.submit({1,requestInput,
                        static_cast<long long>(fence),50.0});
                    if (!plan.applied || plan.truncatedByEnd) {
                        requestState_.store(SpeedRequestState::Rejected,std::memory_order_release);
                        return;
                    }
                    const auto newLength=static_cast<std::size_t>(std::llround(
                        timeline.current().outputPositionForInputSample(
                            double(analysis_.inputFrames()))));
                    if (newLength<=committed+blockFrames_+8192) {
                        requestState_.store(SpeedRequestState::Rejected,std::memory_order_release);
                        return;
                    }
                    map=timeline.current();
                    length=newLength;
                    outputLength_.store(newLength,std::memory_order_release);
                    appliedInput_.store(plan.appliedFrame*1024,std::memory_order_relaxed);
                    appliedOutput_.store(plan.appliedOutputSample,std::memory_order_relaxed);
                    completionOutput_.store(map.starts()[plan.rampEndFrame],std::memory_order_relaxed);
                    planTimestampNs_.store(nowNs(),std::memory_order_relaxed);
                    requestState_.store(SpeedRequestState::Applied,std::memory_order_release);
            };
            if (pollWhileBlocked_)
                engine.process(file_,analysis_,timeline.fixedHalf(),outputLength_.load(),
                    {},plan,blockFrames_,[&](const float* const* data,std::size_t frames,
                                              const std::function<void()>& poll) {
                        publish(data,frames,poll);
                    });
            else
                engine.process(file_,analysis_,timeline.fixedHalf(),outputLength_.load(),
                    [&](const float* const* data,std::size_t frames) {
                        publish(data,frames,[]{});
                    },plan,blockFrames_);
        } catch (const Stopped&) {
        } catch (...) { error_=std::current_exception(); }
        if (requestState_.load(std::memory_order_acquire)==SpeedRequestState::Requested)
            requestState_.store(SpeedRequestState::Rejected,std::memory_order_release);
        finished_.store(true,std::memory_order_release);
    });
}
void Phase24PlaybackPipeline::stop() {
    stop_.store(true,std::memory_order_release);
    if (worker_.joinable()) worker_.join();
}
bool Phase24PlaybackPipeline::requestThreeQuarter(std::size_t frame) noexcept {
    const auto requested=nowNs();
    if (finished_.load(std::memory_order_acquire)) return false;
    SpeedRequestState expected=SpeedRequestState::Idle;
    if (!requestState_.compare_exchange_strong(expected,SpeedRequestState::Submitting,
        std::memory_order_acq_rel,std::memory_order_relaxed)) return false;
    requestedOutput_.store(frame,std::memory_order_relaxed);
    requestTimestampNs_.store(requested,std::memory_order_relaxed);
    acceptedTimestampNs_.store(nowNs(),std::memory_order_relaxed);
    requestState_.store(SpeedRequestState::Requested,std::memory_order_release);
    if (finished_.load(std::memory_order_acquire)) {
        expected=SpeedRequestState::Requested;
        requestState_.compare_exchange_strong(expected,SpeedRequestState::Rejected,
            std::memory_order_acq_rel,std::memory_order_relaxed);
        return false;
    }
    return true;
}
std::size_t Phase24PlaybackPipeline::pullAudio(float* const* output,std::size_t frames) noexcept {
    const auto count=fifo_.read(output,frames);
    presented_.fetch_add(count,std::memory_order_relaxed);
    underrunFrames_.fetch_add(frames-count,std::memory_order_relaxed);
    return count;
}
bool Phase24PlaybackPipeline::waitForPrefill(std::size_t frames,
    std::chrono::milliseconds timeout) {
    if (frames>fifo_.capacity()) throw std::invalid_argument("Prefill exceeds FIFO");
    const auto begin=Clock::now();
    while (fifo_.available()<frames && !finished()) {
        if (Clock::now()-begin>timeout) return false;
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    return fifo_.available()>=frames;
}
Phase24Snapshot Phase24PlaybackPipeline::snapshot() const noexcept {
    Phase24Snapshot value;
    value.requestState=requestState_.load(std::memory_order_acquire);
    value.requestedOutput=requestedOutput_.load();
    value.requestedInput=requestedInput_.load();
    value.publishedAtRequest=publishedAtRequest_.load();
    value.planningFence=planningFence_.load();
    value.appliedInput=appliedInput_.load();
    value.appliedOutput=appliedOutput_.load();
    value.completionOutput=completionOutput_.load();
    value.produced=produced_.load();value.presented=presented_.load();
    value.outputLength=outputLength_.load();
    value.firstUnprocessedInput=firstUnprocessedInput_.load();
    value.preparedAtPlan=preparedAtPlan_.load();
    value.fifoAtPlan=fifoAtPlan_.load();
    value.firstInputAtPlan=firstInputAtPlan_.load();
    value.preparedFence=preparedFence_.load();
    value.processedInputFence=processedInputFence_.load();
    value.fifoHighWater=fifo_.highWater();
    value.rejectedWrites=fifo_.rejectedWrites();
    value.underrunFrames=underrunFrames_.load();
    value.planTimestampNs=planTimestampNs_.load();
    value.requestTimestampNs=requestTimestampNs_.load();
    value.acceptedTimestampNs=acceptedTimestampNs_.load();
    value.workerSeenTimestampNs=workerSeenTimestampNs_.load();
    value.maxWorkerChunkSeconds=maxWorkerChunkSeconds_.load();
    return value;
}
Phase24RealtimeMarkers Phase24PlaybackPipeline::realtimeMarkers() const noexcept {
    return {outputLength_.load(std::memory_order_acquire),
            appliedOutput_.load(std::memory_order_acquire),
            completionOutput_.load(std::memory_order_acquire)};
}
void Phase24PlaybackPipeline::rethrowWorkerError() const {
    if (!finished()) throw std::logic_error("Worker still active");
    if (error_) std::rethrow_exception(error_);
}
}
