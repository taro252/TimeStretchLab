#define main pausedIncludedMain
#include "PausedSpeedNativeTests.cpp"
#undef main

// All gates run on the normal worker; the callback only updates atomic counters.
struct LoopOutputCount {
    std::atomic<std::uint64_t> frames{0},affected{0},padding{0};
    static void output(void* pointer,const float*const*,const ProgressiveOutputSpan& span)noexcept{
        auto& count=*static_cast<LoopOutputCount*>(pointer);count.frames.fetch_add(span.frames,std::memory_order_relaxed);
        count.affected.fetch_add(span.outputAffectedFrames,std::memory_order_relaxed);count.padding.fetch_add(span.failurePaddingFrames,std::memory_order_relaxed);
    }
};
struct FrozenLoop {
    ProgressivePosition position;ProgressiveDiagnostics diagnostics;progressive::LoopSnapshot loop;
    std::uint64_t output=0;std::size_t seeks=0;
};
struct LoopFixture {
    const std::filesystem::path input;WavStreamReader wav;Gate gate;LoopOutputCount count;ProgressiveOptions options;
    std::unique_ptr<ProgressiveMacPlaybackEngine> engine;
    explicit LoopFixture(const std::filesystem::path& path,Preset preset):input(path),wav(path),engine(std::make_unique<ProgressiveMacPlaybackEngine>()){
        options.initialSpeed=1;options.allowExperimentalLoops=true;options.preset=preset;options.controlTestHooks={&gate,Gate::event};
        options.observerContext=&count;options.observeOutputPcm=LoopOutputCount::output;
        engine->prepare(input,options);state(*engine,State::Ready);const auto current=engine->getStateSnapshot();
        auto receipt=engine->requestLoopRange(0,wav.frames(),{current.inputGeneration,current.session,current.renderEpoch});check(receipt.accepted,receipt.reason);
        wait([&]{auto loop=engine->getLoopSnapshot();check(loop.state!=progressive::LoopState::Failed,loop.reason);return loop.initialPositionComplete&&loop.state==progressive::LoopState::Active;});
        check(engine->play(),"loop initial play");state(*engine,State::Playing);wait([&]{return count.frames.load()>=2048;});check(engine->pause(),"loop initial pause");
        check(engine->getCurrentPlaybackPosition().inputFrame.has_value(),"loop pause did not capture input");
    }
    ~LoopFixture(){gate.release=true;if(engine)engine->stop();}
    FrozenLoop freeze(){return {engine->getCurrentPlaybackPosition(),engine->getPlaybackDiagnostics(),engine->getLoopSnapshot(),count.frames.load(),engine->seekHistory().size()};}
    void arm(){gate.entered=false;gate.release=false;gate.armed=true;}
    void entered(){wait([&]{return gate.entered.load();});}
    void hold(const FrozenLoop& before){
        const auto current=engine->getStateSnapshot();const auto position=engine->getCurrentPlaybackPosition();const auto loop=engine->getLoopSnapshot();const auto diagnostics=engine->getPlaybackDiagnostics();
        check(current.state==State::Paused&&!current.resumePending,"paused loop auto-resumed");
        check(position.inputFrame==before.position.inputFrame&&loop.id==before.loop.id&&loop.enabled&&loop.startFrame==before.loop.startFrame&&loop.endFrameExclusive==before.loop.endFrameExclusive&&loop.cycles==before.loop.cycles,"paused input/loop/cycle drift");
        check(count.frames.load()==before.output&&engine->seekHistory().size()==before.seeks,"preparation emitted audio or fabricated seek");
        if(diagnostics.renderEpoch==before.diagnostics.renderEpoch)check(diagnostics.consumedFrames==before.diagnostics.consumedFrames,"old FIFO consumed during preparation");
        else check(diagnostics.consumedFrames==diagnostics.pipeline.outputStartFrame&&diagnostics.currentEpochPresentedFrame==diagnostics.pipeline.outputStartFrame,"new epoch consumed before Resume");
        check(!count.affected&&!count.padding&&!diagnostics.missingFrames&&!diagnostics.underrunCalls,"paused replacement counted as missing/padding/underrun");
    }
    StoppedSpeedOperation prepared(std::uint64_t id,const FrozenLoop& before){
        const auto operation=ready(*engine,id);hold(before);const auto diagnostics=engine->getPlaybackDiagnostics();
        check(operation.loopID==before.loop.id&&operation.cycle==before.loop.cycles&&operation.inputGeneration==before.position.inputGeneration&&operation.resumeInputFrame==*before.position.inputFrame&&operation.positionCaptured,"Ready identity differs from paused loop");
        check(operation.preparationVersion&&operation.readyNs>=operation.acceptedNs&&!operation.outputStarted&&!diagnostics.retiringPipeline,"Ready published before retirement or audio already started");
        check(operation.mode==progressive::SeekMode::Exact,"paused new speed did not use Exact");
        bool found=false;for(const auto& old:engine->closedEpochs())if(old.pipeline.session==operation.sourceSession){
            check(old.pipeline.finalDataAvailable,"old producer not joined before Ready");check(old.pipeline.published>=old.pipeline.consumed,"old FIFO audit coordinates");
            // This fixture starts A=0 on the same initial owner. Its output
            // counter is cumulative; the legacy consumed field wraps at B.
            check(old.pipeline.outputStartFrame==0&&old.pipeline.session==before.diagnostics.session&&old.pipeline.published>=before.output,"fixture cumulative FIFO coordinate");
            check(operation.discardedForStoppedSpeedFrames==old.pipeline.published-before.output,"stopped-speed discard audit differs from retired FIFO");found=true;
        }
        check(found&&operation.discardedForStoppedSpeedFrames>0,"missing dedicated stopped-speed FIFO discard audit");return operation;
    }
};
static void passed(const char* name,std::size_t& executed){++executed;std::cout<<"{\"case\":\""<<name<<"\",\"status\":\"PASS\"}"<<std::endl;}
static void preparedWithoutResume(const std::filesystem::path& input,Preset preset,std::size_t& executed){
    LoopFixture fixture(input,preset);const auto before=fixture.freeze();const auto operation=fixture.prepared(request(*fixture.engine,1.25),before);
    std::this_thread::sleep_for(std::chrono::milliseconds(100));fixture.hold(before);
    const auto snapshot=fixture.engine->getStateSnapshot();check(snapshot.stoppedSpeed&&snapshot.stoppedSpeed->id==operation.id,"Ready lost during paused idle");
    std::cout<<"{\"case\":\"ready_identity\",\"id\":"<<operation.id<<",\"loop_id\":"<<operation.loopID<<",\"cycle\":"<<operation.cycle<<",\"input_C\":"<<operation.resumeInputFrame<<",\"map_version\":"<<operation.mapVersion<<",\"preparation_version\":"<<operation.preparationVersion<<",\"discarded_for_stopped_speed_frames\":"<<operation.discardedForStoppedSpeedFrames<<",\"resume_calls\":0}"<<std::endl;
    passed("ready_without_resume_identity_discard",executed);
}
static void preparedAfterCycles(const std::filesystem::path& input,Preset preset,std::size_t& executed){
    LoopFixture fixture(input,preset);check(fixture.engine->resume(),"multi-cycle Resume");
    wait([&]{const auto loop=fixture.engine->getLoopSnapshot();const auto position=fixture.engine->getCurrentPlaybackPosition();
        check(fixture.engine->getPlaybackState()!=State::Failed,"multi-cycle playback failed");return loop.cycles>=2&&position.inputFrame&&*position.inputFrame>fixture.wav.sampleRate()/50;});
    check(fixture.engine->pause(),"multi-cycle Pause");const auto before=fixture.freeze();
    check(before.loop.cycles>=2&&before.output>2*fixture.wav.frames()&&before.diagnostics.publishedFrames>before.diagnostics.consumedFrames+fixture.wav.frames(),"fixture did not separate local and cumulative positions");
    const auto operation=fixture.prepared(request(*fixture.engine,.75),before);
    check(operation.cycle==before.loop.cycles&&operation.consumedOutputFrame==before.position.outputFrame,"multi-cycle stopped coordinate/identity");
    std::this_thread::sleep_for(std::chrono::milliseconds(100));fixture.hold(before);
    passed("ready_after_cycles_cumulative_fifo_audit",executed);
}
static void latestAndDuplicates(const std::filesystem::path& input,Preset preset,std::size_t& executed){
    LoopFixture fixture(input,preset);const auto before=fixture.freeze();fixture.arm();const auto first=request(*fixture.engine,.75);fixture.entered();
    const auto size=fixture.engine->stoppedSpeedHistory().size();const auto duplicate=fixture.engine->setSpeed(.75);
    check(duplicate.result==Phase39RequestResult::Duplicate&&duplicate.id==first&&fixture.engine->stoppedSpeedHistory().size()==size,"Preparing duplicate created another version");fixture.hold(before);
    const auto latest=request(*fixture.engine,1.0);check(latest!=first,"100->75->100 incorrectly duplicated old applied 100");
    const auto history=fixture.engine->stoppedSpeedHistory();check(history[history.size()-2].id==first&&history[history.size()-2].state==StoppedSpeedState::Replaced,"superseded 75 not Replaced");
    fixture.gate.release=true;const auto operation=fixture.prepared(latest,before);check(operation.speedMicros==1000000,"latest 100 lost");
    const auto completedSize=fixture.engine->stoppedSpeedHistory().size();const auto same=fixture.engine->setSpeed(1.0);
    check(same.result==Phase39RequestResult::Duplicate&&same.id==latest&&fixture.engine->stoppedSpeedHistory().size()==completedSize,"Ready duplicate rebuilt epoch");
    std::this_thread::sleep_for(std::chrono::milliseconds(100));fixture.hold(before);passed("latest_100_75_100_preparing_ready_duplicate",executed);
}
static void deferredResume(const std::filesystem::path& input,Preset preset,bool cancel,std::size_t& executed){
    LoopFixture fixture(input,preset);const auto before=fixture.freeze();fixture.arm();request(*fixture.engine,.75);fixture.entered();
    check((cancel?fixture.engine->play():fixture.engine->resume())&&fixture.engine->getStateSnapshot().resumePending&&fixture.engine->getPlaybackState()==State::Paused,"Preparing Play/Resume was not saved as intent");
    const auto latest=request(*fixture.engine,1.25);if(cancel)check(fixture.engine->pause()&&!fixture.engine->getStateSnapshot().resumePending,"repeat Pause did not cancel Resume intent");
    fixture.gate.release=true;
    if(cancel){fixture.prepared(latest,before);std::this_thread::sleep_for(std::chrono::milliseconds(150));fixture.hold(before);}
    else{
        const auto operation=ready(*fixture.engine,latest);check(operation.speedMicros==1250000,"deferred Resume used replaced speed");state(*fixture.engine,State::Playing);
        wait([&]{return fixture.count.frames.load()>=before.output+2048;});const auto running=fixture.engine->getStateSnapshot();
        check(running.stoppedSpeed&&running.stoppedSpeed->id==latest&&running.stoppedSpeed->outputStarted&&!running.resumePending&&!fixture.engine->getPlaybackDiagnostics().retiringPipeline,"latest preparation did not resume exactly once after retirement");
        std::this_thread::sleep_for(std::chrono::milliseconds(50));check(fixture.engine->getStateSnapshot().renderEpoch==operation.renderEpoch,"deferred Resume rebuilt/restarted the adopted epoch");
        check(fixture.engine->pause(),"deferred Resume final pause");check(fixture.engine->seekHistory().size()==before.seeks,"deferred Resume fabricated seek");
    }
    passed(cancel?"preparing_resume_cancelled_by_pause":"preparing_resume_latest_once",executed);
}
static void clearWhilePaused(const std::filesystem::path& input,Preset preset,std::size_t& executed){
    LoopFixture fixture(input,preset);const auto before=fixture.freeze();fixture.prepared(request(*fixture.engine,1.25),before);fixture.arm();
    auto snapshot=fixture.engine->getStateSnapshot();const auto clear=fixture.engine->requestClearLoop(before.loop.id,{snapshot.inputGeneration,snapshot.session,snapshot.renderEpoch});check(clear.accepted,clear.reason);fixture.entered();
    const auto clearing=fixture.engine->getLoopSnapshot();check(!clearing.enabled&&clearing.clearPending,"Clear did not disable loop while preserving continuation");
    snapshot=fixture.engine->getStateSnapshot();const auto rejected=fixture.engine->requestLoopSpeed(.75,{snapshot.inputGeneration,snapshot.session,snapshot.renderEpoch});
    check(!rejected.accepted&&!rejected.reason.empty()&&rejected.reason.find("解除")!=std::string::npos,"Clear-pending speed request disappeared without rejection/retry reason");
    fixture.gate.release=true;std::this_thread::sleep_for(std::chrono::milliseconds(200));
    const auto after=fixture.engine->getLoopSnapshot();check(fixture.engine->getPlaybackState()==State::Paused&&!fixture.engine->getStateSnapshot().resumePending&&!after.enabled&&after.id==before.loop.id&&after.cycles==before.loop.cycles,"Paused Clear auto-played or revived loop");
    check(fixture.count.frames.load()==before.output&&fixture.engine->seekHistory().size()==before.seeks&&fixture.engine->getCurrentPlaybackPosition().inputFrame==before.position.inputFrame,"Paused Clear emitted audio, moved input, or fabricated user seek");
    passed("paused_clear_rejects_speed_without_auto_play",executed);
}
static void stalePreparation(const std::filesystem::path& input,Preset preset,const std::string& kind,std::size_t& executed){
    LoopFixture fixture(input,preset);const auto before=fixture.freeze();fixture.arm();const auto id=request(*fixture.engine,1.25);fixture.entered();
    check(fixture.engine->resume()&&fixture.engine->getStateSnapshot().resumePending,"stale fixture Resume intent");
    // Only releases the worker gate; all engine calls remain on this serial owner.
    if(kind=="device"){
        fixture.engine->simulateDeviceChangeForTest();state(*fixture.engine,State::Stopped);fixture.gate.release=true;
        wait([&]{const auto diagnostics=fixture.engine->getPlaybackDiagnostics();return !diagnostics.retiringPipeline&&diagnostics.archivedPreparedEpochCount>before.diagnostics.archivedPreparedEpochCount;});
    }else{
        std::jthread release([&]{std::this_thread::sleep_for(std::chrono::milliseconds(20));fixture.gate.release=true;});
        if(kind=="close")fixture.engine.reset();else fixture.engine->stop();
    }
    if(kind=="input"){
        fixture.engine->prepare(input,fixture.options);state(*fixture.engine,State::Ready);
        const auto snapshot=fixture.engine->getStateSnapshot();check(snapshot.inputGeneration!=before.position.inputGeneration&&!snapshot.resumePending&&!snapshot.stoppedSpeed,"old preparation revived after input generation changed");
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(150));check(fixture.count.frames.load()==before.output,"stale completion played audio");
    if(fixture.engine){
        const auto snapshot=fixture.engine->getStateSnapshot();check(snapshot.state==(kind=="input"?State::Ready:State::Stopped)&&!snapshot.resumePending&&!fixture.engine->getLoopSnapshot().enabled,"stale completion restored playback/loop");
        for(const auto& operation:fixture.engine->stoppedSpeedHistory())if(operation.id==id)check(operation.state==StoppedSpeedState::Cancelled,"stale stopped-speed request not Cancelled");
    }
    passed(("stale_preparation_"+kind).c_str(),executed);
}
int main(int argc,char** argv){if(argc!=3)return 1;int result=1;std::thread owner([&]{try{
    const std::filesystem::path input=argv[1];const auto preset=std::string(argv[2])=="baseline"?Preset::Baseline:Preset::Candidate;std::size_t executed=0;constexpr std::size_t expected=10;
    preparedWithoutResume(input,preset,executed);preparedAfterCycles(input,preset,executed);latestAndDuplicates(input,preset,executed);deferredResume(input,preset,false,executed);deferredResume(input,preset,true,executed);clearWhilePaused(input,preset,executed);
    for(const std::string kind:{"stop","input","device","close"})stalePreparation(input,preset,kind,executed);
    check(executed==expected,"paused loop final count");std::cout<<"{\"suite\":\"paused_speed_loop\",\"expected\":"<<expected<<",\"executed\":"<<executed<<",\"status\":\"PASS\"}"<<std::endl;result=0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});owner.join();return result;}
