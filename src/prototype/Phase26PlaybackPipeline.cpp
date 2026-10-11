#include "prototype/Phase26PlaybackPipeline.h"
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
double ratio(PlaybackSpeed speed) {
    return speed==PlaybackSpeed::Half ? 2.0 : 4.0/3.0;
}
StretchConfig frozen(const std::filesystem::path& file,PlaybackSpeed initial) {
    WavStreamReader reader(file);
    StretchConfig config;
    config.sampleRate=reader.sampleRate();
    config.channels=static_cast<int>(reader.channels());
    config.timeRatio=ratio(initial);
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
Phase26PlaybackPipeline::Phase26PlaybackPipeline(const std::filesystem::path& input,
    PlaybackSpeed initial,std::size_t fifoFrames,std::size_t blockFrames,
    std::size_t leadFrames,bool pollWhileBlocked)
    : file_(input),sampleRate_(WavStreamReader(input).sampleRate()),
      channels_(WavStreamReader(input).channels()),blockFrames_(blockFrames),
      leadFrames_(leadFrames ? leadFrames : fifoFrames),initial_(initial),
      pollWhileBlocked_(pollWhileBlocked),
      analysis_(Phase13StreamingEngine(frozen(input,initial)).analyzeTransientEvents(input)),
      fifo_(channels_,fifoFrames) {
    if (blockFrames<1024 || blockFrames>65536 || blockFrames>fifoFrames ||
        leadFrames_<blockFrames || leadFrames_>fifoFrames)
        throw std::invalid_argument("Phase 26 block/FIFO size");
}
Phase26PlaybackPipeline::~Phase26PlaybackPipeline() { stop(); }
void Phase26PlaybackPipeline::start() {
    if (worker_.joinable()) throw std::logic_error("Phase 26 already started");
    fifo_.clearQuiescent();
    stop_=false;finished_=false;state_=Phase26RequestState::Idle;
    planOutcome_=BidirectionalOutcome::NoSafeInterval;
    from_=initial_;target_=initial_;currentTail_=initial_;generation_=0;requestNs_=0;acceptedNs_=0;
    workerSeenNs_=0;planNs_=0;requestedOutput_=0;requestedInput_=0;
    produced_=0;presented_=0;underrunFrames_=0;maxWorkerChunkSeconds_=0;
    planMilliseconds_=0;
    preparedAtPlan_=0;publishedAtPlan_=0;fifoAtPlan_=0;processedInputAtPlan_=0;
    preparedFence_=0;processedInputFence_=0;planningFence_=0;
    appliedOutput_=0;completionOutput_=0;planCount_=0;appliedGeneration_=0;error_=nullptr;
    { std::lock_guard lock(historyMutex_); plans_.clear(); plans_.reserve(64); }
    outputLength_=static_cast<std::size_t>(std::llround(analysis_.inputFrames()*ratio(initial_)));
    worker_=std::thread([this] {
        try {
            Phase26BidirectionalTimeMap timeline(analysis_,sampleRate_,initial_);
            Phase24StreamingSpeedEngine engine(frozen(file_,initial_));
            auto previous=Clock::now();
            const auto publish=[&](const float* const* data,std::size_t frames,
                                   const std::function<void()>& poll) {
                const auto now=Clock::now();
                const auto seconds=std::chrono::duration<double>(now-previous).count();
                auto old=maxWorkerChunkSeconds_.load();
                while (old<seconds && !maxWorkerChunkSeconds_.compare_exchange_weak(old,seconds)) {}
                while (!stop_.load(std::memory_order_acquire) &&
                       (fifo_.free()<frames || fifo_.available()+frames>leadFrames_)) {
                    if (pollWhileBlocked_) poll();
                    std::this_thread::sleep_for(std::chrono::microseconds(100));
                }
                if (stop_.load(std::memory_order_acquire)) throw Stopped{};
                if (pollWhileBlocked_) poll();
                if (!fifo_.write(data,frames)) throw std::runtime_error("Phase 26 FIFO overflow");
                produced_.fetch_add(frames,std::memory_order_release);
                previous=Clock::now();
            };
            const auto plan=[&](std::size_t committed,std::size_t firstInput,
                                 TimeMap& map,std::size_t& length) {
                if (state_.load(std::memory_order_acquire)!=Phase26RequestState::Requested)
                    return;
                workerSeenNs_.store(nowNs(),std::memory_order_relaxed);
                const auto asked=requestedOutput_.load(std::memory_order_relaxed);
                const auto target=target_.load(std::memory_order_relaxed);
                const auto generation=generation_.load(std::memory_order_relaxed);
                publishedAtPlan_.store(produced_.load(std::memory_order_acquire),
                                       std::memory_order_relaxed);
                preparedAtPlan_.store(committed,std::memory_order_relaxed);
                fifoAtPlan_.store(fifo_.available(),std::memory_order_relaxed);
                processedInputAtPlan_.store(firstInput,std::memory_order_relaxed);
                const auto protectedInput=std::min(analysis_.inputFrames(),firstInput+1024);
                const auto inputFence=static_cast<std::size_t>(std::ceil(
                    map.outputPositionForInputSample(double(protectedInput))));
                const auto preparedFence=committed+8192;
                preparedFence_.store(preparedFence,std::memory_order_relaxed);
                processedInputFence_.store(inputFence,std::memory_order_relaxed);
                const auto fence=std::max(preparedFence,inputFence);
                planningFence_.store(fence,std::memory_order_relaxed);
                const auto requestInput=inverseInput(map,asked);
                requestedInput_.store(requestInput,std::memory_order_relaxed);
                const auto beginPlan=Clock::now();
                auto candidate=timeline;
                const auto proposal=candidate.submit({generation,target,requestInput,
                    static_cast<long long>(fence),50.0});
                planOutcome_.store(proposal.outcome,std::memory_order_relaxed);
                if (!proposal.applied()) {
                    planMilliseconds_.store(std::chrono::duration<double,std::milli>(
                        Clock::now()-beginPlan).count(),std::memory_order_relaxed);
                    planNs_.store(nowNs(),std::memory_order_relaxed);
                    state_.store(Phase26RequestState::Rejected,std::memory_order_release);
                    return;
                }
                const auto newLength=static_cast<std::size_t>(std::llround(
                    candidate.current().outputPositionForInputSample(
                        double(analysis_.inputFrames()))));
                if (newLength<=committed+blockFrames_+8192) {
                    planOutcome_.store(BidirectionalOutcome::Truncated,std::memory_order_relaxed);
                    planMilliseconds_.store(std::chrono::duration<double,std::milli>(
                        Clock::now()-beginPlan).count(),std::memory_order_relaxed);
                    planNs_.store(nowNs(),std::memory_order_relaxed);
                    state_.store(Phase26RequestState::Rejected,std::memory_order_release);
                    return;
                }
                timeline=std::move(candidate);
                map=timeline.current();
                length=newLength;
                outputLength_.store(newLength,std::memory_order_release);
                appliedOutput_.store(proposal.appliedOutputSample,std::memory_order_relaxed);
                completionOutput_.store(proposal.completionOutputSample,std::memory_order_relaxed);
                from_.store(proposal.from,std::memory_order_relaxed);
                currentTail_.store(target,std::memory_order_relaxed);
                const auto milliseconds=std::chrono::duration<double,std::milli>(
                    Clock::now()-beginPlan).count();
                planMilliseconds_.store(milliseconds,std::memory_order_relaxed);
                { std::lock_guard lock(historyMutex_);
                  plans_.push_back({proposal,asked,requestInput,fence,milliseconds}); }
                appliedGeneration_.store(generation,std::memory_order_release);
                planCount_.fetch_add(1,std::memory_order_release);
                planNs_.store(nowNs(),std::memory_order_relaxed);
                state_.store(Phase26RequestState::Applied,std::memory_order_release);
            };
            if (pollWhileBlocked_)
                engine.process(file_,analysis_,timeline.current(),outputLength_.load(),
                    {},plan,blockFrames_,[&](const float* const* data,std::size_t frames,
                                              const std::function<void()>& poll) {
                        publish(data,frames,poll);
                    });
            else
                engine.process(file_,analysis_,timeline.current(),outputLength_.load(),
                    [&](const float* const* data,std::size_t frames) {
                        publish(data,frames,[]{});
                    },plan,blockFrames_);
        } catch (const Stopped&) {
        } catch (...) { error_=std::current_exception(); }
        auto pending=Phase26RequestState::Requested;
        state_.compare_exchange_strong(pending,Phase26RequestState::Cancelled,
            std::memory_order_acq_rel,std::memory_order_relaxed);
        finished_.store(true,std::memory_order_release);
    });
    started_.store(true,std::memory_order_release);
}
void Phase26PlaybackPipeline::stop() {
    started_.store(false,std::memory_order_release);
    stop_.store(true,std::memory_order_release);
    if (worker_.joinable()) worker_.join();
    auto pending=Phase26RequestState::Requested;
    state_.compare_exchange_strong(pending,Phase26RequestState::Cancelled,
        std::memory_order_acq_rel,std::memory_order_relaxed);
    pending=Phase26RequestState::Submitting;
    state_.compare_exchange_strong(pending,Phase26RequestState::Cancelled,
        std::memory_order_acq_rel,std::memory_order_relaxed);
    if (presented_.load(std::memory_order_acquire)<
        completionOutput_.load(std::memory_order_acquire)) {
        pending=Phase26RequestState::Applied;
        state_.compare_exchange_strong(pending,Phase26RequestState::Cancelled,
            std::memory_order_acq_rel,std::memory_order_relaxed);
    }
}
Phase26RequestResult Phase26PlaybackPipeline::requestSpeed(
    PlaybackSpeed target,std::size_t presentedOutputFrame) noexcept {
    if (!started_.load(std::memory_order_acquire) ||
        finished_.load(std::memory_order_acquire)) return Phase26RequestResult::Stopped;
    auto expected=state_.load(std::memory_order_acquire);
    if (expected==Phase26RequestState::Applied) {
        if (presented_.load(std::memory_order_acquire)<
            completionOutput_.load(std::memory_order_acquire))
            return Phase26RequestResult::Busy;
    } else if (expected!=Phase26RequestState::Idle &&
               expected!=Phase26RequestState::Rejected) return Phase26RequestResult::Busy;
    if (target==currentTail_.load(std::memory_order_acquire))
        return Phase26RequestResult::Duplicate;
    const auto generation=generation_.load(std::memory_order_acquire)+1;
    if (generation==0) return Phase26RequestResult::LimitReached;
    if (!state_.compare_exchange_strong(expected,Phase26RequestState::Submitting,
        std::memory_order_acq_rel,std::memory_order_relaxed))
        return Phase26RequestResult::Busy;
    requestNs_.store(nowNs(),std::memory_order_relaxed);
    requestedOutput_.store(presentedOutputFrame,std::memory_order_relaxed);
    from_.store(currentTail_.load(std::memory_order_acquire),std::memory_order_relaxed);
    target_.store(target,std::memory_order_relaxed);
    generation_.store(generation,std::memory_order_relaxed);
    workerSeenNs_.store(0,std::memory_order_relaxed);
    planNs_.store(0,std::memory_order_relaxed);
    planMilliseconds_.store(0,std::memory_order_relaxed);
    planOutcome_.store(BidirectionalOutcome::NoSafeInterval,std::memory_order_relaxed);
    acceptedNs_.store(nowNs(),std::memory_order_relaxed);
    state_.store(Phase26RequestState::Requested,std::memory_order_release);
    if (finished_.load(std::memory_order_acquire)) {
        expected=Phase26RequestState::Requested;
        state_.compare_exchange_strong(expected,Phase26RequestState::Cancelled,
            std::memory_order_acq_rel,std::memory_order_relaxed);
        return Phase26RequestResult::Stopped;
    }
    return Phase26RequestResult::Accepted;
}
std::size_t Phase26PlaybackPipeline::pullAudio(float* const* output,
    std::size_t frames) noexcept {
    const auto count=fifo_.read(output,frames);
    presented_.fetch_add(count,std::memory_order_release);
    underrunFrames_.fetch_add(frames-count,std::memory_order_relaxed);
    return count;
}
bool Phase26PlaybackPipeline::waitForPrefill(std::size_t frames,
    std::chrono::milliseconds timeout) {
    if (frames>leadFrames_) throw std::invalid_argument("Prefill exceeds lead limit");
    const auto begin=Clock::now();
    while (fifo_.available()<frames && !finished()) {
        if (Clock::now()-begin>timeout) return false;
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    return fifo_.available()>=frames;
}
Phase26Snapshot Phase26PlaybackPipeline::snapshot() const noexcept {
    Phase26Snapshot value;
    value.state=state_.load(std::memory_order_acquire);
    value.planOutcome=planOutcome_.load(std::memory_order_acquire);
    value.initial=initial_;value.from=from_.load();value.target=target_.load();
    value.generation=generation_.load();
    value.requestNs=requestNs_.load();value.acceptedNs=acceptedNs_.load();
    value.workerSeenNs=workerSeenNs_.load();value.planNs=planNs_.load();
    value.requestedOutput=requestedOutput_.load();
    value.requestedInput=requestedInput_.load();
    value.produced=produced_.load();value.presented=presented_.load();
    value.preparedAtPlan=preparedAtPlan_.load();
    value.publishedAtPlan=publishedAtPlan_.load();value.fifoAtPlan=fifoAtPlan_.load();
    value.processedInputAtPlan=processedInputAtPlan_.load();
    value.preparedFence=preparedFence_.load();
    value.processedInputFence=processedInputFence_.load();
    value.planningFence=planningFence_.load();
    value.appliedOutput=appliedOutput_.load();
    value.completionOutput=completionOutput_.load();
    value.outputLength=outputLength_.load();
    value.fifoHighWater=fifo_.highWater();
    value.underrunFrames=underrunFrames_.load();
    value.rejectedWrites=fifo_.rejectedWrites();
    value.maxWorkerChunkSeconds=maxWorkerChunkSeconds_.load();
    value.planMilliseconds=planMilliseconds_.load();
    const auto count=planCount_.load(std::memory_order_acquire);
    value.currentAudible=value.from;
    value.completedChanges=count-((value.state==Phase26RequestState::Applied ||
        value.state==Phase26RequestState::Cancelled) &&
        value.presented<value.completionOutput ? 1 : 0);
    switch (value.state) {
    case Phase26RequestState::Idle: value.audibleStage=Phase26AudibleStage::Stable; break;
    case Phase26RequestState::Submitting:
    case Phase26RequestState::Requested:
        value.audibleStage=value.workerSeenNs ? Phase26AudibleStage::AwaitingSafeRegion :
            Phase26AudibleStage::Accepted; break;
    case Phase26RequestState::Applied:
        if (value.presented<value.appliedOutput)
            value.audibleStage=Phase26AudibleStage::AwaitingPlayback;
        else if (value.presented<value.completionOutput)
            value.audibleStage=Phase26AudibleStage::Transitioning;
        else { value.audibleStage=Phase26AudibleStage::Complete;
               value.currentAudible=value.target; }
        break;
    case Phase26RequestState::Rejected: value.audibleStage=Phase26AudibleStage::Rejected; break;
    case Phase26RequestState::Cancelled: value.audibleStage=Phase26AudibleStage::Cancelled; break;
    }
    return value;
}
Phase26RealtimeMarkers Phase26PlaybackPipeline::realtimeMarkers() const noexcept {
    return {outputLength_.load(std::memory_order_acquire),
            appliedOutput_.load(std::memory_order_acquire),
            completionOutput_.load(std::memory_order_acquire),
            appliedGeneration_.load(std::memory_order_acquire)};
}
std::vector<BidirectionalPlan> Phase26PlaybackPipeline::history() const {
    std::lock_guard lock(historyMutex_);
    std::vector<BidirectionalPlan> result;
    result.reserve(plans_.size());
    for (const auto& metric:plans_) result.push_back(metric.plan);
    return result;
}
std::vector<Phase26PlanMetric> Phase26PlaybackPipeline::planMetrics() const {
    std::lock_guard lock(historyMutex_);
    return plans_;
}
void Phase26PlaybackPipeline::rethrowWorkerError() const {
    if (!finished()) throw std::logic_error("Worker still active");
    if (error_) std::rethrow_exception(error_);
}
}
