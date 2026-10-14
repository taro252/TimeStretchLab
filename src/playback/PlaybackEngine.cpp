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
static_assert(std::atomic<std::uint64_t>::is_always_lock_free);
static_assert(std::atomic<void*>::is_always_lock_free);
PlaybackEngine::PlaybackEngine(){control_=std::thread([this]{while(!exitControl_.load()){tick();std::this_thread::sleep_for(std::chrono::milliseconds(1));}});}
PlaybackEngine::~PlaybackEngine(){exitControl_=true;if(control_.joinable())control_.join();stop();}
void PlaybackEngine::inhibitRender(){renderEnabled_.store(false,std::memory_order_seq_cst);while(inRender_.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));}
void PlaybackEngine::record(const SpeedOperation& op){if(history_.size()==4096){history_.pop_front();++historyDrops_;}history_.push_back(op);}
void PlaybackEngine::cancelCommands(){for(auto* op:{&pending_,&active_})if(*op){(*op)->status=SpeedStatus::Cancelled;record(**op);op->reset();}}
void PlaybackEngine::prepareLocked(){
    inhibitRender();if(pipeline_)pipeline_->stop();renderPipeline_=nullptr;pipeline_.reset();
    auto speed=Phase39Speed::fromDouble(config_.initialSpeed);
    state_=PlaybackState::Preparing;
    auto options=config_.verificationHooks;options.pcmHash=config_.verifyRawPcm;options.publishPositionMap=true;
    options.userInitiatedQos=false; // Both frozen presets inherit QoS.
    const auto dsp=config_.dspOptions();
    pipeline_=std::make_unique<Phase39PlaybackPipeline>(input_,speed,config_.fifoFrames(),config_.blockFrames(),config_.leadFrames(),
        dsp.timeMapMode==TimeMapMode::OutputTimeL2?Phase39Planning::L2:Phase39Planning::C,Phase39DensityDiagnostic::SafeGuarded,
        config_.detailedDiagnostics,std::filesystem::path{},0,0,std::function<std::uint64_t()>{},dsp.preciseBoundaryL1,options);
    if(pipeline_->channels()<1||pipeline_->channels()>2)throw std::invalid_argument("Only mono/stereo input is supported");
    rate_=pipeline_->sampleRate();channels_=pipeline_->channels();renderPipeline_=pipeline_.get();
    requested_=applied_=speed.micros;calls_=0;consumed_=0;presented_=0;missing_=0;underruns_=0;continuous_=0;maxContinuous_=0;
    firstMissing_=0;lastMissing_=0;eventSequence_=0;concurrent_=0;reason_=StopReason::None;error_.clear();++session_;
    state_=PlaybackState::Ready;
}
bool PlaybackEngine::prepare(const std::filesystem::path& input,Configuration config){
    Phase39Speed::fromDouble(config.initialSpeed);
    if(config.preset!=Preset::Candidate&&config.preset!=Preset::Baseline)throw std::invalid_argument("Unknown preset");
    std::lock_guard lock(mutex_);
    if(state_==PlaybackState::Playing||state_==PlaybackState::Paused||state_==PlaybackState::Preparing)throw std::logic_error("Stop before changing input/preset");
    cancelCommands();input_=input;config_=config;
    try{prepareLocked();return true;}catch(const std::exception&e){failLocked(e.what());return false;}
}
bool PlaybackEngine::play(){
    std::lock_guard lock(mutex_);
    if(state_==PlaybackState::Paused)return false; // Explicit resume preserves state.
    if(state_==PlaybackState::Playing)return true;
    try{
        if(state_==PlaybackState::Stopped||state_==PlaybackState::Ended){config_.initialSpeed=getRequestedSpeed();prepareLocked();}
        if(state_!=PlaybackState::Ready)return false;
        if(pipeline_->snapshot().initial!=Phase39Speed::fromDouble(config_.initialSpeed))prepareLocked();
        pipeline_->start();
        const auto frames=std::min(config_.leadFrames(),std::size_t(std::llround(pipeline_->inputFrames()/config_.initialSpeed)));
        if(!pipeline_->waitForPrefill(frames,std::chrono::seconds(120))){if(pipeline_->finished())pipeline_->rethrowWorkerError();throw std::runtime_error("Playback prefill failed");}
        state_=PlaybackState::Playing;renderEnabled_.store(true,std::memory_order_seq_cst);return true;
    }catch(const std::exception&e){failLocked(e.what());return false;}
}
bool PlaybackEngine::pause(){std::lock_guard lock(mutex_);if(state_!=PlaybackState::Playing)return false;inhibitRender();state_=PlaybackState::Paused;return true;}
bool PlaybackEngine::resume(){std::lock_guard lock(mutex_);if(state_!=PlaybackState::Paused)return false;state_=PlaybackState::Playing;renderEnabled_.store(true,std::memory_order_seq_cst);return true;}
void PlaybackEngine::stop(StopReason reason){std::lock_guard lock(mutex_);inhibitRender();cancelCommands();if(pipeline_)pipeline_->stop();reason_=reason;state_=PlaybackState::Stopped;}
void PlaybackEngine::failLocked(const std::string& text){inhibitRender();cancelCommands();if(pipeline_)pipeline_->stop();error_=text;reason_=StopReason::WorkerError;state_=PlaybackState::Failed;}
std::uint64_t PlaybackEngine::setSpeed(double value){
    auto speed=Phase39Speed::fromDouble(value);std::lock_guard lock(mutex_);requested_=speed.micros;
    SpeedOperation op;op.id=++nextOperation_;op.session=session_;op.target=speed.value();op.observedNs=now();
    if(pending_){pending_->status=SpeedStatus::Replaced;record(*pending_);pending_.reset();}
    if(state_==PlaybackState::Empty||state_==PlaybackState::Preparing||state_==PlaybackState::Failed||state_==PlaybackState::Ended){op.status=SpeedStatus::Rejected;record(op);return op.id;}
    if(state_==PlaybackState::Ready||state_==PlaybackState::Stopped){config_.initialSpeed=speed.value();op.status=SpeedStatus::Configured;record(op);return op.id;}
    pending_=op;return op.id;
}
void PlaybackEngine::tick(){
    std::lock_guard lock(mutex_);if(!pipeline_||(state_!=PlaybackState::Playing&&state_!=PlaybackState::Paused))return;
    try{
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
        if(pipeline_->drained()){inhibitRender();cancelCommands();reason_=StopReason::EndOfStream;state_=PlaybackState::Ended;return;}
        if(state_==PlaybackState::Playing&&!active_&&pending_&&pipeline_->researchCommandReady()){
            const auto result=pipeline_->requestSpeed(Phase39Speed::fromDouble(pending_->target),consumed_.load());
            if(result==Phase39RequestResult::Accepted){active_=pending_;pending_.reset();active_->sentNs=now();active_->generation=pipeline_->snapshot().generation;active_->status=SpeedStatus::Submitted;}
            else if(result!=Phase39RequestResult::Busy){pending_->status=result==Phase39RequestResult::Duplicate?SpeedStatus::Duplicate:SpeedStatus::Rejected;record(*pending_);pending_.reset();}
        }
    }catch(const std::exception&e){failLocked(e.what());}
}
RenderResult PlaybackEngine::renderAudio(float*const* output,std::size_t frames,std::uint64_t timestamp) noexcept{
    RenderResult result;inRender_.fetch_add(1,std::memory_order_seq_cst);
    const auto channels=channels_.load(std::memory_order_relaxed);
    if(renderBusy_.test_and_set(std::memory_order_acquire)){concurrent_.fetch_add(1);silence(output,channels,0,frames);inRender_.fetch_sub(1,std::memory_order_seq_cst);return result;}
    if(renderEnabled_.load(std::memory_order_seq_cst)){
        auto* p=renderPipeline_.load(std::memory_order_acquire);result.outputBefore=consumed_.load();
        const auto marker=p->realtimeMarkers();const auto available=p->available();result.fifoBefore=available;
        result.wanted=std::min<std::size_t>(frames,marker.outputLength>result.outputBefore?marker.outputLength-result.outputBefore:0);
        result.generation=marker.generation;result.lastPublicationNs=p->lastPublishedMachNs();
        result.received=p->pullAudio(output,result.wanted);calls_.fetch_add(1);consumed_.fetch_add(result.received);presented_.fetch_add(result.wanted);
        const auto missing=result.wanted-result.received;
        if(missing){missing_.fetch_add(missing);underruns_.fetch_add(1);lastMissing_=timestamp;std::uint64_t zero=0;firstMissing_.compare_exchange_strong(zero,timestamp);
            auto run=continuous_.fetch_add(missing)+missing;auto max=maxContinuous_.load();while(run>max&&!maxContinuous_.compare_exchange_weak(max,run)){}
            const auto seq=eventSequence_.fetch_add(1);events_[seq%events_.size()]={timestamp,result.outputBefore,result.wanted,result.received,available,result.generation};
        }else continuous_=0;
    }
    silence(output,channels,result.received,frames);renderBusy_.clear(std::memory_order_release);inRender_.fetch_sub(1,std::memory_order_seq_cst);return result;
}
Position PlaybackEngine::getCurrentPlaybackPosition()const{std::lock_guard lock(mutex_);Position p;p.outputFrame=consumed_;if(pipeline_)p.inputFrame=pipeline_->inputPositionForOutput(p.outputFrame);if(rate_){p.inputSeconds=double(p.inputFrame)/rate_;p.outputSeconds=double(p.outputFrame)/rate_;}return p;}
Diagnostics PlaybackEngine::getPlaybackDiagnostics()const{std::lock_guard lock(mutex_);Diagnostics d;d.session=session_;d.renderCalls=calls_;d.consumedFrames=consumed_;d.presentedFrames=presented_;d.missingFrames=missing_;d.underrunCalls=underruns_;d.maxContinuousMissingFrames=maxContinuous_;d.firstUnderrunNs=firstMissing_;d.lastUnderrunNs=lastMissing_;d.eventOverwrites=eventSequence_>events_.size()?eventSequence_-events_.size():0;d.concurrentRenders=concurrent_;d.reason=reason_;d.error=error_;d.operationHistoryDrops=historyDrops_;if(pipeline_){auto s=pipeline_->snapshot();d.generatedFrames=s.generatedPcmFrames;d.outputLength=s.outputLength;d.producedFrames=s.produced;d.fifoAvailable=pipeline_->available();d.fifoHighWater=s.fifoHighWater;d.rejectedWrites=s.rejectedWrites;d.maxWorkerWallSeconds=s.maxWorkerChunkSeconds;d.maxWorkerCpuSeconds=s.maxWorkerCpuSeconds;}return d;}
std::vector<SpeedOperation> PlaybackEngine::operationHistory()const{std::lock_guard lock(mutex_);return {history_.begin(),history_.end()};}
std::optional<SpeedOperation> PlaybackEngine::getPendingSpeedChange()const{std::lock_guard lock(mutex_);return pending_;}
std::optional<SpeedOperation> PlaybackEngine::getActiveSpeedChange()const{std::lock_guard lock(mutex_);return active_;}
Configuration PlaybackEngine::configuration()const{std::lock_guard lock(mutex_);return config_;}
StateSnapshot PlaybackEngine::getStateSnapshot()const{std::lock_guard lock(mutex_);StateSnapshot s;s.state=state_;s.reason=reason_;s.session=session_;s.missingFrames=missing_;s.requestedSpeed=getRequestedSpeed();s.appliedTargetSpeed=getAppliedTargetSpeed();s.pending=pending_;s.active=active_;if(!history_.empty()&&history_.back().session==session_)s.lastResult=history_.back();return s;}
std::vector<UnderrunEvent> PlaybackEngine::underrunEvents()const{std::lock_guard lock(mutex_);if(renderEnabled_||inRender_)throw std::logic_error("Quiesce audio before exporting events");auto n=eventSequence_.load();std::vector<UnderrunEvent> out;for(auto i=n>events_.size()?n-events_.size():0;i<n;++i)out.push_back(events_[i%events_.size()]);return out;}
std::vector<Phase39PlanMetric> PlaybackEngine::plans()const{std::lock_guard lock(mutex_);if(!pipeline_)return {};if(!pipeline_->finished())throw std::logic_error("Worker must finish before plan export");return pipeline_->planMetrics();}
std::vector<Phase39BlockProfile> PlaybackEngine::workerProfiles()const{std::lock_guard lock(mutex_);if(!pipeline_)return {};if(!pipeline_->finished())throw std::logic_error("Worker must finish before profile export");return pipeline_->allBlockProfiles();}
std::string PlaybackEngine::rawPcmSha()const{std::lock_guard lock(mutex_);if(!pipeline_||!pipeline_->finished())throw std::logic_error("PCM hash not finalized");return pipeline_->workerPcmSha();}
const char* name(PlaybackState s){switch(s){case PlaybackState::Empty:return "Empty";case PlaybackState::Preparing:return "Preparing";case PlaybackState::Ready:return "Ready";case PlaybackState::Playing:return "Playing";case PlaybackState::Paused:return "Paused";case PlaybackState::Stopped:return "Stopped";case PlaybackState::Draining:return "Draining";case PlaybackState::Ended:return "Ended";case PlaybackState::Failed:return "Failed";}return "Unknown";}
const char* name(SpeedStatus s){switch(s){case SpeedStatus::Pending:return "Pending";case SpeedStatus::Submitted:return "Submitted";case SpeedStatus::Applied:return "Applied";case SpeedStatus::Completed:return "Completed";case SpeedStatus::Replaced:return "Replaced";case SpeedStatus::Duplicate:return "Duplicate";case SpeedStatus::Rejected:return "Rejected";case SpeedStatus::Cancelled:return "Cancelled";case SpeedStatus::Configured:return "Configured";}return "Unknown";}
const char* name(StopReason s){switch(s){case StopReason::None:return "None";case StopReason::User:return "User";case StopReason::EndOfStream:return "EOS";case StopReason::RouteChanged:return "RouteChanged";case StopReason::WorkerError:return "WorkerError";}return "Unknown";}
}
