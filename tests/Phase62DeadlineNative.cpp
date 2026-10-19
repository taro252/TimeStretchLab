#define PHASE61_SANDBOX_APP 1
#include "Phase61NativeTests.cpp"
#include "Phase61CallbackMallocProbe.h"
#include "Phase62FixTrace.h"
struct LoopPreparationGate {
    unsigned target=2;std::atomic<unsigned> calls{0};std::atomic<bool> entered{false},release{false};
    static void event(void* context,ProgressiveControlTestPoint point)noexcept{
        if(point!=ProgressiveControlTestPoint::SeekPreparationStarted)return;
        auto& gate=*static_cast<LoopPreparationGate*>(context);if(++gate.calls!=gate.target)return;
        gate.entered=true;while(!gate.release.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
};
int manualSpeed(const std::filesystem::path& input,const std::filesystem::path& output){
    require(std::filesystem::create_directories(output),"manual speed output exists");LoopPreparationGate gate;gate.target=2;ProgressiveMacPlaybackEngine e;
    struct Release {LoopPreparationGate& gate;~Release(){gate.release=true;}} release{gate};
    ProgressiveOptions o;o.allowExperimentalLoops=true;o.initialSpeed=2.;o.controlTestHooks={&gate,LoopPreparationGate::event};e.prepare(input,o);wait(e,State::Ready);
    auto s=e.getStateSnapshot();const auto rate=e.getPlaybackDiagnostics().sourceSampleRate;auto loop=e.requestLoopRange(0,rate*2,{s.inputGeneration,s.session,s.renderEpoch});require(loop.accepted,"manual loop");
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(20);
    while(!e.getLoopSnapshot().initialPositionComplete){require(std::chrono::steady_clock::now()<deadline,"manual initial");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    s=e.getStateSnapshot();const auto seek=e.requestSeekToInputFrame(rate/4,s.inputGeneration,s.renderEpoch);require(seek.accepted,"manual admission");
    while(!gate.entered){require(std::chrono::steady_clock::now()<deadline,"manual preparation gate");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    s=e.getStateSnapshot();require(e.setSpeed(.75,s.session,s.inputGeneration,s.renderEpoch).result==ts::prototype::Phase39RequestResult::Accepted,"speed during manual");gate.release=true;
    const auto op=waitSeek(e,seek.id);require(op.state==Seek::Completed&&op.speedMicros==750000&&op.requestedInputFrame==rate/4,"manual ID not replanned/completed");
    require(e.getPlaybackState()==State::Ready&&e.getCurrentPlaybackPosition().inputFrame==rate/4,"manual Ready exact position");
    const auto l=e.getLoopSnapshot();require(l.enabled&&l.id==loop.id&&l.startFrame==0&&l.endFrameExclusive==rate*2&&!l.cycles,"manual loop changed");
    const auto c=e.getStateSnapshot();require(e.requestClearLoop(l.id,{c.inputGeneration,c.session,c.renderEpoch}).accepted,"manual clear");
    require(e.setSpeed(1.,c.session,c.inputGeneration,c.renderEpoch).result==ts::prototype::Phase39RequestResult::Stopped,"speed during clear not rejected");
    const auto busy=e.requestLoopSpeed(1.,{c.inputGeneration,c.session,c.renderEpoch});require(!busy.accepted&&busy.reason.find("解除")!=std::string::npos,"clear busy reason");
    e.stop();std::ofstream f(output/"result.json");f<<"{\"PASS\":true,\"seek_id\":"<<seek.id<<",\"speed_micros\":"<<op.speedMicros<<",\"replans\":"<<op.replans<<",\"input_frame\":"<<op.requestedInputFrame<<",\"clear_speed_rejected\":true}\n";return 0;
}
int nearEnd(const std::filesystem::path& input,const std::filesystem::path& output){
    require(std::filesystem::create_directories(output),"near end output exists");ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.allowExperimentalLoops=true;o.initialSpeed=2.;e.prepare(input,o);wait(e,State::Ready);
    auto c=e.getStateSnapshot();const auto frames=e.getPlaybackDiagnostics().inputFrames;const auto seek=e.requestSeekToInputFrame(frames-128,c.inputGeneration,c.renderEpoch);require(seek.accepted,"near end seek");waitSeek(e,seek.id);
    c=e.getStateSnapshot();progressive::LoopOptions options;options.startPolicy=progressive::LoopStartPolicy::KeepPosition;require(e.requestLoopRange(0,frames,{c.inputGeneration,c.session,c.renderEpoch},options).accepted,"near end admission");wait(e,State::Failed);
    const auto loop=e.getLoopSnapshot();require(loop.state==progressive::LoopState::Failed&&!loop.enabled&&!loop.cycles&&loop.reason.find("最大callback")!=std::string::npos,"near end unsafe arm");e.stop();std::ofstream f(output/"result.json");f<<"{\"PASS\":true,\"expected_playback_state\":\"Failed\",\"cycles\":0,\"reason\":"<<ts::prototype::phase58::jsonString(loop.reason)<<"}\n";return 0;
}
int main(int argc,char** argv){if(argc!=3&&argc!=4)return 1;int code=1;std::thread control([&]{try{
    if(argc==4){code=std::string(argv[3])=="--near-end"?nearEnd(argv[1],argv[2]):manualSpeed(argv[1],argv[2]);return;}
    const std::filesystem::path output=argv[2];require(std::filesystem::create_directories(output),"deadline output exists");ProgressiveMacPlaybackEngine e;
    ProgressiveOptions o;o.allowExperimentalLoops=true;o.initialSpeed=2.;o.loopSupplyFramesForTest=16384+100;
    phase61_heap_reset();o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    e.prepare(argv[1],o);wait(e,State::Ready);const auto c=e.getStateSnapshot();const auto rate=e.getPlaybackDiagnostics().sourceSampleRate;
    require(e.requestLoopRange(0,rate/2,{c.inputGeneration,c.session,c.renderEpoch}).accepted,"supply admission");
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);
    while(!e.getLoopSnapshot().initialPositionComplete){require(std::chrono::steady_clock::now()<deadline,"initial timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    require(e.play(),"supply play");wait(e,State::Failed);const auto loop=e.getLoopSnapshot();const auto failed=e.getStateSnapshot();
    require(failed.reason==StopReason::WorkerError&&loop.state==progressive::LoopState::Failed&&!loop.enabled,"supply failure contract");
    require(loop.cycles==1&&loop.newMissingFrames==412&&loop.outputAffectedFrames==412&&loop.failurePaddingFrames==412&&loop.safetyStopFrames==412,"native 512/100/412 accounting");
    require(loop.reason.find("新入力PCM不足")!=std::string::npos&&failed.error==loop.reason,"original supply reason lost");
    writePhase62Trace(output/"callbacks_all_spans.jsonl",e.loopCallbackRecords());
    e.stop();const auto d=e.getPlaybackDiagnostics();require(d.pipeline.finalDataAvailable,"supply final data");for(const auto& epoch:e.closedEpochs())require(epoch.pipeline.finalDataAvailable,"supply preparation final data");
    require(d.missingFrames==412&&!d.callbackCppNew.value_or(UINT64_MAX)&&!phase61_heap_allocations()&&!phase61_heap_frees(),"supply callback safety");
    require(e.play(),"supply explicit replay");wait(e,State::Playing);require(!e.getLoopSnapshot().enabled,"supply loop revived");e.stop();
    std::ofstream f(output/"result.json");f<<"{\"PASS\":true,\"expected_playback_state\":\"Failed\",\"successful_cycles_before_fault\":"<<loop.cycles<<",\"new_missing\":"<<loop.newMissingFrames<<",\"affected\":"<<loop.outputAffectedFrames<<",\"failure_padding\":"<<loop.failurePaddingFrames<<",\"callback_new\":0,\"callback_heap\":0,\"callback_free\":0,\"reason\":"<<ts::prototype::phase58::jsonString(loop.reason)<<"}\n";code=0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return code;}
