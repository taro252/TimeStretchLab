// Exercise the SAME callback implementation without HAL; no model replacement.
#include "../src/platform/macos/ProgressiveMacPlaybackEngine.mm"
#include "Phase62PcmAudit.h"
#include <iostream>
using namespace ts::playback;
static void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
static int longRender(const char* input){
    ts::prototype::phase58::Configuration config;config.speedMicros=2000000;config.residentInput=true;config.verifyPcm=false;
    auto base=std::make_unique<Pipeline>(input,config);base->start();check(base->waitUntilReady(std::chrono::seconds(30)),"long base Ready");while(!base->finalAnalysisAvailable())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    const auto b=base->sampleRate()/2;auto current=base->createLoopSeek(0,b,2000000);current->start();check(current->waitUntilReady(std::chrono::seconds(30)),"long Ready");base->stop();base.reset();
    RenderState state;state.channels=static_cast<unsigned>(current->channels());state.rate=current->sampleRate();state.active=true;LoopPcmAudit audit(state.channels);state.observerContext=&audit;state.epochObserver=LoopPcmAudit::source;state.outputObserver=LoopPcmAudit::output;
    std::uint64_t epoch=1;auto target=std::make_unique<RenderTarget>();target->pipeline=current.get();target->epoch=epoch;target->presented=current->outputStartFrame();target->loopEnd=current->loopOutputEndFrame();state.target=target.get();
    std::array<std::array<float,4096>,2> pcm{};struct Buffers {UInt32 count;AudioBuffer buffers[2];} buffers{};buffers.count=state.channels;for(unsigned ch=0;ch<state.channels;++ch)buffers.buffers[ch]={1,4096*sizeof(float),pcm[ch].data()};
    AudioTimeStamp stamp{};stamp.mFlags=kAudioTimeStampSampleTimeValid;BOOL silent=NO;
    for(std::uint64_t cycle=1;cycle<=4100;++cycle){
        auto next=current->createLoopSeek(0,b,2000000);next->start();check(next->waitUntilReady(std::chrono::seconds(30)),"long next Ready");auto nextTarget=std::make_unique<RenderTarget>();nextTarget->pipeline=next.get();nextTarget->epoch=++epoch;nextTarget->presented=next->outputStartFrame();nextTarget->loopEnd=next->loopOutputEndFrame();
        auto& h=state.handoff;h.oldTarget=target.get();h.newTarget=nextTarget.get();h.loopCycle=h.scheduledBoundary=true;h.loopID=73;h.inputA=0;h.inputB=b;h.boundaryEnd=target->loopEnd;h.output.prepare(current->sampleRate());h.phase=SwitchPhase::Requested;
        while(h.phase.load()!=SwitchPhase::Done){check(current->available()>=std::min<std::uint64_t>(4096,target->loopEnd.load()-target->presented.load()),"long supply");render(&state,&silent,&stamp,4096,reinterpret_cast<AudioBufferList*>(&buffers));stamp.mSampleTime+=4096;check(!state.loopMissed,"long missed");}
        check(state.loopCycles==cycle&&target->presented==target->loopEnd,"long counter/B");const auto event=state.loopBoundary.read();check(event&&event->cycle==cycle,"long event");
        h.phase=SwitchPhase::Idle;current->stop();check(current->diagnostics().finalDataAvailable&&!current->diagnostics().missingFrames,"long retirement");current=std::move(next);target=std::move(nextTarget);
        if(cycle%100==0)std::cout<<"cycle="<<cycle<<'\n'<<std::flush;
    }
    current->stop();check(!audit.errors&&!audit.nonfinite,"long RAW/mix/order");check(current->diagnostics().sourceHashPasses==1&&current->diagnostics().residentLockCalls==1,"long input reuse");std::cout<<"PASS 4100 actual-callback boundaries (offline fast drive; NOT realtime deadlines)\n";return 0;
}
#include "Phase62OfflineCapture.h"
int main(int argc,char** argv){try{
    if(argc==3&&std::string(argv[2])=="--long")return longRender(argv[1]);
    if(argc!=2)return captureLoopPcm(argc,argv);
    check(argc==2,"input");ts::prototype::phase58::Configuration c;c.speedMicros=1000000;c.residentInput=true;c.verifyPcm=false;
    Pipeline base(argv[1],c);base.start();check(base.waitUntilReady(std::chrono::seconds(30)),"base Ready");
    while(!base.finalAnalysisAvailable())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    std::size_t cases=0;
    for(auto speed:{400000u,1000000u,2000000u})for(auto n:{64u,128u,512u,4096u})for(bool armed:{true,false}){
        const auto a=std::size_t(17),b=a+base.sampleRate()/2+37;
        auto old=base.createLoopSeek(a,b,speed);old->start();check(old->waitUntilReady(std::chrono::seconds(30)),"old Ready");
        auto fresh=base.createLoopSeek(a,b,speed);fresh->start();check(fresh->waitUntilReady(std::chrono::seconds(30)),"new Ready");
        RenderTarget first,second;first.pipeline=old.get();second.pipeline=fresh.get();first.epoch=11;second.epoch=12;
        first.presented=old->outputStartFrame();second.presented=fresh->outputStartFrame();first.loopEnd=old->loopOutputEndFrame();second.loopEnd=fresh->loopOutputEndFrame();
        RenderState state;state.channels=unsigned(base.channels());state.rate=base.sampleRate();state.target=&first;state.active=true;state.loopCycles=4095;
        LoopPcmAudit audit(base.channels());state.observerContext=&audit;state.epochObserver=LoopPcmAudit::source;state.outputObserver=LoopPcmAudit::output;
        auto& h=state.handoff;h.oldTarget=&first;h.newTarget=&second;h.loopCycle=true;h.scheduledBoundary=true;h.loopID=73;h.inputA=a;h.inputB=b;h.boundaryEnd=first.loopEnd;h.output.prepare(base.sampleRate());
        if(armed)h.phase=SwitchPhase::Requested;
        std::array<std::array<float,4096>,2> pcm{};
        struct Buffers {UInt32 count;AudioBuffer buffers[2];} buffers{};buffers.count=state.channels;
        for(unsigned ch=0;ch<state.channels;++ch)buffers.buffers[ch]={1,UInt32(n*sizeof(float)),pcm[ch].data()};
        AudioTimeStamp stamp{};stamp.mFlags=kAudioTimeStampSampleTimeValid|kAudioTimeStampHostTimeValid;BOOL silent=NO;std::uint64_t expectedHalBoundary=0;
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);
        while(h.phase.load()!=SwitchPhase::Done&&!state.loopMissed.load()){
            const auto remaining=first.loopEnd.load()-first.presented.load();const auto want=std::min<std::size_t>(n,remaining);
            if(old->available()<want){check(std::chrono::steady_clock::now()<deadline,"supply timeout");std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
            stamp.mHostTime=mach_absolute_time();const auto origin=state.callbackFrame;
            render(&state,&silent,&stamp,n,reinterpret_cast<AudioBufferList*>(&buffers));stamp.mSampleTime+=n;
            if(h.phase.load()==SwitchPhase::Done)expectedHalBoundary=stamp.mHostTime+static_cast<std::uint64_t>((state.loopBoundary.read()->callbackFrame-origin)*1e9/state.rate);
        }
        if(armed){check(!state.loopMissed&&state.loopCycles==4096,"boundary completion");check(first.presented==first.loopEnd,"old input after B or lost tail");
            check(second.presented>=second.pipeline->outputStartFrame()+h.output.length,"A head missing");
            const auto event=state.loopBoundary.read();check(event&&event->cycle==4096&&event->oldOutputEnd==first.loopEnd&&event->overlapFrames==base.sampleRate()/200,"event");check(event->halBoundaryEstimateNs==expectedHalBoundary,"HAL boundary offset");
            check(!audit.errors&&!audit.nonfinite,"raw/mix/order audit");
        }else{check(state.loopMissed&&state.loopCycles==4095&&state.loopSafetyFrames>0,"explicit miss");check(first.presented==first.loopEnd-base.sampleRate()/200,"late old output");}
        old->stop();fresh->stop();check(!old->diagnostics().missingFrames&&!fresh->diagnostics().missingFrames,"FIFO underflow");++cases;
    }
    base.stop();std::cout<<"PASS actual callback: "<<cases<<" split/mix/deadline cases, 64/128/512/4096 frames, counter crosses 4096\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
