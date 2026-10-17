#import <AVFoundation/AVFoundation.h>
#import <CoreAudio/CoreAudio.h>
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase46HostClock.h"
#include "prototype/Phase61OutputTransition.h"
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
std::uint64_t machNs(){static const auto tb=[] {mach_timebase_info_data_t b{};mach_timebase_info(&b);return b;}();return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*tb.numer/tb.denom);}
struct RenderTarget {
    Pipeline* pipeline=nullptr;
    std::uint64_t session=0,inputGeneration=0,epoch=1;
    std::atomic<std::uint64_t> presented{0},firstPcm{0},firstTarget{0};
};
static_assert(std::atomic<RenderTarget*>::is_always_lock_free);
static_assert(std::atomic<unsigned>::is_always_lock_free);
using SwitchPhase=prototype::phase61::SwitchPhase;
struct RenderSwitch {
    std::atomic<SwitchPhase> phase{SwitchPhase::Idle};
    RenderTarget* oldTarget=nullptr;RenderTarget* newTarget=nullptr;
    prototype::phase61::OutputTransition output;
    std::uint64_t beginNs=0,endNs=0,oldAvailable=0; // audio writes, acquire Done before normal reads
};
struct RenderState {
    RenderSwitch handoff;
    std::atomic<RenderTarget*> target{nullptr};
    unsigned channels=0,numer=1,denom=1;double rate=0;
    std::atomic<bool> active{false},route{false},forcedRoute{false};
    std::atomic<unsigned> inRender{0};
    std::atomic<std::uint64_t> calls{0},presented{0},maximum{0},overruns{0},formats{0};
    std::atomic<std::uint64_t> hostMissing{0},hostBackwards{0},hostCadence{0},sampleErrors{0},halMisses{0};
    std::atomic<std::uint64_t> invalidSample{0},invalidScalar{0};
    std::atomic<std::uint64_t> firstPcm{0},lastTarget{0},recordsCount{0},dropped{0};
    std::vector<MacCallbackRecord> records;
    std::atomic_flag busy=ATOMIC_FLAG_INIT;
    // SourceNode stays alive across seek: do not reset clock continuity there.
    // Pause/resume changes this clock epoch only after callback quiescence.
    std::uint64_t clockEpoch=1;prototype::Phase46HostClock clock;
    RenderAllocationHooks allocationHooks{};
    std::atomic<std::uint64_t> cppAllocations{0};
    std::uint64_t callbackFrame=0; // render consumer only, independent of source jumps
    void* observerContext=nullptr;
    void(*observer)(void*,const float*const*,std::size_t,std::size_t)noexcept=nullptr;
    void(*epochObserver)(void*,const float*const*,std::size_t,std::size_t,std::uint64_t,std::uint64_t,std::uint64_t)noexcept=nullptr;
    decltype(ProgressiveOptions::observeOutputPcm) outputObserver=nullptr;
    std::uint64_t ns()const noexcept{return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*numer/denom);}
};
OSStatus render(RenderState* s,BOOL* silent,const AudioTimeStamp* stamp,AVAudioFrameCount n,AudioBufferList* buffers) noexcept {
    s->inRender.fetch_add(1,std::memory_order_seq_cst);
    if(s->allocationHooks.enter)s->allocationHooks.enter();
    struct Allocations {RenderState* s;bool ownsBusy=false;~Allocations(){if(s->allocationHooks.leave)s->allocationHooks.leave();if(s->allocationHooks.count)s->cppAllocations.fetch_add(s->allocationHooks.count());if(ownsBusy)s->busy.clear(std::memory_order_release);s->inRender.fetch_sub(1,std::memory_order_seq_cst);}} allocations{s};
    if(s->busy.test_and_set(std::memory_order_acquire)){
        if(buffers)for(unsigned c=0;c<buffers->mNumberBuffers;++c)if(buffers->mBuffers[c].mData)std::memset(buffers->mBuffers[c].mData,0,buffers->mBuffers[c].mDataByteSize);
        ++s->formats;*silent=YES;return noErr;
    }
    allocations.ownsBusy=true;
    auto* target=s->target.load(std::memory_order_seq_cst);
    const auto start=s->ns();float* p[2]{};const float* rawPointers[2]{};
    bool valid=buffers&&buffers->mNumberBuffers==s->channels;
    if(buffers)for(unsigned c=0;c<buffers->mNumberBuffers;++c){const auto& b=buffers->mBuffers[c];valid&=b.mData&&b.mNumberChannels==1&&b.mDataByteSize>=n*sizeof(float);if(c<2){p[c]=static_cast<float*>(b.mData);rawPointers[c]=p[c];}}
    const bool active=s->active.load(std::memory_order_seq_cst)&&target;
    prototype::phase58::RenderResult r;
    std::size_t audibleFrames=0;
    if(active&&valid&&target){
        auto& h=s->handoff;auto phase=h.phase.load(std::memory_order_acquire);
        if(phase==SwitchPhase::Requested){
            auto expected=SwitchPhase::Requested;
            if(h.newTarget->pipeline->failed()){
                h.phase.compare_exchange_strong(expected,SwitchPhase::Cancelled,std::memory_order_acq_rel);phase=h.phase.load(std::memory_order_acquire);
            }else if(h.phase.compare_exchange_strong(expected,SwitchPhase::Started,std::memory_order_acq_rel)){
                h.beginNs=s->ns();h.oldAvailable=h.oldTarget->pipeline->available();
                target=h.newTarget;s->target.store(target,std::memory_order_seq_cst);phase=SwitchPhase::Started;
            }else phase=expected;
        }
        if(phase==SwitchPhase::Started)target=h.newTarget;
        r=target->pipeline->pullAudio(p,n);s->presented.fetch_add(r.wanted,std::memory_order_relaxed);target->presented.fetch_add(r.wanted,std::memory_order_relaxed);
        audibleFrames=r.received;
        // These observers always see each source BEFORE any output mix.
        if(r.received&&s->observer)s->observer(s->observerContext,rawPointers,r.received,r.outputBefore);
        if(r.received&&s->epochObserver)s->epochObserver(s->observerContext,rawPointers,r.received,r.outputBefore,target->inputGeneration,target->epoch,target->session);
        std::size_t mixed=0,transitionOffset=0,oldOffset=0,oldReceived=0;std::uint64_t oldEpoch=0;
        if(phase==SwitchPhase::Started){
            mixed=std::min<std::size_t>(n,h.output.remaining());transitionOffset=h.output.cursor;oldEpoch=h.oldTarget->epoch;
            float* oldP[2]{h.output.oldPcm[0].data(),h.output.oldPcm[1].data()};
            // Expected old EOS is not a supply failure. A non-EOS short read is.
            const auto wanted=h.oldTarget->pipeline->finished()?std::min(mixed,h.oldTarget->pipeline->available()):mixed;
            const auto previous=h.oldTarget->pipeline->pullAudio(oldP,wanted);
            oldOffset=previous.outputBefore;oldReceived=previous.received;
            audibleFrames=std::max(audibleFrames,oldReceived);
            for(unsigned c=0;c<s->channels;++c)std::fill(oldP[c]+previous.received,oldP[c]+mixed,0.f);
            h.oldTarget->presented.fetch_add(previous.wanted,std::memory_order_relaxed);
            const float* oldRaw[]{oldP[0],oldP[1]};
            if(previous.received&&s->epochObserver)s->epochObserver(s->observerContext,oldRaw,previous.received,previous.outputBefore,h.oldTarget->inputGeneration,h.oldTarget->epoch,h.oldTarget->session);
            h.output.mix(p,mixed,s->channels);
            h.endNs=s->ns(); // also preserves the last partial chunk on route abort
            // Done releases all old references. Owner still waits inRender==0
            // before clearing the slot or destroying its two raw targets.
            if(!h.output.remaining())h.phase.store(SwitchPhase::Done,std::memory_order_release);
        }
        if(s->outputObserver){ProgressiveOutputSpan span;
            span.newEpoch=target->epoch;span.oldEpoch=oldEpoch;span.callbackFrame=s->callbackFrame;
            span.newOutputOffset=r.outputBefore;span.oldOutputOffset=oldOffset;span.newReceivedFrames=r.received;span.oldReceivedFrames=oldReceived;
            span.frames=n;span.mixedFrames=mixed;span.transitionOffset=transitionOffset;span.transitionLength=mixed?h.output.length:0;
            s->outputObserver(s->observerContext,rawPointers,span);
        }
        s->callbackFrame+=n;
    }else if(buffers){for(unsigned c=0;c<buffers->mNumberBuffers;++c)if(buffers->mBuffers[c].mData)std::memset(buffers->mBuffers[c].mData,0,buffers->mBuffers[c].mDataByteSize);if(active)++s->formats;}
    *silent=audibleFrames==0;
    if(active){
        const auto io=s->ns(),sequence=s->calls.fetch_add(1)+1;
        const auto flags=stamp?stamp->mFlags:0;
        const auto host=stamp&&(flags&kAudioTimeStampHostTimeValid)?static_cast<std::uint64_t>(static_cast<long double>(stamp->mHostTime)*s->numer/s->denom):0;
        const auto sample=stamp?stamp->mSampleTime:0;
        s->invalidSample.fetch_add(!(flags&kAudioTimeStampSampleTimeValid)||!std::isfinite(sample));
        s->invalidScalar.fetch_add(!(flags&kAudioTimeStampRateScalarValid)||!std::isfinite(stamp?stamp->mRateScalar:0));
        if(audibleFrames){std::uint64_t zero=0;s->firstPcm.compare_exchange_strong(zero,start);const bool plausible=host&&std::abs(double(host)-double(start))<=1e9;const auto beginTarget=plausible?host:io;
            if(r.received){zero=0;target->firstPcm.compare_exchange_strong(zero,start);zero=0;target->firstTarget.compare_exchange_strong(zero,beginTarget);}
            s->lastTarget=beginTarget+static_cast<std::uint64_t>(audibleFrames*1e9/s->rate);
        }
        auto evidence=s->clock.observe(s->clockEpoch,start,io,host!=0,host,(flags&kAudioTimeStampSampleTimeValid)!=0,sample,n,s->rate);
        s->hostMissing.fetch_add(evidence.hostMissing);s->hostBackwards.fetch_add(evidence.hostBackwards);s->hostCadence.fetch_add(evidence.cadenceError||evidence.offsetOutlier);s->sampleErrors.fetch_add(evidence.sampleError);
        MacCallbackRecord* record=nullptr;
        if(!s->records.empty()){const auto i=s->recordsCount.fetch_add(1);if(i<s->records.size()){
            record=&s->records[i];*record={};record->sequence=sequence;record->epoch=s->clockEpoch;record->startNs=start;record->ioEndNs=io;record->hostNs=host;record->hostTicks=stamp?stamp->mHostTime:0;record->sampleTime=sample;record->timestampFlags=flags;record->rateScalar=stamp?stamp->mRateScalar:0;record->requested=n;
            record->raw.received=r.received;record->raw.wanted=r.wanted;record->raw.fifoBefore=r.fifoBefore;record->raw.outputBefore=r.outputBefore;record->raw.session=target?target->session:0;
        }else ++s->dropped;}
        const auto end=s->ns();if(record)record->endNs=end;
        // Single callback consumer; the atomic is read only by control threads.
        s->maximum.store(std::max(s->maximum.load(std::memory_order_relaxed),end-start),std::memory_order_relaxed);
        s->overruns.fetch_add(end-start>n*1e9/s->rate);
        s->halMisses.fetch_add(host&&end>host+std::max(100000.,2e9/s->rate));
    }
    return noErr;
}
}
struct ProgressiveMacPlaybackEngine::Impl {
    mutable std::mutex mutex; // only normal control/preparation/monitor threads
    std::atomic<State> state{State::Empty};std::atomic<bool> cancelPrepare{false},exit{false};
    std::thread preparation,monitor;
    std::unique_ptr<Pipeline> pipeline;
    Pipeline* retiringPipeline=nullptr; // normal owner retains until audit is accumulated
    std::unique_ptr<RenderTarget> target;
    std::shared_ptr<RenderState> rendering;
    AVAudioEngine* engine=nil;AVAudioSourceNode* source=nil;id observer=nil;
    std::filesystem::path input;ProgressiveOptions options;
    MacDiagnostics native;prototype::phase58::Diagnostics retired;
    std::vector<Operation> retiredOperations;TimeMap retiredMap;
    std::optional<prototype::phase58::PositionSample> retiredPosition;
    StopReason reason=StopReason::None;
    std::string error;std::uint64_t revision=0,reservation=0;
    bool ownsBudget=false,autoPlay=false;
    std::thread seekWorker;
    std::atomic<std::uint64_t> seekVersion{0};
    std::atomic<bool> seekBusy{false};
    std::vector<progressive::SeekOperation> seeks;
    std::vector<ProgressiveClosedEpoch> closed;
    std::size_t pendingSeek=std::size_t(-1),activeSeek=std::size_t(-1);
    std::size_t seekBase=0;
    std::uint64_t nextEpoch=0,lifetimeMissing=0,lifetimeCalls=0,lifetimeRejected=0,lifetimeMaxMissing=0;
    std::uint64_t retiredEpoch=0,retiredPresented=0;
    std::uint64_t lifetimeWorkerDeadlines=0,lifetimeWorkerNews=0,lifetimeWorkgroupErrors=0;
    static std::uint64_t workerErrors(const prototype::phase58::Diagnostics& p){const auto& m=p.scheduling;return m.policyErrors+m.joinErrors+m.restoreErrors+m.intervalErrors+m.queryErrors+m.waitErrors+m.wakeErrors;}
    bool closedQualityFailed=false;
    double requested=1,acceptedAt=0,readyAfter=-1,constructorS=-1,cpuStart=0;
    std::unique_ptr<RenderTarget> makeTarget(Pipeline* p){
        auto t=std::make_unique<RenderTarget>();t->pipeline=p;t->session=p->diagnostics().session;
        t->inputGeneration=p->inputGeneration();t->epoch=++nextEpoch;t->presented=p->outputStartFrame();return t;
    }
    void cancelSeeks(const std::string& why){
        ++seekVersion;pendingSeek=std::size_t(-1);
        for(std::size_t i=0;i<seeks.size();++i)if(!progressive::terminal(seeks[i].state)&&!startedSeek(i)){seeks[i].state=progressive::SeekState::Cancelled;seeks[i].reason=why;}
    }
    void stopSeeks(){
        {std::lock_guard lock(mutex);cancelSeeks("停止・入力変更により取消");}
        while(seekBusy.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    RenderTarget* effectiveTarget()const {
        if(!pipeline||!rendering)return target.get();
        const auto phase=rendering->handoff.phase.load(std::memory_order_acquire);
        if(phase==SwitchPhase::Started||phase==SwitchPhase::Done)return rendering->handoff.newTarget;
        return rendering->target.load(std::memory_order_seq_cst);
    }
    bool startedSeek(std::size_t index){
        if(index!=activeSeek||!rendering)return false;
        auto& phase=rendering->handoff.phase;auto value=phase.load(std::memory_order_acquire);
        if(value==SwitchPhase::Requested){phase.compare_exchange_strong(value,SwitchPhase::Cancelled,std::memory_order_acq_rel);value=phase.load(std::memory_order_acquire);}
        return value==SwitchPhase::Started||value==SwitchPhase::Done;
    }
    // Impl mutex held; render is quiescent or has released Done.
    void captureSwitch(std::size_t index,const RenderState& s){
        if(index>=seeks.size())return;auto& op=seeks[index];const auto& h=s.handoff;
        op.transitionBeginNs=h.beginNs;op.transitionEndNs=h.endNs;op.oldFifoAtSwitchFrames=h.oldAvailable;op.transitionFrames=h.output.cursor;
        if(h.newTarget){op.firstCallbackNs=h.newTarget->firstPcm;op.estimatedPresentationNs=h.newTarget->firstTarget;}
    }
    // Impl mutex held, after the corresponding normal worker has joined.
    void archiveEpoch(ProgressiveClosedEpoch audit){
        const auto& d=audit.pipeline;lifetimeMissing+=d.missingFrames;lifetimeCalls+=d.missingCalls;lifetimeRejected+=d.rejectedWrites;
        lifetimeMaxMissing=std::max(lifetimeMaxMissing,d.maxConsecutiveMissing);
        lifetimeWorkerDeadlines+=d.scheduling.deadlineMisses;lifetimeWorkerNews+=d.realtimeNewCalls;lifetimeWorkgroupErrors+=workerErrors(d);
        const auto& m=d.scheduling;closedQualityFailed|=d.failed||d.missingFrames||d.missingCalls||d.rejectedWrites||d.realtimeNewCalls||m.deadlineMisses||workerErrors(d);
        if(audit.operations.size()>256){audit.droppedOperations=audit.operations.size()-256;audit.operations.erase(audit.operations.begin(),audit.operations.end()-256);}
        if(closed.size()==16)closed.erase(closed.begin());closed.push_back(std::move(audit));
    }
    void seekLoop(){@autoreleasepool {while(!exit.load()){
        std::unique_ptr<Pipeline> next,old;
        std::unique_ptr<RenderTarget> nextTarget,oldTarget;
        std::shared_ptr<RenderState> renderLease;
        std::size_t index=std::size_t(-1);std::uint64_t version=0;
        bool published=false,transitionDone=false;
        try{
            {std::lock_guard lock(mutex);
                if(pendingSeek!=std::size_t(-1)&&pipeline){
                    index=pendingSeek;pendingSeek=std::size_t(-1);activeSeek=index;seekBusy=true;version=seekVersion;
                    auto& op=seeks[index];op.state=progressive::SeekState::Preparing;op.preparingNs=machNs();
                    const bool analysis=pipeline->finalAnalysisAvailable();op.waitedForAnalysis|=!analysis;
                    op.stage=analysis?progressive::SeekStage::PreparingFifo:progressive::SeekStage::PreparingAnalysis;
                    if(analysis)op.analysisReadyNs=op.preparingNs;
                    op.speedMicros=progressive::speedMicros(requested);
                    next=op.mode==progressive::SeekMode::FastLocal?pipeline->createInteractiveSeek(op.requestedInputFrame,op.speedMicros,pipeline->sampleRate()*std::size_t(op.prerollMillis)/1000):pipeline->createSeek(op.requestedInputFrame,op.speedMicros);
                }
            }
            if(!next){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}
            next->start();const auto deadline=std::chrono::steady_clock::now()+options.prepareTimeout;
            const auto cancelled=[&]{return exit.load()||seekVersion.load()!=version;};
            while(!cancelled()&&!next->waitUntilReady(std::chrono::milliseconds(1))){
                {std::lock_guard lock(mutex);auto& op=seeks[index];if(!op.analysisReadyNs&&next->finalAnalysisAvailable()){op.analysisReadyNs=machNs();op.stage=progressive::SeekStage::PreparingFifo;}}
                if(next->failed())throw std::runtime_error(next->diagnostics().error);
                if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("シークの準備が期限を超えました");
            }
            if(!cancelled()){
                std::lock_guard lock(mutex);auto& op=seeks[index];
                if(!cancelled()&&pipeline&&!progressive::terminal(op.state)){
                    if(op.speedMicros!=progressive::speedMicros(requested)){
                        ++op.replans;op.state=progressive::SeekState::Pending;pendingSeek=index;
                    }else{
                        op.state=progressive::SeekState::Ready;op.readyNs=machNs();if(!op.analysisReadyNs)op.analysisReadyNs=op.readyNs;
                        op.outputStartFrame=next->outputStartFrame();
                        const auto restore=state.load();
                        if(restore!=State::Ready&&restore!=State::Playing&&restore!=State::Paused)throw std::runtime_error("シーク切替前に再生状態が変わりました");
                        if(next->sampleRate()!=pipeline->sampleRate()||next->channels()!=pipeline->channels()||next->inputGeneration()!=pipeline->inputGeneration())throw std::runtime_error("シーク先の形式・世代が不正です");
                        if(options.seekFailureForTest==1)throw std::runtime_error("検証用: シーク先の昇格前失敗");
                        if(restore==State::Playing&&!next->setRealtimeRendering(true))throw std::runtime_error("シーク先の実時間参加に失敗しました");
                        if(restore==State::Playing&&!next->finished()){
                            const auto m=next->diagnostics().scheduling;
                            if(!m.active||!m.policyMeasured||m.observedPolicy!=2||m.policyErrors||m.joinErrors||m.queryErrors)throw std::runtime_error("シーク先の実時間policyを確認できません");
                        }
                        if(options.seekFailureForTest==2)throw std::runtime_error("検証用: シーク先の公開前失敗");
                        nextTarget=makeTarget(next.get());renderLease=rendering;
                        op.renderEpoch=nextTarget->epoch;op.session=nextTarget->session;
                        op.stage=progressive::SeekStage::SwitchReady;op.switchReadyNs=machNs();
                        if(restore==State::Playing&&op.mode==progressive::SeekMode::FastLocal){
                            auto& h=renderLease->handoff;h.oldTarget=target.get();h.newTarget=nextTarget.get();h.output.prepare(next->sampleRate());h.beginNs=h.endNs=h.oldAvailable=0;
                            h.phase.store(SwitchPhase::Requested,std::memory_order_release);published=true;
                        }else transitionDone=true;
                    }
                }
            }
            const auto switchDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
            while(published){
                bool done=false;
                {std::lock_guard lock(mutex);auto& h=renderLease->handoff;auto phase=h.phase.load(std::memory_order_acquire);
                    if(phase==SwitchPhase::Requested&&(cancelled()||state!=State::Playing||requested!=seeks[index].speedMicros/1000000.)){
                        h.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel);phase=h.phase.load(std::memory_order_acquire);
                    }
                    if(phase==SwitchPhase::Started){seeks[index].stage=progressive::SeekStage::Transitioning;}
                    if(phase==SwitchPhase::Done){transitionDone=true;done=true;}
                    if(phase==SwitchPhase::Cancelled){
                        if(!cancelled()&&next->failed())throw std::runtime_error(next->diagnostics().error);
                        transitionDone=!cancelled()&&pipeline&&(state==State::Paused||state==State::Ready);
                        if(!cancelled()&&pipeline&&state==State::Playing){auto& op=seeks[index];++op.replans;op.state=progressive::SeekState::Pending;pendingSeek=index;transitionDone=false;}
                        done=true;
                    }
                    if(!renderLease->active.load()&&phase==SwitchPhase::Started&&state!=State::Playing){
                        // Route/failed stop has already quiesced the callback.
                        h.phase.store(SwitchPhase::Cancelled,std::memory_order_release);done=true;
                    }
                }
                if(done)break;
                if(std::chrono::steady_clock::now()>switchDeadline)throw std::runtime_error("音声callbackの切替確認が1秒以内に届きませんでした");
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
            if(published)while(renderLease->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
            {std::lock_guard lock(mutex);
                if(published)captureSwitch(index,*renderLease);
                if(transitionDone&&pipeline&&nextTarget&&!progressive::terminal(seeks[index].state)){
                    auto& op=seeks[index];
                    if(next->failed())throw std::runtime_error(next->diagnostics().error);
                    if(state==State::Paused&&!next->setRealtimeRendering(false))throw std::runtime_error("Pausedシーク先の実時間policy復元に失敗しました");
                    if(published){const auto& h=renderLease->handoff;op.transitionBeginNs=h.beginNs;op.transitionEndNs=h.endNs;op.oldFifoAtSwitchFrames=h.oldAvailable;op.transitionFrames=h.output.cursor;}
                    old=std::move(pipeline);retiringPipeline=old.get();oldTarget=std::move(target);pipeline=std::move(next);target=std::move(nextTarget);options.initialSpeed=op.speedMicros/1000000.;
                    op.switchedNs=op.transitionBeginNs?op.transitionBeginNs:machNs();
                    rendering->target.store(target.get(),std::memory_order_seq_cst);op.firstCallbackNs=target->firstPcm;op.estimatedPresentationNs=target->firstTarget;
                    op.state=progressive::SeekState::Completed;op.stage=progressive::SeekStage::Finished;
                }
                if(published)renderLease->handoff.phase.store(SwitchPhase::Idle,std::memory_order_release);
            }
        }catch(const std::exception& e){
            std::lock_guard lock(mutex);
            if(index<seeks.size()&&!progressive::terminal(seeks[index].state)){seeks[index].state=progressive::SeekState::Failed;seeks[index].reason=e.what();}
        }
        // Both references outlive the callback; deletion and joining are normal work.
        if(next&&published){
            std::lock_guard lock(mutex);auto& h=renderLease->handoff;auto phase=SwitchPhase::Requested;
            h.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel);
            if(h.phase.load(std::memory_order_acquire)==SwitchPhase::Started||renderLease->target.load()==nextTarget.get()){
                // An exceptional failure after output began cannot roll its
                // consumed PCM back. Quiesce BOTH owners before releasing next.
                fail("切替開始後の失敗により安全停止しました");
            }
            while(renderLease->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
            h.phase.store(SwitchPhase::Idle,std::memory_order_release);
        }
        if(next){next->setRealtimeRendering(false);next->stop();
            ProgressiveClosedEpoch audit;audit.renderEpoch=nextTarget?nextTarget->epoch:0;audit.pipeline=next->diagnostics();audit.operations=next->speedOperations();
            audit.preparedOnly=!nextTarget||!nextTarget->firstPcm.load();
            {std::lock_guard lock(mutex);if(published)captureSwitch(index,*renderLease);archiveEpoch(std::move(audit));}
            next.reset();
        }
        if(old){
            while(renderLease->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
            old->setRealtimeRendering(false);old->stop();
            {std::lock_guard lock(mutex);if(index<seeks.size())seeks[index].discardedForSeekFrames=old->available();}
            ProgressiveClosedEpoch audit;audit.renderEpoch=oldTarget->epoch;audit.pipeline=old->diagnostics();audit.operations=old->speedOperations();
            if(audit.operations.size()>256){audit.droppedOperations=audit.operations.size()-256;audit.operations.erase(audit.operations.begin(),audit.operations.end()-256);}
            {std::lock_guard lock(mutex);for(auto& op:seeks)if(op.renderEpoch==oldTarget->epoch){op.firstCallbackNs=oldTarget->firstPcm;op.estimatedPresentationNs=oldTarget->firstTarget;}}
            std::lock_guard lock(mutex);retiringPipeline=nullptr;archiveEpoch(std::move(audit));
            old.reset();oldTarget.reset();
        }
        {std::lock_guard lock(mutex);activeSeek=std::size_t(-1);seekBusy=false;if(!pipeline)releaseBudget();}
    }}}
    Impl(){seeks.reserve(4096);closed.reserve(16);monitor=std::thread([this]{@autoreleasepool {while(!exit.load()){
        {std::lock_guard lock(mutex);try{tick();}catch(const std::exception& e){fail(e.what());}}
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }}});seekWorker=std::thread([this]{seekLoop();});}
    ~Impl(){cancelPrepare=true;{std::lock_guard lock(mutex);cancelSeeks("破棄により取消");}exit=true;++seekVersion;if(monitor.joinable())monitor.join();if(seekWorker.joinable())seekWorker.join();if(preparation.joinable())preparation.join();std::lock_guard lock(mutex);retire();}
    void releaseBudget(){if(ownsBudget&&!seekBusy.load()){resourceOwner=false;ownsBudget=false;}}
    void quiesce(bool destroy){
        if(rendering)rendering->active.store(false,std::memory_order_seq_cst);
        if(engine&&engine.isRunning)[engine stop];
        if(rendering)while(rendering->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
        if(rendering)native.outputStoppedMachNs=rendering->ns();
        if(destroy){if(observer)[[NSNotificationCenter defaultCenter]removeObserver:observer];observer=nil;if(engine&&source)[engine detachNode:source];source=nil;engine=nil;}
    }
    void retire(){
        quiesce(true);
        if(rendering){auto& h=rendering->handoff;const auto phase=h.phase.load();if(phase==SwitchPhase::Started||phase==SwitchPhase::Done)captureSwitch(activeSeek,*rendering);if(phase!=SwitchPhase::Idle)h.phase.store(SwitchPhase::Cancelled,std::memory_order_release);}
        if(activeSeek<seeks.size()&&!progressive::terminal(seeks[activeSeek].state)){seeks[activeSeek].state=progressive::SeekState::Cancelled;seeks[activeSeek].reason="静止・退役により取消";}
        if(target){retiredEpoch=target->epoch;retiredPresented=target->presented;for(auto& op:seeks)if(op.renderEpoch==target->epoch){op.firstCallbackNs=target->firstPcm;op.estimatedPresentationNs=target->firstTarget;}}
        if(rendering)rendering->target=nullptr;
        if(pipeline){pipeline->setRealtimeRendering(false);pipeline->stop();retired=pipeline->diagnostics();retiredOperations=pipeline->speedOperations();retiredPosition=pipeline->positionSample();
            if(retired.analysisDone&&!retired.failed){try{retiredMap=pipeline->dynamicTimeMap();}catch(const std::logic_error&) {}}
            pipeline.reset();}
        target.reset();
        releaseBudget();
    }
    void fail(const std::string& message){cancelSeeks(message);error=message;reason=StopReason::WorkerError;retire();state=State::Failed;}
    void configure(){@try {
        StageClock clock;engine=[[AVAudioEngine alloc]init];native={};native.deviceId=defaultDevice();
        auto f=[engine.outputNode outputFormatForBus:0];native.deviceRate=f.sampleRate;native.deviceChannels=f.channelCount;native.deviceBufferFrames=bufferFrames(native.deviceId);
        if(!native.deviceRate||!native.deviceChannels)throw std::runtime_error("出力形式が無効です");
        native.devicePresentationLatencyMs=engine.outputNode.presentationLatency*1000;
        rendering=std::make_shared<RenderState>();auto s=rendering;s->rate=pipeline->sampleRate();s->channels=static_cast<unsigned>(pipeline->channels());
        target=makeTarget(pipeline.get());s->target=target.get();
        mach_timebase_info_data_t tb{};if(mach_timebase_info(&tb)!=KERN_SUCCESS)throw std::runtime_error("Mach時計を取得できません");s->numer=tb.numer;s->denom=tb.denom;
        s->observer=options.observeRawPcm;s->observerContext=options.observerContext;
        s->epochObserver=options.observeEpochPcm;s->outputObserver=options.observeOutputPcm;
        s->allocationHooks=options.allocationHooks;
        if(options.callbackRecordLimit){s->records.resize(options.callbackRecordLimit);auto* p=reinterpret_cast<volatile unsigned char*>(s->records.data());const auto bytes=s->records.size()*sizeof(MacCallbackRecord);for(std::size_t i=0;i<bytes;i+=std::size_t(getpagesize()))p[i]=p[i];p[bytes-1]=p[bytes-1];}
        auto format=[[AVAudioFormat alloc]initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:s->rate channels:s->channels interleaved:NO];
        source=[[AVAudioSourceNode alloc]initWithFormat:format renderBlock:^OSStatus(BOOL* silent,const AudioTimeStamp* stamp,AVAudioFrameCount n,AudioBufferList* b){return render(s.get(),silent,stamp,n,b);}];
        [engine attachNode:source];[engine connect:source to:engine.mainMixerNode format:format];engine.mainMixerNode.outputVolume=.5f;
        [engine prepare];native.avConstruction=clock.elapsed();
        observer=[[NSNotificationCenter defaultCenter]addObserverForName:AVAudioEngineConfigurationChangeNotification object:engine queue:nil usingBlock:^(NSNotification*){s->route=true;}];
    }@catch(NSException* e){throw std::runtime_error(e.reason?e.reason.UTF8String:"音声構成APIの例外");}}
    bool startAudio(){@try {
        auto* current=effectiveTarget()->pipeline;
        if(!current->setRealtimeRendering(true))throw std::runtime_error("Audio Workgroupへの昇格・参加に失敗しました");
        const auto m=current->diagnostics().scheduling;
        if(!current->finished()&&(!m.active||!m.policyMeasured||m.policyErrors||m.joinErrors||m.queryErrors))throw std::runtime_error("実時間policyが確認できません");
        if(cancelPrepare.load())throw std::runtime_error("準備が取り消されました");
        StageClock clock;NSError* e=nil;rendering->active=true;native.playCalledSteadyNs=static_cast<std::uint64_t>(seconds()*1e9);
        if(![engine startAndReturnError:&e]){rendering->active=false;throw std::runtime_error(e?e.localizedDescription.UTF8String:"音声開始に失敗しました");}
        native.sourcePresentationLatencyMs=source.outputPresentationLatency*1000;native.avStart=clock.elapsed();state=State::Playing;return true;
    }@catch(NSException* e){throw std::runtime_error(e.reason?e.reason.UTF8String:"音声開始APIの例外");}}
    std::uint64_t tailDeadline()const {return rendering->lastTarget.load()+static_cast<std::uint64_t>(std::max(native.sourcePresentationLatencyMs,native.devicePresentationLatencyMs)*1e6)+5000000;}
    void tick(){
        if(!pipeline)return;
        for(auto& op:seeks)if(auto* t=effectiveTarget();op.renderEpoch&&t&&op.renderEpoch==t->epoch){op.firstCallbackNs=t->firstPcm;op.estimatedPresentationNs=t->firstTarget;}
        if(pipeline->failed()){fail(pipeline->diagnostics().error);return;}
        if(rendering&&(rendering->forcedRoute.exchange(false)||rendering->route.exchange(false))){
            const bool forced=force;force=false;auto f=[engine.outputNode outputFormatForBus:0];
            if(forced||defaultDevice()!=native.deviceId||f.sampleRate!=native.deviceRate||f.channelCount!=native.deviceChannels||bufferFrames(native.deviceId)!=native.deviceBufferFrames){++native.routeChanges;cancelSeeks("装置変更により取消");retire();reason=StopReason::RouteChanged;state=State::Stopped;return;}
        }
        if(seekBusy.load()||pendingSeek!=std::size_t(-1))return;
        if(state==State::Playing&&pipeline->drained())state=State::Draining;
        if(state==State::Draining&&rendering->ns()>=tailDeadline()){
            // Stop callback first, then join/leave and release borrowed owners.
            retire();reason=StopReason::EndOfStream;state=State::Ended;
        }
    }
    bool force=false;
    void launch(){
        cancelPrepare=false;autoPlay=false;acceptedAt=seconds();cpuStart=processCpu();readyAfter=constructorS=-1;++revision;
        retired={};retiredEpoch=retiredPresented=0;retiredOperations.clear();retiredMap={};retiredPosition.reset();rendering.reset();native={};error.clear();reason=StopReason::None;reservation=0;
        state=State::Accepted;
        seekBase=seeks.size();lifetimeWorkerDeadlines=lifetimeWorkerNews=lifetimeWorkgroupErrors=0;lifetimeMissing=lifetimeCalls=lifetimeRejected=lifetimeMaxMissing=0;closed.clear();closedQualityFailed=false;
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
                prototype::phase58::Configuration c;c.speedMicros=progressive::speedMicros(o.initialSpeed);c.candidate=o.preset==Preset::Candidate;c.verifyPcm=false;c.residentInput=true;c.dynamicTransitions=true;c.scheduling=prototype::phase58::WorkerScheduling::AudioWorkgroup;c.sourceSnapshotBytes=bytes;c.seekCheckpoints=o.seekCheckpoints;
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
    double applied(const std::vector<Operation>& ops,const RenderTarget* effective=nullptr)const{double s=options.initialSpeed;if(effective&&effective!=target.get())for(const auto& seek:seeks)if(seek.renderEpoch==effective->epoch){s=seek.speedMicros/1000000.;break;}for(const auto& op:ops)if(op.appliedS>=0)s=op.target/1000000.;return s;}
};
ProgressiveMacPlaybackEngine::ProgressiveMacPlaybackEngine():impl_(std::make_unique<Impl>()){}
ProgressiveMacPlaybackEngine::~ProgressiveMacPlaybackEngine()=default;
bool ProgressiveMacPlaybackEngine::prepare(const std::filesystem::path& p,ProgressiveOptions o){
    workQueue();progressive::speedMicros(o.initialSpeed);
    const auto hooks=unsigned(bool(o.allocationHooks.enter))+unsigned(bool(o.allocationHooks.leave))+unsigned(bool(o.allocationHooks.count));
    if(hooks&&hooks!=3)throw std::invalid_argument("確保計測hookは3個すべてを指定してください");
    if((o.preset!=Preset::Candidate&&o.preset!=Preset::Baseline)||o.callbackRecordLimit>262144||o.prepareTimeout.count()<=0||o.memoryReservationBudget>1024ULL*1024*1024||o.seekFailureForTest>2)throw std::invalid_argument("実験用設定が無効です");
    auto& x=*impl_;auto state=x.state.load();if(state==State::Accepted||state==State::Preparing||state==State::Playing||state==State::Paused||state==State::Draining)throw std::logic_error("入力変更前にstopしてください");
    x.stopSeeks();x.stopPreparation();std::lock_guard lock(x.mutex);x.retire();x.input=p;x.options=o;x.requested=o.initialSpeed;x.launch();return true;
}
bool ProgressiveMacPlaybackEngine::play(){
    workQueue();auto& x=*impl_;auto state=x.state.load();
    if(state==State::Stopped||state==State::Ended){x.stopPreparation();std::lock_guard lock(x.mutex);if(x.input.empty())return false;x.retire();x.options.initialSpeed=x.requested;x.launch();x.autoPlay=true;return true;}
    std::lock_guard lock(x.mutex);if(x.state==State::Playing)return true;if(x.state==State::Accepted||x.state==State::Preparing){x.autoPlay=true;return true;}if(x.state!=State::Ready)return false;
    try{return x.startAudio();}catch(const std::exception& e){x.fail(e.what());return false;}
}
bool ProgressiveMacPlaybackEngine::pause(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);if(x.state!=State::Playing)return false;
    try{auto& h=x.rendering->handoff;auto phase=h.phase.load(std::memory_order_acquire);if(phase==SwitchPhase::Requested)h.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel);
        const auto switchLimit=std::chrono::steady_clock::now()+std::chrono::milliseconds(100);
        while(h.phase.load(std::memory_order_acquire)==SwitchPhase::Started){if(std::chrono::steady_clock::now()>switchLimit)throw std::runtime_error("Pause中の切替確認が届きません");std::this_thread::sleep_for(std::chrono::microseconds(100));}
        x.rendering->active=false;while(x.rendering->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));
        const auto limit=x.rendering->ns()+1000000000;while(x.rendering->ns()<x.tailDeadline()){if(x.rendering->ns()>limit)throw std::runtime_error("末尾提示時刻が無効です");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
        [x.engine pause];while(x.rendering->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));if(!x.effectiveTarget()->pipeline->setRealtimeRendering(false))throw std::runtime_error("Pause時の実時間policy復元に失敗しました");x.state=State::Paused;return true;
    }catch(const std::exception& e){x.fail(e.what());return false;}}
bool ProgressiveMacPlaybackEngine::resume(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);if(x.state!=State::Paused)return false;try{++x.rendering->clockEpoch;return x.startAudio();}catch(const std::exception& e){x.fail(e.what());return false;}}
void ProgressiveMacPlaybackEngine::stop(){workQueue();auto& x=*impl_;x.cancelPrepare=true;x.stopSeeks();x.stopPreparation();std::lock_guard lock(x.mutex);x.retire();x.reason=StopReason::User;x.state=State::Stopped;}
prototype::phase59::RequestReceipt ProgressiveMacPlaybackEngine::setSpeed(double s,std::uint64_t session,std::uint64_t generation,std::uint64_t epoch){workQueue();const auto micros=progressive::speedMicros(s);auto& x=*impl_;std::lock_guard lock(x.mutex);
    if(!x.pipeline)return {0,prototype::Phase39RequestResult::Stopped};
    const auto* before=x.effectiveTarget();if(!before||(epoch&&epoch!=before->epoch)||(session&&session!=before->session)||(generation&&generation!=before->inputGeneration))return {0,prototype::Phase39RequestResult::Stopped};
    // Close the unstarted switch before changing the old epoch's speed. If
    // render won this CAS, resolve identity to the new epoch instead.
    if(x.rendering){auto phase=SwitchPhase::Requested;x.rendering->handoff.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel);}
    const auto* current=x.effectiveTarget();if(!current||(epoch&&epoch!=current->epoch))return {0,prototype::Phase39RequestResult::Stopped};
    auto r=current->pipeline->requestSpeed(micros,current->presented.load(),session,generation);if(r.result==prototype::Phase39RequestResult::Accepted)x.requested=s;return r;}
progressive::SeekReceipt ProgressiveMacPlaybackEngine::requestSeekToInputFrame(std::uint64_t frame,std::uint64_t generation,std::uint64_t epoch){
    return requestSeekFrame(frame,generation,epoch,progressive::SeekMode::Exact,0);
}
progressive::SeekReceipt ProgressiveMacPlaybackEngine::requestFastLocalSeekToInputFrame(std::uint64_t frame,std::uint64_t generation,std::uint64_t epoch,std::uint32_t preroll){
    return requestSeekFrame(frame,generation,epoch,progressive::SeekMode::FastLocal,preroll);
}
progressive::SeekAvailability ProgressiveMacPlaybackEngine::seekAvailability()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);progressive::SeekAvailability a;
    a.interactiveOptIn=x.options.allowUnvalidatedFastLocalSeek;
    a.interactiveAllowed=a.interactiveOptIn&&x.pipeline&&(x.state==State::Ready||x.state==State::Playing||x.state==State::Paused);return a;
}
progressive::SeekReceipt ProgressiveMacPlaybackEngine::requestInteractiveSeekToInputFrame(std::uint64_t frame,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session){
    return requestSeekFrame(frame,generation,epoch,progressive::SeekMode::FastLocal,500,session&&generation&&epoch?session:UINT64_MAX);
}
progressive::SeekReceipt ProgressiveMacPlaybackEngine::requestInteractiveSeekToInputSeconds(double seconds,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session){
    return requestSeekSeconds(seconds,generation,epoch,progressive::SeekMode::FastLocal,500,session&&generation&&epoch?session:UINT64_MAX);
}
progressive::SeekReceipt ProgressiveMacPlaybackEngine::requestSeekFrame(std::uint64_t frame,std::uint64_t generation,std::uint64_t epoch,progressive::SeekMode mode,std::uint32_t preroll,std::uint64_t session){
    workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);progressive::SeekOperation op;
    if(x.seeks.size()>=4096)return {0,false,"シーク操作の上限4096件です"};
    op.id=x.seeks.size()+1;op.requestedInputFrame=frame;op.acceptedNs=machNs();op.mode=mode;op.prerollMillis=preroll;
    if(x.pipeline)op.inputGeneration=x.pipeline->inputGeneration();if(auto* t=x.effectiveTarget())op.sourceRenderEpoch=t->epoch;
    if(!x.pipeline||(x.state!=State::Ready&&x.state!=State::Playing&&x.state!=State::Paused))op.reason="シークにはReady/Playing/Pausedが必要です";
    else if(frame>x.pipeline->inputFrames())op.reason="シーク位置が曲長を超えています";
    else if(generation&&generation!=op.inputGeneration)op.reason="古い入力世代です";
    else if(epoch&&epoch!=op.sourceRenderEpoch)op.reason="古い再生区間です";
    else if(session&&(!x.effectiveTarget()||session!=x.effectiveTarget()->session))op.reason="古いsessionです";
    else if(mode==progressive::SeekMode::FastLocal&&preroll!=500&&preroll!=1000&&preroll!=2000)op.reason="局所準備区間は500/1000/2000msです";
    else if(mode==progressive::SeekMode::FastLocal&&x.pipeline->sampleRate()!=44100&&x.pipeline->sampleRate()!=48000)op.reason="Interactiveは44.1/48kHzが対象です";
    else if(mode==progressive::SeekMode::FastLocal&&!x.options.allowUnvalidatedFastLocalSeek)op.reason="Interactive Seekは開発用opt-inが必要です";
    const bool accepted=op.reason.empty();
    if(accepted){for(std::size_t i=0;i<x.seeks.size();++i)if(!progressive::terminal(x.seeks[i].state)&&!x.startedSeek(i))x.seeks[i].state=progressive::SeekState::Replaced;
        op.state=progressive::SeekState::Pending;op.speedMicros=progressive::speedMicros(x.requested);x.pendingSeek=x.seeks.size();++x.seekVersion;}
    x.seeks.push_back(op);return {op.id,accepted,op.reason};
}
progressive::SeekReceipt ProgressiveMacPlaybackEngine::requestSeekToInputSeconds(double value,std::uint64_t generation,std::uint64_t epoch){
    return requestSeekSeconds(value,generation,epoch,progressive::SeekMode::Exact,0);
}
progressive::SeekReceipt ProgressiveMacPlaybackEngine::requestFastLocalSeekToInputSeconds(double value,std::uint64_t generation,std::uint64_t epoch,std::uint32_t preroll){
    return requestSeekSeconds(value,generation,epoch,progressive::SeekMode::FastLocal,preroll);
}
progressive::SeekReceipt ProgressiveMacPlaybackEngine::requestSeekSeconds(double value,std::uint64_t generation,std::uint64_t epoch,progressive::SeekMode mode,std::uint32_t preroll,std::uint64_t session){
    workQueue();auto& x=*impl_;std::uint64_t frame=0;std::string error;
    {std::lock_guard lock(x.mutex);try{if(!x.pipeline)throw std::logic_error("入力がありません");frame=progressive::inputFrameForSeconds(value,x.pipeline->sampleRate(),x.pipeline->inputFrames());}catch(const std::exception& e){error=e.what();}}
    if(error.empty())return requestSeekFrame(frame,generation,epoch,mode,preroll,session);
    std::lock_guard lock(x.mutex);if(x.seeks.size()>=4096)return {0,false,"シーク操作の上限4096件です"};
    progressive::SeekOperation op;op.id=x.seeks.size()+1;op.reason=error;op.acceptedNs=machNs();op.mode=mode;op.prerollMillis=preroll;
    if(x.pipeline)op.inputGeneration=x.pipeline->inputGeneration();if(auto* t=x.effectiveTarget())op.sourceRenderEpoch=t->epoch;
    x.seeks.push_back(op);return {op.id,false,error};
}
progressive::SeekSnapshot ProgressiveMacPlaybackEngine::getSeekSnapshot()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);progressive::SeekSnapshot s;
    if(x.seeks.size()>x.seekBase)s.latest=x.seeks.back();
    if(x.activeSeek<x.seeks.size()&&!progressive::terminal(x.seeks[x.activeSeek].state))s.activeId=x.seeks[x.activeSeek].id;
    if(x.pendingSeek<x.seeks.size()&&!progressive::terminal(x.seeks[x.pendingSeek].state))s.pendingId=x.seeks[x.pendingSeek].id;
    return s;
}
std::vector<progressive::SeekOperation> ProgressiveMacPlaybackEngine::seekHistory()const{auto& x=*impl_;std::lock_guard lock(x.mutex);return x.seeks;}
std::vector<ProgressiveClosedEpoch> ProgressiveMacPlaybackEngine::closedEpochs()const{auto& x=*impl_;std::lock_guard lock(x.mutex);return x.closed;}
bool ProgressiveMacPlaybackEngine::seekToInputSeconds(double seconds)noexcept{try{return capabilities().seek&&requestSeekToInputSeconds(seconds).accepted;}catch(...){return false;}}
progressive::State ProgressiveMacPlaybackEngine::getPlaybackState()const noexcept{return impl_->state.load();}
ProgressiveStateSnapshot ProgressiveMacPlaybackEngine::getStateSnapshot()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveStateSnapshot s;s.state=x.state;s.reason=x.reason;s.preparation=x.revision;s.requestedSpeed=x.requested;s.error=x.error;
    const auto* t=x.effectiveTarget();const auto d=t?t->pipeline->diagnostics():x.retired;s.session=d.session;s.inputGeneration=d.inputGeneration;s.renderEpoch=t?t->epoch:x.retiredEpoch;auto ops=t?t->pipeline->speedOperations():x.retiredOperations;s.appliedTargetSpeed=x.applied(ops,t);
    for(const auto& op:ops){using O=prototype::phase59::OperationState;if(op.state==O::Pending)s.pending=op;else if(op.state==O::Submitted||op.state==O::Applied)s.active=op;else s.lastResult=op;}return s;}
ProgressivePosition ProgressiveMacPlaybackEngine::getCurrentPlaybackPosition()const{auto& x=*impl_;std::lock_guard lock(x.mutex);const auto* t=x.effectiveTarget();auto sample=t?t->pipeline->positionSample():x.retiredPosition;const auto d=t?t->pipeline->diagnostics():x.retired;ProgressivePosition p;p.session=d.session;p.outputFrame=d.consumed;const auto rate=x.rendering?x.rendering->rate:0;if(rate)p.outputSeconds=p.outputFrame/rate;
    p.inputGeneration=d.inputGeneration;p.renderEpoch=t?t->epoch:x.retiredEpoch;
    if(sample&&sample->session==d.session){p.inputFrame=sample->input;p.sampledOutputFrame=sample->output;if(rate)p.inputSeconds=sample->input/rate;}
    // Before any consumption, retain the exact requested input coordinate.
    // Integer output rounding/EOF clamping need not have a unique inverse.
    if(d.session&&d.consumed==d.outputStartFrame)for(auto it=x.seeks.rbegin();it!=x.seeks.rend();++it)
        if(it->state==progressive::SeekState::Completed&&it->renderEpoch==p.renderEpoch&&it->session==d.session&&it->inputGeneration==d.inputGeneration){
            p.inputFrame=it->requestedInputFrame;p.sampledOutputFrame=d.consumed;if(rate)p.inputSeconds=it->requestedInputFrame/rate;break;}
    return p;}
ProgressiveDiagnostics ProgressiveMacPlaybackEngine::getPlaybackDiagnostics()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveDiagnostics d;d.timeStretchLabSha=TIMESTRETCH_PHASE60_SHA;d.preparation=x.revision;const auto* t=x.effectiveTarget();d.pipeline=t?t->pipeline->diagnostics():x.retired;const auto& p=d.pipeline;
    d.session=p.session;d.inputGeneration=p.inputGeneration;d.renderEpoch=t?t->epoch:x.retiredEpoch;d.generatedFrames=p.generated;d.publishedFrames=p.published;d.consumedFrames=p.consumed;d.presentedFrames=x.rendering?x.rendering->presented.load():0;d.currentEpochPresentedFrame=t?t->presented.load():x.retiredPresented;d.missingFrames=p.missingFrames+x.lifetimeMissing;d.underrunCalls=p.missingCalls+x.lifetimeCalls;d.maxConsecutiveMissingFrames=std::max(std::uint64_t(p.maxConsecutiveMissing),x.lifetimeMaxMissing);d.rejectedWrites=p.rejectedWrites+x.lifetimeRejected;
    d.sourceSampleRate=x.rendering?static_cast<unsigned>(x.rendering->rate):0;d.channels=x.rendering?x.rendering->channels:0;d.inputFrames=p.inputFrames;d.residentInputBytes=p.residentInputBytes;d.temporarySourceBytes=p.sourceSnapshotBytes;d.reservationBytes=x.reservation;d.requestedSpeed=x.requested;d.appliedTargetSpeed=x.applied(t?t->pipeline->speedOperations():x.retiredOperations,t);d.processCpuS=x.acceptedAt?processCpu()-x.cpuStart:0;if(!x.pipeline&&p.session)d.dspWorkerCpuS=p.dspWorkerCpuS;d.acceptedToReadyS=x.readyAfter;d.constructorS=x.constructorS;d.fifoSupplyFailed=progressive::SupplyQuality::evaluate(p.missingFrames,p.missingCalls,p.rejectedWrites).failed;d.error=x.error.empty()?p.error:x.error;
    d.workerDeadlineMisses=x.lifetimeWorkerDeadlines+p.scheduling.deadlineMisses;d.workerNewCalls=x.lifetimeWorkerNews+p.realtimeNewCalls;d.workgroupErrors=x.lifetimeWorkgroupErrors+Impl::workerErrors(p);
    const auto add=[&](Pipeline* source){const auto old=source->diagnostics();d.missingFrames+=old.missingFrames;d.underrunCalls+=old.missingCalls;d.rejectedWrites+=old.rejectedWrites;d.maxConsecutiveMissingFrames=std::max(d.maxConsecutiveMissingFrames,old.maxConsecutiveMissing);d.workerDeadlineMisses+=old.scheduling.deadlineMisses;d.workerNewCalls+=old.realtimeNewCalls;d.workgroupErrors+=Impl::workerErrors(old);};
    if(t&&x.pipeline&&t->pipeline!=x.pipeline.get())add(x.pipeline.get());
    if(x.retiringPipeline)add(x.retiringPipeline);
    const auto& m=p.scheduling;
    d.fifoSupplyFailed=progressive::SupplyQuality::evaluate(d.missingFrames,d.underrunCalls,d.rejectedWrites).failed;
    if(x.closedQualityFailed||d.fifoSupplyFailed||p.failed||m.deadlineMisses||m.policyErrors||m.joinErrors||m.restoreErrors||m.intervalErrors||m.queryErrors||m.waitErrors||m.wakeErrors||(x.rendering&&(x.rendering->overruns||x.rendering->formats)))d.overallAudioQuality=false;
    if(x.rendering&&x.rendering->allocationHooks.enter&&x.rendering->allocationHooks.leave&&x.rendering->allocationHooks.count)d.callbackCppNew=x.rendering->cppAllocations.load();
    rusage r{};getrusage(RUSAGE_SELF,&r);d.peakRssBytes=r.ru_maxrss;mach_task_basic_info_data_t info{};mach_msg_type_number_t count=MACH_TASK_BASIC_INFO_COUNT;if(task_info(mach_task_self(),MACH_TASK_BASIC_INFO,reinterpret_cast<task_info_t>(&info),&count)==KERN_SUCCESS)d.rssBytes=info.resident_size;return d;}
ProgressiveNativeDiagnostics ProgressiveMacPlaybackEngine::getNativeDiagnostics()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveNativeDiagnostics d;static_cast<MacDiagnostics&>(d)=x.native;d.error=x.error;if(auto s=x.rendering){d.firstPcmMachNs=s->firstPcm;d.lastPcmTargetEndNs=s->lastTarget;d.callbackCalls=s->calls;d.maxCallbackNs=s->maximum;d.deadlineMisses=s->overruns;d.formatErrors=s->formats;d.callbackRecordsDropped=s->dropped;d.hostMissing=s->hostMissing;d.hostBackwards=s->hostBackwards;d.hostCadenceErrors=s->hostCadence;d.sampleErrors=s->sampleErrors;d.halWindowMisses=s->halMisses;d.invalidSampleTimeCalls=s->invalidSample;d.invalidRateScalarCalls=s->invalidScalar;}return d;}
std::vector<MacCallbackRecord> ProgressiveMacPlaybackEngine::callbackRecords()const{auto& x=*impl_;std::lock_guard lock(x.mutex);auto s=x.rendering;if(!s)return {};if(s->active||s->inRender||x.state==State::Draining)throw std::logic_error("callback静止後だけ履歴を取得できます");return {s->records.begin(),s->records.begin()+std::min<std::size_t>(s->records.size(),s->recordsCount.load())};}
std::vector<Operation> ProgressiveMacPlaybackEngine::operationHistory()const{auto& x=*impl_;std::lock_guard lock(x.mutex);const auto* t=x.effectiveTarget();return t?t->pipeline->speedOperations():x.retiredOperations;}
TimeMap ProgressiveMacPlaybackEngine::finalTimeMap()const{auto& x=*impl_;std::lock_guard lock(x.mutex);if(x.pipeline||x.retiredMap.empty())throw std::logic_error("静止した確定Mapが必要です");return x.retiredMap;}
void ProgressiveMacPlaybackEngine::simulateDeviceChangeForTest(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);x.force=true;if(x.rendering)x.rendering->forcedRoute=true;}
}
