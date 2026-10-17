#import <AVFoundation/AVFoundation.h>
#import <CoreAudio/CoreAudio.h>
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase46HostClock.h"
#include "audio/WavStream.h"
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <sys/resource.h>
#include <cstring>
#include <thread>

#ifndef TIMESTRETCH_PHASE60_SHA
#define TIMESTRETCH_PHASE60_SHA "unversioned"
#endif
namespace ts::playback {
namespace {
using State=progressive::State;
using Pipeline=prototype::phase58::RealtimePipeline;
using Operation=prototype::phase59::SpeedOperation;
std::atomic<bool> resourceOwner{false};
double processCpu(){rusage r{};getrusage(RUSAGE_SELF,&r);return r.ru_utime.tv_sec+r.ru_utime.tv_usec*1e-6+r.ru_stime.tv_sec+r.ru_stime.tv_usec*1e-6;}
double seconds(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
void workQueue(){if([NSThread isMainThread])throw std::logic_error("再生制御はメインスレッド以外の直列作業キューで実行してください");}
AudioDeviceID defaultDevice(){AudioDeviceID d=0;UInt32 n=sizeof(d);AudioObjectPropertyAddress a{kAudioHardwarePropertyDefaultOutputDevice,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};if(AudioObjectGetPropertyData(kAudioObjectSystemObject,&a,0,nullptr,&n,&d)!=noErr||!d)throw std::runtime_error("出力装置を取得できません");return d;}
unsigned bufferFrames(AudioDeviceID d){UInt32 n=sizeof(UInt32),v=0;AudioObjectPropertyAddress a{kAudioDevicePropertyBufferFrameSize,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};if(AudioObjectGetPropertyData(d,&a,0,nullptr,&n,&v)!=noErr)throw std::runtime_error("装置バッファを取得できません");return v;}
struct RenderState {
    Pipeline* pipeline=nullptr;
    unsigned channels=0,numer=1,denom=1;double rate=0;
    std::uint64_t session=0,epoch=1;
    std::atomic<bool> active{false},route{false},forcedRoute{false};
    std::atomic<unsigned> inRender{0};
    std::atomic<std::uint64_t> calls{0},presented{0},maximum{0},overruns{0},formats{0};
    std::atomic<std::uint64_t> hostMissing{0},hostBackwards{0},hostCadence{0},sampleErrors{0},halMisses{0};
    std::atomic<std::uint64_t> invalidSample{0},invalidScalar{0};
    std::atomic<std::uint64_t> firstPcm{0},lastTarget{0},recordsCount{0},dropped{0};
    std::vector<MacCallbackRecord> records;
    prototype::Phase46HostClock clock;
    void* observerContext=nullptr;
    void(*observer)(void*,const float*const*,std::size_t,std::size_t)noexcept=nullptr;
    std::uint64_t ns()const noexcept{return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*numer/denom);}
};
OSStatus render(RenderState* s,BOOL* silent,const AudioTimeStamp* stamp,AVAudioFrameCount n,AudioBufferList* buffers) noexcept {
    s->inRender.fetch_add(1,std::memory_order_seq_cst);
    const auto start=s->ns();float* p[2]{};const float* rawPointers[2]{};
    bool valid=buffers&&buffers->mNumberBuffers==s->channels;
    if(buffers)for(unsigned c=0;c<buffers->mNumberBuffers;++c){const auto& b=buffers->mBuffers[c];valid&=b.mData&&b.mNumberChannels==1&&b.mDataByteSize>=n*sizeof(float);if(c<2){p[c]=static_cast<float*>(b.mData);rawPointers[c]=p[c];}}
    const bool active=s->active.load(std::memory_order_seq_cst);
    prototype::phase58::RenderResult r;
    if(active&&valid){
        r=s->pipeline->pullAudio(p,n);s->presented.fetch_add(r.wanted,std::memory_order_relaxed);
        if(r.received&&s->observer)s->observer(s->observerContext,rawPointers,r.received,r.outputBefore);
    }else if(buffers){for(unsigned c=0;c<buffers->mNumberBuffers;++c)if(buffers->mBuffers[c].mData)std::memset(buffers->mBuffers[c].mData,0,buffers->mBuffers[c].mDataByteSize);if(active)++s->formats;}
    *silent=r.received==0;
    if(active){
        const auto io=s->ns(),sequence=s->calls.fetch_add(1)+1;
        const auto flags=stamp?stamp->mFlags:0;
        const auto host=stamp&&(flags&kAudioTimeStampHostTimeValid)?static_cast<std::uint64_t>(static_cast<long double>(stamp->mHostTime)*s->numer/s->denom):0;
        const auto sample=stamp?stamp->mSampleTime:0;
        s->invalidSample.fetch_add(!(flags&kAudioTimeStampSampleTimeValid)||!std::isfinite(sample));
        s->invalidScalar.fetch_add(!(flags&kAudioTimeStampRateScalarValid)||!std::isfinite(stamp?stamp->mRateScalar:0));
        if(r.received){std::uint64_t zero=0;s->firstPcm.compare_exchange_strong(zero,start);const bool plausible=host&&std::abs(double(host)-double(start))<=1e9;s->lastTarget=(plausible?host:io)+static_cast<std::uint64_t>(r.received*1e9/s->rate);}
        auto evidence=s->clock.observe(s->epoch,start,io,host!=0,host,(flags&kAudioTimeStampSampleTimeValid)!=0,sample,n,s->rate);
        s->hostMissing.fetch_add(evidence.hostMissing);s->hostBackwards.fetch_add(evidence.hostBackwards);s->hostCadence.fetch_add(evidence.cadenceError||evidence.offsetOutlier);s->sampleErrors.fetch_add(evidence.sampleError);
        MacCallbackRecord* record=nullptr;
        if(!s->records.empty()){const auto i=s->recordsCount.fetch_add(1);if(i<s->records.size()){
            record=&s->records[i];*record={};record->sequence=sequence;record->epoch=s->epoch;record->startNs=start;record->ioEndNs=io;record->hostNs=host;record->hostTicks=stamp?stamp->mHostTime:0;record->sampleTime=sample;record->timestampFlags=flags;record->rateScalar=stamp?stamp->mRateScalar:0;record->requested=n;
            record->raw.received=r.received;record->raw.wanted=r.wanted;record->raw.fifoBefore=r.fifoBefore;record->raw.outputBefore=r.outputBefore;record->raw.session=s->session;
        }else ++s->dropped;}
        const auto end=s->ns();if(record)record->endNs=end;
        // Single callback consumer; the atomic is read only by control threads.
        s->maximum.store(std::max(s->maximum.load(std::memory_order_relaxed),end-start),std::memory_order_relaxed);
        s->overruns.fetch_add(end-start>n*1e9/s->rate);
        s->halMisses.fetch_add(host&&end>host+std::max(100000.,2e9/s->rate));
    }
    s->inRender.fetch_sub(1,std::memory_order_seq_cst);return noErr;
}
}
struct ProgressiveMacPlaybackEngine::Impl {
    mutable std::mutex mutex; // only normal control/preparation/monitor threads
    std::atomic<State> state{State::Empty};std::atomic<bool> cancelPrepare{false},exit{false};
    std::thread preparation,monitor;
    std::unique_ptr<Pipeline> pipeline;
    std::shared_ptr<RenderState> rendering;
    AVAudioEngine* engine=nil;AVAudioSourceNode* source=nil;id observer=nil;
    std::filesystem::path input;ProgressiveOptions options;
    MacDiagnostics native;prototype::phase58::Diagnostics retired;
    std::vector<Operation> retiredOperations;TimeMap retiredMap;
    std::optional<prototype::phase58::PositionSample> retiredPosition;
    StopReason reason=StopReason::None;
    std::string error;std::uint64_t revision=0,reservation=0;
    bool ownsBudget=false,autoPlay=false;
    double requested=1,acceptedAt=0,readyAfter=-1,constructorS=-1,cpuStart=0;
    Impl(){monitor=std::thread([this]{@autoreleasepool {while(!exit.load()){
        {std::lock_guard lock(mutex);try{tick();}catch(const std::exception& e){fail(e.what());}}
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }}});}
    ~Impl(){exit=true;if(monitor.joinable())monitor.join();cancelPrepare=true;if(preparation.joinable())preparation.join();std::lock_guard lock(mutex);retire();}
    void releaseBudget(){if(ownsBudget){resourceOwner=false;ownsBudget=false;}}
    void quiesce(bool destroy){
        if(rendering)rendering->active.store(false,std::memory_order_seq_cst);
        if(engine&&engine.isRunning)[engine stop];
        if(rendering)while(rendering->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
        if(rendering)native.outputStoppedMachNs=rendering->ns();
        if(destroy){if(observer)[[NSNotificationCenter defaultCenter]removeObserver:observer];observer=nil;if(engine&&source)[engine detachNode:source];source=nil;engine=nil;}
    }
    void retire(){
        quiesce(true);
        if(pipeline){pipeline->setRealtimeRendering(false);pipeline->stop();retired=pipeline->diagnostics();retiredOperations=pipeline->speedOperations();retiredPosition=pipeline->positionSample();
            if(retired.analysisDone&&!retired.failed){try{retiredMap=pipeline->dynamicTimeMap();}catch(const std::logic_error&) {}}
            pipeline.reset();}
        releaseBudget();
    }
    void fail(const std::string& message){error=message;reason=StopReason::WorkerError;retire();state=State::Failed;}
    void configure(){@try {
        StageClock clock;engine=[[AVAudioEngine alloc]init];native={};native.deviceId=defaultDevice();
        auto f=[engine.outputNode outputFormatForBus:0];native.deviceRate=f.sampleRate;native.deviceChannels=f.channelCount;native.deviceBufferFrames=bufferFrames(native.deviceId);
        if(!native.deviceRate||!native.deviceChannels)throw std::runtime_error("出力形式が無効です");
        native.devicePresentationLatencyMs=engine.outputNode.presentationLatency*1000;
        rendering=std::make_shared<RenderState>();auto s=rendering;s->pipeline=pipeline.get();s->rate=pipeline->sampleRate();s->channels=static_cast<unsigned>(pipeline->channels());s->session=pipeline->diagnostics().session;
        mach_timebase_info_data_t tb{};if(mach_timebase_info(&tb)!=KERN_SUCCESS)throw std::runtime_error("Mach時計を取得できません");s->numer=tb.numer;s->denom=tb.denom;
        s->observer=options.observeRawPcm;s->observerContext=options.observerContext;
        if(options.callbackRecordLimit){s->records.resize(options.callbackRecordLimit);auto* p=reinterpret_cast<volatile unsigned char*>(s->records.data());const auto bytes=s->records.size()*sizeof(MacCallbackRecord);for(std::size_t i=0;i<bytes;i+=std::size_t(getpagesize()))p[i]=p[i];p[bytes-1]=p[bytes-1];}
        auto format=[[AVAudioFormat alloc]initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:s->rate channels:s->channels interleaved:NO];
        source=[[AVAudioSourceNode alloc]initWithFormat:format renderBlock:^OSStatus(BOOL* silent,const AudioTimeStamp* stamp,AVAudioFrameCount n,AudioBufferList* b){return render(s.get(),silent,stamp,n,b);}];
        [engine attachNode:source];[engine connect:source to:engine.mainMixerNode format:format];engine.mainMixerNode.outputVolume=.5f;
        [engine prepare];native.avConstruction=clock.elapsed();
        observer=[[NSNotificationCenter defaultCenter]addObserverForName:AVAudioEngineConfigurationChangeNotification object:engine queue:nil usingBlock:^(NSNotification*){s->route=true;}];
    }@catch(NSException* e){throw std::runtime_error(e.reason?e.reason.UTF8String:"音声構成APIの例外");}}
    bool startAudio(){@try {
        if(!pipeline->setRealtimeRendering(true))throw std::runtime_error("Audio Workgroupへの昇格・参加に失敗しました");
        const auto m=pipeline->diagnostics().scheduling;
        if(!pipeline->finished()&&(!m.active||!m.policyMeasured||m.policyErrors||m.joinErrors||m.queryErrors))throw std::runtime_error("実時間policyが確認できません");
        if(cancelPrepare.load())throw std::runtime_error("準備が取り消されました");
        StageClock clock;NSError* e=nil;rendering->active=true;native.playCalledSteadyNs=static_cast<std::uint64_t>(seconds()*1e9);
        if(![engine startAndReturnError:&e]){rendering->active=false;throw std::runtime_error(e?e.localizedDescription.UTF8String:"音声開始に失敗しました");}
        native.sourcePresentationLatencyMs=source.outputPresentationLatency*1000;native.avStart=clock.elapsed();state=State::Playing;return true;
    }@catch(NSException* e){throw std::runtime_error(e.reason?e.reason.UTF8String:"音声開始APIの例外");}}
    std::uint64_t tailDeadline()const {return rendering->lastTarget.load()+static_cast<std::uint64_t>(std::max(native.sourcePresentationLatencyMs,native.devicePresentationLatencyMs)*1e6)+5000000;}
    void tick(){
        if(!pipeline)return;
        if(pipeline->failed()){fail(pipeline->diagnostics().error);return;}
        if(rendering&&(rendering->forcedRoute.exchange(false)||rendering->route.exchange(false))){
            const bool forced=force;force=false;auto f=[engine.outputNode outputFormatForBus:0];
            if(forced||defaultDevice()!=native.deviceId||f.sampleRate!=native.deviceRate||f.channelCount!=native.deviceChannels||bufferFrames(native.deviceId)!=native.deviceBufferFrames){++native.routeChanges;retire();reason=StopReason::RouteChanged;state=State::Stopped;return;}
        }
        if(state==State::Playing&&pipeline->drained())state=State::Draining;
        if(state==State::Draining&&rendering->ns()>=tailDeadline()){
            // Stop callback first, then join/leave and release borrowed owners.
            retire();reason=StopReason::EndOfStream;state=State::Ended;
        }
    }
    bool force=false;
    void launch(){
        cancelPrepare=false;autoPlay=false;acceptedAt=seconds();cpuStart=processCpu();readyAfter=constructorS=-1;++revision;
        retired={};retiredOperations.clear();retiredMap={};retiredPosition.reset();rendering.reset();native={};error.clear();reason=StopReason::None;reservation=0;
        state=State::Accepted;
        const auto p=input;const auto o=options;
        preparation=std::thread([this,p,o]{@autoreleasepool {
            std::unique_ptr<Pipeline> next;
            try{
                state=State::Preparing;
                const auto bytes=std::filesystem::file_size(p);WavStreamReader reader(p);
                const auto reserve=progressive::reservationBytes(bytes,reader.frames());
                if(reserve>o.memoryReservationBudget)throw std::length_error("メモリ予約予算を超えています");
                if(std::filesystem::space(std::filesystem::temp_directory_path()).available<bytes+256ULL*1024*1024)throw std::length_error("一時入力複製の空き容量が不足しています");
                bool expected=false;if(!resourceOwner.compare_exchange_strong(expected,true))throw std::runtime_error("別の実験セッションが資源を使用中です");
                {std::lock_guard lock(mutex);ownsBudget=true;reservation=reserve;}
                prototype::phase58::Configuration c;c.speedMicros=progressive::speedMicros(o.initialSpeed);c.candidate=o.preset==Preset::Candidate;c.verifyPcm=false;c.residentInput=true;c.dynamicTransitions=true;c.scheduling=prototype::phase58::WorkerScheduling::AudioWorkgroup;c.sourceSnapshotBytes=bytes;
                const auto began=seconds();next=std::make_unique<Pipeline>(p,c);
                if(next->diagnostics().sourceSnapshotBytes!=bytes||next->inputFrames()!=reader.frames()||next->sampleRate()!=reader.sampleRate()||next->channels()!=reader.channels())throw std::runtime_error("資源見積り中に入力形式・サイズが変化しました");
                {std::lock_guard lock(mutex);constructorS=seconds()-began;}
                if(cancelPrepare.load()){next->stop();return;}
                next->start();const auto deadline=std::chrono::steady_clock::now()+o.prepareTimeout;
                while(!cancelPrepare.load()&&!next->waitUntilReady(std::chrono::milliseconds(10))){if(next->failed())throw std::runtime_error(next->diagnostics().error);if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("Ready待機が期限を超えました");}
                if(cancelPrepare.load()){next->stop();return;}
                std::lock_guard lock(mutex);if(cancelPrepare.load()){next->stop();return;}
                pipeline=std::move(next);configure();
                if(cancelPrepare.load()){retire();return;}
                readyAfter=seconds()-acceptedAt;native.prepareCalledSteadyNs=static_cast<std::uint64_t>(acceptedAt*1e9);state=State::Ready;if(autoPlay)startAudio();
            }catch(const std::exception& e){if(next){next->stop();next.reset();}std::lock_guard lock(mutex);if(!cancelPrepare.load())fail(e.what());}
        }});
    }
    void stopPreparation(){cancelPrepare=true;if(preparation.joinable())preparation.join();}
    double applied(const std::vector<Operation>& ops)const{double s=options.initialSpeed;for(const auto& op:ops)if(op.appliedS>=0)s=op.target/1000000.;return s;}
};
ProgressiveMacPlaybackEngine::ProgressiveMacPlaybackEngine():impl_(std::make_unique<Impl>()){}
ProgressiveMacPlaybackEngine::~ProgressiveMacPlaybackEngine()=default;
bool ProgressiveMacPlaybackEngine::prepare(const std::filesystem::path& p,ProgressiveOptions o){
    workQueue();progressive::speedMicros(o.initialSpeed);
    if((o.preset!=Preset::Candidate&&o.preset!=Preset::Baseline)||o.callbackRecordLimit>262144||o.prepareTimeout.count()<=0||o.memoryReservationBudget>1024ULL*1024*1024)throw std::invalid_argument("実験用設定が無効です");
    auto& x=*impl_;auto state=x.state.load();if(state==State::Accepted||state==State::Preparing||state==State::Playing||state==State::Paused||state==State::Draining)throw std::logic_error("入力変更前にstopしてください");
    x.stopPreparation();std::lock_guard lock(x.mutex);x.retire();x.input=p;x.options=o;x.requested=o.initialSpeed;x.launch();return true;
}
bool ProgressiveMacPlaybackEngine::play(){
    workQueue();auto& x=*impl_;auto state=x.state.load();
    if(state==State::Stopped||state==State::Ended){x.stopPreparation();std::lock_guard lock(x.mutex);if(x.input.empty())return false;x.retire();x.options.initialSpeed=x.requested;x.launch();x.autoPlay=true;return true;}
    std::lock_guard lock(x.mutex);if(x.state==State::Playing)return true;if(x.state==State::Accepted||x.state==State::Preparing){x.autoPlay=true;return true;}if(x.state!=State::Ready)return false;
    try{return x.startAudio();}catch(const std::exception& e){x.fail(e.what());return false;}
}
bool ProgressiveMacPlaybackEngine::pause(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);if(x.state!=State::Playing)return false;
    try{x.rendering->active=false;while(x.rendering->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));
        const auto limit=x.rendering->ns()+1000000000;while(x.rendering->ns()<x.tailDeadline()){if(x.rendering->ns()>limit)throw std::runtime_error("末尾提示時刻が無効です");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
        [x.engine pause];while(x.rendering->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));if(!x.pipeline->setRealtimeRendering(false))throw std::runtime_error("Pause時の実時間policy復元に失敗しました");x.state=State::Paused;return true;
    }catch(const std::exception& e){x.fail(e.what());return false;}}
bool ProgressiveMacPlaybackEngine::resume(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);if(x.state!=State::Paused)return false;try{++x.rendering->epoch;return x.startAudio();}catch(const std::exception& e){x.fail(e.what());return false;}}
void ProgressiveMacPlaybackEngine::stop(){workQueue();auto& x=*impl_;x.stopPreparation();std::lock_guard lock(x.mutex);x.retire();x.reason=StopReason::User;x.state=State::Stopped;}
prototype::phase59::RequestReceipt ProgressiveMacPlaybackEngine::setSpeed(double s,std::uint64_t session,std::uint64_t generation){workQueue();const auto micros=progressive::speedMicros(s);auto& x=*impl_;std::lock_guard lock(x.mutex);
    if(!x.pipeline)return {0,prototype::Phase39RequestResult::Stopped};
    auto r=x.pipeline->requestSpeed(micros,x.rendering?x.rendering->presented.load():0,session,generation);if(r.result==prototype::Phase39RequestResult::Accepted)x.requested=s;return r;}
progressive::State ProgressiveMacPlaybackEngine::getPlaybackState()const noexcept{return impl_->state.load();}
ProgressiveStateSnapshot ProgressiveMacPlaybackEngine::getStateSnapshot()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveStateSnapshot s;s.state=x.state;s.reason=x.reason;s.preparation=x.revision;s.requestedSpeed=x.requested;s.error=x.error;
    const auto d=x.pipeline?x.pipeline->diagnostics():x.retired;s.session=s.inputGeneration=d.session;auto ops=x.pipeline?x.pipeline->speedOperations():x.retiredOperations;s.appliedTargetSpeed=x.applied(ops);
    for(const auto& op:ops){using O=prototype::phase59::OperationState;if(op.state==O::Pending)s.pending=op;else if(op.state==O::Submitted||op.state==O::Applied)s.active=op;else s.lastResult=op;}return s;}
ProgressivePosition ProgressiveMacPlaybackEngine::getCurrentPlaybackPosition()const{auto& x=*impl_;std::lock_guard lock(x.mutex);auto sample=x.pipeline?x.pipeline->positionSample():x.retiredPosition;const auto d=x.pipeline?x.pipeline->diagnostics():x.retired;ProgressivePosition p;p.session=d.session;p.outputFrame=d.consumed;const auto rate=x.rendering?x.rendering->rate:0;if(rate)p.outputSeconds=p.outputFrame/rate;
    if(sample&&sample->session==d.session){p.inputFrame=sample->input;p.sampledOutputFrame=sample->output;if(rate)p.inputSeconds=sample->input/rate;}return p;}
ProgressiveDiagnostics ProgressiveMacPlaybackEngine::getPlaybackDiagnostics()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveDiagnostics d;d.timeStretchLabSha=TIMESTRETCH_PHASE60_SHA;d.preparation=x.revision;d.pipeline=x.pipeline?x.pipeline->diagnostics():x.retired;const auto& p=d.pipeline;
    d.session=d.inputGeneration=p.session;d.generatedFrames=p.generated;d.publishedFrames=p.published;d.consumedFrames=p.consumed;d.presentedFrames=x.rendering?x.rendering->presented.load():0;d.missingFrames=p.missingFrames;d.underrunCalls=p.missingCalls;d.maxConsecutiveMissingFrames=p.maxConsecutiveMissing;d.rejectedWrites=p.rejectedWrites;
    d.sourceSampleRate=x.rendering?static_cast<unsigned>(x.rendering->rate):0;d.channels=x.rendering?x.rendering->channels:0;d.inputFrames=p.inputFrames;d.residentInputBytes=p.residentInputBytes;d.temporarySourceBytes=p.sourceSnapshotBytes;d.reservationBytes=x.reservation;d.requestedSpeed=x.requested;d.appliedTargetSpeed=x.applied(x.pipeline?x.pipeline->speedOperations():x.retiredOperations);d.processCpuS=x.acceptedAt?processCpu()-x.cpuStart:0;if(!x.pipeline&&p.session)d.dspWorkerCpuS=p.dspWorkerCpuS;d.acceptedToReadyS=x.readyAfter;d.constructorS=x.constructorS;d.fifoSupplyFailed=progressive::SupplyQuality::evaluate(p.missingFrames,p.missingCalls,p.rejectedWrites).failed;d.error=x.error.empty()?p.error:x.error;
    const auto& m=p.scheduling;
    if(d.fifoSupplyFailed||p.failed||m.deadlineMisses||m.policyErrors||m.joinErrors||m.restoreErrors||m.intervalErrors||m.queryErrors||m.waitErrors||m.wakeErrors||(x.rendering&&(x.rendering->overruns||x.rendering->formats)))d.overallAudioQuality=false;
    rusage r{};getrusage(RUSAGE_SELF,&r);d.peakRssBytes=r.ru_maxrss;mach_task_basic_info_data_t info{};mach_msg_type_number_t count=MACH_TASK_BASIC_INFO_COUNT;if(task_info(mach_task_self(),MACH_TASK_BASIC_INFO,reinterpret_cast<task_info_t>(&info),&count)==KERN_SUCCESS)d.rssBytes=info.resident_size;return d;}
ProgressiveNativeDiagnostics ProgressiveMacPlaybackEngine::getNativeDiagnostics()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveNativeDiagnostics d;static_cast<MacDiagnostics&>(d)=x.native;d.error=x.error;if(auto s=x.rendering){d.firstPcmMachNs=s->firstPcm;d.lastPcmTargetEndNs=s->lastTarget;d.callbackCalls=s->calls;d.maxCallbackNs=s->maximum;d.deadlineMisses=s->overruns;d.formatErrors=s->formats;d.callbackRecordsDropped=s->dropped;d.hostMissing=s->hostMissing;d.hostBackwards=s->hostBackwards;d.hostCadenceErrors=s->hostCadence;d.sampleErrors=s->sampleErrors;d.halWindowMisses=s->halMisses;d.invalidSampleTimeCalls=s->invalidSample;d.invalidRateScalarCalls=s->invalidScalar;}return d;}
std::vector<MacCallbackRecord> ProgressiveMacPlaybackEngine::callbackRecords()const{auto& x=*impl_;std::lock_guard lock(x.mutex);auto s=x.rendering;if(!s)return {};if(s->active||s->inRender||x.state==State::Draining)throw std::logic_error("callback静止後だけ履歴を取得できます");return {s->records.begin(),s->records.begin()+std::min<std::size_t>(s->records.size(),s->recordsCount.load())};}
std::vector<Operation> ProgressiveMacPlaybackEngine::operationHistory()const{auto& x=*impl_;std::lock_guard lock(x.mutex);return x.pipeline?x.pipeline->speedOperations():x.retiredOperations;}
TimeMap ProgressiveMacPlaybackEngine::finalTimeMap()const{auto& x=*impl_;std::lock_guard lock(x.mutex);if(x.pipeline||x.retiredMap.empty())throw std::logic_error("静止した確定Mapが必要です");return x.retiredMap;}
void ProgressiveMacPlaybackEngine::simulateDeviceChangeForTest(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);x.force=true;if(x.rendering)x.rendering->forcedRoute=true;}
}
