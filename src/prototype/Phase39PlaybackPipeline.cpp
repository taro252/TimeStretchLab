#include "prototype/Phase39PlaybackPipeline.h"
#include "prototype/Phase50Boundary.h"
#include "prototype/Phase42DensityGuard.h"
#include "prototype/Phase45PcmDigest.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <stdexcept>
#include <ctime>
#include <fstream>
#include <pthread.h>
#include <mach/mach_time.h>

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
std::uint64_t unixNowNs() {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count());
}
double workerCpuSeconds() {
    timespec stamp{};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID,&stamp)!=0) return 0;
    return double(stamp.tv_sec)+double(stamp.tv_nsec)*1e-9;
}
struct ScopedPlanTiming {
    double& wall;
    double& cpu;
    Clock::time_point begin=Clock::now();
    double cpuBegin=workerCpuSeconds();
    ~ScopedPlanTiming() {
        wall+=std::chrono::duration<double>(Clock::now()-begin).count();
        cpu+=std::max(0.0,workerCpuSeconds()-cpuBegin);
    }
};
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
    std::size_t probeLast,std::function<std::uint64_t()> allocationCounter,bool preciseBoundary)
    : file_(input),sampleRate_(WavStreamReader(input).sampleRate()),
      channels_(WavStreamReader(input).channels()),blockFrames_(blockFrames),
      leadFrames_(leadFrames ? leadFrames : fifoFrames),initial_(initial),planning_(planning),
      densityDiagnostic_(densityDiagnostic),enableProfile_(enableProfile),
      componentCsv_(std::move(componentCsv)),probeFirst_(probeFirst),probeLast_(probeLast),
      allocationCounter_(std::move(allocationCounter)),
      phase50PreciseBoundary_(preciseBoundary),
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
    workerSeenNs_=0;planNs_=0;requestedOutput_=0;requestedInput_=0;densityReady_=true;
    produced_=0;presented_=0;underrunFrames_=0;lastPublishedUnixNs_=0;lastPublishedMachNs_=0;
    profileRecordsDropped_=0;workerPcmSha_.clear();
    workerPcmHashEnabled_=std::getenv("PHASE46_PCM_SHA")!=nullptr;
    maxWorkerChunkSeconds_=0;
    maxWorkerCpuSeconds_=0;maxFifoWaitSeconds_=0;
    maxWorkerCycleSeconds_=0;maxWorkerCycleCpuSeconds_=0;
    fifoWaitNanoseconds_=0;workerChunksOver100Ms_=0;workerQosApplied_=false;stallObservation_={};
    planMilliseconds_=0;planCpuMilliseconds_=0;
    maxFifoWriteSeconds_=0;maxHistoryMutexWaitSeconds_=0;
    preparedAtPlan_=0;publishedAtPlan_=0;fifoAtPlan_=0;processedInputAtPlan_=0;
    planningFence_=0;
    appliedOutput_=0;completionOutput_=0;planCount_=0;appliedGeneration_=0;error_=nullptr;
    stageDigests_={};
    slowestBlocks_.clear();
    allBlockProfiles_.clear();
    guardMetrics_.clear();
    guardMetrics_.reserve(64);
    if (enableProfile_) {
        slowestBlocks_.reserve(20);
        allBlockProfiles_.reserve(16384);
    }
    { std::lock_guard lock(historyMutex_);
      plans_.clear(); plans_.reserve(64);
      workerChunkSeconds_.clear(); workerChunkSeconds_.reserve(65536); }
    { std::lock_guard lock(historyMutex_);
      workerCycleSeconds_.clear(); workerCycleSeconds_.reserve(65536); }
    outputLength_=static_cast<std::size_t>(std::llround(analysis_.inputFrames()*initial_.timeRatio()));
    worker_=std::thread([this] {
        try {
            // Research-only scheduling control. CoreAudio's render thread has
            // higher priority; the product default remains unchanged.
            if (std::getenv("PHASE44_WORKER_QOS"))
                workerQosApplied_.store(
                    pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED,0)==0,
                    std::memory_order_relaxed);
            Phase39TimeMap timeline(analysis_,sampleRate_,initial_,planning_);
            Phase36StreamingSpeedEngine engine(frozen(file_,initial_));
            Phase45PcmDigest pcmDigest;
            std::vector<float> interleaved(workerPcmHashEnabled_ ? blockFrames_*channels_ : 0);
            mach_timebase_info_data_t timebase{};mach_timebase_info(&timebase);
            const auto machNs=[&] {
                return static_cast<std::uint64_t>((static_cast<long double>(mach_absolute_time())*
                    timebase.numer)/timebase.denom);
            };
            std::ofstream componentOutput;
            if (!componentCsv_.empty()) {
                componentOutput.open(componentCsv_);
                if (!componentOutput) throw std::runtime_error("Component CSV open failed");
                componentOutput<<"sample,channel,low_raw,mid_raw,high_raw,lp250_diff,lp3500_diff,final\n";
            }
            auto previous=Clock::now();
            auto previousUnix=unixNowNs();
            auto previousMach=machNs();
            std::uint64_t workerTid=0;
            pthread_threadid_np(nullptr,&workerTid);
            auto previousCpu=workerCpuSeconds();
            auto previousNew=allocationCounter_ ? allocationCounter_() : 0;
            bool hasPublished=false;
            std::uint64_t cycleSequence=0;
            double planCycleWall=0,planCycleCpu=0;
            double planMutexWait=0,planMutexHold=0;
            double postPublicationMutexWait=0,postPublicationMutexHold=0;
            double postPauseWall=0,postPauseCpu=0;
            Phase39BlockProfile latestProfile;
            // Diagnostic producer stall, default disabled. Unlike a simulated
            // short read, this lets the consumer actually drain the FIFO.
            const double injectedStallMs=std::getenv("PHASE45_WORKER_STALL_MS") ?
                std::stod(std::getenv("PHASE45_WORKER_STALL_MS")) : 0;
            if (!std::isfinite(injectedStallMs) || injectedStallMs<0)
                throw std::invalid_argument("Invalid diagnostic worker stall");
            const double controlledMs=std::getenv("PHASE49_STALL_MS") ? std::stod(std::getenv("PHASE49_STALL_MS")) : 0;
            if (!std::isfinite(controlledMs) || controlledMs<0 || controlledMs>2000 || (controlledMs>0 && injectedStallMs>0))
                throw std::invalid_argument("Invalid controlled stall");
            const auto controlledOutput=std::getenv("PHASE49_STALL_OUTPUT") ? std::stoull(std::getenv("PHASE49_STALL_OUTPUT")) : std::size_t(sampleRate_*4.5);
            const auto controlledGoal=std::getenv("PHASE49_STALL_FIFO") ? std::stoull(std::getenv("PHASE49_STALL_FIFO")) : leadFrames_;
            if (controlledMs>0 && (!controlledOutput || controlledOutput>outputLength_.load() || !controlledGoal || controlledGoal>leadFrames_))
                throw std::invalid_argument("Invalid controlled stall frontier");
            stallObservation_.configured=controlledMs>0;stallObservation_.requestedMs=controlledMs;
            stallObservation_.outputThreshold=controlledOutput;stallObservation_.fifoGoal=controlledGoal;
            bool stalled=false;
            std::array<std::size_t,3> controlledNextInput{};
            const auto publish=[&](const float* const* data,std::size_t frames,
                                   const std::function<void()>& poll) {
                if (!stalled && injectedStallMs>0 && produced_.load()>=65536) {
                    stalled=true;
                    const auto until=Clock::now()+std::chrono::duration<double,std::milli>(injectedStallMs);
                    while (!stop_.load(std::memory_order_acquire) && Clock::now()<until)
                        std::this_thread::sleep_for(std::chrono::microseconds(100));
                }
                if (workerPcmHashEnabled_) {
                    if (frames>blockFrames_) throw std::runtime_error("PCM digest block exceeds workspace");
                    for (std::size_t i=0;i<frames;++i) for (std::size_t c=0;c<channels_;++c)
                        interleaved[i*channels_+c]=data[c][i];
                    pcmDigest.update(interleaved.data(),frames*channels_*sizeof(float));
                }
                const auto previousBookkeepingWait=postPublicationMutexWait;
                const auto previousBookkeepingHold=postPublicationMutexHold;
                const auto now=Clock::now();
                const auto seconds=std::chrono::duration<double>(now-previous).count();
                const auto cpuNow=workerCpuSeconds();
                const auto cpuSeconds=std::max(0.0,cpuNow-previousCpu);
                if (enableProfile_) {
                    latestProfile={};
                    latestProfile.cycleSequence=cycleSequence+1;
                    latestProfile.startUnixNs=previousUnix;
                    latestProfile.startMachNs=previousMach;
                    latestProfile.threadId=workerTid;
                    latestProfile.chunkWallSeconds=seconds;
                    latestProfile.chunkCpuSeconds=cpuSeconds;
                    latestProfile.injectedPauseWallSeconds=postPauseWall;
                    latestProfile.injectedPauseCpuSeconds=postPauseCpu;
                    latestProfile.allocationCounterEnabled=bool(allocationCounter_);
                }
                postPauseWall=postPauseCpu=0;
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
                const auto historyHold=
                    std::chrono::duration<double>(Clock::now()-mutexStart).count()-mutexWait;
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
                const auto fifoBefore=fifo_.available();
                if (!fifo_.write(data,frames)) throw std::runtime_error("Phase 39 FIFO overflow");
                const auto fifoAfter=fifo_.available();
                const auto writeSeconds=std::chrono::duration<double>(Clock::now()-writeStart).count();
                if (enableProfile_) latestProfile.fifoWriteSeconds=writeSeconds;
                auto oldWrite=maxFifoWriteSeconds_.load();
                while (oldWrite<writeSeconds &&
                       !maxFifoWriteSeconds_.compare_exchange_weak(oldWrite,writeSeconds)) {}
                produced_.fetch_add(frames,std::memory_order_release);
                ++cycleSequence;
                const auto publishedAt=Clock::now();
                const auto publishedUnix=unixNowNs();
                const auto publishedMach=machNs();
                lastPublishedUnixNs_.store(publishedUnix,std::memory_order_release);
                lastPublishedMachNs_.store(publishedMach,std::memory_order_release);
                const auto publishedCpu=workerCpuSeconds();
                const auto cycleSeconds=std::chrono::duration<double>(publishedAt-previous).count();
                const auto cycleCpu=std::max(0.0,publishedCpu-previousCpu);
                auto oldCycle=maxWorkerCycleSeconds_.load();
                while (oldCycle<cycleSeconds &&
                       !maxWorkerCycleSeconds_.compare_exchange_weak(oldCycle,cycleSeconds)) {}
                auto oldCycleCpu=maxWorkerCycleCpuSeconds_.load();
                while (oldCycleCpu<cycleCpu &&
                       !maxWorkerCycleCpuSeconds_.compare_exchange_weak(oldCycleCpu,cycleCpu)) {}
                { const auto lockBegin=Clock::now();
                  std::unique_lock lock(historyMutex_);
                  const auto wait=std::chrono::duration<double>(Clock::now()-lockBegin).count();
                  if (workerCycleSeconds_.size()<65536)
                      workerCycleSeconds_.push_back(cycleSeconds);
                  lock.unlock();
                  // This bookkeeping occurs after publication, so it belongs
                  // to the NEXT publication-to-publication worker cycle.
                  postPublicationMutexWait=wait;
                  postPublicationMutexHold=
                      std::chrono::duration<double>(Clock::now()-lockBegin).count()-wait; }
                if (enableProfile_) {
                    // poll() can plan while waiting for FIFO space. Account for
                    // its mutex and planning time before clearing cycle totals.
                    latestProfile.mutexWaitSeconds=
                        mutexWait+planMutexWait+previousBookkeepingWait;
                    latestProfile.mutexHoldSeconds=
                        historyHold+planMutexHold+previousBookkeepingHold;
                    latestProfile.endUnixNs=publishedUnix;
                    latestProfile.publishedMachNs=publishedMach;
                    latestProfile.publicationFrames=frames;
                    latestProfile.fifoBeforeWrite=fifoBefore;
                    latestProfile.fifoAfterWrite=fifoAfter;
                    latestProfile.fullCycleWallSeconds=cycleSeconds;
                    latestProfile.fullCycleCpuSeconds=cycleCpu;
                    latestProfile.publicationIntervalSeconds=
                        hasPublished ? latestProfile.fullCycleWallSeconds : -1.0;
                    latestProfile.planWallSeconds=planCycleWall;
                    latestProfile.planCpuSeconds=planCycleCpu;
                    if (allocationCounter_)
                        latestProfile.cppNewCalls=allocationCounter_()-previousNew;
                }
                previous=publishedAt;
                hasPublished=true;
                previousUnix=publishedUnix;
                previousMach=publishedMach;
                previousCpu=publishedCpu;
                if (allocationCounter_) previousNew=allocationCounter_();
                planCycleWall=planCycleCpu=0;
                planMutexWait=planMutexHold=0;
                // After a real publication, wait only when the requested stock
                // is observed. No DSP/history is reset and the consumer runs.
                if (controlledMs>0 && !stallObservation_.triggered &&
                    produced_.load(std::memory_order_acquire)>=controlledOutput) {
                    // Research-only stock control: drain to the requested
                    // starting stock before the timed pause. This preparatory
                    // supply gap is separately visible in publication times.
                    if (std::getenv("PHASE50_STALL_DRAIN"))
                        while (!stop_.load(std::memory_order_acquire) && fifo_.available()>controlledGoal)
                            std::this_thread::sleep_for(std::chrono::microseconds(50));
                    const auto sampledAt=machNs();const auto stock=fifo_.available();
                    if (stock==controlledGoal) {
                        auto& o=stallObservation_;o.triggered=true;o.startMachNs=sampledAt;
                        o.measurementEndMachNs=machNs();o.fifoBefore=stock;o.threadId=workerTid;
                        o.publishedFrames=produced_.load();o.cycleSequence=cycleSequence;o.nextInput=controlledNextInput;
                        const auto cpuStart=workerCpuSeconds();
                        const auto until=Clock::now()+std::chrono::duration<double,std::milli>(controlledMs);
                        while (!stop_.load(std::memory_order_acquire) && Clock::now()<until)
                            std::this_thread::sleep_for(std::chrono::microseconds(100));
                        o.endMachNs=machNs();o.fifoAfter=fifo_.available();o.cancelled=stop_.load();
                        o.wallSeconds=(o.endMachNs-o.startMachNs)/1e9;
                        o.cpuSeconds=std::max(0.0,workerCpuSeconds()-cpuStart);
                        postPauseWall=o.wallSeconds;postPauseCpu=o.cpuSeconds;
                    }
                }
            };
            const auto plan=[&](const Phase36StreamingSpeedEngine::Frontier& frontier,
                                 TimeMap& map,std::size_t& length,
                                 std::vector<std::pair<std::size_t,bool>>& modeChanges) {
                if(controlledMs>0)controlledNextInput=frontier.nextInput;
                densityReady_.store(modeChanges.empty() || std::all_of(frontier.nextInput.begin(),frontier.nextInput.end(),
                    [&](auto p){return p>modeChanges.back().first;}),std::memory_order_release);
                if (state_.load(std::memory_order_acquire)!=Phase39RequestState::Requested)
                    return;
                ScopedPlanTiming planTiming{planCycleWall,planCycleCpu};
                workerSeenNs_.store(nowNs(),std::memory_order_relaxed);
                const auto committed=frontier.preparedOutput;
                const auto asked=requestedOutput_.load(std::memory_order_relaxed);
                const Phase39Speed target{targetMicros_.load(std::memory_order_relaxed)};
                const Phase39Speed from{currentTailMicros_.load(std::memory_order_relaxed)};
                const auto generation=generation_.load(std::memory_order_relaxed);
                if (generation==1 && std::getenv("PHASE44_FORCE_NO_SAFE_FIRST")) {
                    planOutcome_.store(Phase39Outcome::NoSafeInterval,
                                       std::memory_order_relaxed);
                    planNs_.store(nowNs(),std::memory_order_relaxed);
                    state_.store(Phase39RequestState::Rejected,
                                 std::memory_order_release);
                    return;
                }
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
                std::array<std::size_t,3> immutableOutputs{},densityOutputs{};
                constexpr std::array<std::size_t,3> hops={2048,1024,256};
                for (std::size_t r=0;r<3;++r) {
                    const auto firstMutableNode=frontier.lastProcessedInput[r]/1024+1;
                    const auto node=std::min(firstMutableNode,map.starts().size()-1);
                    immutableOutputs[r]=static_cast<std::size_t>(map.starts()[node]);
                    fence=std::max(fence,immutableOutputs[r]);
                    const auto densityNode=std::min(
                        (frontier.nextInput[r]+hops[r]+1023)/1024,
                        map.starts().size()-1);
                    densityOutputs[r]=static_cast<std::size_t>(map.starts()[densityNode]);
                    fence=std::max(fence,densityOutputs[r]);
                    fence=std::max(fence,frontier.finalizedOla[r]);
                }
                // The 2049-tap low FIR may reference 1024 future samples.
                // Add a whole block of margin to cover transformed source
                // blocks and the zero-phase contribution before the change.
                for (const auto sourcePosition:frontier.firstUnprocessedFirSource)
                    fence=std::max(fence,sourcePosition+4096);
                const auto boundaryAudit=phase50Boundary(frontier,map,published);
                if (boundaryAudit.legacy!=fence) throw std::logic_error("Legacy boundary audit differs");
                if (phase50PreciseBoundary_) fence=boundaryAudit.precise;
                planningFence_.store(fence,std::memory_order_relaxed);
                const auto requestInput=inverseInput(map,asked);
                requestedInput_.store(requestInput,std::memory_order_relaxed);
                const auto beginPlan=Clock::now();
                const auto beginPlanCpu=workerCpuSeconds();
                const auto reject=[&](Phase39Outcome outcome) {
                    planOutcome_.store(outcome,std::memory_order_relaxed);
                    planMilliseconds_.store(std::chrono::duration<double,std::milli>(
                        Clock::now()-beginPlan).count(),std::memory_order_relaxed);
                    planCpuMilliseconds_.store((workerCpuSeconds()-beginPlanCpu)*1000.0,
                                                std::memory_order_relaxed);
                    planNs_.store(nowNs(),std::memory_order_relaxed);
                    state_.store(Phase39RequestState::Rejected,std::memory_order_release);
                };
                auto candidate=timeline;
                const auto proposal=candidate.submit({generation,target,requestInput,
                    static_cast<long long>(fence),50.0});
                planOutcome_.store(proposal.outcome,std::memory_order_relaxed);
                if (!proposal.applied()) {
                    reject(proposal.outcome);
                    return;
                }
                if (!candidate.monotonic() || candidate.touchesProtected(proposal)) {
                    reject(Phase39Outcome::NoSafeInterval);
                    return;
                }
                const bool statePreserved=phase50PreservesState(frontier,map,candidate.current());
                if (phase50PreciseBoundary_ && !statePreserved) {
                    reject(Phase39Outcome::NoSafeInterval);
                    return;
                }
                const auto newLength=static_cast<std::size_t>(std::llround(
                    candidate.current().outputPositionForInputSample(
                        double(analysis_.inputFrames()))));
                if (newLength<=std::max({committed,
                        frontier.firstUnprocessedFirSource[0],
                        frontier.firstUnprocessedFirSource[1]})+blockFrames_) {
                    reject(Phase39Outcome::Truncated);
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
                        reject(Phase39Outcome::NoSafeInterval);
                        return;
                    }
                    densityDecision=chooseSafeDensitySwitch(candidate.current(),proposal,
                        frontier,modeChanges,from.value()<0.50,target.value()<0.50,
                        fence,analysis_.inputFrames(),enableProfile_);
                    guardMetrics_.push_back({generation,fifo_.available(),densityDecision});
                    if (!densityDecision.safe) {
                        reject(Phase39Outcome::NoSafeInterval);
                        return;
                    }
                    modeInput=densityDecision.inputSample;
                }
                if (changesDensity && modeInput<=*std::max_element(
                        frontier.lastProcessedInput.begin(),frontier.lastProcessedInput.end())) {
                    reject(Phase39Outcome::NoSafeInterval);
                    return;
                }
                std::array<std::size_t,4> holds{};
                for (auto i=proposal.firstMutableFrame;i<proposal.appliedFrame;++i)
                    if (timeline.diagnosticProtected(i) || !timeline.diagnosticSafeRun(i))
                        holds[timeline.diagnosticProtected(i) ? 0 : 1]+=map.starts()[i+1]-map.starts()[i];
                for (auto i=proposal.appliedFrame;i<proposal.rampEndFrame;++i)
                    if (candidate.diagnosticProtected(i) || !candidate.diagnosticSafeRun(i))
                        holds[candidate.diagnosticProtected(i) ? 2 : 3]+=candidate.current().starts()[i+1]-candidate.current().starts()[i];
                timeline=std::move(candidate);
                map=timeline.current();
                if (changesDensity)
                    modeChanges.emplace_back(modeInput,target.value()<0.50);
                    densityReady_.store(false,std::memory_order_release);
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
                { const auto lockBegin=Clock::now();
                  std::unique_lock lock(historyMutex_);
                  const auto lockWait=std::chrono::duration<double>(Clock::now()-lockBegin).count();
                  planMutexWait+=lockWait;
                  plans_.push_back({proposal,from,target,generation,
                      requestNs_.load(std::memory_order_relaxed),nowNs(),
                      asked,requestInput,fence,committed,published,firstInput,
                      frontier.nextInput,frontier.lastProcessedInput,
                      frontier.finalizedOla,frontier.firstUnprocessedFirSource,
                      modeInput,densityDecision.maximumHop,densityDecision.maximumHopStep,
                      densityDecision.minimumWeight,densityDecision.minimumLocalSpeed,
                      densityDecision.maximumLocalSpeed,
                      densityDecision.candidatesTried,timeline.fixedMapBytes(),milliseconds,
                      immutableOutputs,densityOutputs,fifoAtPlan_.load(),
                      changesDensity ? std::size_t(std::llround(map.outputPositionForInputSample(double(modeInput)))) : 0,holds,
                      boundaryAudit.precise,boundaryAudit.legacy,statePreserved});
                  lock.unlock();
                  planMutexHold+=std::chrono::duration<double>(Clock::now()-lockBegin).count()-
                      lockWait; }
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
                    if (allBlockProfiles_.size()<allBlockProfiles_.capacity())
                        allBlockProfiles_.push_back(latestProfile);
                    else profileRecordsDropped_.fetch_add(1,std::memory_order_relaxed);
                    if (slowestBlocks_.size()<20) slowestBlocks_.push_back(latestProfile);
                    else {
                        const auto weakest=std::min_element(slowestBlocks_.begin(),
                            slowestBlocks_.end(),[](const auto& a,const auto& b) {
                                return a.fullCycleWallSeconds<b.fullCycleWallSeconds;
                            });
                        if (latestProfile.fullCycleWallSeconds>weakest->fullCycleWallSeconds)
                            *weakest=latestProfile;
                    }
                }) : Phase36StreamingSpeedEngine::ProfileHook{};
            const auto result=engine.process(file_,analysis_,timeline.current(),outputLength_.load(),
                blockFrames_,[&](const float* const* data,std::size_t frames,
                                         const std::function<void()>& poll) {
                    publish(data,frames,poll);
                },plan,{},profileHook,
                componentOutput ? &componentOutput : nullptr,probeFirst_,probeLast_,
                densityDiagnostic_==Phase39DensityDiagnostic::SafeGuarded);
            stageDigests_=result.stages;
            if (workerPcmHashEnabled_) workerPcmSha_=pcmDigest.finish();
        } catch (const Stopped&) {
        } catch (...) { error_=std::current_exception(); }
        auto pending=Phase39RequestState::Requested;
        state_.compare_exchange_strong(pending,Phase39RequestState::Cancelled,
            std::memory_order_acq_rel,std::memory_order_relaxed);
        finished_.store(true,std::memory_order_release);
    });
    started_.store(true,std::memory_order_release);
}
std::string Phase39PlaybackPipeline::workerPcmSha() const {
    if (!finished_.load(std::memory_order_acquire))
        throw std::logic_error("PCM digest available after worker completion");
    return workerPcmHashEnabled_ ? workerPcmSha_ : "unmeasured";
}
std::vector<Phase39BlockProfile> Phase39PlaybackPipeline::slowestBlocks() const {
    if (!finished_.load(std::memory_order_acquire))
        throw std::logic_error("Profile is available after worker completion");
    auto result=slowestBlocks_;
    std::sort(result.begin(),result.end(),[](const auto& a,const auto& b) {
        return a.fullCycleWallSeconds>b.fullCycleWallSeconds;
    });
    return result;
}
std::vector<Phase39BlockProfile> Phase39PlaybackPipeline::allBlockProfiles() const {
    if (!finished_.load(std::memory_order_acquire))
        throw std::logic_error("Profile is available after worker completion");
    return allBlockProfiles_;
}
std::vector<Phase39GuardMetric> Phase39PlaybackPipeline::guardMetrics() const {
    if (!finished_.load(std::memory_order_acquire))
        throw std::logic_error("Guard metrics are available after worker completion");
    return guardMetrics_;
}
Phase49StallObservation Phase39PlaybackPipeline::stallObservation() const {
    if (!finished_.load(std::memory_order_acquire)) throw std::logic_error("Stall observation available after completion");
    return stallObservation_;
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
    value.maxWorkerCycleSeconds=maxWorkerCycleSeconds_.load();
    value.maxWorkerCycleCpuSeconds=maxWorkerCycleCpuSeconds_.load();
    value.maxFifoWaitSeconds=maxFifoWaitSeconds_.load();
    value.maxFifoWriteSeconds=maxFifoWriteSeconds_.load();
    value.maxHistoryMutexWaitSeconds=maxHistoryMutexWaitSeconds_.load();
    value.fifoWaitNanoseconds=fifoWaitNanoseconds_.load();
    value.workerChunksOver100Ms=workerChunksOver100Ms_.load();
    value.workerQosApplied=workerQosApplied_.load();
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
double Phase39PlaybackPipeline::workerCycleP95Seconds() const {
    std::vector<double> durations;
    { std::lock_guard lock(historyMutex_); durations=workerCycleSeconds_; }
    if (durations.empty()) return 0;
    const auto index=static_cast<std::size_t>(std::ceil(durations.size()*0.95))-1;
    std::nth_element(durations.begin(),durations.begin()+index,durations.end());
    return durations[index];
}
double Phase39PlaybackPipeline::workerCycleP99Seconds() const {
    std::vector<double> durations;
    { std::lock_guard lock(historyMutex_); durations=workerCycleSeconds_; }
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
