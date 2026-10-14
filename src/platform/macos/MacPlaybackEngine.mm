#import <AVFoundation/AVFoundation.h>
#import <CoreAudio/CoreAudio.h>
#include "platform/macos/MacPlaybackEngine.h"
#include "prototype/Phase46HostClock.h"
#include <mach/mach_time.h>
#include <cmath>
#include <thread>
#include <cstring>
namespace ts::playback {
namespace {
struct RenderState {
    PlaybackEngine* core=nullptr;
    std::atomic<bool> active{false},routeNotification{false},forcedRoute{false};
    std::atomic<unsigned> inRender{0};
    unsigned channels=0,numer=1,denom=1;double rate=0;
    std::uint64_t epoch=1;
    std::vector<MacCallbackRecord> records; // Prepared once, export after quiescence.
    std::atomic<std::uint64_t> calls{0},recordCount{0},dropped{0},maximum{0},overruns{0},formats{0};
    std::atomic<std::uint64_t> missingHost{0},backwards{0},cadence{0},sampleErrors{0},halMisses{0};
    std::atomic<std::uint64_t> lastPcmTargetEndNs{0};
    prototype::Phase46HostClock hostClock;
    RenderAllocationHooks hooks;std::uint64_t allocationBase=0;
    std::uint64_t ns()const noexcept{return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*numer/denom);}
};
OSStatus render(RenderState* s,BOOL* silent,const AudioTimeStamp* stamp,AVAudioFrameCount frames,AudioBufferList* buffers)noexcept{
    s->inRender.fetch_add(1,std::memory_order_seq_cst);if(s->hooks.enter)s->hooks.enter();
    const auto start=s->ns();
    RenderResult raw;bool valid=buffers->mNumberBuffers==s->channels;
    float* pointers[2]{};
    for(unsigned c=0;c<buffers->mNumberBuffers;++c){auto& b=buffers->mBuffers[c];if(c<2)pointers[c]=static_cast<float*>(b.mData);valid&=b.mData&&b.mNumberChannels==1&&b.mDataByteSize>=frames*sizeof(float);}
    bool running=s->active.load(std::memory_order_seq_cst);
    if(running&&valid)raw=s->core->renderAudio(pointers,frames,start);
    else {for(unsigned c=0;c<buffers->mNumberBuffers;++c)if(buffers->mBuffers[c].mData)std::memset(buffers->mBuffers[c].mData,0,buffers->mBuffers[c].mDataByteSize);if(running&&!valid)s->formats.fetch_add(1);}
    const auto io=s->ns();
    *silent=raw.received==0;
    if(running){
        const auto seq=s->calls.fetch_add(1)+1;
        const auto flags=stamp?stamp->mFlags:0;
        const auto host=stamp&&((flags&kAudioTimeStampHostTimeValid)!=0)?static_cast<std::uint64_t>(static_cast<long double>(stamp->mHostTime)*s->numer/s->denom):0;
        const auto sample=stamp?stamp->mSampleTime:0;
        const bool plausibleHost=host&&std::abs(static_cast<double>(host)-static_cast<double>(start))<=1e9;
        if(raw.received) s->lastPcmTargetEndNs.store((plausibleHost?host:io)+static_cast<std::uint64_t>(raw.received*1e9/s->rate),std::memory_order_release);
        auto evidence=s->hostClock.observe(s->epoch,start,io,host!=0,host,(flags&kAudioTimeStampSampleTimeValid)!=0,sample,frames,s->rate);
        s->missingHost.fetch_add(evidence.hostMissing);s->backwards.fetch_add(evidence.hostBackwards);s->cadence.fetch_add(evidence.cadenceError||evidence.offsetOutlier);s->sampleErrors.fetch_add(evidence.sampleError);
        const auto index=s->recordCount.fetch_add(1);MacCallbackRecord* record=nullptr;
        if(!s->records.empty()){if(index<s->records.size()){record=&s->records[index];*record={seq,s->epoch,start,0,io,host,sample,flags,frames,raw};}else s->dropped.fetch_add(1);}
        const auto end=s->ns();if(record)record->endNs=end;
        auto maximum=s->maximum.load();while(end-start>maximum&&!s->maximum.compare_exchange_weak(maximum,end-start)){}
        s->overruns.fetch_add(end-start>frames*1e9/s->rate);
        s->halMisses.fetch_add(host!=0&&end>host+std::max(100000.,2e9/s->rate));
    }
    if(s->hooks.leave)s->hooks.leave();s->inRender.fetch_sub(1,std::memory_order_seq_cst);return noErr;
}
unsigned deviceProperty(AudioDeviceID device,AudioObjectPropertySelector selector){UInt32 v=0,n=sizeof(v);AudioObjectPropertyAddress a{selector,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};if(AudioObjectGetPropertyData(device,&a,0,nullptr,&n,&v)!=noErr)throw std::runtime_error("Device property unavailable");return v;}
AudioDeviceID defaultDevice(){AudioDeviceID v=0;UInt32 n=sizeof(v);AudioObjectPropertyAddress a{kAudioHardwarePropertyDefaultOutputDevice,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};if(AudioObjectGetPropertyData(kAudioObjectSystemObject,&a,0,nullptr,&n,&v)!=noErr||!v)throw std::runtime_error("No default audio device");return v;}
}
struct MacPlaybackEngine::Impl {
    mutable std::mutex mutex;PlaybackEngine core;MacOptions options;
    AVAudioEngine* engine=nil;AVAudioSourceNode* source=nil;id observer=nil;
    std::shared_ptr<RenderState> renderState;
    MacDiagnostics device;
    std::atomic<bool> exit{false},outputActive{false};std::thread monitor;
    Impl(){monitor=std::thread([this]{while(!exit){std::this_thread::sleep_for(std::chrono::milliseconds(5));std::lock_guard lock(mutex);if(!renderState)continue;
        try{
            if(renderState->forcedRoute.exchange(false)||renderState->routeNotification.exchange(false)){
                bool changed=defaultDevice()!=device.deviceId;
                auto f=[engine.outputNode outputFormatForBus:0];changed|=f.sampleRate!=device.deviceRate||f.channelCount!=device.deviceChannels;
                // A test event always requests the same safe stop as a real route.
                if(changed||forced){quiesce(false);core.stop(StopReason::RouteChanged);++device.routeChanges;forced=false;}
            }
            if(core.getPlaybackState()==PlaybackState::Ended && !renderState->inRender.load() && renderState->ns()>=drainDeadline())quiesce(false);
            if(core.getPlaybackState()==PlaybackState::Failed)quiesce(false);
        }catch(const std::exception&e){device.error=e.what();quiesce(false);core.stop(StopReason::RouteChanged);++device.routeChanges;}
    }});}
    bool forced=false;
    std::uint64_t drainDeadline()const{return renderState->lastPcmTargetEndNs.load(std::memory_order_acquire)+5000000;}
    void drainRenderedTail(){const auto limit=renderState->ns()+1000000000;while(renderState->ns()<drainDeadline()){if(renderState->ns()>limit){device.error="Invalid render-tail deadline";break;}std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
    ~Impl(){exit=true;if(monitor.joinable())monitor.join();std::lock_guard lock(mutex);quiesce(true);core.stop();}
    void quiesce(bool destroy){
        const bool wasActive=outputActive.load();
        if(renderState)renderState->active.store(false,std::memory_order_seq_cst);
        if(engine&&engine.isRunning){[engine stop];}
        if(renderState)while(renderState->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
        outputActive=false;
        if(renderState&&wasActive)device.outputStoppedMachNs=renderState->ns();
        if(destroy){if(observer)[[NSNotificationCenter defaultCenter]removeObserver:observer];observer=nil;if(source&&engine)[engine detachNode:source];source=nil;engine=nil;}
    }
    void configure(){
        quiesce(true);engine=[[AVAudioEngine alloc]init];device={};device.deviceId=defaultDevice();
        auto f=[engine.outputNode outputFormatForBus:0];device.deviceRate=f.sampleRate;device.deviceChannels=f.channelCount;
        if(!device.deviceRate||!device.deviceChannels)throw std::runtime_error("Invalid device format");
        device.deviceBufferFrames=deviceProperty(device.deviceId,kAudioDevicePropertyBufferFrameSize);
        device.devicePresentationLatencyMs=engine.outputNode.presentationLatency*1000;
        renderState=std::make_shared<RenderState>();renderState->core=&core;renderState->channels=static_cast<unsigned>(core.channels());renderState->rate=core.sampleRate();renderState->hooks=options.allocationHooks;renderState->allocationBase=options.allocationHooks.count?options.allocationHooks.count():0;
        mach_timebase_info_data_t tb{};mach_timebase_info(&tb);renderState->numer=tb.numer;renderState->denom=tb.denom;
        const auto steady=[](){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();};
        auto before=steady();device.bridgeMachNs=renderState->ns();auto after=steady();
        device.bridgeSteadyNs=before+(after-before)/2;device.bridgeUncertaintyNs=after-before;
        if(options.recordCallbacks)renderState->records.resize(262144);
        auto state=renderState;
        auto format=[[AVAudioFormat alloc]initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:core.sampleRate() channels:static_cast<AVAudioChannelCount>(core.channels()) interleaved:NO];
        source=[[AVAudioSourceNode alloc]initWithFormat:format renderBlock:^OSStatus(BOOL* silent,const AudioTimeStamp* ts,AVAudioFrameCount frames,AudioBufferList* buffers){return render(state.get(),silent,ts,frames,buffers);}];
        [engine attachNode:source];[engine connect:source to:engine.mainMixerNode format:format];engine.mainMixerNode.outputVolume=options.playbackGain;[engine prepare];
        observer=[[NSNotificationCenter defaultCenter]addObserverForName:AVAudioEngineConfigurationChangeNotification object:engine queue:nil usingBlock:^(NSNotification*){state->routeNotification.store(true);}];
    }
    bool startAudio(){NSError* error=nil;renderState->active=true;outputActive=true;if(![engine startAndReturnError:&error]){renderState->active=false;outputActive=false;core.pause();device.error=error?[[error description]UTF8String]:"Audio start failed";return false;}device.sourcePresentationLatencyMs=source.outputPresentationLatency*1000;return true;}
};
MacPlaybackEngine::MacPlaybackEngine():impl_(std::make_unique<Impl>()){}
MacPlaybackEngine::~MacPlaybackEngine()=default;
bool MacPlaybackEngine::prepare(const std::filesystem::path& p,Configuration c,MacOptions o){
    if(!std::isfinite(o.playbackGain)||o.playbackGain<0||o.playbackGain>1)throw std::invalid_argument("Playback gain");
    std::lock_guard lock(impl_->mutex);if(impl_->core.getPlaybackState()==PlaybackState::Playing||impl_->core.getPlaybackState()==PlaybackState::Paused||(impl_->core.getPlaybackState()==PlaybackState::Ended&&impl_->outputActive))throw std::logic_error("Stop before prepare; rendered tail may still be draining");
    impl_->quiesce(true);impl_->options=o;if(!impl_->core.prepare(p,c))return false;
    try{impl_->configure();return true;}catch(const std::exception&e){impl_->device.error=e.what();impl_->core.stop();return false;}
}
bool MacPlaybackEngine::play(){std::lock_guard lock(impl_->mutex);auto old=impl_->core.getPlaybackState();if(old==PlaybackState::Playing)return true;if(old==PlaybackState::Ended&&impl_->outputActive)return false;if(!impl_->core.play())return false;try{if(old==PlaybackState::Stopped||old==PlaybackState::Ended)impl_->configure();return impl_->startAudio();}catch(const std::exception&e){impl_->device.error=e.what();impl_->quiesce(false);impl_->core.stop();return false;}}
bool MacPlaybackEngine::pause(){std::lock_guard lock(impl_->mutex);if(!impl_->core.pause())return false;while(impl_->renderState->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));impl_->drainRenderedTail();impl_->renderState->active=false;[impl_->engine pause];while(impl_->renderState->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));return true;}
bool MacPlaybackEngine::resume(){std::lock_guard lock(impl_->mutex);if(!impl_->core.resume())return false;++impl_->renderState->epoch;return impl_->startAudio();}
void MacPlaybackEngine::stop(){std::lock_guard lock(impl_->mutex);impl_->core.pause();impl_->quiesce(false);impl_->core.stop();}
std::uint64_t MacPlaybackEngine::setSpeed(double s){return impl_->core.setSpeed(s);}
PlaybackState MacPlaybackEngine::getPlaybackState()const noexcept{auto state=impl_->core.getPlaybackState();return state==PlaybackState::Ended&&impl_->outputActive?PlaybackState::Draining:state;}
double MacPlaybackEngine::getRequestedSpeed()const{return impl_->core.getRequestedSpeed();}
double MacPlaybackEngine::getAppliedTargetSpeed()const{return impl_->core.getAppliedTargetSpeed();}
Position MacPlaybackEngine::getCurrentPlaybackPosition()const{return impl_->core.getCurrentPlaybackPosition();}
std::optional<SpeedOperation> MacPlaybackEngine::getPendingSpeedChange()const{return impl_->core.getPendingSpeedChange();}
std::optional<SpeedOperation> MacPlaybackEngine::getActiveSpeedChange()const{return impl_->core.getActiveSpeedChange();}
StateSnapshot MacPlaybackEngine::getStateSnapshot()const{auto s=impl_->core.getStateSnapshot();if(s.state==PlaybackState::Ended&&impl_->outputActive)s.state=PlaybackState::Draining;return s;}
Diagnostics MacPlaybackEngine::getPlaybackDiagnostics()const{return impl_->core.getPlaybackDiagnostics();}
std::vector<SpeedOperation> MacPlaybackEngine::operationHistory()const{return impl_->core.operationHistory();}
std::vector<prototype::Phase39PlanMetric> MacPlaybackEngine::plans()const{return impl_->core.plans();}
std::vector<prototype::Phase39BlockProfile> MacPlaybackEngine::workerProfiles()const{return impl_->core.workerProfiles();}
std::string MacPlaybackEngine::rawPcmSha()const{return impl_->core.rawPcmSha();}
std::uint32_t MacPlaybackEngine::sampleRate()const{return impl_->core.sampleRate();}
std::size_t MacPlaybackEngine::channels()const{return impl_->core.channels();}
MacDiagnostics MacPlaybackEngine::getNativeDiagnostics()const{std::lock_guard lock(impl_->mutex);auto d=impl_->device;if(auto s=impl_->renderState){d.lastPcmTargetEndNs=s->lastPcmTargetEndNs;d.callbackCalls=s->calls;d.maxCallbackNs=s->maximum;d.deadlineMisses=s->overruns;d.formatErrors=s->formats;d.callbackRecordsDropped=s->dropped;d.hostMissing=s->missingHost;d.hostBackwards=s->backwards;d.hostCadenceErrors=s->cadence;d.sampleErrors=s->sampleErrors;d.halWindowMisses=s->halMisses;d.allocationMeasured=s->hooks.count!=nullptr;if(s->hooks.count){const auto total=s->hooks.count();if(total<s->allocationBase)d.error="Allocation counter moved backwards";else d.callbackCppAllocations=total-s->allocationBase;}}return d;}
std::vector<MacCallbackRecord> MacPlaybackEngine::callbackRecords()const{
    std::lock_guard lock(impl_->mutex);auto s=impl_->renderState;if(!s)return {};
    auto state=impl_->core.getPlaybackState();
    if(state==PlaybackState::Ended&&impl_->outputActive)state=PlaybackState::Draining;
    if(!detail::callbackHistoryReadable(state,s->active.load(),s->inRender.load()))
        throw std::logic_error("Callback history is unavailable while rendering or draining");
    return {s->records.begin(),s->records.begin()+std::min<std::size_t>(s->records.size(),s->recordCount)};
}
void MacPlaybackEngine::simulateDeviceChangeForTest(){std::lock_guard lock(impl_->mutex);impl_->forced=true;if(impl_->renderState)impl_->renderState->forcedRoute=true;}
}
