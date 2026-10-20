// The product render function, real FIFO/pipeline, and a normal-thread gate.
#ifdef PHASE62_FIX_BASELINE_SOURCE
#include PHASE62_FIX_BASELINE_SOURCE
#else
#include "../src/platform/macos/ProgressiveMacPlaybackEngine.mm"
#endif
#include <iostream>
using namespace ts::playback;
static void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
struct Fixture {
    std::unique_ptr<Pipeline> base,old,fresh;
    RenderTarget first,second;RenderState state;
    std::array<std::array<float,4096>,2> pcm{};
    struct Buffers {UInt32 count;AudioBuffer buffer[2];} buffers{};
    AudioTimeStamp stamp{};BOOL silent=NO;
    explicit Fixture(const char* path){
        ts::prototype::phase58::Configuration c;c.speedMicros=1000000;c.residentInput=true;c.verifyPcm=false;
        base=std::make_unique<Pipeline>(path,c);base->start();check(base->waitUntilReady(std::chrono::seconds(30)),"base Ready");
        wait([&]{return base->finalAnalysisAvailable();});state.rate=base->sampleRate();state.channels=unsigned(base->channels());state.active=true;
        state.target=&first;first.epoch=11;second.epoch=12;buffers.count=state.channels;
        for(unsigned ch=0;ch<state.channels;++ch)buffers.buffer[ch]={1,4096*sizeof(float),pcm[ch].data()};
        stamp.mFlags=kAudioTimeStampSampleTimeValid;
#ifndef PHASE62_FIX_BASELINE_SOURCE
        state.loopRecords.resize(256);
#endif
    }
    ~Fixture(){state.active=false;if(old)old->stop();if(fresh)fresh->stop();if(base)base->stop();}
    template<class Predicate> static void wait(Predicate predicate){const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(!predicate()){check(std::chrono::steady_clock::now()<until,"gate/PCM timeout");std::this_thread::sleep_for(std::chrono::microseconds(100));}}
    void setup(std::size_t b,bool clear=false,std::size_t oldLimit=0,std::size_t newLimit=0,bool reusable=false){
        old=base->createLoopSeek(0,b,1000000);fresh=clear?base->createSeek(b,1000000):base->createLoopSeek(0,b,1000000);
#ifndef PHASE62_FIX_BASELINE_SOURCE
        if(reusable)old->enableLoopReuse(0);
#endif
        if(oldLimit)old->setPublicationLimitForTest(oldLimit);if(newLimit)fresh->setPublicationLimitForTest(newLimit);
        old->start();fresh->start();wait([&]{return old->available()&&fresh->available()&&old->loopOutputEndFrame();});
        first.pipeline=old.get();second.pipeline=fresh.get();first.presented=old->outputStartFrame();second.presented=fresh->outputStartFrame();first.loopEnd=old->loopOutputEndFrame();second.loopEnd=clear?0:fresh->loopOutputEndFrame();
        base->stop();
    }
    void renderFrames(unsigned n){for(unsigned ch=0;ch<state.channels;++ch)buffers.buffer[ch].mDataByteSize=n*sizeof(float);render(&state,&silent,&stamp,n,reinterpret_cast<AudioBufferList*>(&buffers));stamp.mSampleTime+=n;}
    void advanceTo(std::size_t position){while(first.presented<position){const auto n=std::min<std::size_t>(512,position-first.presented.load());wait([&]{return old->available()>=n;});renderFrames(unsigned(n));check(!state.loopMissed,"unexpected miss before injection");}}
    void arm(bool clear=false){auto& h=state.handoff;h.oldTarget=&first;h.newTarget=&second;h.scheduledBoundary=true;h.loopCycle=!clear;h.loopID=7;h.boundaryEnd=first.loopEnd;h.output.prepare(unsigned(state.rate));h.phase=SwitchPhase::Requested;}
};
struct Gate {std::atomic<bool> entered{false},release{false};static void observed(void* p){auto& g=*static_cast<Gate*>(p);g.entered=true;Fixture::wait([&]{return g.release.load();});}};
#ifndef PHASE62_FIX_BASELINE_SOURCE
static void cancellationTransactions(){
    using D=ts::prototype::phase58::LoopTransitionState;
    RenderSwitch h;h.awaitDynamic=true;h.phase=SwitchPhase::Requested;std::atomic<D> dsp{D::Applying};unsigned attempts=0;
    const auto cancel=[&]{++attempts;auto expected=D::Requested;return dsp.compare_exchange_strong(expected,D::Cancelled);};
    check(!cancelPreparedSwitch(h,true,cancel)&&h.phase==SwitchPhase::Requested,"Applying route released before DSP result");
    dsp=D::Requested; // A failed safe-frontier validation returns to Requested.
    check(cancelPreparedSwitch(h,true,cancel)&&dsp==D::Cancelled&&h.phase==SwitchPhase::Cancelled&&attempts==2,"retry transaction not cancelled before route closure");
    auto expected=D::Requested;check(!dsp.compare_exchange_strong(expected,D::Applying),"cancelled old request committed late");
    h.phase=SwitchPhase::Requested;dsp=D::Committed;check(!cancelPreparedSwitch(h,true,cancel)&&h.phase==SwitchPhase::Requested,"committed replacement was released");
    const auto calls=attempts;check(cancelPreparedSwitch(h,false,cancel)&&attempts==calls,"quiescent Stop waited for an irreversible audio route");
    h.phase=SwitchPhase::Started;check(!cancelStoppedSwitch(h,true,true),"active callback reference cancelled");
    check(!cancelStoppedSwitch(h,false,false),"valid partial output cancelled without Stop");
    check(cancelStoppedSwitch(h,false,true)&&h.phase==SwitchPhase::Cancelled,"quiescent Started Stop still waits for callback");
    h.phase=SwitchPhase::Done;check(!cancelStoppedSwitch(h,false,true)&&h.phase==SwitchPhase::Done,"completed output rolled back by Stop");
    RenderState s;RenderTarget old,next;s.target=&next;s.active=true;
    check(!detachStoppedPreparation(s,&next,&old)&&s.target==&next,"active preparation detached");
    s.active=false;s.inRender=1;check(!detachStoppedPreparation(s,&next,&old),"referenced preparation detached");
    s.inRender=0;check(detachStoppedPreparation(s,&next,&old)&&s.target==&old&&!s.active,"stopped preparation left dangling render target");
    std::cout<<"PASS DSP retry cancellation ordering and quiescent Started Stop\n";
}
static void stoppedPartial(const char* path,unsigned partial,bool periodic){
    Fixture f(path);f.setup(std::size_t(f.state.rate)/10,false,0,0,periodic);const auto fade=std::size_t(f.state.rate)/200;
    f.advanceTo(f.first.loopEnd-fade-(512-partial));Fixture::wait([&]{return f.old->available()>=512&&f.fresh->available()>=fade;});
    f.arm();f.state.handoff.periodic=periodic;f.renderFrames(512);
    check(f.state.handoff.phase==SwitchPhase::Started&&f.state.handoff.output.cursor==partial,"real partial switch not reached");
    f.state.active=false;check(!f.state.inRender&&cancelStoppedSwitch(f.state.handoff,false,true),"quiescent partial switch did not cancel");
    check(detachStoppedPreparation(f.state,&f.second,&f.first)==!periodic&&f.state.target==&f.first,"partial Stop did not release preparation target");
    const auto frames=f.state.callbackFrame;const auto oldConsumed=f.old->diagnostics().consumed,newConsumed=f.fresh->diagnostics().consumed;
    f.renderFrames(64);check(f.state.callbackFrame==frames&&f.old->diagnostics().consumed==oldConsumed&&f.fresh->diagnostics().consumed==newConsumed&&!f.state.loopCycles,"stopped partial switch consumed or fabricated cycle");
    f.old->stop();f.fresh->stop();check(f.old->diagnostics().finalDataAvailable&&f.fresh->diagnostics().finalDataAvailable,"partial Stop released unjoined owner");
    std::cout<<"PASS stopped real partial="<<partial<<" periodic="<<periodic<<" without callback gate\n";
}
#endif
static void pauseRace(const char* path,unsigned partial){
    Fixture f(path);f.setup(std::size_t(f.state.rate)/10);const auto fade=std::size_t(f.state.rate)/200;
    f.advanceTo(f.first.loopEnd-fade-(512-partial));Fixture::wait([&]{return f.old->available()>=512&&f.fresh->available()>=fade;});f.arm();Gate gate;std::exception_ptr error;
    std::thread control([&]{try{
#ifdef PHASE62_FIX_BASELINE_SOURCE
        // Exact former pause ordering; only its observation is gated.
        auto phase=f.state.handoff.phase.load();check(phase==SwitchPhase::Requested,"baseline observation");Gate::observed(&gate);
        f.state.active=false;while(f.state.inRender.load())std::this_thread::yield();
#else
        pauseRender(&f.state,Gate::observed,&gate);
#endif
    }catch(...){error=std::current_exception();}});
    Fixture::wait([&]{return gate.entered.load();});f.renderFrames(512);const bool partialExpected=f.state.handoff.phase==SwitchPhase::Started&&f.state.handoff.output.cursor==partial;std::cerr<<"partial="<<partial<<" actual="<<f.state.handoff.output.cursor<<" phase="<<int(f.state.handoff.phase.load())<<" missed="<<f.state.loopMissed.load()<<std::endl;gate.release=true;
#ifdef PHASE62_FIX_BASELINE_SOURCE
    control.join();if(error)std::rethrow_exception(error);check(partialExpected,"partial mix not reproduced");check(!f.state.active&&f.state.handoff.phase==SwitchPhase::Started,"baseline pause race missing");std::cout<<"REPRODUCED pause partial="<<partial<<" inactive Started\n";
#else
    Fixture::wait([&]{return f.state.pauseRequested.load();});f.renderFrames(512);control.join();if(error)std::rethrow_exception(error);check(partialExpected,"partial mix not reproduced");
    check(f.state.pauseAcknowledged&&!f.state.active&&f.state.handoff.phase==SwitchPhase::Done,"pause did not finish mix");
    check(f.state.loopCycles==1&&!f.state.loopMissed&&!f.state.loopSafetyFrames,"pause became failure");
    const auto clock=f.state.callbackFrame;f.renderFrames(64);check(f.state.callbackFrame==clock&&f.state.loopCycles==1,"paused progress");
    f.state.handoff.phase=SwitchPhase::Idle;f.state.pauseRequested=false;f.state.pauseAcknowledged=false;f.state.active=true;f.renderFrames(64);check(!f.state.loopMissed,"resume failed");
    std::cout<<"PASS pause partial="<<partial<<" completed then quiescent/resume\n";
#endif
}
static void shortage(const char* path,bool clear,bool oldShort,bool newShort,bool onlyZeroWeight=false){
    Fixture f(path);const auto rate=std::size_t(f.state.rate),b=rate,fade=rate/200;const auto end=f.base->fixedOutputFrameForInput(b);
    const auto oldLimit=oldShort?end-fade+(onlyZeroWeight?fade-1:100):0;
    const auto newStart=clear?end:0;const auto newLimit=newShort?newStart+100:0;
    f.setup(b,clear,oldLimit,newLimit);f.advanceTo(end-fade);f.arm(clear);f.renderFrames(512);
#ifdef PHASE62_FIX_BASELINE_SOURCE
    if(clear)check(!f.state.loopMissed,"baseline Clear miss unexpectedly detected");
    else check(f.state.loopMissed,"baseline auto miss not reproduced");
    check(f.state.loopSafetyFrames==(clear?0:512-fade),"baseline padding omission not reproduced");std::cout<<"REPRODUCED clear="<<clear<<" old="<<oldShort<<" new="<<newShort<<" paddingReported="<<f.state.loopSafetyFrames<<" expected412\n";
#else
    const auto oldMissing=oldShort?(onlyZeroWeight?1:fade-100):0;const auto newMissing=newShort?fade-100:0;
    const auto affected=onlyZeroWeight?0:newShort?fade-100:oldShort?fade-101:0;
    check(f.state.oldMissing==oldMissing&&f.state.newMissing==newMissing,"input missing accounting");check(f.state.outputAffected==affected,"weighted union accounting");
    check(f.state.loopSafetyFrames==(affected?412:0),"failure padding accounting");check(f.state.loopCycles==(clear||affected?0:1),"unsuccessful cycle counted");check(f.state.loopMissed==bool(affected),"Clear/loop failure classification");
    const auto& record=f.state.loopRecords[(f.state.loopRecordCount-1)%f.state.loopRecords.size()];check(record.failurePaddingFrames==f.state.loopSafetyFrames&&record.outputAffectedFrames==affected,"span/callback totals");
    std::cout<<"PASS shortage clear="<<clear<<" old="<<oldShort<<" new="<<newShort<<" affected="<<affected<<" padding="<<f.state.loopSafetyFrames<<'\n';
#endif
}
static void singleShort(const char* path){
    Fixture f(path);const auto rate=std::size_t(f.state.rate);f.setup(rate*2,false,100,0);Fixture::wait([&]{return f.old->available()==100;});f.renderFrames(512);
    check(f.state.loopMissed,"512/100 miss not detected");
#ifdef PHASE62_FIX_BASELINE_SOURCE
    check(f.state.loopSafetyFrames==0,"baseline 412 omission missing");std::cout<<"REPRODUCED requested512 received100 padding412 reported0\n";
#else
    check(f.state.loopSafetyFrames==412&&f.state.newMissing==412&&f.state.outputAffected==412,"512/100/412 accounting");std::cout<<"PASS requested512 received100 padding412\n";
#endif
}
#ifndef PHASE62_FIX_BASELINE_SOURCE
static void lateClear(const char* path){
    Fixture f(path);const auto rate=std::size_t(f.state.rate),b=rate/10,fade=rate/200;
    f.setup(b,true,0,0,true);Fixture::wait([&]{return f.old->available()>=b*2;});
    f.advanceTo(b-20);f.arm(true);f.state.handoff.notBeforeCycle=f.old->loopReadCycle()+1;
    f.renderFrames(64);
    check(f.state.handoff.phase==SwitchPhase::Requested&&f.state.target==&f.first,"late Clear started inside committed tail");
    check(f.state.loopCycles==1&&!f.state.loopMissed&&!f.state.loopSafetyFrames,"valid self-repeat lost while Clear pending");
    f.advanceTo(b-fade);Fixture::wait([&]{return f.fresh->available()>=512;});f.renderFrames(512);
    check(f.state.handoff.phase==SwitchPhase::Done&&f.state.target==&f.second,"Clear did not connect at next safe B");
    check(f.state.loopCycles==1&&!f.state.loopMissed&&!f.state.loopSafetyFrames,"Clear connection counted or supply failed");
    std::cout<<"PASS late Clear retains repetition, waits one committed tail, connects without extra cycle\n";
}
#endif
int main(int argc,char** argv){try{check(argc==2,"input");
#ifndef PHASE62_FIX_BASELINE_SOURCE
    cancellationTransactions();for(bool periodic:{false,true})for(unsigned partial:{1u,64u})stoppedPartial(argv[1],partial,periodic);
#endif
    pauseRace(argv[1],1);pauseRace(argv[1],64);singleShort(argv[1]);
    for(bool clear:{false,true})for(auto kind:{1,2,3})shortage(argv[1],clear,kind&1,kind&2);
#ifndef PHASE62_FIX_BASELINE_SOURCE
    shortage(argv[1],false,true,false,true);
    lateClear(argv[1]);
#endif
    std::cout<<"PASS deterministic safety suite\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
