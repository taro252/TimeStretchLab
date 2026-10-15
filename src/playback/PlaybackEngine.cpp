#include "playback/PlaybackEngine.h"
#include <cstring>
#include <algorithm>
#include <stdexcept>
#include <cmath>
namespace ts::playback {
using namespace prototype;
namespace {
std::uint64_t now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
void silence(float*const* out,std::size_t channels,std::size_t first,std::size_t last){for(std::size_t c=0;c<channels;++c)std::fill(out[c]+first,out[c]+last,0.f);}
}
struct PlaybackEngine::RenderCounters {
    Phase39PlaybackPipeline* pipeline=nullptr;std::uint64_t session=0;
    std::atomic<std::uint64_t> calls{0},consumed{0},presented{0},missing{0},underruns{0},continuous{0},maxContinuous{0};
    std::atomic<std::uint64_t> firstMissing{0},lastMissing{0},eventSequence{0},concurrent{0};
    std::array<UnderrunEvent,2048> events{};
};
static_assert(std::atomic<std::uint64_t>::is_always_lock_free);
static_assert(std::atomic<void*>::is_always_lock_free);
PlaybackEngine::PlaybackEngine(){renderCounters_=std::make_shared<RenderCounters>();renderCountersPtr_=renderCounters_.get();control_=std::thread([this]{while(!exitControl_.load()){tick();std::this_thread::sleep_for(std::chrono::milliseconds(1));}});}
PlaybackEngine::~PlaybackEngine(){exitControl_=true;if(control_.joinable())control_.join();stop();}
void PlaybackEngine::inhibitRender(){renderEnabled_.store(false,std::memory_order_seq_cst);while(inRender_.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));}
void PlaybackEngine::record(const SpeedOperation& op){if(history_.size()==4096){history_.pop_front();++historyDrops_;}history_.push_back(op);}
void PlaybackEngine::cancelCommands(){for(auto* op:{&pending_,&active_})if(*op){(*op)->status=SpeedStatus::Cancelled;record(**op);op->reset();}}
void PlaybackEngine::resetSession(std::size_t start,std::shared_ptr<RenderCounters> ready){
    if(!ready)ready=std::make_shared<RenderCounters>();
    ready->consumed=start;ready->presented=start;ready->session=++session_;ready->pipeline=pipeline_.get();
    auto previous=renderCounters_;
    renderCounters_=std::move(ready);renderCountersPtr_.store(renderCounters_.get(),std::memory_order_seq_cst);
    while(inRender_.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
    reason_=StopReason::None;error_.clear();
}
void PlaybackEngine::recordSeek(const SeekSnapshot& s){if(seekHistory_.size()==128)seekHistory_.pop_front();seekHistory_.push_back(s);}
void PlaybackEngine::cancelSeeks(){
    ++seekVersion_;
    for(auto* op:{&pendingSeek_,&activeSeek_})if(*op){(*op)->status=SeekStatus::Cancelled;(*op)->readyNs=now();recordSeek(**op);if(seekSnapshot_.id==(*op)->id)seekSnapshot_=**op;op->reset();}
}
void PlaybackEngine::prepareLocked(std::optional<std::size_t> startInput){
    StageClock total;startup_={};
    inhibitRender();if(pipeline_)pipeline_->stop();pipeline_.reset();
    auto speed=Phase39Speed::fromDouble(config_.initialSpeed);
    state_=PlaybackState::Preparing;
    auto options=config_.verificationHooks;options.pcmHash=config_.verifyRawPcm;options.publishPositionMap=true;
    options.userInitiatedQos=false; // Both frozen presets inherit QoS.
    const auto dsp=config_.dspOptions();options.startInputFrame=startInput;segmentInput_=startInput;sessionStarted_=false;
    auto cache=config_.reuseAnalysis ? (config_.analysisCache ? config_.analysisCache : PlaybackAnalysisCache::sharedDefault()) : uncached_;
    analysisLease_.reset();
    analysisLease_=std::make_shared<const AnalysisLease>(cache->acquire(input_,startup_));
    const auto cacheState=cache->diagnostics();startup_.analysisBytes=analysisLease_->data->bytes;
    startup_.cacheResidentBytes=cacheState.residentBytes;startup_.cacheLimitBytes=cacheState.limitBytes;
    startup_.analysisRuns=cacheState.analyses;startup_.cacheHits=cacheState.hits;startup_.bytesHashed=cacheState.bytesHashed;
    Phase54PreparedInput prepared{analysisLease_->data->analysis,analysisLease_,[lease=analysisLease_]{lease->validate();}};
    StageClock pipelineClock;
    pipeline_=std::make_unique<Phase39PlaybackPipeline>(analysisLease_->path(),speed,config_.fifoFrames(),config_.blockFrames(),config_.leadFrames(),
        dsp.timeMapMode==TimeMapMode::OutputTimeL2?Phase39Planning::L2:Phase39Planning::C,Phase39DensityDiagnostic::SafeGuarded,
        config_.detailedDiagnostics,std::filesystem::path{},0,0,std::function<std::uint64_t()>{},dsp.preciseBoundaryL1,options,std::move(prepared));
    startup_.pipeline=pipelineClock.elapsed();
    if(pipeline_->channels()<1||pipeline_->channels()>2)throw std::invalid_argument("Only mono/stereo input is supported");
    rate_=pipeline_->sampleRate();channels_=pipeline_->channels();
    requested_=applied_=speed.micros;resetSession(0);
    seekSnapshot_={};seekSnapshot_.session=session_;
    state_=PlaybackState::Ready;startup_.prepare=total.elapsed();
}
bool PlaybackEngine::prepare(const std::filesystem::path& input,Configuration config){
    Phase39Speed::fromDouble(config.initialSpeed);
    if(config.preset!=Preset::Candidate&&config.preset!=Preset::Baseline)throw std::invalid_argument("Unknown preset");
    std::lock_guard lock(mutex_);
    if(state_==PlaybackState::Playing||state_==PlaybackState::Paused||state_==PlaybackState::Preparing)throw std::logic_error("Stop before changing input/preset");
    cancelSeeks();cancelCommands();input_=input;config_=config;
    try{prepareLocked();return true;}catch(const std::exception&e){failLocked(e.what());return false;}
}
bool PlaybackEngine::play(){
    std::lock_guard lock(mutex_);
    if(pendingSeek_||activeSeek_)return false;
    if(state_==PlaybackState::Paused)return false; // Explicit resume preserves state.
    if(state_==PlaybackState::Playing)return true;
    try{
        if(state_==PlaybackState::Stopped||state_==PlaybackState::Ended){config_.initialSpeed=getRequestedSpeed();prepareLocked();}
        if(state_!=PlaybackState::Ready)return false;
        if(pipeline_->snapshot().initial!=Phase39Speed::fromDouble(config_.initialSpeed))prepareLocked(segmentInput_);
        StageClock prefillClock;if(!sessionStarted_){pipeline_->start();sessionStarted_=true;}
        while(!pipeline_->startPositionReady()&&!pipeline_->finished())std::this_thread::sleep_for(std::chrono::microseconds(100));
        if(pipeline_->finished())pipeline_->rethrowWorkerError();
        const auto start=pipeline_->outputStartFrame();renderCounters_->consumed=start;renderCounters_->presented=start;
        const auto frames=std::min(config_.leadFrames(),pipeline_->snapshot().outputLength-start);
        if(!pipeline_->waitForPrefill(frames,std::chrono::seconds(120))){if(pipeline_->finished())pipeline_->rethrowWorkerError();throw std::runtime_error("Playback prefill failed");}
        startup_.prefill=prefillClock.elapsed();
        state_=PlaybackState::Playing;renderEnabled_.store(true,std::memory_order_seq_cst);return true;
    }catch(const std::exception&e){failLocked(e.what());return false;}
}
bool PlaybackEngine::pause(){std::lock_guard lock(mutex_);if(state_!=PlaybackState::Playing)return false;inhibitRender();state_=PlaybackState::Paused;return true;}
bool PlaybackEngine::resume(){std::lock_guard lock(mutex_);if(state_!=PlaybackState::Paused)return false;state_=PlaybackState::Playing;renderEnabled_.store(true,std::memory_order_seq_cst);return true;}
void PlaybackEngine::stop(StopReason reason){std::lock_guard lock(mutex_);inhibitRender();cancelSeeks();cancelCommands();if(pipeline_)pipeline_->stop();reason_=reason;state_=PlaybackState::Stopped;}
void PlaybackEngine::failLocked(const std::string& text){inhibitRender();cancelSeeks();cancelCommands();if(pipeline_)pipeline_->stop();error_=text;reason_=StopReason::WorkerError;state_=PlaybackState::Failed;}
std::uint64_t PlaybackEngine::setSpeed(double value){
    auto speed=Phase39Speed::fromDouble(value);std::lock_guard lock(mutex_);requested_=speed.micros;
    SpeedOperation op;op.id=++nextOperation_;op.session=session_;op.target=speed.value();op.observedNs=now();
    if(pending_){pending_->status=SpeedStatus::Replaced;record(*pending_);pending_.reset();}
    if(state_==PlaybackState::Empty||state_==PlaybackState::Preparing||state_==PlaybackState::Failed||state_==PlaybackState::Ended){op.status=SpeedStatus::Rejected;record(op);return op.id;}
    if(state_==PlaybackState::Ready||state_==PlaybackState::Stopped){config_.initialSpeed=speed.value();op.status=SpeedStatus::Configured;record(op);return op.id;}
    pending_=op;return op.id;
}
std::uint64_t PlaybackEngine::seekToInputSeconds(double seconds){
    if(!std::isfinite(seconds)||seconds<0)throw std::invalid_argument("Finite nonnegative seek seconds required");
    const auto rate=sampleRate();if(!rate)throw std::logic_error("Prepare before seconds-based seek");
    const auto value=seconds*rate;if(value>double(std::numeric_limits<std::uint64_t>::max()/2))throw std::out_of_range("Seek seconds overflow");
    return seekToInputFrame(static_cast<std::uint64_t>(std::llround(value)));
}
std::uint64_t PlaybackEngine::seekToInputFrame(std::uint64_t frame){
    std::lock_guard lock(mutex_);SeekSnapshot request;request.id=++nextSeek_;request.session=session_;request.requestedInputFrame=frame;request.observedNs=now();request.initialSpeed=getRequestedSpeed();
    if(!analysisLease_||frame>analysisLease_->data->analysis.inputFrames()||
       (state_!=PlaybackState::Ready&&state_!=PlaybackState::Playing&&state_!=PlaybackState::Paused)){
        request.status=SeekStatus::Rejected;request.reason="Seek requires Ready/Playing/Paused and an in-range input frame";request.readyNs=now();recordSeek(request);seekSnapshot_=request;return request.id;
    }
    for(auto* previous:{&pendingSeek_,&activeSeek_})if(*previous){(*previous)->status=SeekStatus::Replaced;(*previous)->readyNs=now();recordSeek(**previous);previous->reset();}
    request.status=SeekStatus::Pending;pendingSeek_=request;seekSnapshot_=request;seekVersion_=request.id;return request.id;
}
SeekSnapshot PlaybackEngine::getSeekSnapshot()const{std::lock_guard lock(mutex_);auto s=seekSnapshot_;s.activeId=activeSeek_?activeSeek_->id:0;s.pendingId=pendingSeek_?pendingSeek_->id:0;return s;}
std::vector<SegmentEvidence> PlaybackEngine::closedSegmentEvidence()const{std::lock_guard lock(mutex_);return {closedSegments_.begin(),closedSegments_.end()};}
std::vector<SeekSnapshot> PlaybackEngine::seekHistory()const{std::lock_guard lock(mutex_);return {seekHistory_.begin(),seekHistory_.end()};}
void PlaybackEngine::performSeek(std::unique_lock<std::mutex>& lock){
    auto request=*pendingSeek_;request.initialSpeed=getRequestedSpeed();pendingSeek_.reset();request.status=SeekStatus::Preparing;activeSeek_=request;if(seekSnapshot_.id<=request.id)seekSnapshot_=request;
    // Keep the old stream intact until the replacement FIFO is prepared.
    const auto path=input_;const auto expectedContent=analysisLease_->data->contentSha256;auto config=config_;config.initialSpeed=request.initialSpeed;
    auto cache=config.reuseAnalysis ? (config.analysisCache?config.analysisCache:PlaybackAnalysisCache::sharedDefault()) : uncached_;
    lock.unlock();
    try{
        StageClock total;StartupDiagnostics timing;
        auto lease=std::make_shared<const AnalysisLease>(cache->acquire(path,timing));
        if(lease->data->contentSha256!=expectedContent)throw std::runtime_error("Input contents changed; explicit prepare required");
        if(seekVersion_.load()!=request.id||exitControl_) {lock.lock();return;}
        auto options=config.verificationHooks;options.pcmHash=config.verifyRawPcm;options.publishPositionMap=true;options.userInitiatedQos=false;options.startInputFrame=request.requestedInputFrame;
        auto dsp=config.dspOptions();StageClock construct;
        auto next=std::make_unique<Phase39PlaybackPipeline>(lease->path(),Phase39Speed::fromDouble(config.initialSpeed),config.fifoFrames(),config.blockFrames(),config.leadFrames(),
            dsp.timeMapMode==TimeMapMode::OutputTimeL2?Phase39Planning::L2:Phase39Planning::C,Phase39DensityDiagnostic::SafeGuarded,config.detailedDiagnostics,std::filesystem::path{},0,0,std::function<std::uint64_t()>{},dsp.preciseBoundaryL1,options,
            Phase54PreparedInput{lease->data->analysis,lease,[lease]{lease->validate();}});
        timing.pipeline=construct.elapsed();StageClock prefill;next->start();
        const auto cancelled=[&]{return seekVersion_.load()!=request.id||exitControl_.load();};
        while(!next->startPositionReady()&&!next->finished()&&!cancelled())std::this_thread::sleep_for(std::chrono::microseconds(100));
        const auto start=next->outputStartFrame();const auto goal=std::min(config.leadFrames(),next->snapshot().outputLength-start);
        unsigned checks=0;
        while(next->available()<goal&&!next->finished()&&!cancelled()){
            if(++checks%10==0){std::lock_guard current(mutex_);if(seekVersion_.load()==request.id&&pipeline_)refreshActiveSpeed();}
            if(prefill.elapsed().wallSeconds>120)throw std::runtime_error("Seek reconstruction timed out");
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        }
        if(cancelled()){next->stop();lock.lock();return;}
        if(next->finished())next->rethrowWorkerError();if(next->available()<goal)throw std::runtime_error("Seek prefill failed");
        timing.prefill=prefill.elapsed();timing.prepare=total.elapsed();auto cacheState=cache->diagnostics();timing.analysisBytes=lease->data->bytes;timing.cacheResidentBytes=cacheState.residentBytes;timing.cacheLimitBytes=cacheState.limitBytes;timing.analysisRuns=cacheState.analyses;timing.cacheHits=cacheState.hits;timing.bytesHashed=cacheState.bytesHashed;
        auto nextRender=std::make_shared<RenderCounters>();
        lock.lock();if(cancelled()){lock.unlock();next->stop();lock.lock();return;}
        if(Phase39Speed::fromDouble(getRequestedSpeed())!=Phase39Speed::fromDouble(config.initialSpeed)){
            request.initialSpeed=getRequestedSpeed();++request.replans;request.status=SeekStatus::Pending;
            pendingSeek_=request;activeSeek_.reset();if(seekSnapshot_.id<=request.id)seekSnapshot_=request;lock.unlock();next->stop();lock.lock();return;
        }
        std::optional<SpeedOperation> configured;
        if(pending_&&pending_->observedNs>=request.observedNs){configured=pending_;pending_.reset();}
        cancelCommands();
        struct Retirement {
            std::atomic<unsigned>& readers;std::atomic<RenderCounters*>& published;std::atomic<bool>& enabled;
            std::shared_ptr<RenderCounters> counters;std::unique_ptr<Phase39PlaybackPipeline> pipeline;
            void finish(){if(!pipeline)return;if(published.load(std::memory_order_seq_cst)==counters.get())enabled=false;
                while(readers.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
                pipeline->stop();pipeline.reset();counters.reset();}
            ~Retirement(){finish();}
        };
        request.readyNs=now();auto retiredLease=analysisLease_;const auto restore=state_.load();Retirement old{inRender_,renderCountersPtr_,renderEnabled_,renderCounters_,std::move(pipeline_)};
        pipeline_=std::move(next);analysisLease_=std::move(lease);startup_=timing;config_.initialSpeed=config.initialSpeed;segmentInput_=request.requestedInputFrame;sessionStarted_=true;
        resetSession(start,std::move(nextRender));applied_=Phase39Speed::fromDouble(config.initialSpeed).micros;
        if(configured){configured->session=session_;configured->status=SpeedStatus::Configured;record(*configured);}
        state_=restore;renderEnabled_.store(restore==PlaybackState::Playing,std::memory_order_seq_cst);
        request.status=SeekStatus::Completed;request.outputFrame=start;request.session=session_;if(seekSnapshot_.id<=request.id)seekSnapshot_=request;recordSeek(request);activeSeek_.reset();
        // Readers pin their segment with inRender before loading the pointer.
        // Keep the retired segment/pipeline alive through a quiescent point.
        lock.unlock();while(inRender_.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
        SegmentEvidence audit;
        while(inRender_.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
        if(old.pipeline){
            old.pipeline->stop();auto snap=old.pipeline->snapshot();audit.session=old.counters->session;
            audit.outputStart=old.pipeline->outputStartFrame();audit.publishedEnd=snap.produced;audit.consumedEnd=old.counters->consumed;
            audit.outputLength=snap.outputLength;audit.sampleRate=old.pipeline->sampleRate();audit.channels=old.pipeline->channels();
            audit.initialSpeed=snap.initial.value();audit.preset=config.preset;audit.missingFrames=old.counters->missing;
            audit.contentSha256=retiredLease->data->contentSha256;
            if(config.verifyRawPcm){
                if(old.pipeline->finished()){audit.rawPcmSha256=old.pipeline->workerPcmSha();audit.plans=old.pipeline->planMetrics();}
                else audit.rawPcmSha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
            }
            try{if(old.pipeline->finished())old.pipeline->rethrowWorkerError();}catch(const std::exception& e){audit.workerError=e.what();}
        }
        old.finish();lock.lock();
        if(audit.session){if(closedSegments_.size()==16)closedSegments_.pop_front();closedSegments_.push_back(std::move(audit));}
    }catch(const std::exception& e){
        if(!lock.owns_lock())lock.lock();if(seekVersion_.load()==request.id){request.status=SeekStatus::Failed;request.reason=e.what();request.readyNs=now();if(seekSnapshot_.id<=request.id)seekSnapshot_=request;recordSeek(request);activeSeek_.reset();}
    }
}
void PlaybackEngine::refreshActiveSpeed(){
        const auto snap=pipeline_->snapshot();
        if(active_){
            if(snap.generation!=active_->generation)throw std::runtime_error("Playback generation mismatch");
            if(snap.state==Phase39RequestState::Rejected||snap.state==Phase39RequestState::Cancelled){active_->status=snap.state==Phase39RequestState::Rejected?SpeedStatus::Rejected:SpeedStatus::Cancelled;active_->outcome=snap.planOutcome;record(*active_);active_.reset();}
            else if(snap.state==Phase39RequestState::Applied){
                applied_=Phase39Speed::fromDouble(active_->target).micros;active_->status=SpeedStatus::Applied;
                active_->applyOutput=snap.appliedOutput;active_->completeOutput=snap.completionOutput;
                if(pipeline_->researchTransitionComplete()){active_->status=SpeedStatus::Completed;active_->completedNs=now();record(*active_);active_.reset();}
            }
        }
        if(pipeline_->finished())pipeline_->rethrowWorkerError();
}
void PlaybackEngine::tick(){
    std::unique_lock lock(mutex_);if(pendingSeek_){performSeek(lock);return;}if(!pipeline_||(state_!=PlaybackState::Playing&&state_!=PlaybackState::Paused))return;
    try{
        refreshActiveSpeed();
        if(pipeline_->drained()){inhibitRender();cancelCommands();reason_=StopReason::EndOfStream;state_=PlaybackState::Ended;return;}
        if(state_==PlaybackState::Playing&&!active_&&pending_&&pipeline_->researchCommandReady()){
            const auto result=pipeline_->requestSpeed(Phase39Speed::fromDouble(pending_->target),renderCounters_->consumed.load());
            if(result==Phase39RequestResult::Accepted){pending_->session=session_;active_=pending_;pending_.reset();active_->sentNs=now();active_->generation=pipeline_->snapshot().generation;active_->status=SpeedStatus::Submitted;}
            else if(result!=Phase39RequestResult::Busy){pending_->status=result==Phase39RequestResult::Duplicate?SpeedStatus::Duplicate:SpeedStatus::Rejected;record(*pending_);pending_.reset();}
        }
    }catch(const std::exception&e){failLocked(e.what());}
}
RenderResult PlaybackEngine::renderAudio(float*const* output,std::size_t frames,std::uint64_t timestamp) noexcept{
    RenderResult result;inRender_.fetch_add(1,std::memory_order_seq_cst);
    const auto channels=channels_.load(std::memory_order_relaxed);
    auto* render=renderCountersPtr_.load(std::memory_order_seq_cst);
    if(renderBusy_.test_and_set(std::memory_order_acquire)){render->concurrent.fetch_add(1);silence(output,channels,0,frames);inRender_.fetch_sub(1,std::memory_order_seq_cst);return result;}
    if(renderEnabled_.load(std::memory_order_seq_cst)){
        auto* p=render->pipeline;result.session=render->session;result.outputBefore=render->consumed.load();
        const auto marker=p->realtimeMarkers();const auto available=p->available();result.fifoBefore=available;
        result.wanted=std::min<std::size_t>(frames,marker.outputLength>result.outputBefore?marker.outputLength-result.outputBefore:0);
        result.generation=marker.generation;result.lastPublicationNs=p->lastPublishedMachNs();
        result.received=p->pullAudio(output,result.wanted);render->calls.fetch_add(1);render->consumed.fetch_add(result.received);render->presented.fetch_add(result.wanted);
        const auto missing=result.wanted-result.received;
        if(missing){lifetimeMissing_.fetch_add(missing);lifetimeUnderruns_.fetch_add(1);render->missing.fetch_add(missing);render->underruns.fetch_add(1);render->lastMissing=timestamp;std::uint64_t zero=0;render->firstMissing.compare_exchange_strong(zero,timestamp);
            auto run=render->continuous.fetch_add(missing)+missing;auto max=render->maxContinuous.load();while(run>max&&!render->maxContinuous.compare_exchange_weak(max,run)){}
            const auto seq=render->eventSequence.fetch_add(1);render->events[seq%render->events.size()]={timestamp,result.outputBefore,result.wanted,result.received,available,result.generation};
        }else render->continuous=0;
    }
    silence(output,channels,result.received,frames);renderBusy_.clear(std::memory_order_release);inRender_.fetch_sub(1,std::memory_order_seq_cst);return result;
}
Position PlaybackEngine::getCurrentPlaybackPosition()const{std::lock_guard lock(mutex_);Position p;p.outputFrame=renderCounters_->consumed;if(pipeline_)p.inputFrame=pipeline_->inputPositionForOutput(p.outputFrame);if(rate_){p.inputSeconds=double(p.inputFrame)/rate_;p.outputSeconds=double(p.outputFrame)/rate_;}return p;}
Diagnostics PlaybackEngine::getPlaybackDiagnostics()const{std::lock_guard lock(mutex_);Diagnostics d;d.session=session_;d.lifetimeMissingFrames=lifetimeMissing_;d.lifetimeUnderrunCalls=lifetimeUnderruns_;d.renderCalls=renderCounters_->calls;d.consumedFrames=renderCounters_->consumed;d.presentedFrames=renderCounters_->presented;d.missingFrames=renderCounters_->missing;d.underrunCalls=renderCounters_->underruns;d.maxContinuousMissingFrames=renderCounters_->maxContinuous;d.firstUnderrunNs=renderCounters_->firstMissing;d.lastUnderrunNs=renderCounters_->lastMissing;d.eventOverwrites=renderCounters_->eventSequence>renderCounters_->events.size()?renderCounters_->eventSequence-renderCounters_->events.size():0;d.concurrentRenders=renderCounters_->concurrent;d.reason=reason_;d.error=error_;d.operationHistoryDrops=historyDrops_;if(pipeline_){auto s=pipeline_->snapshot();d.generatedFrames=s.generatedPcmFrames;d.outputLength=s.outputLength;d.inputFrames=pipeline_->inputFrames();d.outputStartFrame=pipeline_->outputStartFrame();d.producedFrames=s.produced;d.fifoAvailable=pipeline_->available();d.fifoHighWater=s.fifoHighWater;d.rejectedWrites=s.rejectedWrites;d.maxWorkerWallSeconds=s.maxWorkerChunkSeconds;d.maxWorkerCpuSeconds=s.maxWorkerCpuSeconds;}return d;}
std::vector<SpeedOperation> PlaybackEngine::operationHistory()const{std::lock_guard lock(mutex_);return {history_.begin(),history_.end()};}
std::optional<SpeedOperation> PlaybackEngine::getPendingSpeedChange()const{std::lock_guard lock(mutex_);return pending_;}
std::optional<SpeedOperation> PlaybackEngine::getActiveSpeedChange()const{std::lock_guard lock(mutex_);return active_;}
StartupDiagnostics PlaybackEngine::getStartupDiagnostics()const{std::lock_guard lock(mutex_);auto s=startup_;if(pipeline_){auto p=pipeline_->startupDiagnostics();s.timeMap=p.timeMap;s.workerInitialization=p.workerInitialization;}return s;}
Configuration PlaybackEngine::configuration()const{std::lock_guard lock(mutex_);return config_;}
StateSnapshot PlaybackEngine::getStateSnapshot()const{std::lock_guard lock(mutex_);StateSnapshot s;s.state=state_;s.reason=reason_;s.session=session_;s.missingFrames=renderCounters_->missing;s.requestedSpeed=getRequestedSpeed();s.appliedTargetSpeed=getAppliedTargetSpeed();s.pending=pending_;s.active=active_;if(!history_.empty()&&history_.back().session==session_)s.lastResult=history_.back();return s;}
std::vector<UnderrunEvent> PlaybackEngine::underrunEvents()const{std::lock_guard lock(mutex_);if(renderEnabled_||inRender_)throw std::logic_error("Quiesce audio before exporting events");auto n=renderCounters_->eventSequence.load();std::vector<UnderrunEvent> out;for(auto i=n>renderCounters_->events.size()?n-renderCounters_->events.size():0;i<n;++i)out.push_back(renderCounters_->events[i%renderCounters_->events.size()]);return out;}
std::vector<Phase39PlanMetric> PlaybackEngine::plans()const{std::lock_guard lock(mutex_);if(!pipeline_)return {};if(!pipeline_->finished())throw std::logic_error("Worker must finish before plan export");return pipeline_->planMetrics();}
std::vector<Phase39BlockProfile> PlaybackEngine::workerProfiles()const{std::lock_guard lock(mutex_);if(!pipeline_)return {};if(!pipeline_->finished())throw std::logic_error("Worker must finish before profile export");return pipeline_->allBlockProfiles();}
std::string PlaybackEngine::rawPcmSha()const{std::lock_guard lock(mutex_);if(!pipeline_||!pipeline_->finished())throw std::logic_error("PCM hash not finalized");return pipeline_->workerPcmSha();}
const char* name(SeekStatus s){switch(s){case SeekStatus::Pending:return "Pending";case SeekStatus::Preparing:return "Preparing";case SeekStatus::Completed:return "Completed";case SeekStatus::Replaced:return "Replaced";case SeekStatus::Cancelled:return "Cancelled";case SeekStatus::Rejected:return "Rejected";case SeekStatus::Failed:return "Failed";}return "Unknown";}
const char* name(PlaybackState s){switch(s){case PlaybackState::Empty:return "Empty";case PlaybackState::Preparing:return "Preparing";case PlaybackState::Ready:return "Ready";case PlaybackState::Playing:return "Playing";case PlaybackState::Paused:return "Paused";case PlaybackState::Stopped:return "Stopped";case PlaybackState::Draining:return "Draining";case PlaybackState::Ended:return "Ended";case PlaybackState::Failed:return "Failed";}return "Unknown";}
const char* name(SpeedStatus s){switch(s){case SpeedStatus::Pending:return "Pending";case SpeedStatus::Submitted:return "Submitted";case SpeedStatus::Applied:return "Applied";case SpeedStatus::Completed:return "Completed";case SpeedStatus::Replaced:return "Replaced";case SpeedStatus::Duplicate:return "Duplicate";case SpeedStatus::Rejected:return "Rejected";case SpeedStatus::Cancelled:return "Cancelled";case SpeedStatus::Configured:return "Configured";}return "Unknown";}
const char* name(StopReason s){switch(s){case StopReason::None:return "None";case StopReason::User:return "User";case StopReason::EndOfStream:return "EOS";case StopReason::RouteChanged:return "RouteChanged";case StopReason::WorkerError:return "WorkerError";}return "Unknown";}
}
