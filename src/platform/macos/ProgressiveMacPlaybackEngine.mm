#import <AVFoundation/AVFoundation.h>
#import <CoreAudio/CoreAudio.h>
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase46HostClock.h"
#include "prototype/Phase61OutputTransition.h"
#include "prototype/Phase62LoopBoundary.h"
#include "playback/LoopSpeedLedger.h"
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
    std::atomic<std::uint64_t> logicalEpoch{0};
    std::uint64_t currentEpoch()const noexcept{const auto value=logicalEpoch.load();return value?value:epoch;}
    std::uint64_t loopA=0,loopB=0;
    std::atomic<bool> repeatAllowed{true};
    std::array<float,2> previousTail{};bool hasPreviousTail=false; // audio consumer only
    std::atomic<std::uint64_t> presented{0},firstPcm{0},firstTarget{0};
    std::atomic<std::uint64_t> loopEnd{0},loopID{0};
    std::uint32_t speedMicros=1000000;
};
static_assert(std::atomic<RenderTarget*>::is_always_lock_free);
static_assert(std::atomic<unsigned>::is_always_lock_free);
using SwitchPhase=prototype::phase61::SwitchPhase;
struct RenderSwitch {
    std::atomic<SwitchPhase> phase{SwitchPhase::Idle};
    RenderTarget* oldTarget=nullptr;RenderTarget* newTarget=nullptr;
    prototype::phase61::OutputTransition output;
    std::atomic<std::size_t> observedMixCursor{0}; // bounded callback value, normal test audit
    bool loopCycle=false,scheduledBoundary=false,periodic=false;
    bool committedDynamic=false; // replacement is required by the adopted map
    bool awaitDynamic=false,dynamicNoChange=false;
    std::atomic<std::uint64_t> dynamicOperation{0}; // only this request may arm B
    std::uint64_t notBeforeCycle=0;
    std::uint64_t loopID=0,inputA=0,inputB=0,boundaryEnd=0;
    std::uint64_t beginNs=0,endNs=0,oldAvailable=0; // audio writes, acquire Done before normal reads
};
// Normal owner only. An Applying attempt can reject its plan and return to
// Requested. Revalidate/cancel that DSP transaction before closing its route;
// a read of Applying/Committed alone is not a cancellation reservation.
template<class CancelDsp> bool cancelPreparedSwitch(RenderSwitch& h,bool live,CancelDsp&& cancelDsp){
    if(h.phase.load(std::memory_order_acquire)!=SwitchPhase::Requested)return false;
    if(live&&h.awaitDynamic&&!cancelDsp())return false;
    auto expected=SwitchPhase::Requested;
    return h.phase.compare_exchange_strong(expected,SwitchPhase::Cancelled,std::memory_order_acq_rel);
}
bool cancelStoppedSwitch(RenderSwitch& h,bool active,bool mustStop){
    if(active||!mustStop)return false;
    auto expected=SwitchPhase::Started;
    return h.phase.compare_exchange_strong(expected,SwitchPhase::Cancelled,std::memory_order_acq_rel);
}
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
    bool mixTestObservation=false;
    std::atomic<std::uint64_t> cppAllocations{0};
    std::atomic<bool> loopMissed{false};
    std::atomic<bool> pauseRequested{false},pauseAcknowledged{false};
    std::atomic<std::uint64_t> oldMissing{0},newMissing{0},outputAffected{0};
    std::vector<ProgressiveCallbackRecord> loopRecords,clockAnomalyRecords;
    std::size_t anomalyCount=0,anomalyAfter=0;std::uint64_t anomalyEvents=0;
    std::uint64_t loopRecordCount=0; // callback writer; export after quiescence
    ProgressiveCallbackRecord* recording=nullptr;
    double deviceRate=0;std::uint32_t previousFrames=0;
    std::atomic<std::uint64_t> speedRequestID{0},routeChanges{0};
    enum class Failure {None,MissingOld,MissingNew,MissingBoth,NoPrepared,CallbackLimit,SpanLimit};
    std::atomic<Failure> loopFailure{Failure::None};
    void miss(Failure why)noexcept{auto none=Failure::None;loopFailure.compare_exchange_strong(none,why);loopMissed=true;}
    void span(const ProgressiveOutputSpan& value)noexcept{
        if(recording&&recording->spanCount<recording->spans.size()){
            recording->spans[recording->spanCount++]=value;
            recording->oldMissingFrames+=value.oldMissingFrames;recording->newMissingFrames+=value.newMissingFrames;
            recording->outputAffectedFrames+=value.outputAffectedFrames;recording->failurePaddingFrames+=value.failurePaddingFrames;
        }
        if(outputObserver)outputObserver(observerContext,lastPointers,value);
    }
    const float* lastPointers[2]{};
    std::atomic<std::uint64_t> loopCycles{0},loopSafetyFrames{0};
    prototype::phase59::ValueMailbox<progressive::LoopBoundaryEvent> loopBoundary;
    std::array<prototype::phase59::ValueMailbox<progressive::LoopBoundaryEvent>,64> boundaryRing;
    std::atomic<std::uint64_t> boundaryWritten{0};
    std::atomic<std::uint64_t>* epochCounter=nullptr;std::uint64_t localEpoch=100;
    std::uint64_t nextLogicalEpoch()noexcept{return epochCounter?epochCounter->fetch_add(1)+1:++localEpoch;}
    std::uint64_t countedLoopID=0,settingCycles=0;
    void publishBoundary(progressive::LoopBoundaryEvent event)noexcept{
        if(countedLoopID!=event.loopID){countedLoopID=event.loopID;settingCycles=0;}event.settingCycle=++settingCycles;
        loopBoundary.publish(event);const auto i=boundaryWritten.load(std::memory_order_relaxed);boundaryRing[i%boundaryRing.size()].publish(event);boundaryWritten.store(i+1,std::memory_order_release);
    }
    std::uint64_t callbackStartNs=0,callbackHostNs=0,callbackOriginFrame=0;
    std::uint64_t callbackFrame=0; // render consumer only, independent of source jumps
    void* observerContext=nullptr;
    void(*observer)(void*,const float*const*,std::size_t,std::size_t)noexcept=nullptr;
    void(*epochObserver)(void*,const float*const*,std::size_t,std::size_t,std::uint64_t,std::uint64_t,std::uint64_t)noexcept=nullptr;
    decltype(ProgressiveOptions::observeOutputPcm) outputObserver=nullptr;
    std::uint64_t ns()const noexcept{return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*numer/denom);}
};
// Normal owner, after output quiescence. A nonperiodic partial switch points
// target at the preparation already. Detach it before that owner is destroyed;
// this never rewinds audible output or reactivates a stopped callback.
bool detachStoppedPreparation(RenderState& s,RenderTarget* preparation,RenderTarget* surviving){
    if(s.active.load(std::memory_order_seq_cst)||s.inRender.load(std::memory_order_seq_cst))return false;
    auto* expected=preparation;
    return s.target.compare_exchange_strong(expected,surviving,std::memory_order_seq_cst);
}
// Normal-thread handshake. The callback acknowledges only after a started mix
// has completed. No observation followed by an independent active=false race.
void pauseRender(RenderState* s,void(*observed)(void*)=nullptr,void* context=nullptr){
    auto& h=s->handoff;auto phase=h.phase.load(std::memory_order_acquire);
    if(observed)observed(context);
    if(phase==SwitchPhase::Requested&&!h.scheduledBoundary)h.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel);
    s->pauseRequested.store(true,std::memory_order_release);
    const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(1);
    while(!s->pauseAcknowledged.load(std::memory_order_acquire)){
        if(std::chrono::steady_clock::now()>limit)throw std::runtime_error("Pause要求のcallback応答が届きません");
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }
    while(s->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
}
std::size_t periodSpan(RenderTarget*,const RenderState*,std::size_t)noexcept;
// A rounded, empty initial C->B has no PCM and is not a natural loop.
// Only the callback changes presented; the requested input remains on the job.
void normalizeEmptyEntry(RenderTarget* t)noexcept{
    if(t&&t->pipeline->loopReuseEnabled()&&t->pipeline->outputStartFrame()==t->loopEnd.load()&&t->presented.load()==t->loopEnd.load())t->presented=t->pipeline->loopOutputStartFrame();
}
// The caller splits at B and both correction edges before pulling. RAW
// observers run first; this modifies one bounded source span in place.
void correctEntryPeriod(RenderState* s,RenderTarget* t,float*const* pcm,std::size_t count,std::size_t at,std::uint64_t cycle,ProgressiveOutputSpan& span,bool old)noexcept{
    if(!t->pipeline->loopReuseEnabled())return;
    using Boundary=prototype::phase62::PeriodBoundary;
    const std::size_t a=t->pipeline->loopOutputStartFrame(),b=t->loopEnd.load(),length=b-a,position=at-a,fade=Boundary::length(unsigned(s->rate),length);
    const bool tail=at>=b-fade,head=t->hasPreviousTail&&position<fade;
    const auto first=t->pipeline->loopFirstSample();std::array<float,2> last=t->previousTail;
    if(tail){if(auto descriptor=t->pipeline->loopPcmDescriptor(cycle))last=descriptor->last;else{s->miss(RenderState::Failure::NoPrepared);return;}}
    if(old){span.oldPeriodicBoundary=true;span.oldCorrectionHead=head;span.oldCorrectionTail=tail;span.oldBoundaryFrames=fade;span.oldPeriodFrames=length;span.oldPeriodOffset=position;span.oldBoundaryLast=last;span.oldBoundaryFirst=first;}
    else{span.periodicBoundary=true;span.correctionBeforeMix=true;span.correctionHead=head;span.correctionTail=tail;span.boundaryFrames=fade;span.periodFrames=length;span.periodOffset=position;span.boundaryLast=last;span.boundaryFirst=first;}
    for(std::size_t i=0;i<count;++i)for(unsigned c=0;c<s->channels;++c){
        if(tail)pcm[c][i]=Boundary::tail(pcm[c][i],last[c],first[c],position+i-(length-fade),fade);
        else if(head)pcm[c][i]=Boundary::head(pcm[c][i],last[c],first[c],position+i,fade);
    }
    if(at+count==b&&!s->loopMissed.load()){
        const auto epoch=t->currentEpoch();t->previousTail=last;t->hasPreviousTail=true;t->presented=a;t->logicalEpoch=s->nextLogicalEpoch();
        if(!old){
            progressive::LoopBoundaryEvent event;
            event.loopID=t->loopID;event.cycle=s->loopCycles.fetch_add(1)+1;event.oldEpoch=epoch;event.newEpoch=t->currentEpoch();event.inputA=t->loopA;event.inputBExclusive=t->loopB;
            event.oldOutputEnd=b;event.newOutputStart=a;event.callbackFrame=s->callbackFrame+count;event.renderNs=s->ns();event.boundaryProcessingFrames=std::uint32_t(fade);
            if(s->callbackHostNs)event.halBoundaryEstimateNs=s->callbackHostNs+std::uint64_t((event.callbackFrame-s->callbackOriginFrame)*1e9/s->rate);
            s->publishBoundary(event);
        }
    }
}
// Bounded PCM work only; no ownership, I/O, locks, DSP or control APIs.
void renderPcm(RenderState* s,float*const* p,std::size_t n,prototype::phase58::RenderResult& r,std::size_t& audibleFrames)noexcept{
    auto* target=s->target.load(std::memory_order_seq_cst);const float* rawPointers[]{p[0],p[1]};
        auto& h=s->handoff;auto phase=h.phase.load(std::memory_order_acquire);
        if(phase==SwitchPhase::Requested&&(!h.scheduledBoundary||(target->presented.load()>=h.boundaryEnd-h.output.length&&(!target->pipeline->loopReuseEnabled()||target->pipeline->loopReadCycle()>=h.notBeforeCycle)))){
            auto expected=SwitchPhase::Requested;
            if(h.newTarget->pipeline->failed()){
                h.phase.compare_exchange_strong(expected,SwitchPhase::Cancelled,std::memory_order_acq_rel);phase=h.phase.load(std::memory_order_acquire);
            }else if(h.phase.compare_exchange_strong(expected,SwitchPhase::Started,std::memory_order_acq_rel)){
                h.beginNs=s->ns();h.oldAvailable=h.oldTarget->pipeline->available();
                target=h.newTarget;if(h.oldTarget->pipeline->loopReuseEnabled())target->logicalEpoch=s->nextLogicalEpoch();s->target.store(target,std::memory_order_seq_cst);phase=SwitchPhase::Started;
            }else phase=expected;
        }
        if(phase==SwitchPhase::Started)target=h.newTarget;
        const auto newEpoch=target->currentEpoch(),newCycle=target->pipeline->loopReadCycle();ProgressiveOutputSpan span;
        r=target->pipeline->pullAudio(p,n);s->presented.fetch_add(r.wanted,std::memory_order_relaxed);target->presented.fetch_add(r.wanted,std::memory_order_relaxed);
        audibleFrames=r.received;
        if(r.received&&(target->loopEnd.load()||(phase==SwitchPhase::Started&&h.scheduledBoundary))){
            std::uint64_t zero=0;target->firstPcm.compare_exchange_strong(zero,s->callbackStartNs);
            if(s->callbackHostNs){zero=0;target->firstTarget.compare_exchange_strong(zero,s->callbackHostNs+static_cast<std::uint64_t>((s->callbackFrame-s->callbackOriginFrame)*1e9/s->rate));}
        }
        // These observers always see each source BEFORE any output mix.
        if(r.received&&s->observer)s->observer(s->observerContext,rawPointers,r.received,r.outputBefore);
        if(r.received&&s->epochObserver)s->epochObserver(s->observerContext,rawPointers,r.received,r.outputBefore,target->inputGeneration,newEpoch,target->session);
        if(target->pipeline->loopReuseEnabled()&&r.received==n)correctEntryPeriod(s,target,p,n,r.outputBefore,newCycle,span,false);
        std::size_t mixed=0,transitionOffset=0,oldOffset=0,oldReceived=0,oldWanted=0;std::uint64_t oldEpoch=0;
        if(phase==SwitchPhase::Started){
            mixed=std::min<std::size_t>(n,h.output.remaining());transitionOffset=h.output.cursor;oldEpoch=h.oldTarget->currentEpoch();
            float* oldP[2]{h.output.oldPcm[0].data(),h.output.oldPcm[1].data()};
            // Expected old EOS is not a supply failure. A non-EOS short read is.
            auto wanted=h.oldTarget->pipeline->finished()?std::min(mixed,h.oldTarget->pipeline->available()):mixed;
            if(const auto end=h.oldTarget->loopEnd.load()){const auto position=h.oldTarget->presented.load();wanted=std::min<std::uint64_t>(wanted,end>position?end-position:0);}
            const auto oldCycle=h.oldTarget->pipeline->loopReadCycle();const auto previous=h.oldTarget->pipeline->pullAudio(oldP,wanted);
            // Supply is accounted below for BOTH loop and Clear continuation.
            oldOffset=previous.outputBefore;oldReceived=previous.received;oldWanted=previous.wanted;
            audibleFrames=std::max(audibleFrames,oldReceived);
            for(unsigned c=0;c<s->channels;++c)std::fill(oldP[c]+previous.received,oldP[c]+mixed,0.f);
            h.oldTarget->presented.fetch_add(previous.wanted,std::memory_order_relaxed);
            const float* oldRaw[]{oldP[0],oldP[1]};
            if(previous.received&&s->epochObserver)s->epochObserver(s->observerContext,oldRaw,previous.received,previous.outputBefore,h.oldTarget->inputGeneration,h.oldTarget->currentEpoch(),h.oldTarget->session);
            if(!h.scheduledBoundary&&h.oldTarget->pipeline->loopReuseEnabled()&&previous.received==mixed)correctEntryPeriod(s,h.oldTarget,oldP,mixed,previous.outputBefore,oldCycle,span,true);
            h.output.mix(p,mixed,s->channels);if(s->mixTestObservation)h.observedMixCursor.store(h.output.cursor,std::memory_order_release);
            h.endNs=s->ns(); // also preserves the last partial chunk on route abort
            // Done releases all old references. Owner still waits inRender==0
            // before clearing the slot or destroying its two raw targets.
            if(!h.output.remaining()){
                if(h.loopCycle&&h.oldTarget->presented.load()!=h.boundaryEnd)s->miss(RenderState::Failure::MissingOld);
                if(h.loopCycle&&!s->loopMissed.load()&&r.received==n&&oldReceived>=mixed-1){progressive::LoopBoundaryEvent event;
                    event.loopID=h.loopID;event.cycle=s->loopCycles.fetch_add(1)+1;event.oldEpoch=h.oldTarget->currentEpoch();event.newEpoch=h.newTarget->currentEpoch();
                    event.inputA=h.inputA;event.inputBExclusive=h.inputB;event.oldOutputEnd=h.boundaryEnd;
                    event.newOutputStart=h.newTarget->pipeline->outputStartFrame();event.callbackFrame=s->callbackFrame+mixed;
                    event.renderNs=s->ns();if(s->callbackHostNs)event.halBoundaryEstimateNs=s->callbackHostNs+static_cast<std::uint64_t>((event.callbackFrame-s->callbackOriginFrame)*1e9/s->rate);event.overlapFrames=static_cast<std::uint32_t>(h.output.length);s->publishBoundary(event);
                }
                h.phase.store(SwitchPhase::Done,std::memory_order_release);
            }
        }
        span.newEpoch=newEpoch;span.oldEpoch=oldEpoch;span.callbackFrame=s->callbackFrame;
        span.newOutputOffset=r.outputBefore;span.oldOutputOffset=oldOffset;span.newReceivedFrames=r.received;span.oldReceivedFrames=oldReceived;
        span.frames=n;span.mixedFrames=mixed;span.transitionOffset=transitionOffset;span.transitionLength=mixed?h.output.length:0;
        const bool protectedOutput=target->loopEnd.load()||(phase==SwitchPhase::Started&&h.scheduledBoundary);
        if(protectedOutput){
            span.newMissingFrames=r.wanted-r.received;span.oldMissingFrames=oldWanted-oldReceived;
            std::size_t first=n;
            for(std::size_t i=0;i<n;++i){
                const bool missingNew=i>=r.received&&i<r.wanted;
                const bool missingOld=i<oldWanted&&i>=oldReceived&&transitionOffset+i+1<h.output.length;
                if(missingNew||missingOld){++span.outputAffectedFrames;first=std::min(first,i);}
            }
            s->oldMissing.fetch_add(span.oldMissingFrames);s->newMissing.fetch_add(span.newMissingFrames);s->outputAffected.fetch_add(span.outputAffectedFrames);
            if(span.outputAffectedFrames){
                s->miss(span.oldMissingFrames&&span.newMissingFrames?RenderState::Failure::MissingBoth:span.newMissingFrames?RenderState::Failure::MissingNew:RenderState::Failure::MissingOld);
                span.failurePaddingOffset=first;span.failurePaddingFrames=n-first;
                for(unsigned c=0;c<s->channels;++c)std::fill(p[c]+first,p[c]+n,0.f);
                s->loopSafetyFrames.fetch_add(span.failurePaddingFrames);audibleFrames=std::min(audibleFrames,first);
            }
        }
        s->lastPointers[0]=rawPointers[0];s->lastPointers[1]=rawPointers[1];s->span(span);
    s->callbackFrame+=n;
}
// One span never crosses a logical B, head correction edge, or tail edge.
// Repeating DSP ownership is independent of these logical epochs.
std::size_t periodSpan(RenderTarget* t,const RenderState* s,std::size_t requested)noexcept{
    const std::size_t a=t->pipeline->loopOutputStartFrame(),b=t->loopEnd.load(),position=t->presented.load();
    if(position<a||position>=b)return 0;
    const auto length=b-a,n=prototype::phase62::PeriodBoundary::length(static_cast<unsigned>(s->rate),length);
    auto end=b;
    if(position<a+n)end=a+n;
    else if(position<b-n)end=b-n;
    return std::min<std::uint64_t>(requested,end-position);
}
bool renderPeriod(RenderState* s,float*const* p,std::size_t n,prototype::phase58::RenderResult& r,std::size_t& audible)noexcept{
    using Boundary=prototype::phase62::PeriodBoundary;
    auto* t=s->target.load();auto& h=s->handoff;auto phase=h.phase.load(std::memory_order_acquire);
    const std::size_t a=t->pipeline->loopOutputStartFrame(),b=t->loopEnd.load(),at=t->presented.load();
    const auto length=b-a,fade=Boundary::length(static_cast<unsigned>(s->rate),length),position=at-a;
    const auto cycle=t->pipeline->loopReuseEnabled()?t->pipeline->loopReadCycle():0;
    const bool tail=at>=b-fade,head=t->hasPreviousTail&&position<fade;
    std::array<float,2> first=t->pipeline->loopFirstSample(),last{};
    if(tail){
        if(t->pipeline->loopReuseEnabled()){
            const auto descriptor=t->pipeline->loopPcmDescriptor(cycle);
            if(!descriptor){s->miss(RenderState::Failure::NoPrepared);return false;}last=descriptor->last;
        }else if(!t->pipeline->peekAudioFrame(b-at-1,last)){s->miss(RenderState::Failure::NoPrepared);return false;}
        const bool armed=phase==SwitchPhase::Requested||phase==SwitchPhase::Started;
        const auto decision=armed&&h.awaitDynamic?t->pipeline->loopTransition():prototype::phase58::LoopTransitionSnapshot{};
        const bool matching=armed&&h.awaitDynamic&&h.dynamicOperation.load(std::memory_order_acquire)&&h.dynamicOperation.load()==decision.operationID;
        const bool committed=matching&&decision.state==prototype::phase58::LoopTransitionState::Committed;
        const bool fixed=matching&&decision.state==prototype::phase58::LoopTransitionState::FixedBoundaryCommitted;
        const bool routeReady=armed&&(!h.awaitDynamic||committed||fixed);
        const auto requiredCycle=(committed||fixed)?decision.cycle:armed?h.notBeforeCycle:0;
        if(phase==SwitchPhase::Requested&&h.periodic&&routeReady&&cycle>=requiredCycle&&(!h.awaitDynamic||at==b-fade)){
            auto expected=SwitchPhase::Requested;
            if(h.phase.compare_exchange_strong(expected,SwitchPhase::Started,std::memory_order_acq_rel)){
                h.beginNs=s->ns();h.oldAvailable=t->pipeline->available();h.output.cursor=at-(b-fade);phase=SwitchPhase::Started;
            }else phase=expected;
        }
        if(phase==SwitchPhase::Started&&h.periodic)first=h.newTarget->pipeline->loopFirstSample();
        else if(!t->repeatAllowed.load()){s->miss(RenderState::Failure::NoPrepared);return false;}
    }
    const auto epoch=t->currentEpoch();r=t->pipeline->pullAudio(p,n);s->presented.fetch_add(r.wanted);t->presented.fetch_add(r.wanted);audible=r.received;
    const float* pointers[]{p[0],p[1]};
    if(r.received&&s->observer)s->observer(s->observerContext,pointers,r.received,r.outputBefore);
    if(r.received&&s->epochObserver)s->epochObserver(s->observerContext,pointers,r.received,r.outputBefore,t->inputGeneration,epoch,t->session);
    if(r.received){std::uint64_t zero=0;t->firstPcm.compare_exchange_strong(zero,s->callbackStartNs);if(s->callbackHostNs){zero=0;t->firstTarget.compare_exchange_strong(zero,s->callbackHostNs+static_cast<std::uint64_t>((s->callbackFrame-s->callbackOriginFrame)*1e9/s->rate));}}
    ProgressiveOutputSpan span;span.newEpoch=epoch;span.callbackFrame=s->callbackFrame;span.newOutputOffset=r.outputBefore;span.newReceivedFrames=r.received;span.frames=n;
    span.periodicBoundary=true;span.periodFrames=length;span.periodOffset=position;span.boundaryFrames=fade;span.correctionHead=head;span.correctionTail=tail;
    span.boundaryLast=head?t->previousTail:last;span.boundaryFirst=first;
    for(std::size_t i=0;i<r.received;++i)for(unsigned c=0;c<s->channels;++c){
        if(tail)p[c][i]=Boundary::tail(p[c][i],last[c],first[c],position+i-(length-fade),fade);
        else if(head)p[c][i]=Boundary::head(p[c][i],t->previousTail[c],first[c],position+i,fade);
    }
    if(r.received!=r.wanted){
        span.newMissingFrames=r.wanted-r.received;span.outputAffectedFrames=span.newMissingFrames;
        span.failurePaddingOffset=r.received;span.failurePaddingFrames=n-r.received;
        s->newMissing.fetch_add(span.newMissingFrames);s->outputAffected.fetch_add(span.outputAffectedFrames);s->loopSafetyFrames.fetch_add(span.failurePaddingFrames);
        s->miss(RenderState::Failure::MissingNew);
        for(unsigned c=0;c<s->channels;++c)std::fill(p[c]+r.received,p[c]+n,0.f);
    }
    s->lastPointers[0]=pointers[0];s->lastPointers[1]=pointers[1];s->span(span);s->callbackFrame+=n;
    if(tail&&phase==SwitchPhase::Started&&h.periodic){h.output.cursor=std::min(h.output.length,h.output.cursor+n);if(s->mixTestObservation)h.observedMixCursor.store(h.output.cursor,std::memory_order_release);h.endNs=s->ns();}
    if(t->presented.load()==b&&!s->loopMissed.load()){
        RenderTarget* next=t;
        if(phase==SwitchPhase::Started&&h.periodic){
            next=h.newTarget;next->logicalEpoch=s->nextLogicalEpoch();s->target.store(next,std::memory_order_seq_cst);
        }else if(!t->pipeline->loopReuseEnabled()||!t->repeatAllowed.load()){s->miss(RenderState::Failure::NoPrepared);return true;}
        else{t->presented=a;t->logicalEpoch=s->nextLogicalEpoch();}
        next->previousTail=last;next->hasPreviousTail=true;
        progressive::LoopBoundaryEvent event;event.loopID=t->loopID;event.cycle=s->loopCycles.fetch_add(1)+1;event.oldEpoch=epoch;event.newEpoch=next->currentEpoch();
        event.inputA=t->loopA;event.inputBExclusive=t->loopB;event.oldOutputEnd=b;event.newOutputStart=next->pipeline->loopOutputStartFrame();
        event.callbackFrame=s->callbackFrame;event.renderNs=s->ns();event.boundaryProcessingFrames=static_cast<std::uint32_t>(fade);
        if(s->callbackHostNs)event.halBoundaryEstimateNs=s->callbackHostNs+static_cast<std::uint64_t>((event.callbackFrame-s->callbackOriginFrame)*1e9/s->rate);
        s->publishBoundary(event);
        if(phase==SwitchPhase::Started&&h.periodic)h.phase.store(SwitchPhase::Done,std::memory_order_release);
    }
    return true;
}
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
    const auto start=s->ns();float* p[2]{};
    s->recording=nullptr;
    if(s->active.load()&&!s->loopRecords.empty()){
        auto& item=s->loopRecords[s->loopRecordCount++%s->loopRecords.size()];item={};s->recording=&item;
        item.machNumer=s->numer;item.machDenom=s->denom;item.sourceRate=s->rate;item.deviceRate=s->deviceRate;item.previousFrames=s->previousFrames;
        item.renderEpoch=target?target->currentEpoch():0;item.speedRequestID=s->speedRequestID.load();item.routeChanges=s->routeChanges.load();
    }
    bool valid=buffers&&buffers->mNumberBuffers==s->channels;
    if(buffers)for(unsigned c=0;c<buffers->mNumberBuffers;++c){const auto& b=buffers->mBuffers[c];valid&=b.mData&&b.mNumberChannels==1&&b.mDataByteSize>=n*sizeof(float);if(c<2){p[c]=static_cast<float*>(b.mData);}}
    const bool active=s->active.load(std::memory_order_seq_cst)&&target;
    prototype::phase58::RenderResult r;
    std::size_t audibleFrames=0;
    if(active&&valid&&target){
        s->callbackStartNs=start;s->callbackOriginFrame=s->callbackFrame;
        const auto host=stamp&&(stamp->mFlags&kAudioTimeStampHostTimeValid)?static_cast<std::uint64_t>(static_cast<long double>(stamp->mHostTime)*s->numer/s->denom):0;
        s->callbackHostNs=host&&std::abs(double(host)-double(start))<=1e9?host:0;
        std::size_t offset=0;
        // Exact periods are >=512 frames; callback <=4096. Head/prefix/tail
        // need <=3*(ceil(4096/512)+1)+1=28 spans; capacity is 32.
        for(unsigned span=0;offset<n&&span<progressiveMaximumSpans;++span){
            target=s->target.load(std::memory_order_seq_cst);auto& h=s->handoff;
            if(target->pipeline->loopReuseEnabled())target->loopEnd=target->pipeline->loopOutputEndFrame();
            const auto phase=h.phase.load(std::memory_order_acquire);
            if(s->pauseRequested.load(std::memory_order_acquire)&&phase!=SwitchPhase::Started){s->active=false;s->pauseAcknowledged.store(true,std::memory_order_release);break;}
            std::size_t count=n-offset;
            if(s->loopMissed.load())break;
            if(target->loopEnd.load()&&n>4096){s->miss(RenderState::Failure::CallbackLimit);break;}
        const bool period=target->pipeline->loopReuseEnabled()||((phase==SwitchPhase::Requested||phase==SwitchPhase::Started)&&h.periodic);
            const bool ordinaryStart=phase==SwitchPhase::Requested&&!h.scheduledBoundary;
            const bool ordinaryMix=phase==SwitchPhase::Started&&!h.periodic;
            if(ordinaryStart)normalizeEmptyEntry(h.newTarget);
            else normalizeEmptyEntry(target);
            const bool continuation=phase==SwitchPhase::Requested&&h.scheduledBoundary&&!h.periodic&&target->presented.load()>=h.boundaryEnd-h.output.length&&(!target->pipeline->loopReuseEnabled()||target->pipeline->loopReadCycle()>=h.notBeforeCycle);
            if(period&&!ordinaryStart&&!ordinaryMix&&!continuation){
                count=periodSpan(target,s,count);
                if(!count){s->miss(RenderState::Failure::SpanLimit);break;}
                float* part[]{p[0]+offset,p[1]?p[1]+offset:nullptr};std::size_t audible=0;
                if(!renderPeriod(s,part,count,r,audible))break;
                audibleFrames+=audible;offset+=count;if(s->loopMissed.load())break;continue;
            }
            if(phase==SwitchPhase::Started||(ordinaryStart&&h.newTarget->pipeline->loopReuseEnabled()))count=std::min(count,h.output.remaining());
            else if(const auto end=target->loopEnd.load()){
                const auto fade=std::size_t(s->rate)/200;
                const prototype::phase62::Boundary boundary{end,fade};
                const auto position=target->presented.load();
                if(phase==SwitchPhase::Requested&&!h.scheduledBoundary){} // explicit operation takes priority
                else if(const auto prefix=boundary.prefix(position,count))count=prefix;
                else if(phase==SwitchPhase::Requested&&h.scheduledBoundary&&position==boundary.fadeBegin())count=std::min(count,h.output.length);
                else {s->miss(RenderState::Failure::NoPrepared);break;}
            }
            // An entry mix retains its cursor while each source independently
            // crosses B. Never let a source observation conceal that wrap.
            auto* incoming=ordinaryStart?h.newTarget:target;
            if(incoming->pipeline->loopReuseEnabled())count=std::min(count,periodSpan(incoming,s,count));
            if((ordinaryStart||ordinaryMix)&&!h.scheduledBoundary&&h.oldTarget->pipeline->loopReuseEnabled()){
                normalizeEmptyEntry(h.oldTarget);count=std::min(count,periodSpan(h.oldTarget,s,count));
            }
            if(!count){s->miss(RenderState::Failure::SpanLimit);break;}
            // A scheduled loop switch starts only at B-fade, never early.
            float* part[]{p[0]+offset,p[1]?p[1]+offset:nullptr};std::size_t audible=0;
            renderPcm(s,part,count,r,audible);audibleFrames+=audible;offset+=count;
            if(s->loopMissed.load())break;
        }
        if(s->pauseRequested.load(std::memory_order_acquire)&&s->handoff.phase.load(std::memory_order_acquire)!=SwitchPhase::Started){s->active=false;s->pauseAcknowledged.store(true,std::memory_order_release);}
        if(offset<n){
            for(unsigned c=0;c<s->channels;++c)std::fill(p[c]+offset,p[c]+n,0.f);
            if(s->pauseAcknowledged.load()){if(s->recording)s->recording->pauseSilenceFrames=n-offset;}
            else{
                if(!s->loopMissed.load())s->miss(RenderState::Failure::SpanLimit);
                s->loopSafetyFrames.fetch_add(n-offset);
                ProgressiveOutputSpan padding;padding.callbackFrame=s->callbackFrame;padding.frames=n-offset;padding.failurePaddingFrames=n-offset;padding.unrenderedFailure=true;
                s->lastPointers[0]=p[0]+offset;s->lastPointers[1]=p[1]?p[1]+offset:nullptr;s->span(padding);
                s->callbackFrame+=n-offset;
            }
        }
        target=s->target.load(std::memory_order_seq_cst);
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
        if(s->recording){auto& item=*s->recording;item.clock=evidence;auto& record=item.callback;
            record.sequence=sequence;record.epoch=s->clockEpoch;record.startNs=start;record.ioEndNs=io;record.hostNs=host;record.hostTicks=stamp?stamp->mHostTime:0;
            record.sampleTime=sample;record.timestampFlags=flags;record.rateScalar=stamp?stamp->mRateScalar:0;record.requested=n;
            for(std::size_t i=0;i<item.spanCount;++i){record.raw.received+=item.spans[i].newReceivedFrames;record.raw.wanted+=item.spans[i].frames;}
        }
        s->previousFrames=n;
        MacCallbackRecord* record=nullptr;
        if(!s->records.empty()){const auto i=s->recordsCount.fetch_add(1);if(i<s->records.size()){
            record=&s->records[i];*record={};record->sequence=sequence;record->epoch=s->clockEpoch;record->startNs=start;record->ioEndNs=io;record->hostNs=host;record->hostTicks=stamp?stamp->mHostTime:0;record->sampleTime=sample;record->timestampFlags=flags;record->rateScalar=stamp?stamp->mRateScalar:0;record->requested=n;
            record->raw.received=r.received;record->raw.wanted=r.wanted;record->raw.fifoBefore=r.fifoBefore;record->raw.outputBefore=r.outputBefore;record->raw.session=target?target->session:0;
        }else ++s->dropped;}
        if(s->recording){
            const bool anomaly=evidence.hostMissing||evidence.hostBackwards||evidence.cadenceError||evidence.offsetOutlier||evidence.sampleError||evidence.halWindowMiss;
            if(anomaly)++s->anomalyEvents;
            if(!s->clockAnomalyRecords.empty()){
                if(anomaly&&!s->anomalyCount){
                    const auto count=std::min<std::uint64_t>(17,s->loopRecordCount);
                    for(auto i=s->loopRecordCount-count;i<s->loopRecordCount;++i)s->clockAnomalyRecords[s->anomalyCount++]=s->loopRecords[i%s->loopRecords.size()];
                    s->anomalyAfter=16;
                }else if(s->anomalyAfter){s->clockAnomalyRecords[s->anomalyCount++]=*s->recording;--s->anomalyAfter;}
            }
        }
        // Include the bounded anomaly-window copy in callback timing. Its
        // cost must not disappear from deadline/HAL-window diagnostics.
        const auto end=s->ns();if(record)record->endNs=end;
        if(s->recording){
            s->recording->callback.endNs=end;
            if(s->anomalyCount&&s->clockAnomalyRecords[s->anomalyCount-1].callback.sequence==sequence)
                s->clockAnomalyRecords[s->anomalyCount-1].callback.endNs=end;
        }
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
    static constexpr std::size_t loopIndex=std::size_t(-2),stoppedIndex=std::size_t(-3);
    progressive::SeekOperation stoppedJob; // internal preparation; never a user seek event
    std::vector<StoppedSpeedOperation> stoppedSpeeds;
    progressive::LoopSpeedLedger loopSpeeds;
    std::size_t stoppedBase=0,stoppedJobOperation=0;
    bool pendingStopped=false,resumePending=false,stoppedStartBlocked=false;
    std::optional<std::uint64_t> stoppedInput;
    StoppedSpeedOperation* stoppedSpeed(){return stoppedSpeeds.size()>stoppedBase?&stoppedSpeeds.back():nullptr;}
    bool stoppedPreparing(){auto* op=stoppedSpeed();return op&&op->state==StoppedSpeedState::Preparing;}
    void cancelStopped(const std::string& why){
        resumePending=false;pendingStopped=false;stoppedStartBlocked=false;stoppedInput.reset();
        if(auto* op=stoppedSpeed();op&&(op->state==StoppedSpeedState::Preparing||(op->state==StoppedSpeedState::ReadyForResume&&!op->outputStarted))){op->state=StoppedSpeedState::Cancelled;op->reason=why;}
        if(!progressive::terminal(stoppedJob.state)){stoppedJob.state=progressive::SeekState::Cancelled;stoppedJob.reason=why;}
    }
    // Mutex held, output stopped. A false return is a short poll, never a wait.
    bool captureStopped(StoppedSpeedOperation& op){
        auto* t=effectiveTarget();if(!t)return false;
        auto sample=t->pipeline->stoppedPosition();if(!sample)return false;
        op.sourceSession=sample->session;op.sourceRenderEpoch=t->currentEpoch();op.inputGeneration=t->inputGeneration;
        op.mapVersion=sample->mapVersion;op.consumedOutputFrame=sample->output;
        if(!stoppedInput)stoppedInput=sample->input;
        op.resumeInputFrame=*stoppedInput;op.positionCaptured=true;return true;
    }
    void stoppedReady(const progressive::SeekOperation& job){
        auto* op=stoppedSpeed();if(!op||op->state!=StoppedSpeedState::Preparing||op->speedMicros!=job.speedMicros||op->resumeInputFrame!=job.requestedInputFrame||op->inputGeneration!=job.inputGeneration||op->preparationVersion!=seekVersion.load()||(op->loopID&&(!loopLive()||op->loopID!=loop.id)))return;
        op->session=job.session;op->renderEpoch=job.renderEpoch;op->outputStartFrame=job.outputStartFrame;
        op->readyNs=machNs();op->state=StoppedSpeedState::ReadyForResume;op->mode=job.mode;pendingStopped=false;stoppedStartBlocked=false;
        if(auto* external=loopSpeeds.find(op->id);external&&!progressive::terminal(external->state)){
            external->state=progressive::LoopSpeedState::ReadyForResume;external->readyNs=op->readyNs;
            external->session=op->session;external->renderEpoch=op->renderEpoch;external->resumeInputFrame=op->resumeInputFrame;
            external->preparationVersion=op->preparationVersion;external->cycle=op->cycle;
        }
    }
    bool outputPreparationPending(){
        // A scheduled native Loop boundary needs Playing to finish. Its existing
        // start/resume contract must not wait for that boundary's worker.
        return stoppedPreparing()||pendingStopped||(pausedClearInput.has_value()&&(pendingLoop||seekBusy.load()))||(!loopLive()&&!loop.clearPending&&(pendingSeek!=std::size_t(-1)||seekBusy.load()));
    }
    bool acceptStart(){
        // A failed preparation remains blocked while its owner retires. Do not
        // register a fresh Resume intent merely because seekBusy is still true.
        if(stoppedStartBlocked)return false;
        if(outputPreparationPending()){resumePending=true;return true;}
        if(state==State::Paused)++rendering->clockEpoch;
        return startAudio();
    }
    progressive::SeekOperation loopJob;
    progressive::LoopSnapshot loop;
    std::vector<progressive::LoopBoundaryEvent> boundaries;
    std::uint64_t loopRequestID=0,loopCycleBase=0,boundaryRead=0;
    std::uint64_t activeLoopSpeedRequestID=0;
    bool pendingLoop=false,loopInitial=false,loopKeep=false,loopContinuation=false;
    std::optional<std::uint64_t> pausedClearInput;
    progressive::SeekOperation& seekOp(std::size_t i){return i==loopIndex?loopJob:i==stoppedIndex?stoppedJob:seeks.at(i);}
    bool loopLive()const{return loop.enabled;}
    void syncLoopSpeeds(Pipeline* source=nullptr,RenderTarget* observedTarget=nullptr){
        using LS=progressive::LoopSpeedState;
        auto* t=effectiveTarget();if(!source)source=pipeline.get();
        const auto now=machNs();
        if(rendering){const auto phase=rendering->handoff.phase.load(std::memory_order_acquire);
            if(phase==SwitchPhase::Started||phase==SwitchPhase::Done)if(auto* op=loopSpeeds.find(activeLoopSpeedRequestID);op&&!progressive::terminal(op->state)){
                op->adoptionPending=true;
                auto* adopted=rendering->handoff.newTarget;
                if(!op->committed&&adopted&&adopted->firstPcm.load(std::memory_order_acquire)){
                    op->outputStarted=true;if(!op->firstPcmObservedNs)op->firstPcmObservedNs=now;
                    op->session=adopted->session;op->renderEpoch=adopted->currentEpoch();
                    if(!op->committed)op->state=LS::Applied;
                }
            }
        }
        // B may land at the last frame of a callback: adoption is already Done,
        // but the first new PCM is observed only by the following callback.
        if(t&&t->firstPcm.load())for(const auto& row:loopSpeeds.records())if(!progressive::terminal(row.state)&&row.fixedBoundary&&row.session==t->session){
            auto& op=*loopSpeeds.find(row.id);op.state=LS::Completed;op.outputStarted=true;op.firstPcmObservedNs=op.completedNs=op.terminalNs=now;
        }
        for(const auto& prepared:stoppedSpeeds)if(auto* external=loopSpeeds.find(prepared.id);external&&!external->clearContinuation&&!progressive::terminal(external->state)){
            external->preparationVersion=prepared.preparationVersion;external->resumeInputFrame=prepared.resumeInputFrame;
            if(prepared.state==StoppedSpeedState::Replaced||prepared.state==StoppedSpeedState::Cancelled||prepared.state==StoppedSpeedState::Failed){
                external->state=prepared.state==StoppedSpeedState::Replaced?LS::Replaced:prepared.state==StoppedSpeedState::Failed?LS::Failed:LS::Cancelled;
                external->reason=prepared.reason;external->terminalNs=now;
            }else if(prepared.outputStarted){
                external->outputStarted=true;
                if(t&&t->session==prepared.session&&t->firstPcm.load()){
                    external->state=LS::Completed;external->firstPcmObservedNs=now;external->completedNs=external->terminalNs=now;
                }
            }
        }
        if(!source)return;
        const auto descriptor=source->loopTransition();const auto ops=source->speedOperations();const auto d=source->diagnostics();
        auto* sourceTarget=observedTarget?observedTarget:target&&target->pipeline==source?target.get():t;
        if(descriptor.state==prototype::phase58::LoopTransitionState::Applying||descriptor.state==prototype::phase58::LoopTransitionState::Committed||descriptor.state==prototype::phase58::LoopTransitionState::FixedBoundaryCommitted){
            for(const auto& row:loopSpeeds.records())if(!progressive::terminal(row.state)&&row.dynamicSession==d.session&&row.dynamicOperationID==descriptor.operationID){
                auto& op=*loopSpeeds.find(row.id);op.adoptionPending=true;
                if(descriptor.state==prototype::phase58::LoopTransitionState::Committed){op.committed=true;op.state=LS::Committed;if(!op.commitObservedNs)op.commitObservedNs=now;
                    op.producerCycle=descriptor.cycle;op.mapVersion=descriptor.mapVersion;op.outputEnd=descriptor.localEnd;}
                else if(descriptor.state==prototype::phase58::LoopTransitionState::FixedBoundaryCommitted){op.state=LS::FixedBoundaryCommitted;op.fixedBoundaryCommitted=true;op.deferral=descriptor.reason==prototype::phase58::LoopTransitionReason::OperationLimit?progressive::LoopSpeedDeferral::InternalLimit:descriptor.reason==prototype::phase58::LoopTransitionReason::PreparationDeadline?progressive::LoopSpeedDeferral::PreparationDeadline:progressive::LoopSpeedDeferral::ProtectedFrontier;op.reason=descriptor.reason==prototype::phase58::LoopTransitionReason::OperationLimit?"動的履歴上限により、公開済みPCMを保護する固定Bへ延期":descriptor.reason==prototype::phase58::LoopTransitionReason::PreparationDeadline?"cache状態再構成が期限・対象周期を越えたため、有効なcache出力を保持して固定Bへ延期":"公開済みFIFOと未公開PCMの後に合法な動的区間がないため、producerが確定した固定Bへ延期";op.producerCycle=descriptor.cycle;op.mapVersion=descriptor.mapVersion;op.outputEnd=descriptor.localEnd;if(!op.commitObservedNs)op.commitObservedNs=now;}
            }
        }
        for(const auto& row:loopSpeeds.records()){
                if(progressive::terminal(row.state)||!row.dynamicOperationID||row.dynamicOperationID>ops.size())continue;
                const auto& internal=ops[row.dynamicOperationID-1];
                if(row.dynamicSession!=internal.session||row.dynamicOperationID!=internal.id)continue;
                auto& external=*loopSpeeds.find(row.id);
                if(internal.appliedS>=0){
                    external.committed=true;if(!external.commitObservedNs)external.commitObservedNs=now;
                    external.firstChangedOutputFrame=std::max(0LL,internal.change.plan.appliedOutputSample);
                    external.completionOutputFrame=std::max(0LL,internal.change.plan.completionOutputSample);
                    external.state=LS::Committed;
                    if(descriptor.operationID==internal.id&&descriptor.state==prototype::phase58::LoopTransitionState::Committed){
                        external.producerCycle=descriptor.cycle;external.mapVersion=descriptor.mapVersion;external.outputEnd=descriptor.localEnd;
                        const auto start=external.firstChangedOutputFrame;
                        const auto published=source->diagnosticFifoCursors().write;
                        if(start>=descriptor.localStart&&published>descriptor.cumulativeStart+start-descriptor.localStart&&!external.firstChangedPublishedObservedNs)external.firstChangedPublishedObservedNs=now;
                        if(source->loopReadCycle()==descriptor.cycle&&d.consumed>start){external.outputStarted=true;external.state=LS::Applied;if(!external.firstPcmObservedNs){external.firstPcmObservedNs=now;external.cycle=loop.cycles;external.renderEpoch=sourceTarget?sourceTarget->currentEpoch():0;}}
                    }
                    if(internal.completedS>=0){external.state=LS::Completed;external.completedNs=external.terminalNs=now;}
                }
        }
    }
    bool committedLoopBoundary()const{if(state!=State::Playing||!pipeline)return false;const auto s=pipeline->loopTransition().state;return s==prototype::phase58::LoopTransitionState::Applying||s==prototype::phase58::LoopTransitionState::Committed||s==prototype::phase58::LoopTransitionState::FixedBoundaryCommitted;}
    void cancelLoop(const std::string& why){
        syncLoopSpeeds();loopSpeeds.cancel(loop.id,machNs(),why);
        loop.enabled=false;loop.clearPending=false;pendingLoop=false;
        if(loop.state!=progressive::LoopState::Disabled&&loop.state!=progressive::LoopState::Failed){loop.state=progressive::LoopState::Cancelled;loop.reason=why;}
    }
    void collectLoopBoundary(){
        if(!rendering)return;
        loop.safetyStopFrames=rendering->loopSafetyFrames.load();loop.failurePaddingFrames=loop.safetyStopFrames;loop.oldMissingFrames=rendering->oldMissing.load();loop.newMissingFrames=rendering->newMissing.load();loop.outputAffectedFrames=rendering->outputAffected.load();
        const auto written=rendering->boundaryWritten.load(std::memory_order_acquire);
        boundaryRead=std::max(boundaryRead,written>64?written-64:0);
        for(;boundaryRead<written;++boundaryRead){
            const auto e=rendering->boundaryRing[boundaryRead%64].read();if(!e)break;
            if(e->cycle!=boundaryRead+1)continue;
            if(e->loopID!=loop.id)continue;
            loop.cycles=e->settingCycle;
            if(!loop.lastBoundary||loop.lastBoundary->cycle!=e->cycle){loop.lastBoundary=*e;if(boundaries.size()==64)boundaries.erase(boundaries.begin());boundaries.push_back(*e);}
        }
        if(auto* t=effectiveTarget();t&&t->pipeline->loopReuseEnabled()){
            const auto d=t->pipeline->diagnostics().loopReuse;loop.reusable=true;loop.periodFrames=t->loopEnd-t->pipeline->loopOutputStartFrame();
            loop.cacheBytes=d.cacheBytes;loop.reuseCount=d.cyclesPrepared;loop.seedRestores=d.seedRestores;loop.mapBuilds=d.mapBuilds;loop.workerCreations=d.workerCreations;
            loop.coldDiscardedFrames=d.coldDiscardedFrames;loop.warmDiscardedFrames=d.warmDiscardedFrames;
        }
    }
    std::atomic<std::uint64_t> nextEpoch{0};std::uint64_t lifetimeMissing=0,lifetimeCalls=0,lifetimeRejected=0,lifetimeMaxMissing=0;
    std::uint64_t retiredEpoch=0,retiredPresented=0;
    std::uint64_t lifetimeWorkerDeadlines=0,lifetimeWorkerNews=0,lifetimeWorkgroupErrors=0;
    std::uint64_t archivedEpochCount=0,archivedPreparedEpochCount=0;
    static std::uint64_t workerErrors(const prototype::phase58::Diagnostics& p){const auto& m=p.scheduling;return m.policyErrors+m.joinErrors+m.restoreErrors+m.intervalErrors+m.queryErrors+m.waitErrors+m.wakeErrors;}
    bool closedQualityFailed=false;
    double requested=1,acceptedAt=0,readyAfter=-1,constructorS=-1,cpuStart=0;
    void partialMixTestEvent(ProgressiveControlTestPoint point)noexcept{
        if(!options.controlTestHooks.event||!rendering)return;
        auto& h=rendering->handoff;if(h.phase.load(std::memory_order_acquire)!=SwitchPhase::Started)return;
        const auto cursor=h.observedMixCursor.load(std::memory_order_acquire);
        if(cursor&&cursor<h.output.length)controlTestEvent(point);
    }
    void controlTestEvent(ProgressiveControlTestPoint point)noexcept{
        if(options.controlTestHooks.event)options.controlTestHooks.event(options.controlTestHooks.context,point);
    }
    std::unique_ptr<RenderTarget> makeTarget(Pipeline* p){
        auto t=std::make_unique<RenderTarget>();t->pipeline=p;t->session=p->diagnostics().session;
        t->inputGeneration=p->inputGeneration();t->epoch=++nextEpoch;t->speedMicros=progressive::speedMicros(requested);t->presented=p->outputStartFrame();return t;
    }
    void cancelSeeks(const std::string& why,std::uint64_t keepLoopSpeedID=0){
        syncLoopSpeeds();loopSpeeds.cancel(loop.id,machNs(),why,keepLoopSpeedID);pausedClearInput.reset();
        if(pipeline)pipeline->cancelLoopTransition();
        ++seekVersion;pendingSeek=std::size_t(-1);pendingLoop=false;cancelStopped(why);
        if(!progressive::terminal(loopJob.state)&&!startedSeek(loopIndex)){loopJob.state=progressive::SeekState::Cancelled;loopJob.reason=why;}
        for(std::size_t i=0;i<seeks.size();++i)if(!progressive::terminal(seeks[i].state)&&!startedSeek(i)){seeks[i].state=progressive::SeekState::Cancelled;seeks[i].reason=why;}
    }
    void stopSeeks(){
        {std::lock_guard lock(mutex);cancelSeeks("停止・入力変更により取消");}
        if(seekBusy.load())controlTestEvent(ProgressiveControlTestPoint::SeekCleanupWait);
        while(seekBusy.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    RenderTarget* effectiveTarget()const {
        if(!pipeline||!rendering)return target.get();
        return rendering->target.load(std::memory_order_seq_cst);
    }
    bool startedSeek(std::size_t index){
        if(index!=activeSeek||!rendering)return false;
        auto& phase=rendering->handoff.phase;auto value=phase.load(std::memory_order_acquire);
        if(value==SwitchPhase::Requested){if(handoffRequired())return true;phase.compare_exchange_strong(value,SwitchPhase::Cancelled,std::memory_order_acq_rel);value=phase.load(std::memory_order_acquire);}
        return value==SwitchPhase::Started||value==SwitchPhase::Done;
    }
    bool handoffRequired()const{return committedLoopBoundary();}
    // Impl mutex held; render is quiescent or has released Done.
    void captureSwitch(std::size_t index,const RenderState& s){
        if(index!=loopIndex&&index!=stoppedIndex&&index>=seeks.size())return;auto& op=seekOp(index);const auto& h=s.handoff;
        op.transitionBeginNs=h.beginNs;op.transitionEndNs=h.endNs;op.oldFifoAtSwitchFrames=h.oldAvailable;op.transitionFrames=h.output.cursor;
        if(h.newTarget){op.renderEpoch=h.newTarget->currentEpoch();op.firstCallbackNs=h.newTarget->firstPcm;op.estimatedPresentationNs=h.newTarget->firstTarget;}
    }
    // Impl mutex held, after the corresponding normal worker has joined.
    void archiveEpoch(ProgressiveClosedEpoch audit){
        ++archivedEpochCount;if(audit.preparedOnly)++archivedPreparedEpochCount;
        const auto& d=audit.pipeline;lifetimeMissing+=d.missingFrames;lifetimeCalls+=d.missingCalls;lifetimeRejected+=d.rejectedWrites;
        lifetimeMaxMissing=std::max(lifetimeMaxMissing,d.maxConsecutiveMissing);
        lifetimeWorkerDeadlines+=d.scheduling.deadlineMisses;lifetimeWorkerNews+=d.realtimeNewCalls;lifetimeWorkgroupErrors+=workerErrors(d);
        const auto& m=d.scheduling;closedQualityFailed|=d.failed||d.missingFrames||d.missingCalls||d.rejectedWrites||d.realtimeNewCalls||m.deadlineMisses||workerErrors(d);
        if(audit.operations.size()>256){audit.droppedOperations=audit.operations.size()-256;audit.operations.erase(audit.operations.begin(),audit.operations.end()-256);}
        if(closed.size()==16)closed.erase(closed.begin());closed.push_back(std::move(audit));
    }
    void seekLoop(){@autoreleasepool {while(!exit.load()){
        controlTestEvent(ProgressiveControlTestPoint::LoopJobDispatch);
        std::unique_ptr<Pipeline> next,old;
        std::unique_ptr<RenderTarget> nextTarget,oldTarget;
        std::shared_ptr<RenderState> renderLease;
        std::size_t index=std::size_t(-1);std::uint64_t version=0;
        bool published=false,transitionDone=false,autoCycle=false,continuation=false;std::uint64_t jobLoopID=0,jobSpeedRequestID=0;
        prototype::phase58::LoopTransitionSnapshot dynamic;
        auto finalFailure=progressive::LoopSpeedDeferral::PreparationFailed;
        try{
            {std::lock_guard lock(mutex);
                collectLoopBoundary();if(!loopLive()&&!loop.clearPending)pendingLoop=false;
                if(pipeline&&pendingSeek==std::size_t(-1)&&!pendingLoop&&target&&target->loopEnd.load()&&!pipeline->loopReuseEnabled()&&(loopLive()||loop.clearPending))pendingLoop=true;
                if(pendingLoop&&pipeline&&pendingSeek==std::size_t(-1)){
                    index=loopIndex;pendingLoop=false;activeSeek=index;seekBusy=true;version=seekVersion;
                    autoCycle=!loopInitial;continuation=loop.clearPending;if(continuation&&pausedClearInput)autoCycle=false;jobLoopID=loop.id;jobSpeedRequestID=loop.speedRequestID;
                    loopJob={};auto& op=loopJob;op.id=loop.id;op.state=progressive::SeekState::Preparing;op.preparingNs=machNs();op.acceptedNs=op.preparingNs;
                    op.inputGeneration=pipeline->inputGeneration();op.sourceRenderEpoch=target->currentEpoch();op.speedMicros=progressive::speedMicros(requested);
                    op.requestedInputFrame=continuation?pausedClearInput.value_or(loop.endFrameExclusive):loop.startFrame;
                    if(loopKeep&&loopInitial)autoCycle=true;
                    next=continuation?pipeline->createSeek(op.requestedInputFrame,op.speedMicros):pipeline->createLoopSeek(op.requestedInputFrame,loop.endFrameExclusive,op.speedMicros);
                    if(!continuation){next->enableLoopReuse(loop.startFrame);if(options.loopSupplyFramesForTest)next->setLoopSupplyLimitForTest(options.loopSupplyFramesForTest);}
                    loop.lastPreparationNs=op.preparingNs;++loop.preparationCount;if(!loop.initialPositionComplete)loop.state=progressive::LoopState::Preparing;
                }else if(pendingSeek!=std::size_t(-1)&&pipeline&&(!stoppedPreparing()||captureStopped(*stoppedSpeed()))){
                    index=pendingSeek;pendingSeek=std::size_t(-1);activeSeek=index;seekBusy=true;version=seekVersion;
                    auto& op=seekOp(index);op.state=progressive::SeekState::Preparing;op.preparingNs=machNs();
                    const bool analysis=pipeline->finalAnalysisAvailable();op.waitedForAnalysis|=!analysis;
                    op.stage=analysis?progressive::SeekStage::PreparingFifo:progressive::SeekStage::PreparingAnalysis;
                    if(analysis)op.analysisReadyNs=op.preparingNs;
                    op.speedMicros=progressive::speedMicros(requested);
                    next=loopLive()?pipeline->createLoopSeek(op.requestedInputFrame,loop.endFrameExclusive,op.speedMicros):op.mode==progressive::SeekMode::FastLocal?pipeline->createInteractiveSeek(op.requestedInputFrame,op.speedMicros,pipeline->sampleRate()*std::size_t(op.prerollMillis)/1000):pipeline->createSeek(op.requestedInputFrame,op.speedMicros);
                    if(loopLive()){jobLoopID=loop.id;jobSpeedRequestID=loop.speedRequestID;next->enableLoopReuse(loop.startFrame);if(op.mode!=progressive::SeekMode::Exact){op.mode=progressive::SeekMode::Exact;op.reason="Loop内は固定Exactへ再準備（局所位相方式は未採用）";}}
                }else if(pendingStopped&&pipeline&&(state==State::Ready||state==State::Paused)){
                    auto& speed=*stoppedSpeed();
                    if(captureStopped(speed)){
                        index=stoppedIndex;pendingStopped=false;activeSeek=index;seekBusy=true;version=seekVersion;
                        stoppedJobOperation=stoppedSpeeds.size()-1;stoppedJob={};auto& op=stoppedJob;
                        op.state=progressive::SeekState::Preparing;op.preparingNs=machNs();op.acceptedNs=speed.acceptedNs;
                        op.inputGeneration=speed.inputGeneration;op.sourceRenderEpoch=speed.sourceRenderEpoch;
                        op.speedMicros=speed.speedMicros;op.requestedInputFrame=speed.resumeInputFrame;
                        // Exact is intentional: no local-phase approximation or opt-in expansion.
                        next=loopLive()?pipeline->createLoopSeek(op.requestedInputFrame,loop.endFrameExclusive,op.speedMicros):pipeline->createSeek(op.requestedInputFrame,op.speedMicros);
                        if(loopLive()){jobLoopID=loop.id;jobSpeedRequestID=speed.id;next->enableLoopReuse(loop.startFrame);}
                    }else if(machNs()-speed.acceptedNs>std::uint64_t(options.prepareTimeout.count())*1000000){
                        speed.state=StoppedSpeedState::Failed;speed.reason="停止位置の確定が期限を超えました";pendingStopped=false;resumePending=false;stoppedStartBlocked=true;
                    }
                }
            }
            if(!next){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}
            {std::lock_guard lock(mutex);activeLoopSpeedRequestID=jobSpeedRequestID;
                if(auto* external=loopSpeeds.find(jobSpeedRequestID);external&&!progressive::terminal(external->state)){
                    external->state=progressive::LoopSpeedState::Preparing;external->preparationVersion=version;external->preparingNs=machNs();
                }}
            next->start();controlTestEvent(ProgressiveControlTestPoint::SeekPreparationStarted);
            const auto deadline=std::chrono::steady_clock::now()+options.prepareTimeout;
            controlTestEvent(ProgressiveControlTestPoint::NextPreparationDeadline);
            if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("シークの準備が期限を超えました");
            const auto cancelled=[&]{return exit.load()||seekVersion.load()!=version;};
            const auto offerDynamic=[&]{
                auto& h=renderLease->handoff;const auto receipt=pipeline->requestLoopTransition(seekOp(index).speedMicros,target->presented.load(),&h.dynamicOperation);
                auto* external=loopSpeeds.find(jobSpeedRequestID);
                if(receipt.result==prototype::Phase39RequestResult::Accepted){
                    if(external&&!progressive::terminal(external->state)){external->dynamicOperationID=receipt.id;external->session=external->dynamicSession=target->session;external->planningRenderEpoch=target->currentEpoch();external->readyNs=machNs();}
                }else if(receipt.result==prototype::Phase39RequestResult::Busy){
                    if(external)external->deferral=progressive::LoopSpeedDeferral::BusyRetry;
                    loop.speedDeferReason="旧動的要求の取消回収待ち。回収後に現在周期への適用を再試行";
                }else if(receipt.result==prototype::Phase39RequestResult::Duplicate){
                    // Returning to the current fixed speed before any commit
                    // requires no owner switch and must retain ALL old FIFO.
                    h.dynamicNoChange=true;auto expected=SwitchPhase::Requested;
                    if(!h.phase.compare_exchange_strong(expected,SwitchPhase::Cancelled,std::memory_order_acq_rel))throw std::logic_error("同速度要求の取消点が不正です");
                    if(external&&!progressive::terminal(external->state)){external->noChange=true;external->state=progressive::LoopSpeedState::Completed;external->reason="未commit要求を取消し、既存の同速度PCMを継続";external->completedNs=external->terminalNs=machNs();}
                    if(jobSpeedRequestID==loop.speedRequestID)pendingLoop=false;
                    if(loopKeep&&loopInitial){loopInitial=false;loop.initialPositionComplete=true;loop.state=progressive::LoopState::Active;}
                    loop.speedDeferReason.clear();
                }else{
                    finalFailure=receipt.result==prototype::Phase39RequestResult::LimitReached?progressive::LoopSpeedDeferral::InternalLimit:progressive::LoopSpeedDeferral::Unsupported;
                    if(external)external->deferral=finalFailure;
                    throw std::runtime_error(receipt.result==prototype::Phase39RequestResult::LimitReached?"内部動的要求台帳の上限です。有効な旧PCMを保持して拒否":"動的要求を受け付けられる所有者状態ではありません。有効な旧PCMを保持して拒否");
                }
            };
            while(!cancelled()&&!next->waitUntilReady(std::chrono::milliseconds(1))){
                {std::lock_guard lock(mutex);auto& op=seekOp(index);if(!op.analysisReadyNs&&next->finalAnalysisAvailable()){op.analysisReadyNs=machNs();op.stage=progressive::SeekStage::PreparingFifo;}}
                if(next->failed())throw std::runtime_error(next->diagnostics().error);
                if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("シークの準備が期限を超えました");
            }
            if(!cancelled()){
                std::lock_guard lock(mutex);auto& op=seekOp(index);
                if(!cancelled()&&pipeline&&!progressive::terminal(op.state)){
                    const bool retainInitialSupply=index==loopIndex&&autoCycle&&loopKeep&&loopInitial&&!pipeline->loopReuseEnabled();
                    if(op.speedMicros!=progressive::speedMicros(requested)&&!retainInitialSupply){
                        ++op.replans;op.state=progressive::SeekState::Pending;if(index==loopIndex)pendingLoop=true;else if(index==stoppedIndex)pendingStopped=true;else pendingSeek=index;
                    }else{
                        op.state=progressive::SeekState::Ready;op.readyNs=machNs();if(!op.analysisReadyNs)op.analysisReadyNs=op.readyNs;
                        if(auto* external=loopSpeeds.find(jobSpeedRequestID);external&&!progressive::terminal(external->state))external->readyNs=op.readyNs;
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
                        nextTarget=makeTarget(next.get());nextTarget->speedMicros=op.speedMicros;renderLease=rendering;
                        if(index==loopIndex&&!continuation&&next->loopOutputEndFrame()-next->loopOutputStartFrame()<prototype::phase62::PeriodBoundary::minimumFrames)throw std::runtime_error("確定出力周期が512フレーム未満です");
                        if(next->loopOutputEndFrame()){nextTarget->loopEnd=next->loopOutputEndFrame();nextTarget->loopID=loop.id;nextTarget->loopA=loop.startFrame;nextTarget->loopB=loop.endFrameExclusive;}
                        if(index==loopIndex&&autoCycle&&loopKeep&&loopInitial){
                            target->loopEnd=pipeline->fixedOutputFrameForInput(loop.endFrameExclusive);target->loopID=loop.id;target->loopA=loop.startFrame;target->loopB=loop.endFrameExclusive;
                            const auto previousSupply=pipeline->diagnostics();
                            if(previousSupply.missingFrames||previousSupply.rejectedWrites)throw std::runtime_error("現在区間のPCM供給異常により全曲ループの境界を確定できません");
                            if(target->presented.load()+(restore==State::Playing?4096:0)+pipeline->sampleRate()/200>=target->loopEnd.load())throw std::runtime_error("現在位置が全曲ループの準備期限を過ぎています（最大callbackと混合の余裕が必要）");
                        }
                        if(index==loopIndex&&loopKeep&&loopInitial&&!pipeline->loopReuseEnabled()){
                            const auto preparation=pipeline->diagnostics().loopReuse.normalPreparation;
                            if(preparation==prototype::phase58::NormalLoopReuseState::Failed||preparation==prototype::phase58::NormalLoopReuseState::LimitReached){
                                loop.speedDeferReason=preparation==prototype::phase58::NormalLoopReuseState::LimitReached?"通常ownerの保存点上限。初回B供給版を保持してB以降に最新速度を準備":"通常ownerの自己反復準備失敗。初回B供給版を保持してB以降に最新速度を準備";
                                if(auto* external=loopSpeeds.find(loop.speedRequestID);external&&!progressive::terminal(external->state)){external->deferral=preparation==prototype::phase58::NormalLoopReuseState::LimitReached?progressive::LoopSpeedDeferral::InternalLimit:progressive::LoopSpeedDeferral::PreparationFailed;external->reason=loop.speedDeferReason;}
                            }
                        }
                        if(index==loopIndex){loop.lastReadyNs=machNs();if(!loop.readyNs)loop.readyNs=loop.lastReadyNs;loop.maxPreparationNs=std::max(loop.maxPreparationNs,loop.lastReadyNs-loop.lastPreparationNs);if(loopInitial)loopCycleBase=rendering->loopCycles.load();if(loopLive())loop.state=progressive::LoopState::Armed;}
                        op.renderEpoch=nextTarget->currentEpoch();op.session=nextTarget->session;
                        op.stage=progressive::SeekStage::SwitchReady;op.switchReadyNs=machNs();
                        if((restore==State::Playing&&(op.mode==progressive::SeekMode::FastLocal||index==loopIndex||loopLive()))||(index==loopIndex&&autoCycle)){
                            auto& h=renderLease->handoff;h.oldTarget=target.get();h.newTarget=nextTarget.get();h.output.prepare(next->sampleRate());h.observedMixCursor=0;
                            h.committedDynamic=false;h.awaitDynamic=restore==State::Playing&&autoCycle&&!continuation&&pipeline->loopReuseEnabled();h.dynamicNoChange=false;h.dynamicOperation=0;
                            h.scheduledBoundary=index==loopIndex&&autoCycle;h.periodic=h.scheduledBoundary&&!continuation&&next->loopReuseEnabled();h.loopCycle=h.scheduledBoundary&&!continuation;h.loopID=jobLoopID;h.inputA=loop.startFrame;h.inputB=loop.endFrameExclusive;h.boundaryEnd=target->loopEnd;
                            if(h.scheduledBoundary){
                                if(!h.boundaryEnd)throw std::runtime_error("ループの確定Bがありません");
                                h.notBeforeCycle=pipeline->loopReuseEnabled()?pipeline->loopReadCycle():0;
                                if(target->presented.load()>h.boundaryEnd-h.output.length){
                                    if(pipeline->loopReuseEnabled()&&(h.periodic||continuation))++h.notBeforeCycle;
                                    else throw std::runtime_error("次周期PCMの準備がB直前の期限を超えました");
                                }
                            }
                            h.beginNs=h.endNs=h.oldAvailable=0;
                            h.phase.store(SwitchPhase::Requested,std::memory_order_release);published=true;
                            // Callback references, FIFO, promotion and every
                            // allocating preparation precede irreversible DSP
                            // commit. A delayed normal thread is no longer
                            // needed to publish the dynamic B handoff.
                        }else transitionDone=true;
                    }
                }
            }
            if(published)controlTestEvent(ProgressiveControlTestPoint::SwitchPublished);
            const auto switchDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);
            bool observedStart=false;
            while(published){
                bool done=false,notifyStart=false;
                {std::lock_guard lock(mutex);auto& h=renderLease->handoff;auto phase=h.phase.load(std::memory_order_acquire);
                    if(h.awaitDynamic&&phase==SwitchPhase::Requested&&!h.dynamicOperation.load()&&!cancelled()&&requested==seekOp(index).speedMicros/1000000.)offerDynamic();
                    if(h.awaitDynamic&&pipeline){dynamic=pipeline->loopTransition();using D=prototype::phase58::LoopTransitionState;
                        if(dynamic.operationID==h.dynamicOperation.load()){
                            if(dynamic.state==D::Committed){loop.dynamicOperationID=dynamic.operationID;loop.dynamicSpeedRequestID=jobSpeedRequestID;loop.dynamicCycle=dynamic.cycle;loop.mapVersion=dynamic.mapVersion;loop.dynamicOutputEnd=dynamic.localEnd;loop.speedDeferReason.clear();}
                            else if(dynamic.state==D::Rejected||dynamic.state==D::FixedBoundaryCommitted)loop.speedDeferReason="Phase59保護範囲の後に合法な遷移区間がないため、公開済みFIFOと未公開PCMを保持するproducer確定Bへ延期";
                        }
                    }
                    syncLoopSpeeds();
                    if(phase==SwitchPhase::Requested&&(cancelled()||(state!=State::Playing&&!(index==loopIndex&&autoCycle&&(state==State::Ready||state==State::Paused)))||(requested!=seekOp(index).speedMicros/1000000.&&!handoffRequired()&&!(index==loopIndex&&autoCycle&&!continuation&&!pipeline->loopReuseEnabled())))){
                        cancelPreparedSwitch(h,state==State::Playing&&renderLease->active.load(std::memory_order_acquire),[&]{return !pipeline||pipeline->cancelLoopTransition();});phase=h.phase.load(std::memory_order_acquire);
                    }
                    if(phase==SwitchPhase::Started){seekOp(index).stage=progressive::SeekStage::Transitioning;}
                    if(phase==SwitchPhase::Done){transitionDone=true;done=true;}
                    if(!observedStart&&(phase==SwitchPhase::Started||phase==SwitchPhase::Done)){observedStart=true;notifyStart=true;}
                    if(phase==SwitchPhase::Cancelled){
                        if(jobSpeedRequestID!=loop.speedRequestID)if(auto* external=loopSpeeds.find(jobSpeedRequestID);external&&!progressive::terminal(external->state)&&!external->committed&&!external->outputStarted){
                            external->state=loop.clearPending?progressive::LoopSpeedState::Cancelled:progressive::LoopSpeedState::Replaced;external->terminalNs=machNs();external->reason=loop.clearPending?"ClearによるDSP/native取消が確定":"DSP/native取消の確定後に最新速度へ置換";
                        }
                        if(!cancelled()&&next->failed())throw std::runtime_error(next->diagnostics().error);
                        transitionDone=!h.dynamicNoChange&&!cancelled()&&pipeline&&!h.scheduledBoundary&&seekOp(index).speedMicros==progressive::speedMicros(requested)&&(state==State::Paused||state==State::Ready);
                        if(!h.dynamicNoChange&&!cancelled()&&pipeline&&state==State::Playing){auto& op=seekOp(index);++op.replans;op.state=progressive::SeekState::Pending;if(index==loopIndex)pendingLoop=true;else if(index==stoppedIndex)pendingStopped=true;else pendingSeek=index;transitionDone=false;}
                        if(h.dynamicNoChange){seekOp(index).state=progressive::SeekState::Cancelled;seekOp(index).reason="既存の同速度出力を継続。準備版だけを退役";}
                        done=true;
                    }
                    if(cancelStoppedSwitch(h,renderLease->active.load(),state!=State::Playing||cancelled())){
                        // Stop can leave state=Playing until this worker joins.
                        // Output is already quiescent; no callback can finish a
                        // partial switch. Record cancellation instead of waiting.
                        auto& op=seekOp(index);if(!progressive::terminal(op.state)){op.state=progressive::SeekState::Cancelled;op.reason="出力静止後の停止・失効により切替を取消";}done=true;
                    }
                }
                if(notifyStart)controlTestEvent(ProgressiveControlTestPoint::SwitchStartedOrDone);
                if(done)break;
                if(!(index==loopIndex&&autoCycle)&&std::chrono::steady_clock::now()>switchDeadline)throw std::runtime_error("音声callbackの切替確認が1秒以内に届きませんでした");
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
            if(published)while(renderLease->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
            {std::lock_guard lock(mutex);
                if(published)captureSwitch(index,*renderLease);collectLoopBoundary();
                if(transitionDone&&pipeline&&nextTarget&&!progressive::terminal(seekOp(index).state)&&(!cancelled()||published)){
                    auto& op=seekOp(index);
                    if(next->failed())throw std::runtime_error(next->diagnostics().error);
                    if(state==State::Paused&&!next->setRealtimeRendering(false))throw std::runtime_error("Pausedシーク先の実時間policy復元に失敗しました");
                    if(published){const auto& h=renderLease->handoff;op.transitionBeginNs=h.beginNs;op.transitionEndNs=h.endNs;op.oldFifoAtSwitchFrames=h.oldAvailable;op.transitionFrames=h.output.cursor;}
                    syncLoopSpeeds();
                    old=std::move(pipeline);retiringPipeline=old.get();oldTarget=std::move(target);pipeline=std::move(next);target=std::move(nextTarget);options.initialSpeed=op.speedMicros/1000000.;
                    op.switchedNs=op.transitionBeginNs?op.transitionBeginNs:machNs();
                    rendering->target.store(target.get(),std::memory_order_seq_cst);op.firstCallbackNs=target->firstPcm;op.estimatedPresentationNs=target->firstTarget;
                    if(jobLoopID==loop.id&&loopLive()&&op.speedMicros==progressive::speedMicros(requested))pendingLoop=false;
                    op.renderEpoch=target->currentEpoch();op.state=progressive::SeekState::Completed;op.stage=progressive::SeekStage::Finished;
                    if(auto* external=loopSpeeds.find(jobSpeedRequestID);external&&!progressive::terminal(external->state)&&!external->committed&&index!=stoppedIndex){
                        external->fixedBoundary=true;external->session=target->session;external->renderEpoch=op.renderEpoch;
                        external->outputEnd=target->loopEnd;external->cycle=loop.cycles;
                        if(auto position=pipeline->positionSample())external->mapVersion=position->mapVersion;
                        if(target->firstPcm.load()){external->state=progressive::LoopSpeedState::Completed;external->outputStarted=true;external->firstPcmObservedNs=external->completedNs=external->terminalNs=machNs();}
                    }
                    if(state==State::Ready||state==State::Paused){
                        // A completed output switch may already have consumed new
                        // PCM before pause. Keep the captured cursor, not the seek target.
                        if(!stoppedInput)if(auto sample=pipeline->stoppedPosition())stoppedInput=sample->input;
                        // ReadyForResume is published only after old stop/join
                        // below. The monitor must not start the adopted epoch
                        // while the old execution owner is still retiring.
                        stoppedStartBlocked=false;
                    }
                    if(index!=loopIndex&&jobLoopID==loop.id&&loopLive()){loopInitial=false;loop.initialPositionComplete=true;loop.state=progressive::LoopState::Active;loop.currentRenderEpoch=target->currentEpoch();}
                    if(index==loopIndex&&jobLoopID==loop.id){
                        loopInitial=false;loop.initialPositionComplete=true;loop.currentRenderEpoch=target->currentEpoch();
                        loop.appliedSpeed=target->speedMicros/1000000.;
                        if(continuation){if(!pausedClearInput)loop.clearPending=false;}else if(loopLive())loop.state=progressive::LoopState::Active;
                    }
                }
                if(published)renderLease->handoff.phase.store(SwitchPhase::Idle,std::memory_order_release);
            }
        }catch(const std::exception& e){
            std::lock_guard lock(mutex);
            if(auto* external=loopSpeeds.find(jobSpeedRequestID);external&&!progressive::terminal(external->state)){
                external->state=progressive::LoopSpeedState::Failed;external->reason=e.what();external->terminalNs=machNs();external->deferral=finalFailure;
            }
            if(seekVersion.load()==version&&(index==loopIndex||index==stoppedIndex||index<seeks.size())&&!progressive::terminal(seekOp(index).state)){seekOp(index).state=progressive::SeekState::Failed;seekOp(index).reason=e.what();}
            if(index==stoppedIndex&&stoppedJobOperation<stoppedSpeeds.size()){
                auto& op=stoppedSpeeds[stoppedJobOperation];if(op.state==StoppedSpeedState::Preparing){op.state=StoppedSpeedState::Failed;op.reason=e.what();resumePending=false;pendingStopped=false;stoppedStartBlocked=true;}
            }else if(index<seeks.size()&&stoppedPreparing()&&seekVersion.load()==version){
                auto& op=*stoppedSpeed();op.state=StoppedSpeedState::Failed;op.reason=e.what();resumePending=false;pendingStopped=false;stoppedStartBlocked=true;
            }
            if(index==loopIndex&&jobLoopID==loop.id&&(loopLive()||loop.clearPending)&&seekVersion.load()==version){
                const auto phase=rendering?rendering->handoff.phase.load():SwitchPhase::Idle;
                const bool validOld=autoCycle&&!continuation&&pipeline&&!pipeline->failed()&&pipeline->loopReuseEnabled()&&!committedLoopBoundary()&&phase!=SwitchPhase::Started&&phase!=SwitchPhase::Done;
                const bool stoppedContinuation=continuation&&pausedClearInput&&pipeline&&!pipeline->failed()&&(state==State::Ready||state==State::Paused);
                if(stoppedContinuation){
                    loop.state=progressive::LoopState::Failed;loop.reason=std::string("停止位置を保持してClear準備に失敗: ")+e.what();
                    loop.clearPending=true;pendingLoop=false;resumePending=false;stoppedStartBlocked=true;
                }else if(validOld){
                    loop.state=progressive::LoopState::Active;loop.reason=std::string("速度準備失敗。有効な旧出力を維持: ")+e.what();
                    if(loop.speedRequestID==jobSpeedRequestID){loop.speedPreparationFailed=true;loop.speedFailureRequestID=jobSpeedRequestID;pendingLoop=false;}
                }else{loop.state=progressive::LoopState::Failed;loop.reason=e.what();loop.enabled=false;loop.clearPending=false;fail(e.what());}
            }
        }
        // Both references outlive the callback; deletion and joining are normal work.
        if(next&&published){
            std::lock_guard lock(mutex);auto& h=renderLease->handoff;auto phase=SwitchPhase::Requested;
            h.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel);
            const bool stoppedCancellation=(exit.load()||seekVersion.load()!=version)&&!renderLease->active.load(std::memory_order_seq_cst);
            if(!stoppedCancellation&&(h.phase.load(std::memory_order_acquire)==SwitchPhase::Started||renderLease->target.load()==nextTarget.get())){
                // An exceptional failure after output began cannot roll its
                // consumed PCM back. Quiesce BOTH owners before releasing next.
                fail("切替開始後の失敗により安全停止しました");
            }
            while(renderLease->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
            while(renderLease->target.load(std::memory_order_seq_cst)==nextTarget.get()&&!detachStoppedPreparation(*renderLease,nextTarget.get(),target.get()))
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            h.phase.store(SwitchPhase::Idle,std::memory_order_release);
        }
        if(next){controlTestEvent(ProgressiveControlTestPoint::RetiringPreparation);next->setRealtimeRendering(false);next->stop();
            ProgressiveClosedEpoch audit;audit.renderEpoch=nextTarget?nextTarget->currentEpoch():0;audit.pipeline=next->diagnostics();audit.operations=next->speedOperations();
            audit.preparedOnly=!nextTarget||!nextTarget->firstPcm.load();
            {std::lock_guard lock(mutex);if(published)captureSwitch(index,*renderLease);collectLoopBoundary();archiveEpoch(std::move(audit));}
            next.reset();
        }
        if(old){
            while(renderLease->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
            controlTestEvent(ProgressiveControlTestPoint::RetiringOld);
            old->setRealtimeRendering(false);old->stop();
            {std::lock_guard lock(mutex);if(index<seeks.size())seekOp(index).discardedForSeekFrames=old->available();
                if(auto* speed=stoppedSpeed();speed&&speed->state==StoppedSpeedState::Preparing&&speed->preparationVersion==version)speed->discardedForStoppedSpeedFrames=old->available();
                if(continuation&&pausedClearInput){loop.pausedClearDiscardedFrames+=old->available();loop.pausedClearInputFrame=*pausedClearInput;if(auto* external=loopSpeeds.find(jobSpeedRequestID))external->discardedForPausedClearFrames=old->available();}}
            ProgressiveClosedEpoch audit;audit.renderEpoch=oldTarget->currentEpoch();audit.pipeline=old->diagnostics();audit.operations=old->speedOperations();
            if(audit.operations.size()>256){audit.droppedOperations=audit.operations.size()-256;audit.operations.erase(audit.operations.begin(),audit.operations.end()-256);}
            {std::lock_guard lock(mutex);for(auto& op:seeks)if(op.renderEpoch==oldTarget->currentEpoch()){op.firstCallbackNs=oldTarget->firstPcm;op.estimatedPresentationNs=oldTarget->firstTarget;}}
            std::lock_guard lock(mutex);syncLoopSpeeds(old.get(),oldTarget.get());loopSpeeds.retireEpoch(oldTarget->session,oldTarget->firstPcm.load()!=0,machNs());retiringPipeline=nullptr;archiveEpoch(std::move(audit));
            old.reset();oldTarget.reset();
        }
        {std::lock_guard lock(mutex);
            if(transitionDone&&pipeline&&seekVersion.load()==version&&(state==State::Ready||state==State::Paused)){
                stoppedReady(seekOp(index));
                if(auto* external=loopSpeeds.find(jobSpeedRequestID);external&&external->clearContinuation&&!progressive::terminal(external->state)){external->state=progressive::LoopSpeedState::ReadyForResume;external->readyNs=machNs();}
            }
            if(auto* external=loopSpeeds.find(jobSpeedRequestID);external&&!progressive::terminal(external->state)&&!external->committed&&!transitionDone&&jobSpeedRequestID!=loop.speedRequestID){
                external->adoptionPending=false;external->state=progressive::LoopSpeedState::Replaced;external->reason="未commit準備版の取消・退役後に最新要求へ置換";external->terminalNs=machNs();
            }
            const bool clearFinished=transitionDone&&continuation&&jobLoopID==loop.id&&seekVersion.load()==version;
            if(clearFinished)pausedClearInput.reset();
            activeLoopSpeedRequestID=0;
            activeSeek=std::size_t(-1);seekBusy=false;if(!pipeline)releaseBudget();
            // Clear completion and a retained Resume intent are one control
            // publication. Observers must not see !clearPending + Paused while
            // a later monitor tick still owes the already-accepted restart.
            if(clearFinished){
                try{if(resumePending&&(state==State::Ready||state==State::Paused)&&!outputPreparationPending())acceptStart();}
                catch(const std::exception& e){fail(e.what());}
                loop.clearPending=false;
            }
            controlTestEvent(ProgressiveControlTestPoint::SeekCleanupComplete);}
    }}}
    Impl(){stoppedSpeeds.reserve(4096);seeks.reserve(4096);closed.reserve(16);boundaries.reserve(64);monitor=std::thread([this]{@autoreleasepool {while(!exit.load()){
        {std::lock_guard lock(mutex);try{tick();}catch(const std::exception& e){fail(e.what());}}
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }}});seekWorker=std::thread([this]{seekLoop();});}
    ~Impl(){cancelPrepare=true;{std::lock_guard lock(mutex);quiesce(false);cancelSeeks("破棄により取消");}exit=true;++seekVersion;if(monitor.joinable())monitor.join();if(seekWorker.joinable())seekWorker.join();if(preparation.joinable())preparation.join();std::lock_guard lock(mutex);retire();rendering.reset();
        if(options.receiveFinalLoopSpeedAudit){
            const FinalLoopSpeedAudit audit{loopSpeeds.records(),1,true,!pipeline&&!retiringPipeline&&!rendering};
            (void)options.receiveFinalLoopSpeedAudit(options.finalLoopSpeedAuditContext,audit);
        }
    }
    void releaseBudget(){if(ownsBudget&&!seekBusy.load()){resourceOwner=false;ownsBudget=false;}}
    void quiesce(bool destroy){
        if(rendering)rendering->active.store(false,std::memory_order_seq_cst);
        if(engine&&engine.isRunning)[engine stop];
        if(rendering)while(rendering->inRender.load(std::memory_order_seq_cst))std::this_thread::sleep_for(std::chrono::microseconds(100));
        if(rendering)native.outputStoppedMachNs=rendering->ns();
        if(destroy){if(observer)[[NSNotificationCenter defaultCenter]removeObserver:observer];observer=nil;if(engine&&source)[engine detachNode:source];source=nil;engine=nil;}
    }
    void retire(){
        quiesce(true);cancelStopped("停止・入力変更・障害により取消");collectLoopBoundary();cancelLoop("停止・入力変更・障害により取消");
        if(rendering){auto& h=rendering->handoff;const auto phase=h.phase.load();if(phase==SwitchPhase::Started||phase==SwitchPhase::Done)captureSwitch(activeSeek,*rendering);if(phase!=SwitchPhase::Idle)h.phase.store(SwitchPhase::Cancelled,std::memory_order_release);}
        if(activeSeek<seeks.size()&&!progressive::terminal(seeks[activeSeek].state)){seeks[activeSeek].state=progressive::SeekState::Cancelled;seeks[activeSeek].reason="静止・退役により取消";}
        if(target){retiredEpoch=target->currentEpoch();retiredPresented=target->presented;for(auto& op:seeks)if(op.renderEpoch==target->currentEpoch()){op.firstCallbackNs=target->firstPcm;op.estimatedPresentationNs=target->firstTarget;}}
        if(rendering)rendering->target=nullptr;
        if(pipeline){pipeline->setRealtimeRendering(false);pipeline->stop();retired=pipeline->diagnostics();retiredOperations=pipeline->speedOperations();retiredPosition=pipeline->positionSample();
            if(retired.analysisDone&&!retired.failed){try{retiredMap=pipeline->dynamicTimeMap();}catch(const std::logic_error&) {}}
            pipeline.reset();}
        target.reset();
        releaseBudget();
    }
    void fail(const std::string& message){if(state==State::Failed&&!error.empty())return;if(loop.enabled||loop.clearPending){loop.enabled=false;loop.clearPending=false;loop.state=progressive::LoopState::Failed;loop.reason=message;}cancelSeeks(message);error=message;reason=StopReason::WorkerError;retire();state=State::Failed;}
    void configure(){@try {
        StageClock clock;engine=[[AVAudioEngine alloc]init];native={};native.deviceId=defaultDevice();
        auto f=[engine.outputNode outputFormatForBus:0];native.deviceRate=f.sampleRate;native.deviceChannels=f.channelCount;native.deviceBufferFrames=bufferFrames(native.deviceId);
        if(!native.deviceRate||!native.deviceChannels)throw std::runtime_error("出力形式が無効です");
        native.devicePresentationLatencyMs=engine.outputNode.presentationLatency*1000;
        rendering=std::make_shared<RenderState>();auto s=rendering;s->epochCounter=&nextEpoch;s->rate=pipeline->sampleRate();s->deviceRate=native.deviceRate;s->channels=static_cast<unsigned>(pipeline->channels());if(options.allowExperimentalLoops){s->loopRecords.resize(256);s->clockAnomalyRecords.resize(33);}
        target=makeTarget(pipeline.get());s->target=target.get();
        mach_timebase_info_data_t tb{};if(mach_timebase_info(&tb)!=KERN_SUCCESS)throw std::runtime_error("Mach時計を取得できません");s->numer=tb.numer;s->denom=tb.denom;
        s->observer=options.observeRawPcm;s->observerContext=options.observerContext;
        s->epochObserver=options.observeEpochPcm;s->outputObserver=options.observeOutputPcm;s->mixTestObservation=options.controlTestHooks.event!=nullptr;
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
        auto& h=rendering->handoff;
        if(h.phase.load()==SwitchPhase::Requested&&h.scheduledBoundary&&!h.newTarget->pipeline->setRealtimeRendering(true))throw std::runtime_error("ループ先のAudio Workgroup参加に失敗しました");
        if(cancelPrepare.load())throw std::runtime_error("準備が取り消されました");
        resumePending=false;stoppedInput.reset();
        StageClock clock;NSError* e=nil;rendering->pauseRequested=false;rendering->pauseAcknowledged=false;rendering->active=true;native.playCalledSteadyNs=static_cast<std::uint64_t>(seconds()*1e9);
        if(![engine startAndReturnError:&e]){rendering->active=false;throw std::runtime_error(e?e.localizedDescription.UTF8String:"音声開始に失敗しました");}
        native.sourcePresentationLatencyMs=source.outputPresentationLatency*1000;native.avStart=clock.elapsed();state=State::Playing;
        if(auto* op=stoppedSpeed();op&&op->state==StoppedSpeedState::ReadyForResume)op->outputStarted=true;
        return true;
    }@catch(NSException* e){throw std::runtime_error(e.reason?e.reason.UTF8String:"音声開始APIの例外");}}
    std::uint64_t tailDeadline()const {return rendering->lastTarget.load()+static_cast<std::uint64_t>(std::max(native.sourcePresentationLatencyMs,native.devicePresentationLatencyMs)*1e6)+5000000;}
    void tick(){
        if(!pipeline)return;collectLoopBoundary();syncLoopSpeeds();
        if(rendering&&rendering->loopMissed.load()){
            loop.state=progressive::LoopState::Failed;loop.reason="ループ出力の安全停止: ";
            switch(rendering->loopFailure.load()){
                case RenderState::Failure::MissingOld:loop.reason+="旧入力PCM不足";break;
                case RenderState::Failure::MissingNew:loop.reason+="新入力PCM不足";break;
                case RenderState::Failure::MissingBoth:loop.reason+="新旧入力PCM不足";break;
                case RenderState::Failure::NoPrepared:loop.reason+="境界の次周期PCM未準備";break;
                case RenderState::Failure::CallbackLimit:loop.reason+="callback上限超過";break;
                default:loop.reason+="span上限超過";break;
            }loop.enabled=false;loop.clearPending=false;fail(loop.reason);return;
        }
        for(auto& op:seeks)if(auto* t=effectiveTarget();op.renderEpoch&&t&&op.renderEpoch==t->currentEpoch()){op.firstCallbackNs=t->firstPcm;op.estimatedPresentationNs=t->firstTarget;}
        if(pipeline->failed()){fail(pipeline->diagnostics().error);return;}
        if(rendering&&(rendering->forcedRoute.exchange(false)||rendering->route.exchange(false))){
            const bool forced=force;force=false;auto f=[engine.outputNode outputFormatForBus:0];
            if(forced||defaultDevice()!=native.deviceId||f.sampleRate!=native.deviceRate||f.channelCount!=native.deviceChannels||bufferFrames(native.deviceId)!=native.deviceBufferFrames){++native.routeChanges;if(rendering)rendering->routeChanges=native.routeChanges;cancelSeeks("装置変更により取消");retire();reason=StopReason::RouteChanged;state=State::Stopped;return;}
        }
        if(resumePending&&(state==State::Ready||state==State::Paused)&&!outputPreparationPending())acceptStart();
        if(seekBusy.load()||pendingStopped||pendingSeek!=std::size_t(-1)||loopLive()||loop.clearPending)return;
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
        loop={};pendingLoop=false;pausedClearInput.reset();boundaryRead=0;boundaries.clear();stoppedBase=stoppedSpeeds.size();pendingStopped=resumePending=stoppedStartBlocked=false;stoppedInput.reset();
        state=State::Accepted;
        seekBase=seeks.size();lifetimeWorkerDeadlines=lifetimeWorkerNews=lifetimeWorkgroupErrors=0;lifetimeMissing=lifetimeCalls=lifetimeRejected=lifetimeMaxMissing=0;closed.clear();closedQualityFailed=false;archivedEpochCount=archivedPreparedEpochCount=0;
        const auto p=input;const auto o=options;
        preparation=std::thread([this,p,o]{@autoreleasepool {
            std::unique_ptr<Pipeline> next;
            try{
                state=State::Preparing;
                const auto bytes=std::filesystem::file_size(p);WavStreamReader reader(p);
                const auto reserve=progressive::reservationBytes(bytes,reader.frames())+(o.allowExperimentalLoops?24ULL*1024*1024:0);
                if(reserve>o.memoryReservationBudget)throw std::length_error("メモリ予約予算を超えています");
                if(std::filesystem::space(std::filesystem::temp_directory_path()).available<bytes+256ULL*1024*1024)throw std::length_error("一時入力複製の空き容量が不足しています");
                controlTestEvent(ProgressiveControlTestPoint::AcquiringResources);
                bool expected=false;if(!resourceOwner.compare_exchange_strong(expected,true))throw std::runtime_error("別の実験セッションが資源を使用中です");
                {std::lock_guard lock(mutex);ownsBudget=true;reservation=reserve;}
                prototype::phase58::Configuration c;c.speedMicros=progressive::speedMicros(o.initialSpeed);c.candidate=o.preset==Preset::Candidate;c.verifyPcm=false;c.residentInput=true;c.dynamicTransitions=true;c.scheduling=prototype::phase58::WorkerScheduling::AudioWorkgroup;c.sourceSnapshotBytes=bytes;c.seekCheckpoints=o.seekCheckpoints;c.lifecycleTestHooks=o.pipelineLifecycleTestHooks;c.controlTestHooks=o.pipelineControlTestHooks;c.boundedEpochReservations=o.allowExperimentalLoops;
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
    double applied(const std::vector<Operation>& ops,const RenderTarget* effective=nullptr)const{double s=effective&&effective->loopEnd.load()?effective->speedMicros/1000000.:options.initialSpeed;if(effective&&effective!=target.get())for(const auto& seek:seeks)if(seek.renderEpoch==effective->currentEpoch()){s=seek.speedMicros/1000000.;break;}for(const auto& op:ops)if(op.appliedS>=0)s=op.target/1000000.;return s;}
};
ProgressiveMacPlaybackEngine::ProgressiveMacPlaybackEngine():impl_(std::make_unique<Impl>()){}
ProgressiveMacPlaybackEngine::~ProgressiveMacPlaybackEngine()=default;
progressive::LoopAvailability ProgressiveMacPlaybackEngine::loopAvailability()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);progressive::LoopAvailability a;
    a.optIn=x.options.allowExperimentalLoops;a.allowed=a.optIn&&x.pipeline&&(x.state==State::Ready||x.state==State::Playing||x.state==State::Paused);return a;
}
progressive::LoopReceipt ProgressiveMacPlaybackEngine::requestLoopRange(std::uint64_t a,std::uint64_t b,progressive::LoopContext context,progressive::LoopOptions options){
    workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);const auto id=++x.loopRequestID;std::string why;
    auto* t=x.effectiveTarget();
    if(!x.options.allowExperimentalLoops)why="ループは開発用opt-inが必要です";
    else if(!x.pipeline||!t||(x.state!=State::Ready&&x.state!=State::Playing&&x.state!=State::Paused))why="ループにはReady/Playing/Pausedが必要です";
    else if(!context.inputGeneration||!context.session||!context.renderEpoch||context.inputGeneration!=t->inputGeneration||context.session!=t->session||context.renderEpoch!=t->currentEpoch())why="入力世代・session・renderEpochが一致しません";
    else if(x.committedLoopBoundary())why="採用済み動的周期のB引継ぎ待ちです。境界完了後に最新文脈で範囲を再要求してください";
    else if(!progressive::validLoopRange(a,b,x.pipeline->inputFrames()))why="ループは0<=A<B<=入力長の半開区間です";
    else if(!progressive::executableLoopRange(a,b,x.pipeline->sampleRate()))why="100ms未満は実行拒否（保存は1フレームから可能）。確定出力周期にも512フレーム下限があります";
    else if(options.startPolicy!=progressive::LoopStartPolicy::ReturnToA&&options.startPolicy!=progressive::LoopStartPolicy::KeepPosition)why="開始方針が不正です";
    else if(options.startPolicy==progressive::LoopStartPolicy::KeepPosition){
        if(a!=0||b!=x.pipeline->inputFrames())why="現在位置維持は全曲ループ専用です";
        else if(t->pipeline->loopOutputEndFrame()&&x.loop.endFrameExclusive!=x.pipeline->inputFrames())why="有界AB区間から現在位置維持へ移るには、解除完了またはA復帰が必要です";
        else try{(void)x.pipeline->fixedOutputFrameForInput(b);}catch(const std::exception& e){why=e.what();}
    }
    if(!why.empty()){
        if(!x.loop.enabled&&!x.loop.clearPending){x.loop={};x.loop.id=id;x.loop.inputGeneration=context.inputGeneration;x.loop.session=context.session;x.loop.sourceRenderEpoch=context.renderEpoch;x.loop.startFrame=a;x.loop.endFrameExclusive=b;x.loop.state=progressive::LoopState::Rejected;x.loop.reason=why;}
        return {id,false,why};
    }
    if(x.state==State::Playing&&!x.pipeline->cancelLoopTransition())return {id,false,"動的周期の採用が確定しました。B引継ぎ後に範囲を再要求してください"};
    x.cancelSeeks("新しいループ設定を優先");x.loop={};x.loop.id=id;x.loop.enabled=true;x.loop.state=progressive::LoopState::Pending;
    x.loop.startFrame=a;x.loop.endFrameExclusive=b;x.loop.inputGeneration=context.inputGeneration;x.loop.session=context.session;x.loop.sourceRenderEpoch=context.renderEpoch;
    x.loop.acceptedNs=machNs();x.loop.requestedSpeed=x.requested;x.loop.appliedSpeed=t->speedMicros/1000000.;
    x.loopInitial=true;x.loopKeep=options.startPolicy==progressive::LoopStartPolicy::KeepPosition;x.pendingLoop=true;
    if(x.loopKeep&&!t->loopEnd.load()){
        // Publish the boundary identity before enabling the producer runtime
        // protocol, so Clear always retains an explicit B continuation.
        t->loopA=a;t->loopB=b;t->loopID=id;t->loopEnd=x.pipeline->fixedOutputFrameForInput(b);
        if(!x.pipeline->requestNormalLoopReuse())x.loop.speedDeferReason="通常ownerの生成が終了済み、または原点準備待ち。既存の初回B供給版を維持";
    }
    x.loopCycleBase=x.rendering?x.rendering->loopCycles.load():0;x.boundaries.clear();return {id,true,{}};
}
progressive::LoopReceipt ProgressiveMacPlaybackEngine::requestClearLoop(std::uint64_t id,progressive::LoopContext context){
    workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);auto* t=x.effectiveTarget();
    if(!id||id!=x.loop.id||!context.inputGeneration||context.inputGeneration!=x.loop.inputGeneration||!context.session||
       (context.session!=x.loop.session&&(!t||context.session!=t->session))||!t||t->inputGeneration!=x.loop.inputGeneration)
        return {id,false,"解除対象のloopID・入力世代・sessionが一致しません"};
    if(!x.loop.enabled&&!x.loop.clearPending)return {id,true,{}};
    const bool stopped=x.state==State::Ready||x.state==State::Paused;
    std::optional<std::uint64_t> clearInput;
    if(stopped){clearInput=x.stoppedInput;if(!clearInput)if(auto position=t->pipeline->stoppedPosition())clearInput=position->input;
        if(!clearInput)return {id,false,"停止位置の採用Map標本待ちです。静止後の最新文脈でClearを再要求してください"};}
    x.partialMixTestEvent(ProgressiveControlTestPoint::PartialMixClearDecision);
    x.syncLoopSpeeds();std::uint64_t continuationSpeedID=0;
    const auto transferable=[&](const progressive::LoopSpeedOperation* latest){return latest&&!progressive::terminal(latest->state)&&!latest->committed&&(!latest->outputStarted||!latest->firstPcmObservedNs)&&!latest->fixedBoundaryCommitted&&!latest->adoptionPending&&latest->inputGeneration==t->inputGeneration&&latest->speedMicros==progressive::speedMicros(x.requested);};
    if(auto* latest=x.loopSpeeds.find(x.loop.speedRequestID);transferable(latest)){
        // Provisional exemption only while cancellation resolves Requested vs
        // Started. Internal stopped-job cancellation must not erase this ID.
        continuationSpeedID=latest->id;latest->clearContinuation=true;
    }
    // Resolve native cancellation before closing any external row. A Started
    // winner (or DSP Applying which still owns its route) keeps its active ID,
    // independently of the latest continuation ID.
    auto& handoff=x.rendering->handoff;
    const bool dspCancelled=!x.committedLoopBoundary()&&x.pipeline->cancelLoopTransition();
    auto nativePhase=handoff.phase.load(std::memory_order_acquire);
    if(nativePhase==SwitchPhase::Requested&&dspCancelled)x.controlTestEvent(ProgressiveControlTestPoint::ClearCancellationDecision);
    if(nativePhase==SwitchPhase::Requested&&dspCancelled)handoff.phase.compare_exchange_strong(nativePhase,SwitchPhase::Cancelled,std::memory_order_acq_rel);
    nativePhase=handoff.phase.load(std::memory_order_acquire);
    const bool nativeRetained=nativePhase==SwitchPhase::Started||nativePhase==SwitchPhase::Done||nativePhase==SwitchPhase::Requested;
    x.syncLoopSpeeds();
    x.loopSpeeds.cancelUnstarted(x.loop.id,machNs(),"Clearにより未開始の速度要求を取消",continuationSpeedID,nativeRetained?x.activeLoopSpeedRequestID:0);
    if(stopped||(!nativeRetained&&dspCancelled))x.cancelSeeks("ループ解除",continuationSpeedID);
    const auto phase=x.rendering->handoff.phase.load(std::memory_order_acquire);
    const bool enteringLoop=(phase==SwitchPhase::Started||phase==SwitchPhase::Done)&&x.rendering->handoff.newTarget&&x.rendering->handoff.newTarget->loopEnd.load()!=0;
    // Started is published before target.store. Inspect the retained new target
    // as well, rather than using the stale pre-cancellation normal target.
    const bool needsContinuation=stopped||x.effectiveTarget()->loopEnd.load()!=0||enteringLoop;
    x.syncLoopSpeeds();
    if(auto* latest=x.loopSpeeds.find(continuationSpeedID)){
        if(needsContinuation&&transferable(latest)){latest->state=progressive::LoopSpeedState::Preparing;latest->reason="未commitの最新速度を明示固定ExactのClear継続へ移管";}
        else{
            latest->clearContinuation=false;
            if(!needsContinuation&&!progressive::terminal(latest->state)){latest->state=progressive::LoopSpeedState::Cancelled;latest->terminalNs=machNs();latest->reason="Loop初回採用前のClearで取消。通常再生の速度変更は最新文脈で再要求してください";}
        }
    }
    x.loop.enabled=false;x.loop.state=progressive::LoopState::Cancelled;x.loop.reason="解除受付。開始済み混合と有効な反復PCMを維持し、準備後の安全なBから通常再生へ接続";
    x.pausedClearInput=clearInput;x.loop.clearPending=needsContinuation;x.loopInitial=false;x.loopKeep=false;x.pendingLoop=x.loop.clearPending;
    return {id,true,{}};
}
progressive::LoopSnapshot ProgressiveMacPlaybackEngine::getLoopSnapshot()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);x.collectLoopBoundary();auto result=x.loop;
    if(auto* t=x.effectiveTarget()){result.currentRenderEpoch=t->currentEpoch();result.appliedSpeed=x.applied(t->pipeline->speedOperations(),t);}return result;
}
std::vector<progressive::LoopBoundaryEvent> ProgressiveMacPlaybackEngine::loopHistory()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);x.collectLoopBoundary();return x.boundaries;
}
std::vector<progressive::LoopSpeedOperation> ProgressiveMacPlaybackEngine::loopSpeedHistory()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);x.syncLoopSpeeds();return x.loopSpeeds.records();
}
std::optional<progressive::LoopSpeedOperation> ProgressiveMacPlaybackEngine::loopSpeedOperation(std::uint64_t id)const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);x.syncLoopSpeeds();if(const auto* op=x.loopSpeeds.find(id))return *op;return {};
}
std::optional<LoopSpeedPcmEvidence> ProgressiveMacPlaybackEngine::loopSpeedPcmEvidence(std::uint64_t id)const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);x.syncLoopSpeeds();const auto* op=x.loopSpeeds.find(id);if(!op||!op->dynamicOperationID)return {};
    for(auto* owner:{x.pipeline.get(),x.retiringPipeline})if(owner&&owner->diagnostics().session==op->dynamicSession){
        const auto descriptor=owner->loopTransition();if(descriptor.operationID!=op->dynamicOperationID)return {};
        if(auto map=owner->loopCommittedTimeMap())return LoopSpeedPcmEvidence{*op,descriptor,std::move(*map)};
    }
    return {};
}
bool ProgressiveMacPlaybackEngine::prepare(const std::filesystem::path& p,ProgressiveOptions o){
    workQueue();progressive::speedMicros(o.initialSpeed);
    const auto hooks=unsigned(bool(o.allocationHooks.enter))+unsigned(bool(o.allocationHooks.leave))+unsigned(bool(o.allocationHooks.count));
    if(hooks&&hooks!=3)throw std::invalid_argument("確保計測hookは3個すべてを指定してください");
    if((o.preset!=Preset::Candidate&&o.preset!=Preset::Baseline)||o.callbackRecordLimit>262144||o.prepareTimeout.count()<=0||o.memoryReservationBudget>1024ULL*1024*1024||o.seekFailureForTest>2||!o.loopSpeedOperationLimitForTest||o.loopSpeedOperationLimitForTest>4096||!o.stoppedSpeedOperationLimitForTest||o.stoppedSpeedOperationLimitForTest>4096)throw std::invalid_argument("実験用設定が無効です");
    auto& x=*impl_;auto state=x.state.load();if(state==State::Accepted||state==State::Preparing||state==State::Playing||state==State::Paused||state==State::Draining)throw std::logic_error("入力変更前にstopしてください");
    x.stopSeeks();x.stopPreparation();std::lock_guard lock(x.mutex);x.retire();x.input=p;x.options=o;x.requested=o.initialSpeed;x.launch();return true;
}
bool ProgressiveMacPlaybackEngine::play(){
    workQueue();auto& x=*impl_;auto state=x.state.load();
    if(state==State::Stopped||state==State::Ended){
        // No engine mutex held: seek cleanup needs it to archive the old epoch,
        // clear seekBusy and release this instance's reservation before launch.
        x.controlTestEvent(ProgressiveControlTestPoint::RestartWait);
        x.stopSeeks();x.stopPreparation();std::lock_guard lock(x.mutex);
        if(x.input.empty()||(x.state!=State::Stopped&&x.state!=State::Ended))return false;
        x.retire();x.options.initialSpeed=x.requested;
        x.controlTestEvent(ProgressiveControlTestPoint::RestartLaunch);
        x.launch();x.autoPlay=true;return true;
    }
    std::lock_guard lock(x.mutex);if(x.state==State::Playing)return true;if(x.state==State::Accepted||x.state==State::Preparing){x.autoPlay=true;return true;}if(x.state!=State::Ready&&x.state!=State::Paused)return false;
    try{return x.acceptStart();}catch(const std::exception& e){x.fail(e.what());return false;}
}
bool ProgressiveMacPlaybackEngine::pause(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);
    if(x.state==State::Paused||x.state==State::Ready){const bool accepted=x.resumePending||x.state==State::Paused;x.resumePending=false;return accepted;}
    if(x.state!=State::Playing)return false;
    try{pauseRender(x.rendering.get(),[](void* context){static_cast<Impl*>(context)->controlTestEvent(ProgressiveControlTestPoint::PauseObserved);},&x);
        const auto limit=x.rendering->ns()+1000000000;while(x.rendering->ns()<x.tailDeadline()){if(x.rendering->ns()>limit)throw std::runtime_error("末尾提示時刻が無効です");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
        [x.engine pause];while(x.rendering->inRender.load())std::this_thread::sleep_for(std::chrono::microseconds(100));if(!x.effectiveTarget()->pipeline->setRealtimeRendering(false))throw std::runtime_error("Pause時の実時間policy復元に失敗しました");x.state=State::Paused;x.resumePending=false;x.stoppedInput.reset();return true;
    }catch(const std::exception& e){x.fail(e.what());return false;}}
bool ProgressiveMacPlaybackEngine::resume(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);if(x.state!=State::Paused)return false;try{return x.acceptStart();}catch(const std::exception& e){x.fail(e.what());return false;}}
void ProgressiveMacPlaybackEngine::stop(){workQueue();auto& x=*impl_;{std::lock_guard lock(x.mutex);x.partialMixTestEvent(ProgressiveControlTestPoint::PartialMixStopDecision);x.quiesce(false);x.cancelLoop("明示Stop");}x.cancelPrepare=true;x.stopSeeks();x.stopPreparation();std::lock_guard lock(x.mutex);x.retire();x.reason=StopReason::User;x.state=State::Stopped;}
prototype::phase59::RequestReceipt ProgressiveMacPlaybackEngine::setSpeed(double s,std::uint64_t session,std::uint64_t generation,std::uint64_t epoch){return setSpeedImpl(s,session,generation,epoch,nullptr);}
progressive::LoopSpeedReceipt ProgressiveMacPlaybackEngine::requestLoopSpeed(double speed,progressive::LoopContext context){
    workQueue();using Code=progressive::LoopSpeedReceiptCode;
    if(!context.inputGeneration||!context.session||!context.renderEpoch)return {0,false,false,"入力世代・session・renderEpochをすべて指定してください",Code::InvalidContext};
    std::string reason;Code code=Code::Stopped;const auto r=setSpeedImpl(speed,context.session,context.inputGeneration,context.renderEpoch,&reason,&code);
    return {r.id,r.result==prototype::Phase39RequestResult::Accepted||r.result==prototype::Phase39RequestResult::Duplicate,r.result==prototype::Phase39RequestResult::Duplicate,std::move(reason),code};
}
prototype::phase59::RequestReceipt ProgressiveMacPlaybackEngine::setSpeedImpl(double s,std::uint64_t session,std::uint64_t generation,std::uint64_t epoch,std::string* why,progressive::LoopSpeedReceiptCode* code){
    workQueue();using Result=prototype::Phase39RequestResult;using Code=progressive::LoopSpeedReceiptCode;
    const auto micros=progressive::speedMicros(s);auto& x=*impl_;std::lock_guard lock(x.mutex);
    const auto receipt=[&](std::uint64_t id,Result result,Code reasonCode,const char* reason=""){
        if(why)*why=reason;if(code)*code=reasonCode;return prototype::phase59::RequestReceipt{id,result};
    };
    if(!x.pipeline)return receipt(0,Result::Stopped,Code::NoInput,"再生入力がありません");
    const auto* before=x.effectiveTarget();
    if(!before||(epoch&&epoch!=before->currentEpoch())||(session&&session!=before->session)||(generation&&generation!=before->inputGeneration))
        return receipt(0,Result::Stopped,Code::StaleContext,"入力世代・session・renderEpochが一致しません");
    if(x.loop.clearPending)return receipt(0,Result::Stopped,Code::ClearPending,"ループ解除の継続準備待ちです。解除後に最新文脈で再要求してください");
    if(why&&!x.loopLive())return receipt(0,Result::Stopped,Code::NoLoop,"有効なループがありません。通常再生にはsetSpeedを使用してください");
    x.syncLoopSpeeds();
    if(x.loopLive()&&x.state==State::Playing){
        if(x.requested==s&&!x.loop.speedPreparationFailed)return receipt(x.loop.speedRequestID,Result::Duplicate,
            x.loop.speedRequestID?Code::Duplicate:Code::DuplicateInitial,x.loop.speedRequestID?"既存の外部要求です":"初期速度と同値です。対応する外部要求IDはありません");
        if(x.loopKeep&&x.loopInitial&&!x.pipeline->loopReuseEnabled()&&x.seekBusy.load()&&x.activeLoopSpeedRequestID&&x.activeLoopSpeedRequestID!=x.loop.speedRequestID)
            return receipt(0,Result::Busy,Code::Busy,"初回Bの供給版を保持中です。通常ownerの自己反復準備後に最新速度を再要求してください");
        // Admission precedes cancellation, requested, resume intent, or owner changes.
        if(x.loopSpeeds.full(x.options.loopSpeedOperationLimitForTest))return receipt(0,Result::LimitReached,Code::LimitReached,"外部Loop速度要求台帳の上限です（製品最大4096件）。既存要求は保持します");
        progressive::LoopSpeedOperation external;external.id=++x.loopRequestID;external.loopID=x.loop.id;
        external.inputGeneration=before->inputGeneration;external.sourceSession=before->session;external.sourceRenderEpoch=before->currentEpoch();
        external.acceptedCycle=x.loop.cycles;external.speedMicros=micros;external.acceptedNs=machNs();x.loopSpeeds.accept(external);
        x.partialMixTestEvent(ProgressiveControlTestPoint::PartialMixReplaceDecision);
        const bool retainBoundary=!x.pipeline->cancelLoopTransition();
        x.syncLoopSpeeds();
        // Admission is complete. Establish cancellation/adoption before any old
        // ID can become terminal. The required first-B supply is also retained
        // while its job is still preparing (there need not be a handoff yet).
        const bool initialSupply=x.loopKeep&&x.loopInitial&&!x.pipeline->loopReuseEnabled();
        std::uint64_t retained=initialSupply?x.activeLoopSpeedRequestID:0;
        if(x.rendering){auto& h=x.rendering->handoff;auto phase=h.phase.load(std::memory_order_acquire);
            if(phase==SwitchPhase::Requested){
                x.controlTestEvent(ProgressiveControlTestPoint::SpeedReplacementDecision);
                if(!retainBoundary&&!initialSupply&&(!h.scheduledBoundary||h.oldTarget->pipeline->loopReuseEnabled())){
                    if(!h.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel))retained=x.activeLoopSpeedRequestID;
                }else retained=x.activeLoopSpeedRequestID;
            }else if(phase==SwitchPhase::Started||phase==SwitchPhase::Done)retained=x.activeLoopSpeedRequestID;
        }
        x.syncLoopSpeeds();
        x.loopSpeeds.replaceUnstarted(x.loop.id,external.id,external.acceptedNs,retained);
        x.requested=s;x.loop.requestedSpeed=s;x.loop.speedRequestID=external.id;x.loop.speedPreparationFailed=false;if(x.rendering)x.rendering->speedRequestID=external.id;
        x.loop.speedDeferReason.clear();
        if(x.loopKeep&&x.loopInitial&&!x.pipeline->loopReuseEnabled())x.loop.speedDeferReason="KeepPosition初回の自己反復準備待ち";
        x.pendingLoop=true;return receipt(external.id,Result::Accepted,Code::Accepted);
    }
    if(x.state==State::Ready||x.state==State::Paused){
        if(auto* previous=x.stoppedSpeed();previous&&!previous->outputStarted&&previous->speedMicros==micros&&previous->inputGeneration==before->inputGeneration&&previous->loopID==(x.loopLive()?x.loop.id:0)&&(previous->state==StoppedSpeedState::Preparing||previous->state==StoppedSpeedState::ReadyForResume))return receipt(previous->id,Result::Duplicate,Code::Duplicate,"同じ停止位置・準備版の既存要求です");
        if(x.loopLive()&&!x.loop.speedRequestID&&x.requested==s)return receipt(0,Result::Duplicate,Code::DuplicateInitial,"初期速度と同値です。対応する外部要求IDはありません");
        if(x.loopLive()&&x.loopSpeeds.full(x.options.loopSpeedOperationLimitForTest))return receipt(0,Result::LimitReached,Code::LimitReached,"外部Loop速度要求台帳の上限です（製品最大4096件）。既存要求は保持します");
        if(x.stoppedSpeeds.size()>=x.options.stoppedSpeedOperationLimitForTest)return receipt(0,Result::LimitReached,Code::LimitReached,"停止中速度準備台帳の上限です（製品最大4096件）。停止位置と再開意思を保持します");
        StoppedSpeedOperation op;op.id=(std::uint64_t(1)<<63)|(x.stoppedSpeeds.size()+1);op.speedMicros=micros;op.acceptedNs=machNs();
        op.sourceSession=before->session;op.sourceRenderEpoch=before->currentEpoch();op.inputGeneration=before->inputGeneration;
        if(x.loopLive()){
            progressive::LoopSpeedOperation external;external.id=op.id;external.loopID=x.loop.id;external.inputGeneration=op.inputGeneration;
            external.sourceSession=op.sourceSession;external.sourceRenderEpoch=op.sourceRenderEpoch;external.acceptedCycle=x.loop.cycles;external.speedMicros=micros;external.acceptedNs=op.acceptedNs;
            x.loopSpeeds.accept(external);x.loopSpeeds.replaceUnstarted(x.loop.id,op.id,op.acceptedNs);
        }
        if(auto* previous=x.stoppedSpeed();previous&&!previous->outputStarted&&(previous->state==StoppedSpeedState::Preparing||previous->state==StoppedSpeedState::ReadyForResume)){previous->state=StoppedSpeedState::Replaced;previous->reason="未開始の停止中準備を最新要求へ置換";}
        x.requested=s;x.stoppedStartBlocked=false;++x.seekVersion;op.preparationVersion=x.seekVersion.load();
        if(x.loopLive()){
            x.collectLoopBoundary();op.loopID=x.loop.id;op.cycle=x.loop.cycles;
            x.loop.requestedSpeed=s;x.loop.speedRequestID=op.id;x.pendingLoop=false;
            if(x.rendering){x.rendering->speedRequestID=op.id;auto phase=SwitchPhase::Requested;x.rendering->handoff.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel);}
        }
        if(!progressive::terminal(x.stoppedJob.state))x.stoppedJob.state=progressive::SeekState::Replaced;
        if(x.activeSeek<x.seeks.size()&&!progressive::terminal(x.seeks[x.activeSeek].state)&&!x.startedSeek(x.activeSeek)){
            x.pendingSeek=x.activeSeek;x.seeks[x.activeSeek].state=progressive::SeekState::Pending;
        }
        if(x.pendingSeek<x.seeks.size())x.stoppedInput=x.seeks[x.pendingSeek].requestedInputFrame;
        x.captureStopped(op);x.stoppedSpeeds.push_back(op);x.pendingStopped=x.pendingSeek==std::size_t(-1);
        return receipt(op.id,Result::Accepted,Code::Accepted);
    }
    if(x.rendering){auto phase=SwitchPhase::Requested;x.rendering->handoff.phase.compare_exchange_strong(phase,SwitchPhase::Cancelled,std::memory_order_acq_rel);}
    const auto* current=x.effectiveTarget();if(!current||(epoch&&epoch!=current->currentEpoch()))return receipt(0,Result::Stopped,Code::StaleContext,"切替後の再生区間が要求文脈と一致しません");
    auto r=current->pipeline->requestSpeed(micros,current->presented.load(),session,generation);
    if(r.result==Result::Accepted)x.requested=s;
    if(code)*code=r.result==Result::Accepted?Code::Accepted:r.result==Result::Duplicate?Code::Duplicate:r.result==Result::LimitReached?Code::LimitReached:r.result==Result::Busy?Code::Busy:Code::Stopped;
    if(why&&r.result!=Result::Accepted&&r.result!=Result::Duplicate)*why="下位速度要求を受付できません";
    return r;
}
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
    if(x.pipeline)op.inputGeneration=x.pipeline->inputGeneration();if(auto* t=x.effectiveTarget())op.sourceRenderEpoch=t->currentEpoch();
    if(!x.pipeline||(x.state!=State::Ready&&x.state!=State::Playing&&x.state!=State::Paused))op.reason="シークにはReady/Playing/Pausedが必要です";
    else if(frame>x.pipeline->inputFrames())op.reason="シーク位置が曲長を超えています";
    else if(generation&&generation!=op.inputGeneration)op.reason="古い入力世代です";
    else if(epoch&&epoch!=op.sourceRenderEpoch)op.reason="古い再生区間です";
    else if(session&&(!x.effectiveTarget()||session!=x.effectiveTarget()->session))op.reason="古いsessionです";
    else if(mode==progressive::SeekMode::FastLocal&&preroll!=500&&preroll!=1000&&preroll!=2000)op.reason="局所準備区間は500/1000/2000msです";
    else if(mode==progressive::SeekMode::FastLocal&&x.pipeline->sampleRate()!=44100&&x.pipeline->sampleRate()!=48000)op.reason="Interactiveは44.1/48kHzが対象です";
    else if(mode==progressive::SeekMode::FastLocal&&!x.options.allowUnvalidatedFastLocalSeek)op.reason="Interactive Seekは開発用opt-inが必要です";
    const bool accepted=op.reason.empty();
    const bool retainBoundary=accepted&&x.state==State::Playing&&!x.pipeline->cancelLoopTransition();
    if(accepted&&x.loop.clearPending){
        if(auto* transferred=x.loopSpeeds.find(x.loop.speedRequestID);transferred&&transferred->clearContinuation&&!progressive::terminal(transferred->state)){
            transferred->state=progressive::LoopSpeedState::Cancelled;transferred->terminalNs=machNs();transferred->reason="明示seek ID="+std::to_string(op.id)+" がClear継続を置換。以後の速度・位置はそのseek操作で追跡";
        }
        x.pausedClearInput.reset();x.loop.clearPending=false;x.pendingLoop=false;x.loopInitial=false;
    }
    if(accepted&&x.loopLive()){
        if(frame<x.loop.startFrame||frame>=x.loop.endFrameExclusive)op.requestedInputFrame=x.loop.startFrame;
        x.pendingLoop=false;x.loopInitial=false;
    }
    if(accepted&&(x.state==State::Ready||x.state==State::Paused)){
        x.stoppedInput=op.requestedInputFrame;x.pendingStopped=false;
        if(!progressive::terminal(x.stoppedJob.state))x.stoppedJob.state=progressive::SeekState::Replaced;
        if(auto* speed=x.stoppedSpeed();speed&&!speed->outputStarted&&(speed->state==StoppedSpeedState::Preparing||speed->state==StoppedSpeedState::ReadyForResume)){
            speed->state=StoppedSpeedState::Preparing;speed->resumeInputFrame=op.requestedInputFrame;speed->readyNs=0;speed->renderEpoch=0;
        }
    }
    if(accepted){for(std::size_t i=0;i<x.seeks.size();++i)if(!progressive::terminal(x.seeks[i].state)&&!x.startedSeek(i))x.seeks[i].state=progressive::SeekState::Replaced;
        op.state=progressive::SeekState::Pending;op.speedMicros=progressive::speedMicros(x.requested);x.pendingSeek=x.seeks.size();if(!retainBoundary)++x.seekVersion;
        if(auto* speed=x.stoppedSpeed();speed&&speed->state==StoppedSpeedState::Preparing)speed->preparationVersion=x.seekVersion.load();}
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
    if(x.pipeline)op.inputGeneration=x.pipeline->inputGeneration();if(auto* t=x.effectiveTarget())op.sourceRenderEpoch=t->currentEpoch();
    x.seeks.push_back(op);return {op.id,false,error};
}
progressive::SeekSnapshot ProgressiveMacPlaybackEngine::getSeekSnapshot()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);progressive::SeekSnapshot s;
    if(x.seeks.size()>x.seekBase)s.latest=x.seeks.back();
    if(x.activeSeek<x.seeks.size()&&!progressive::terminal(x.seeks[x.activeSeek].state))s.activeId=x.seeks[x.activeSeek].id;
    if(x.pendingSeek<x.seeks.size()&&!progressive::terminal(x.seeks[x.pendingSeek].state))s.pendingId=x.seeks[x.pendingSeek].id;
    return s;
}
std::vector<StoppedSpeedOperation> ProgressiveMacPlaybackEngine::stoppedSpeedHistory()const{auto& x=*impl_;std::lock_guard lock(x.mutex);return x.stoppedSpeeds;}
std::vector<progressive::SeekOperation> ProgressiveMacPlaybackEngine::seekHistory()const{auto& x=*impl_;std::lock_guard lock(x.mutex);return x.seeks;}
std::vector<ProgressiveClosedEpoch> ProgressiveMacPlaybackEngine::closedEpochs()const{auto& x=*impl_;std::lock_guard lock(x.mutex);return x.closed;}
bool ProgressiveMacPlaybackEngine::seekToInputSeconds(double seconds)noexcept{try{return capabilities().seek&&requestSeekToInputSeconds(seconds).accepted;}catch(...){return false;}}
progressive::State ProgressiveMacPlaybackEngine::getPlaybackState()const noexcept{return impl_->state.load();}
ProgressiveStateSnapshot ProgressiveMacPlaybackEngine::getStateSnapshot()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveStateSnapshot s;s.state=x.state;s.reason=x.reason;s.preparation=x.revision;s.requestedSpeed=x.requested;s.error=x.error;
    const auto* t=x.effectiveTarget();const auto d=t?t->pipeline->diagnostics():x.retired;s.session=d.session;s.inputGeneration=d.inputGeneration;s.renderEpoch=t?t->currentEpoch():x.retiredEpoch;auto ops=t?t->pipeline->speedOperations():x.retiredOperations;s.appliedTargetSpeed=x.applied(ops,t);
    if(auto* op=x.stoppedSpeed())s.stoppedSpeed=*op;s.resumePending=x.resumePending;
    for(const auto& op:ops){using O=prototype::phase59::OperationState;if(op.state==O::Pending)s.pending=op;else if(op.state==O::Submitted||op.state==O::Applied)s.active=op;else s.lastResult=op;}return s;}
ProgressivePosition ProgressiveMacPlaybackEngine::getCurrentPlaybackPosition()const{auto& x=*impl_;std::lock_guard lock(x.mutex);const auto* t=x.effectiveTarget();auto sample=t?t->pipeline->positionSample():x.retiredPosition;const auto d=t?t->pipeline->diagnostics():x.retired;ProgressivePosition p;p.session=d.session;p.outputFrame=d.consumed;const auto rate=x.rendering?x.rendering->rate:0;if(rate)p.outputSeconds=p.outputFrame/rate;
    p.inputGeneration=d.inputGeneration;p.renderEpoch=t?t->currentEpoch():x.retiredEpoch;
    if(sample&&sample->session==d.session&&((x.state!=State::Ready&&x.state!=State::Paused)||sample->output==d.consumed)){p.inputFrame=sample->input;p.sampledOutputFrame=sample->output;if(rate)p.inputSeconds=sample->input/rate;}
    if(t&&t->loopEnd.load()&&d.consumed==d.outputStartFrame&&t->loopID.load()==x.loop.id){p.inputFrame=x.loop.startFrame;p.sampledOutputFrame=d.consumed;if(rate)p.inputSeconds=x.loop.startFrame/rate;}
    // Before any consumption, retain the exact requested input coordinate.
    // Integer output rounding/EOF clamping need not have a unique inverse.
    if(d.session&&d.consumed==d.outputStartFrame)for(auto it=x.seeks.rbegin();it!=x.seeks.rend();++it)
        if(it->state==progressive::SeekState::Completed&&it->renderEpoch==p.renderEpoch&&it->session==d.session&&it->inputGeneration==d.inputGeneration){
            p.inputFrame=it->requestedInputFrame;p.sampledOutputFrame=d.consumed;if(rate)p.inputSeconds=it->requestedInputFrame/rate;break;}
    if(t&&(x.state==State::Ready||x.state==State::Paused))if(auto exact=t->pipeline->stoppedPosition()){
        p.inputFrame=exact->input;p.sampledOutputFrame=exact->output;if(rate)p.inputSeconds=exact->input/rate;
    }
    return p;}
ProgressiveDiagnostics ProgressiveMacPlaybackEngine::getPlaybackDiagnostics()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveDiagnostics d;if(x.options.allowExperimentalLoops)d.engineKind="Experimental Progressive Phase62";d.timeStretchLabSha=TIMESTRETCH_PHASE60_SHA;d.preparation=x.revision;const auto* t=x.effectiveTarget();d.pipeline=t?t->pipeline->diagnostics():x.retired;const auto& p=d.pipeline;
    d.session=p.session;d.inputGeneration=p.inputGeneration;d.renderEpoch=t?t->currentEpoch():x.retiredEpoch;d.generatedFrames=p.generated;d.publishedFrames=p.published;d.consumedFrames=p.consumed;d.presentedFrames=x.rendering?x.rendering->presented.load():0;d.currentEpochPresentedFrame=t?t->presented.load():x.retiredPresented;d.missingFrames=p.missingFrames+x.lifetimeMissing;d.underrunCalls=p.missingCalls+x.lifetimeCalls;d.maxConsecutiveMissingFrames=std::max(std::uint64_t(p.maxConsecutiveMissing),x.lifetimeMaxMissing);d.rejectedWrites=p.rejectedWrites+x.lifetimeRejected;
    d.sourceSampleRate=x.rendering?static_cast<unsigned>(x.rendering->rate):0;d.channels=x.rendering?x.rendering->channels:0;d.inputFrames=p.inputFrames;d.residentInputBytes=p.residentInputBytes;d.temporarySourceBytes=p.sourceSnapshotBytes;d.reservationBytes=x.reservation;d.requestedSpeed=x.requested;d.appliedTargetSpeed=x.applied(t?t->pipeline->speedOperations():x.retiredOperations,t);d.processCpuS=x.acceptedAt?processCpu()-x.cpuStart:0;if(!x.pipeline&&p.session)d.dspWorkerCpuS=p.dspWorkerCpuS;d.acceptedToReadyS=x.readyAfter;d.constructorS=x.constructorS;d.fifoSupplyFailed=progressive::SupplyQuality::evaluate(p.missingFrames,p.missingCalls,p.rejectedWrites).failed;d.error=x.error.empty()?p.error:x.error;
    d.workerDeadlineMisses=x.lifetimeWorkerDeadlines+p.scheduling.deadlineMisses;d.workerNewCalls=x.lifetimeWorkerNews+p.realtimeNewCalls;d.workgroupErrors=x.lifetimeWorkgroupErrors+Impl::workerErrors(p);
    d.archivedEpochCount=x.archivedEpochCount;d.archivedPreparedEpochCount=x.archivedPreparedEpochCount;
    const auto add=[&](Pipeline* source){const auto old=source->diagnostics();d.missingFrames+=old.missingFrames;d.underrunCalls+=old.missingCalls;d.rejectedWrites+=old.rejectedWrites;d.maxConsecutiveMissingFrames=std::max(d.maxConsecutiveMissingFrames,old.maxConsecutiveMissing);d.workerDeadlineMisses+=old.scheduling.deadlineMisses;d.workerNewCalls+=old.realtimeNewCalls;d.workgroupErrors+=Impl::workerErrors(old);return old;};
    if(t&&x.pipeline&&t->pipeline!=x.pipeline.get())add(x.pipeline.get());
    if(x.retiringPipeline)d.retiringPipeline=add(x.retiringPipeline);
    const auto& m=p.scheduling;
    d.fifoSupplyFailed=progressive::SupplyQuality::evaluate(d.missingFrames,d.underrunCalls,d.rejectedWrites).failed;
    if(x.closedQualityFailed||d.fifoSupplyFailed||p.failed||m.deadlineMisses||m.policyErrors||m.joinErrors||m.restoreErrors||m.intervalErrors||m.queryErrors||m.waitErrors||m.wakeErrors||(x.rendering&&(x.rendering->overruns||x.rendering->formats)))d.overallAudioQuality=false;
    if(x.rendering&&x.rendering->allocationHooks.enter&&x.rendering->allocationHooks.leave&&x.rendering->allocationHooks.count)d.callbackCppNew=x.rendering->cppAllocations.load();
    rusage r{};getrusage(RUSAGE_SELF,&r);d.peakRssBytes=r.ru_maxrss;mach_task_basic_info_data_t info{};mach_msg_type_number_t count=MACH_TASK_BASIC_INFO_COUNT;if(task_info(mach_task_self(),MACH_TASK_BASIC_INFO,reinterpret_cast<task_info_t>(&info),&count)==KERN_SUCCESS)d.rssBytes=info.resident_size;return d;}
ProgressiveNativeDiagnostics ProgressiveMacPlaybackEngine::getNativeDiagnostics()const{auto& x=*impl_;std::lock_guard lock(x.mutex);ProgressiveNativeDiagnostics d;static_cast<MacDiagnostics&>(d)=x.native;d.error=x.error;if(auto s=x.rendering){d.firstPcmMachNs=s->firstPcm;d.lastPcmTargetEndNs=s->lastTarget;d.callbackCalls=s->calls;d.maxCallbackNs=s->maximum;d.deadlineMisses=s->overruns;d.formatErrors=s->formats;d.callbackRecordsDropped=s->dropped;d.hostMissing=s->hostMissing;d.hostBackwards=s->hostBackwards;d.hostCadenceErrors=s->hostCadence;d.sampleErrors=s->sampleErrors;d.halWindowMisses=s->halMisses;d.invalidSampleTimeCalls=s->invalidSample;d.invalidRateScalarCalls=s->invalidScalar;}return d;}
std::vector<MacCallbackRecord> ProgressiveMacPlaybackEngine::callbackRecords()const{auto& x=*impl_;std::lock_guard lock(x.mutex);auto s=x.rendering;if(!s)return {};if(s->active||s->inRender||x.state==State::Draining)throw std::logic_error("callback静止後だけ履歴を取得できます");return {s->records.begin(),s->records.begin()+std::min<std::size_t>(s->records.size(),s->recordsCount.load())};}
std::vector<ProgressiveCallbackRecord> ProgressiveMacPlaybackEngine::loopClockAnomalyRecords()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);auto s=x.rendering;if(!s)return {};
    if(s->active||s->inRender||x.state==State::Draining)throw std::logic_error("callback静止後だけ異常前後履歴を取得できます");
    return {s->clockAnomalyRecords.begin(),s->clockAnomalyRecords.begin()+s->anomalyCount};
}
std::vector<ProgressiveCallbackRecord> ProgressiveMacPlaybackEngine::loopCallbackRecords()const{
    auto& x=*impl_;std::lock_guard lock(x.mutex);auto s=x.rendering;if(!s)return {};
    if(s->active||s->inRender||x.state==State::Draining)throw std::logic_error("callback静止後だけ全span履歴を取得できます");
    std::vector<ProgressiveCallbackRecord> result;const auto count=std::min<std::uint64_t>(s->loopRecordCount,s->loopRecords.size());result.reserve(count);
    for(auto i=s->loopRecordCount-count;i<s->loopRecordCount;++i)result.push_back(s->loopRecords[i%s->loopRecords.size()]);return result;
}
std::vector<Operation> ProgressiveMacPlaybackEngine::operationHistory()const{auto& x=*impl_;std::lock_guard lock(x.mutex);const auto* t=x.effectiveTarget();return t?t->pipeline->speedOperations():x.retiredOperations;}
TimeMap ProgressiveMacPlaybackEngine::finalTimeMap()const{auto& x=*impl_;std::lock_guard lock(x.mutex);if(x.pipeline||x.retiredMap.empty())throw std::logic_error("静止した確定Mapが必要です");return x.retiredMap;}
void ProgressiveMacPlaybackEngine::simulateDeviceChangeForTest(){workQueue();auto& x=*impl_;std::lock_guard lock(x.mutex);x.force=true;if(x.rendering)x.rendering->forcedRoute=true;}
}
