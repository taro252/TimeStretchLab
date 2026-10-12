#include "prototype/Phase39PlaybackPipeline.h"
#include "prototype/Phase42DensityGuard.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <ctime>
#include <fstream>

namespace ts::prototype {
namespace {
using Clock=std::chrono::steady_clock;
struct Stopped {};
static_assert(std::atomic<std::size_t>::is_always_lock_free);
static_assert(std::atomic<std::uint64_t>::is_always_lock_free);
std::uint64_t nowNs() {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        Clock::now().time_since_epoch()).count());
}
double workerCpuSeconds() {
    timespec stamp{};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID,&stamp)!=0) return 0;
    return double(stamp.tv_sec)+double(stamp.tv_nsec)*1e-9;
}
StretchConfig frozen(const std::filesystem::path& file,Phase39Speed initial) {
    if (!initial.valid()) throw std::invalid_argument("Invalid initial speed");
    WavStreamReader reader(file);
    StretchConfig config;
    config.sampleRate=reader.sampleRate();
    config.channels=static_cast<int>(reader.channels());
    config.timeRatio=initial.timeRatio();
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
Phase39PlaybackPipeline::Phase39PlaybackPipeline(const std::filesystem::path& input,
    Phase39Speed initial,std::size_t fifoFrames,std::size_t blockFrames,
    std::size_t leadFrames,Phase39Planning planning,Phase39DensityDiagnostic densityDiagnostic,
    bool enableProfile,std::filesystem::path componentCsv,std::size_t probeFirst,
    std::size_t probeLast,std::function<std::uint64_t()> allocationCounter)
    : file_(input),sampleRate_(WavStreamReader(input).sampleRate()),
      channels_(WavStreamReader(input).channels()),blockFrames_(blockFrames),
      leadFrames_(leadFrames ? leadFrames : fifoFrames),initial_(initial),planning_(planning),
      densityDiagnostic_(densityDiagnostic),enableProfile_(enableProfile),
      componentCsv_(std::move(componentCsv)),probeFirst_(probeFirst),probeLast_(probeLast),
      allocationCounter_(std::move(allocationCounter)),
      analysis_(Phase13StreamingEngine(frozen(input,{500000})).analyzeTransientEvents(input)),
      fifo_(channels_,fifoFrames) {
    if (blockFrames<1024 || blockFrames>65536 || blockFrames>fifoFrames ||
        leadFrames_<blockFrames || leadFrames_>fifoFrames)
        throw std::invalid_argument("Phase 39 block/FIFO size");
}
Phase39PlaybackPipeline::~Phase39PlaybackPipeline() { stop(); }
void Phase39PlaybackPipeline::start() {
    if (worker_.joinable()) throw std::logic_error("Phase 39 already started");
    fifo_.clearQuiescent();
    stop_=false;finished_=false;state_=Phase39RequestState::Idle;
    planOutcome_=Phase39Outcome::NoSafeInterval;
    fromMicros_=initial_.micros;targetMicros_=initial_.micros;
    currentTailMicros_=initial_.micros;
    generation_=0;requestNs_=0;acceptedNs_=0;
    workerSeenNs_=0;planNs_=0;requestedOutput_=0;requestedInput_=0;
    produced_=0;presented_=0;underrunFrames_=0;maxWorkerChunkSeconds_=0;
    maxWorkerCpuSeconds_=0;maxFifoWaitSeconds_=0;
    fifoWaitNanoseconds_=0;workerChunksOver100Ms_=0;
    planMilliseconds_=0;planCpuMilliseconds_=0;
    maxFifoWriteSeconds_=0;maxHistoryMutexWaitSeconds_=0;
    preparedAtPlan_=0;publishedAtPlan_=0;fifoAtPlan_=0;processedInputAtPlan_=0;
    planningFence_=0;
    appliedOutput_=0;completionOutput_=0;planCount_=0;appliedGeneration_=0;error_=nullptr;
    stageDigests_={};
    slowestBlocks_.clear();
    if (enableProfile_) slowestBlocks_.reserve(20);
    { std::lock_guard lock(historyMutex_);
      plans_.clear(); plans_.reserve(64);
      workerChunkSeconds_.clear(); workerChunkSeconds_.reserve(65536); }
    outputLength_=static_cast<std::size_t>(std::llround(analysis_.inputFrames()*initial_.timeRatio()));
    worker_=std::thread([this] {
        try {
            Phase39TimeMap timeline(analysis_,sampleRate_,initial_,planning_);
            Phase36StreamingSpeedEngine engine(frozen(file_,initial_));
            std::ofstream componentOutput;
            if (!componentCsv_.empty()) {
                componentOutput.open(componentCsv_);
                if (!componentOutput) throw std::runtime_error("Component CSV open failed");
                componentOutput<<"sample,channel,low_raw,mid_raw,high_raw,lp250_diff,lp3500_diff,final\n";
            }
            auto previous=Clock::now();
            auto previousCpu=workerCpuSeconds();
            auto previousNew=allocationCounter_ ? allocationCounter_() : 0;
            Phase39BlockProfile latestProfile;
            const auto publish=[&](const float* const* data,std::size_t frames,
                                   const std::function<void()>& poll) {
                const auto now=Clock::now();
                const auto seconds=std::chrono::duration<double>(now-previous).count();
                const auto cpuNow=workerCpuSeconds();
                const auto cpuSeconds=std::max(0.0,cpuNow-previousCpu);
                if (enableProfile_) {
                    latestProfile.chunkWallSeconds=seconds;
                    latestProfile.chunkCpuSeconds=cpuSeconds;
                    const auto currentNew=allocationCounter_ ? allocationCounter_() : 0;
                    latestProfile.cppNewCalls=currentNew-previousNew;
                }
                auto oldCpu=maxWorkerCpuSeconds_.load();
                while (oldCpu<cpuSeconds &&
                       !maxWorkerCpuSeconds_.compare_exchange_weak(oldCpu,cpuSeconds)) {}
                if (seconds>0.1) workerChunksOver100Ms_.fetch_add(1);
                auto old=maxWorkerChunkSeconds_.load();
                while (old<seconds && !maxWorkerChunkSeconds_.compare_exchange_weak(old,seconds)) {}
                const auto mutexStart=Clock::now();
                std::unique_lock historyLock(historyMutex_);
                const auto mutexWait=std::chrono::duration<double>(Clock::now()-mutexStart).count();
                auto oldMutex=maxHistoryMutexWaitSeconds_.load();
                while (oldMutex<mutexWait &&
                       !maxHistoryMutexWaitSeconds_.compare_exchange_weak(oldMutex,mutexWait)) {}
                if (workerChunkSeconds_.size()<65536)
                    workerChunkSeconds_.push_back(seconds);
                historyLock.unlock();
                const auto waitBegin=Clock::now();
                while (!stop_.load(std::memory_order_acquire) &&
                       (fifo_.free()<frames || fifo_.available()+frames>leadFrames_)) {
                    poll();
                    std::this_thread::sleep_for(std::chrono::microseconds(100));
                }
                if (stop_.load(std::memory_order_acquire)) throw Stopped{};
                const auto waited=std::chrono::duration<double>(Clock::now()-waitBegin).count();
                if (enableProfile_) latestProfile.fifoWaitSeconds=waited;
                fifoWaitNanoseconds_.fetch_add(static_cast<std::uint64_t>(waited*1e9));
                auto oldWait=maxFifoWaitSeconds_.load();
                while (oldWait<waited &&
                       !maxFifoWaitSeconds_.compare_exchange_weak(oldWait,waited)) {}
                poll();
                const auto writeStart=Clock::now();
                if (!fifo_.write(data,frames)) throw std::runtime_error("Phase 39 FIFO overflow");
                const auto writeSeconds=std::chrono::duration<double>(Clock::now()-writeStart).count();
                auto oldWrite=maxFifoWriteSeconds_.load();
                while (oldWrite<writeSeconds &&
                       !maxFifoWriteSeconds_.compare_exchange_weak(oldWrite,writeSeconds)) {}
                produced_.fetch_add(frames,std::memory_order_release);
                previous=Clock::now();
                previousCpu=workerCpuSeconds();
                if (allocationCounter_) previousNew=allocationCounter_();
            };
            const auto plan=[&](const Phase36StreamingSpeedEngine::Frontier& frontier,
                                 TimeMap& map,std::size_t& length,
                                 std::vector<std::pair<std::size_t,bool>>& modeChanges) {
                if (state_.load(std::memory_order_acquire)!=Phase39RequestState::Requested)
                    return;
                workerSeenNs_.store(nowNs(),std::memory_order_relaxed);
                const auto committed=frontier.preparedOutput;
                const auto asked=requestedOutput_.load(std::memory_order_relaxed);
                const Phase39Speed target{targetMicros_.load(std::memory_order_relaxed)};
                const Phase39Speed from{currentTailMicros_.load(std::memory_order_relaxed)};
                const auto generation=generation_.load(std::memory_order_relaxed);
                const auto published=produced_.load(std::memory_order_acquire);
                publishedAtPlan_.store(published,std::memory_order_relaxed);
                preparedAtPlan_.store(committed,std::memory_order_relaxed);
                fifoAtPlan_.store(fifo_.available(),std::memory_order_relaxed);
                const auto firstInput=*std::max_element(
                    frontier.nextInput.begin(),frontier.nextInput.end());
                processedInputAtPlan_.store(firstInput,std::memory_order_relaxed);
                // A high-resolution frame may interpolate between two Mid
                // TimeMap nodes. Preserve BOTH nodes used by the last frame
                // already processed at each resolution, then start changing
                // only at the following node. FIR source blocks already
                // transformed are independently immutable.
                auto fence=std::max(committed,published);
                constexpr std::array<std::size_t,3> hops={2048,1024,256};
                for (std::size_t r=0;r<3;++r) {
                    const auto firstMutableNode=frontier.lastProcessedInput[r]/1024+1;
                    const auto node=std::min(firstMutableNode,map.starts().size()-1);
                    fence=std::max(fence,static_cast<std::size_t>(map.starts()[node]));
                    const auto densityNode=std::min(
                        (frontier.nextInput[r]+hops[r]+1023)/1024,
                        map.starts().size()-1);
                    fence=std::max(fence,static_cast<std::size_t>(map.starts()[densityNode]));
                    fence=std::max(fence,frontier.finalizedOla[r]);
                }
                // The 2049-tap low FIR may reference 1024 future samples.
                // Add a whole block of margin to cover transformed source
                // blocks and the zero-phase contribution before the change.
                for (const auto sourcePosition:frontier.firstUnprocessedFirSource)
                    fence=std::max(fence,sourcePosition+4096);
                planningFence_.store(fence,std::memory_order_relaxed);
                const auto requestInput=inverseInput(map,asked);
                requestedInput_.store(requestInput,std::memory_order_relaxed);
                const auto beginPlan=Clock::now();
                const auto beginPlanCpu=workerCpuSeconds();
                auto candidate=timeline;
                const auto proposal=candidate.submit({generation,target,requestInput,
                    static_cast<long long>(fence),50.0});
                planOutcome_.store(proposal.outcome,std::memory_order_relaxed);
                if (!proposal.applied()) {
                    planMilliseconds_.store(std::chrono::duration<double,std::milli>(
                        Clock::now()-beginPlan).count(),std::memory_order_relaxed);
                    planNs_.store(nowNs(),std::memory_order_relaxed);
                    state_.store(Phase39RequestState::Rejected,std::memory_order_release);
                    return;
                }
                if (!candidate.monotonic() || candidate.touchesProtected(proposal)) {
                    planOutcome_.store(Phase39Outcome::NoSafeInterval,std::memory_order_relaxed);
                    state_.store(Phase39RequestState::Rejected,std::memory_order_release);
                    return;
                }
                const auto newLength=static_cast<std::size_t>(std::llround(
                    candidate.current().outputPositionForInputSample(
                        double(analysis_.inputFrames()))));
                if (newLength<=std::max({committed,
                        frontier.firstUnprocessedFirSource[0],
                        frontier.firstUnprocessedFirSource[1]})+blockFrames_) {
                    planOutcome_.store(Phase39Outcome::Truncated,std::memory_order_relaxed);
                    planMilliseconds_.store(std::chrono::duration<double,std::milli>(
                        Clock::now()-beginPlan).count(),std::memory_order_relaxed);
                    planNs_.store(nowNs(),std::memory_order_relaxed);
                    state_.store(Phase39RequestState::Rejected,std::memory_order_release);
                    return;
                }
                const bool changesDensity=(from.value()<0.50)!=(target.value()<0.50) &&
                    densityDiagnostic_!=Phase39DensityDiagnostic::HoldInitial;
                const auto modeFrame=densityDiagnostic_==Phase39DensityDiagnostic::AfterRamp ?
                    proposal.rampEndFrame : proposal.appliedFrame;
                auto modeInput=modeFrame*1024;
                Phase42DensityDecision densityDecision;
                if (changesDensity && densityDiagnostic_==Phase39DensityDiagnostic::SafeGuarded) {
                    if (!modeChanges.empty() &&
                        std::any_of(frontier.nextInput.begin(),frontier.nextInput.end(),
                            [&](std::size_t next) { return next<=modeChanges.back().first; })) {
                        planOutcome_.store(Phase39Outcome::NoSafeInterval,std::memory_order_relaxed);
                        state_.store(Phase39RequestState::Rejected,std::memory_order_release);
                        return;
                    }
                    densityDecision=chooseSafeDensitySwitch(candidate.current(),proposal,
                        frontier,modeChanges,from.value()<0.50,target.value()<0.50,
                        fence,analysis_.inputFrames());
                    if (!densityDecision.safe) {
                        planOutcome_.store(Phase39Outcome::NoSafeInterval,std::memory_order_relaxed);
                        state_.store(Phase39RequestState::Rejected,std::memory_order_release);
                        return;
                    }
                    modeInput=densityDecision.inputSample;
                }
                if (changesDensity && modeInput<=*std::max_element(
                        frontier.lastProcessedInput.begin(),frontier.lastProcessedInput.end())) {
                    planOutcome_.store(Phase39Outcome::NoSafeInterval,std::memory_order_relaxed);
                    state_.store(Phase39RequestState::Rejected,std::memory_order_release);
                    return;
                }
                timeline=std::move(candidate);
                map=timeline.current();
                if (changesDensity)
                    modeChanges.emplace_back(modeInput,target.value()<0.50);
                length=newLength;
                outputLength_.store(newLength,std::memory_order_release);
                appliedOutput_.store(proposal.appliedOutputSample,std::memory_order_relaxed);
                completionOutput_.store(proposal.completionOutputSample,std::memory_order_relaxed);
                fromMicros_.store(from.micros,std::memory_order_relaxed);
                currentTailMicros_.store(target.micros,std::memory_order_relaxed);
                const auto milliseconds=std::chrono::duration<double,std::milli>(
                    Clock::now()-beginPlan).count();
                planMilliseconds_.store(milliseconds,std::memory_order_relaxed);
                planCpuMilliseconds_.store((workerCpuSeconds()-beginPlanCpu)*1000.0,
                                            std::memory_order_relaxed);
                { std::lock_guard lock(historyMutex_);
                  plans_.push_back({proposal,from,target,generation,
                      requestNs_.load(std::memory_order_relaxed),nowNs(),
                      asked,requestInput,fence,committed,published,firstInput,
                      frontier.nextInput,frontier.lastProcessedInput,
                      frontier.finalizedOla,frontier.firstUnprocessedFirSource,
                      modeInput,densityDecision.maximumHop,densityDecision.maximumHopStep,
                      densityDecision.minimumWeight,densityDecision.minimumLocalSpeed,
                      densityDecision.maximumLocalSpeed,
                      densityDecision.candidatesTried,timeline.fixedMapBytes(),milliseconds}); }
                appliedGeneration_.store(generation,std::memory_order_release);
                planCount_.fetch_add(1,std::memory_order_release);
                planNs_.store(nowNs(),std::memory_order_relaxed);
                state_.store(Phase39RequestState::Applied,std::memory_order_release);
            };
            const Phase36StreamingSpeedEngine::ProfileHook profileHook=enableProfile_ ?
                Phase36StreamingSpeedEngine::ProfileHook([&](std::size_t start,
                    const Phase36StreamingSpeedEngine::WorkProfile& work) {
                    latestProfile.outputStart=start;
                    latestProfile.work=work;
                    if (slowestBlocks_.size()<20) slowestBlocks_.push_back(latestProfile);
                    else {
                        const auto weakest=std::min_element(slowestBlocks_.begin(),
                            slowestBlocks_.end(),[](const auto& a,const auto& b) {
                                return a.chunkWallSeconds<b.chunkWallSeconds;
                            });
                        if (latestProfile.chunkWallSeconds>weakest->chunkWallSeconds)
                            *weakest=latestProfile;
                    }
                }) : Phase36StreamingSpeedEngine::ProfileHook{};
            const auto result=engine.process(file_,analysis_,timeline.current(),outputLength_.load(),
                blockFrames_,[&](const float* const* data,std::size_t frames,
                                         const std::function<void()>& poll) {
                    publish(data,frames,poll);
                },plan,{},profileHook,
                componentOutput ? &componentOutput : nullptr,probeFirst_,probeLast_);
            stageDigests_=result.stages;
        } catch (const Stopped&) {
        } catch (...) { error_=std::current_exception(); }
        auto pending=Phase39RequestState::Requested;
        state_.compare_exchange_strong(pending,Phase39RequestState::Cancelled,
            std::memory_order_acq_rel,std::memory_order_relaxed);
        finished_.store(true,std::memory_order_release);
    });
    started_.store(true,std::memory_order_release);
}
std::vector<Phase39BlockProfile> Phase39PlaybackPipeline::slowestBlocks() const {
    if (!finished_.load(std::memory_order_acquire))
        throw std::logic_error("Profile is available after worker completion");
    auto result=slowestBlocks_;
    std::sort(result.begin(),result.end(),[](const auto& a,const auto& b) {
        return a.chunkWallSeconds>b.chunkWallSeconds;
    });
    return result;
}
void Phase39PlaybackPipeline::stop() {
    started_.store(false,std::memory_order_release);
    stop_.store(true,std::memory_order_release);
    if (worker_.joinable()) worker_.join();
    auto pending=Phase39RequestState::Requested;
    state_.compare_exchange_strong(pending,Phase39RequestState::Cancelled,
        std::memory_order_acq_rel,std::memory_order_relaxed);
    pending=Phase39RequestState::Submitting;
    state_.compare_exchange_strong(pending,Phase39RequestState::Cancelled,
        std::memory_order_acq_rel,std::memory_order_relaxed);
    if (presented_.load(std::memory_order_acquire)<
        completionOutput_.load(std::memory_order_acquire)) {
        pending=Phase39RequestState::Applied;
        state_.compare_exchange_strong(pending,Phase39RequestState::Cancelled,
            std::memory_order_acq_rel,std::memory_order_relaxed);
    }
}
Phase39RequestResult Phase39PlaybackPipeline::requestSpeed(
    Phase39Speed target,std::size_t presentedOutputFrame) noexcept {
    if (!target.valid()) return Phase39RequestResult::Invalid;
    if (!started_.load(std::memory_order_acquire) ||
        finished_.load(std::memory_order_acquire)) return Phase39RequestResult::Stopped;
    auto expected=state_.load(std::memory_order_acquire);
    if (expected==Phase39RequestState::Applied) {
        if (presented_.load(std::memory_order_acquire)<
            completionOutput_.load(std::memory_order_acquire))
            return Phase39RequestResult::Busy;
    } else if (expected!=Phase39RequestState::Idle &&
               expected!=Phase39RequestState::Rejected) return Phase39RequestResult::Busy;
    if (target.micros==currentTailMicros_.load(std::memory_order_acquire))
        return Phase39RequestResult::Duplicate;
    const auto generation=generation_.load(std::memory_order_acquire)+1;
    if (generation==0) return Phase39RequestResult::LimitReached;
    if (!state_.compare_exchange_strong(expected,Phase39RequestState::Submitting,
        std::memory_order_acq_rel,std::memory_order_relaxed))
        return Phase39RequestResult::Busy;
    requestNs_.store(nowNs(),std::memory_order_relaxed);
    requestedOutput_.store(presentedOutputFrame,std::memory_order_relaxed);
    fromMicros_.store(currentTailMicros_.load(std::memory_order_acquire),
                      std::memory_order_relaxed);
    targetMicros_.store(target.micros,std::memory_order_relaxed);
    generation_.store(generation,std::memory_order_relaxed);
    workerSeenNs_.store(0,std::memory_order_relaxed);
    planNs_.store(0,std::memory_order_relaxed);
    planMilliseconds_.store(0,std::memory_order_relaxed);
    planOutcome_.store(Phase39Outcome::NoSafeInterval,std::memory_order_relaxed);
    acceptedNs_.store(nowNs(),std::memory_order_relaxed);
    state_.store(Phase39RequestState::Requested,std::memory_order_release);
    if (finished_.load(std::memory_order_acquire)) {
        expected=Phase39RequestState::Requested;
        state_.compare_exchange_strong(expected,Phase39RequestState::Cancelled,
            std::memory_order_acq_rel,std::memory_order_relaxed);
        return Phase39RequestResult::Stopped;
    }
    return Phase39RequestResult::Accepted;
}
std::size_t Phase39PlaybackPipeline::pullAudio(float* const* output,
    std::size_t frames) noexcept {
    const auto count=fifo_.read(output,frames);
    presented_.fetch_add(count,std::memory_order_release);
    underrunFrames_.fetch_add(frames-count,std::memory_order_relaxed);
    return count;
}
bool Phase39PlaybackPipeline::waitForPrefill(std::size_t frames,
    std::chrono::milliseconds timeout) {
    if (frames>leadFrames_) throw std::invalid_argument("Prefill exceeds lead limit");
    const auto begin=Clock::now();
    while (fifo_.available()<frames && !finished()) {
        if (Clock::now()-begin>timeout) return false;
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    return fifo_.available()>=frames;
}
Phase39Snapshot Phase39PlaybackPipeline::snapshot() const noexcept {
    Phase39Snapshot value;
    value.state=state_.load(std::memory_order_acquire);
    value.planOutcome=planOutcome_.load(std::memory_order_acquire);
    value.initial=initial_;
    value.from={fromMicros_.load()};value.target={targetMicros_.load()};
    value.generation=generation_.load();
    value.requestNs=requestNs_.load();value.acceptedNs=acceptedNs_.load();
    value.workerSeenNs=workerSeenNs_.load();value.planNs=planNs_.load();
    value.requestedOutput=requestedOutput_.load();
    value.requestedInput=requestedInput_.load();
    value.produced=produced_.load();value.presented=presented_.load();
    value.preparedAtPlan=preparedAtPlan_.load();
    value.publishedAtPlan=publishedAtPlan_.load();value.fifoAtPlan=fifoAtPlan_.load();
    value.processedInputAtPlan=processedInputAtPlan_.load();
    value.planningFence=planningFence_.load();
    value.appliedOutput=appliedOutput_.load();
    value.completionOutput=completionOutput_.load();
    value.outputLength=outputLength_.load();
    value.fifoHighWater=fifo_.highWater();
    value.underrunFrames=underrunFrames_.load();
    value.rejectedWrites=fifo_.rejectedWrites();
    value.maxWorkerChunkSeconds=maxWorkerChunkSeconds_.load();
    value.maxWorkerCpuSeconds=maxWorkerCpuSeconds_.load();
    value.maxFifoWaitSeconds=maxFifoWaitSeconds_.load();
    value.maxFifoWriteSeconds=maxFifoWriteSeconds_.load();
    value.maxHistoryMutexWaitSeconds=maxHistoryMutexWaitSeconds_.load();
    value.fifoWaitNanoseconds=fifoWaitNanoseconds_.load();
    value.workerChunksOver100Ms=workerChunksOver100Ms_.load();
    value.planMilliseconds=planMilliseconds_.load();
    value.planCpuMilliseconds=planCpuMilliseconds_.load();
    const auto count=planCount_.load(std::memory_order_acquire);
    value.currentAudible=value.from;
    value.completedChanges=count-((value.state==Phase39RequestState::Applied ||
        value.state==Phase39RequestState::Cancelled) &&
        value.presented<value.completionOutput ? 1 : 0);
    if (value.state==Phase39RequestState::Applied &&
        value.presented>=value.completionOutput) value.currentAudible=value.target;
    return value;
}
Phase39RealtimeMarkers Phase39PlaybackPipeline::realtimeMarkers() const noexcept {
    return {outputLength_.load(std::memory_order_acquire),
            appliedOutput_.load(std::memory_order_acquire),
            completionOutput_.load(std::memory_order_acquire),
            appliedGeneration_.load(std::memory_order_acquire)};
}
std::vector<Phase39PlanMetric> Phase39PlaybackPipeline::planMetrics() const {
    std::lock_guard lock(historyMutex_);
    return plans_;
}
double Phase39PlaybackPipeline::workerChunkP95Seconds() const {
    std::vector<double> durations;
    { std::lock_guard lock(historyMutex_); durations=workerChunkSeconds_; }
    if (durations.empty()) return 0;
    const auto index=static_cast<std::size_t>(std::ceil(durations.size()*0.95))-1;
    std::nth_element(durations.begin(),durations.begin()+index,durations.end());
    return durations[index];
}
double Phase39PlaybackPipeline::workerChunkP99Seconds() const {
    std::vector<double> durations;
    { std::lock_guard lock(historyMutex_); durations=workerChunkSeconds_; }
    if (durations.empty()) return 0;
    const auto index=static_cast<std::size_t>(std::ceil(durations.size()*0.99))-1;
    std::nth_element(durations.begin(),durations.begin()+index,durations.end());
    return durations[index];
}
Phase13StageDigests Phase39PlaybackPipeline::stageDigests() const {
    if (!finished()) throw std::logic_error("Worker still active");
    return stageDigests_;
}
void Phase39PlaybackPipeline::rethrowWorkerError() const {
    if (!finished()) throw std::logic_error("Worker still active");
    if (error_) std::rethrow_exception(error_);
}
}
