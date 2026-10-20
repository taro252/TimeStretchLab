// Native minimum reproduction. Run this host serially, without other audio or
// performance tests. It records both contracts even when the old engine fails.
#define main pausedIncludedMain
#include "PausedSpeedNativeTests.cpp"
#undef main
#include "prototype/Phase59Diagnostics.h"

struct ProbeCapture {
    std::atomic<std::uint64_t> outputFrames{0},rawFrames{0},nonfinite{0},missing{0};
    std::atomic<std::uint64_t> expectedSession{0},recorded{0},rawErrors{0};std::size_t channels=0;std::vector<float> actual;
    static void raw(void* pointer,const float*const* pcm,std::size_t frames,std::size_t at,std::uint64_t,std::uint64_t,std::uint64_t session)noexcept{
        auto& capture=*static_cast<ProbeCapture*>(pointer);capture.rawFrames.fetch_add(frames,std::memory_order_relaxed);
        if(session==capture.expectedSession.load()){
            const auto offset=capture.recorded.load();if(at!=offset||offset+frames>capture.actual.size()/capture.channels){++capture.rawErrors;return;}
            for(std::size_t i=0;i<frames;++i)for(std::size_t c=0;c<capture.channels;++c)capture.actual[(offset+i)*capture.channels+c]=pcm[c][i];capture.recorded=offset+frames;
        }
        // Channel count is checked by the renderer. The native fixture records
        // channel 0 here; a separate PCM oracle is required for full comparison.
        for(std::size_t i=0;i<frames;++i)if(!std::isfinite(pcm[0][i]))capture.nonfinite.fetch_add(1,std::memory_order_relaxed);
    }
    static void output(void* pointer,const float*const*,const ProgressiveOutputSpan& span)noexcept{
        auto& capture=*static_cast<ProbeCapture*>(pointer);capture.outputFrames.fetch_add(span.frames,std::memory_order_relaxed);capture.missing.fetch_add(span.outputAffectedFrames+span.failurePaddingFrames,std::memory_order_relaxed);
    }
};
static void writeOperations(const std::vector<phase59::SpeedOperation>& operations){
    std::cout<<'[';bool comma=false;for(const auto& operation:operations){if(comma)std::cout<<',';comma=true;
        std::cout<<"{\"id\":"<<operation.id<<",\"session\":"<<operation.session<<",\"input_generation\":"<<operation.inputGeneration
            <<",\"target\":"<<operation.target<<",\"state\":\""<<phase59::name(operation.state)<<"\",\"accepted_s\":"<<operation.acceptedS
            <<",\"applied_s\":"<<operation.appliedS<<",\"completed_s\":"<<operation.completedS<<",\"logical_presented\":"<<operation.logicalPresented
            <<",\"published_at_plan\":"<<operation.publishedAtPlan<<",\"consumed_at_apply\":"<<operation.consumedAtApply
            <<",\"frontier_prepared_output\":"<<operation.frontier.preparedOutput<<'}';}
    std::cout<<']';
}
static bool probe(const std::filesystem::path& input,Preset preset,const std::filesystem::path& output){
    WavStreamReader wav(input);check(wav.frames()>=std::uint64_t(wav.sampleRate())*9,"native probe needs >=9 seconds of input; do not substitute the mandatory long fixture");
    ProbeCapture capture;capture.channels=wav.channels();capture.actual.resize(std::size_t(wav.sampleRate())*24*wav.channels());
    if(!output.empty()){check(!std::filesystem::exists(output),"new export directory required");std::filesystem::create_directories(output);}
    ProgressiveOptions options;options.preset=preset;options.allowExperimentalLoops=true;options.initialSpeed=1;options.callbackRecordLimit=256;
    options.observerContext=&capture;options.observeEpochPcm=ProbeCapture::raw;options.observeOutputPcm=ProbeCapture::output;
    ProgressiveMacPlaybackEngine engine;engine.prepare(input,options);state(engine,State::Ready);const auto initial=engine.getStateSnapshot();
    const auto loop=engine.requestLoopRange(0,std::uint64_t(wav.sampleRate())*8,{initial.inputGeneration,initial.session,initial.renderEpoch});check(loop.accepted,loop.reason);
    wait([&]{const auto snapshot=engine.getLoopSnapshot();check(snapshot.state!=progressive::LoopState::Failed,snapshot.reason);return snapshot.initialPositionComplete&&(snapshot.state==progressive::LoopState::Active||snapshot.state==progressive::LoopState::Armed);});
    capture.expectedSession=engine.getStateSnapshot().session;check(engine.play(),"native probe play");state(engine,State::Playing);wait([&]{return capture.outputFrames.load()>=wav.sampleRate()*3/10;});
    const auto before=engine.getLoopSnapshot();const auto playingRequest=engine.setSpeed(.75);const auto requestedAt=std::chrono::steady_clock::now();
    const auto observeUntil=requestedAt+std::chrono::milliseconds(1500);
    while(std::chrono::steady_clock::now()<observeUntil){bool complete=false;for(const auto& op:engine.operationHistory())complete|=op.target==750000&&op.completedS>=0;if(complete)break;std::this_thread::sleep_for(std::chrono::milliseconds(10));}
    const auto playing=engine.getStateSnapshot();const auto playingLoop=engine.getLoopSnapshot();const auto playingDiagnostics=engine.getPlaybackDiagnostics();const auto operations=engine.operationHistory();
    bool applicationObserved=false;for(const auto& operation:operations)if(operation.target==750000&&operation.id==playingLoop.dynamicOperationID&&operation.appliedS>=0&&operation.completedS>=0)applicationObserved=true;
    const bool currentCycle=applicationObserved&&playingLoop.cycles==before.cycles;
    std::cout<<"{\"case\":\"playing_current_cycle\",\"preset\":\""<<(preset==Preset::Candidate?"candidate":"baseline")<<"\",\"request_id\":"<<playingRequest.id
        <<",\"accepted\":"<<(playingRequest.result==Phase39RequestResult::Accepted?"true":"false")<<",\"observation_ms\":"<<std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-requestedAt).count()
        <<",\"state\":\""<<progressive::name(playing.state)<<"\",\"cycles_before\":"<<before.cycles<<",\"cycles_after\":"<<playingLoop.cycles
        <<",\"applied_speed\":"<<playingLoop.appliedSpeed<<",\"consumed\":"<<playingDiagnostics.consumedFrames<<",\"published\":"<<playingDiagnostics.publishedFrames
        <<",\"current_cycle_application_observed\":"<<(currentCycle?"true":"false")<<",\"independent_PCM_compared\":false,\"operations\":";writeOperations(operations);
    std::cout<<",\"status\":\""<<(currentCycle?"OBSERVED_CURRENT_CYCLE_APPLICATION":"REPRODUCED_BOUNDARY_WAIT")<<"\"}"<<std::endl;
    check(playing.state!=State::Failed,playing.error);check(engine.pause(),"native probe pause");
    const auto historyPosition=engine.getCurrentPlaybackPosition();const auto historyState=engine.getStateSnapshot();const auto outputAtHistoryPause=capture.outputFrames.load();const auto historySeeks=engine.seekHistory().size();
    std::this_thread::sleep_for(std::chrono::milliseconds(40));check(engine.getCurrentPlaybackPosition().inputFrame==historyPosition.inputFrame&&capture.outputFrames.load()==outputAtHistoryPause,"unchanged-speed pause advanced");
    check(engine.resume(),"dynamic history Resume");wait([&]{return capture.outputFrames.load()>=outputAtHistoryPause+2048;});check(engine.pause(),"dynamic history final Pause");
    check(engine.getStateSnapshot().session==historyState.session&&engine.getStateSnapshot().renderEpoch==historyState.renderEpoch&&!engine.getStateSnapshot().stoppedSpeed&&engine.seekHistory().size()==historySeeks,"unchanged-speed Pause/Resume replaced dynamic history");
    std::cout<<"{\"case\":\"unchanged_speed_dynamic_pause_resume\",\"status\":\"PASS\",\"raw_prefix_includes_continuation\":true}"<<std::endl;
    const auto capturedFrames=capture.recorded.load();
    if(!output.empty()){
        check(!capture.rawErrors,"native raw continuity/capacity failure");
        std::ofstream raw(output/"actual.f32",std::ios::binary);raw.write(reinterpret_cast<const char*>(capture.actual.data()),capturedFrames*wav.channels()*sizeof(float));raw.close();check(bool(raw),"native RAW export");
        phase59::exportOperations(output,operations,1000000);
        std::ofstream metadata(output/"NATIVE.json");metadata<<"{\"captured_frames\":"<<capturedFrames<<",\"channels\":"<<wav.channels()<<",\"source_rate\":"<<wav.sampleRate()<<",\"input_B\":"<<wav.sampleRate()*8<<",\"dynamic_B\":"<<playingLoop.dynamicOutputEnd<<",\"map_version\":"<<playingLoop.mapVersion<<",\"device_rate\":"<<engine.getNativeDiagnostics().deviceRate<<",\"device_buffer\":"<<engine.getNativeDiagnostics().deviceBufferFrames<<",\"current_cycle_observed\":"<<(currentCycle?"true":"false")<<",\"raw_errors\":"<<capture.rawErrors<<"}\n";
    }
    const auto paused=engine.getStateSnapshot();const auto pausedLoop=engine.getLoopSnapshot();const auto pausedDiagnostics=engine.getPlaybackDiagnostics();const auto pausedPosition=engine.getCurrentPlaybackPosition();
    check(pausedPosition.inputFrame.has_value(),"paused input coordinate unavailable");const auto audibleAtPause=capture.outputFrames.load();const auto seeksAtPause=engine.seekHistory().size();
    const auto pausedRequest=engine.setSpeed(1.25);const auto preparationAt=std::chrono::steady_clock::now();bool readyBeforeResume=false,held=true,oldEpochConsumed=false,autoPlayed=false;
    const auto deadline=preparationAt+std::chrono::seconds(5);
    while(std::chrono::steady_clock::now()<deadline){const auto snapshot=engine.getStateSnapshot();const auto position=engine.getCurrentPlaybackPosition();const auto diagnostics=engine.getPlaybackDiagnostics();const auto activeLoop=engine.getLoopSnapshot();
        autoPlayed|=snapshot.state==State::Playing;held&=snapshot.state==State::Paused&&position.inputFrame==pausedPosition.inputFrame&&activeLoop.id==pausedLoop.id&&activeLoop.cycles==pausedLoop.cycles&&capture.outputFrames.load()==audibleAtPause;
        if(diagnostics.renderEpoch==pausedDiagnostics.renderEpoch)oldEpochConsumed|=diagnostics.consumedFrames!=pausedDiagnostics.consumedFrames;
        else held&=diagnostics.consumedFrames==diagnostics.pipeline.outputStartFrame&&diagnostics.currentEpochPresentedFrame==diagnostics.pipeline.outputStartFrame;
        if(snapshot.stoppedSpeed&&snapshot.stoppedSpeed->id==pausedRequest.id&&snapshot.stoppedSpeed->speedMicros==1250000&&snapshot.stoppedSpeed->state==StoppedSpeedState::ReadyForResume){readyBeforeResume=true;break;}
        if(snapshot.state==State::Failed||(snapshot.stoppedSpeed&&snapshot.stoppedSpeed->id==pausedRequest.id&&snapshot.stoppedSpeed->state==StoppedSpeedState::Failed))break;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    const auto final=engine.getStateSnapshot();const auto finalLoop=engine.getLoopSnapshot();const auto finalDiagnostics=engine.getPlaybackDiagnostics();const auto finalPosition=engine.getCurrentPlaybackPosition();
    held&=!oldEpochConsumed&&!autoPlayed&&engine.seekHistory().size()==seeksAtPause&&!final.resumePending;
    std::cout<<"{\"case\":\"paused_ready_without_resume\",\"preset\":\""<<(preset==Preset::Candidate?"candidate":"baseline")<<"\",\"request_id\":"<<pausedRequest.id
        <<",\"accepted\":"<<(pausedRequest.result==Phase39RequestResult::Accepted?"true":"false")<<",\"wait_ms\":"<<std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-preparationAt).count()
        <<",\"ready_before_resume\":"<<(readyBeforeResume?"true":"false")<<",\"resume_calls\":0,\"position_and_loop_held\":"<<(held?"true":"false")
        <<",\"state\":\""<<progressive::name(final.state)<<"\",\"stopped_state\":\""<<(final.stoppedSpeed?name(final.stoppedSpeed->state):"ABSENT")
        <<"\",\"input_before\":"<<*pausedPosition.inputFrame<<",\"input_after\":"<<(finalPosition.inputFrame?std::to_string(*finalPosition.inputFrame):"null")
        <<",\"cycles_before\":"<<pausedLoop.cycles<<",\"cycles_after\":"<<finalLoop.cycles<<",\"loop_id_before\":"<<pausedLoop.id<<",\"loop_id_after\":"<<finalLoop.id
        <<",\"epoch_before\":"<<paused.renderEpoch<<",\"epoch_after\":"<<final.renderEpoch<<",\"consumed_before\":"<<pausedDiagnostics.consumedFrames<<",\"consumed_after\":"<<finalDiagnostics.consumedFrames
        <<",\"output_before\":"<<audibleAtPause<<",\"output_after\":"<<capture.outputFrames.load()<<",\"seek_count_before\":"<<seeksAtPause<<",\"seek_count_after\":"<<engine.seekHistory().size()
        <<",\"status\":\""<<(readyBeforeResume&&held?"PASS":"REPRODUCED_PAUSED_NOT_READY")<<"\"}"<<std::endl;
    const auto native=engine.getNativeDiagnostics();engine.stop();
    check(!phase58::RealtimePipeline::executionOwnerCounts().alive&&phase58::RealtimePipeline::executionOwnerCounts().peak<=2,"execution owner lifetime cap/retirement");
    std::cout<<"{\"case\":\"probe_summary\",\"current_cycle_observed\":"<<(currentCycle?"true":"false")<<",\"paused_ready_and_held\":"<<(readyBeforeResume&&held?"true":"false")
        <<",\"missing\":"<<finalDiagnostics.missingFrames<<",\"output_affected_or_padding\":"<<capture.missing.load()<<",\"nonfinite_channel0\":"<<capture.nonfinite.load()
        <<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames<<",\"source_rate\":"<<wav.sampleRate()<<",\"channels\":"<<wav.channels()
        <<",\"independent_PCM_compared\":false,\"callback_allocation_probe\":\"NOT_RUN\",\"contract_observations_pass\":"<<(currentCycle&&readyBeforeResume&&held?"true":"false")<<"}"<<std::endl;
    return currentCycle&&readyBeforeResume&&held&&!capture.nonfinite&&!capture.missing&&!finalDiagnostics.missingFrames;
}
int main(int argc,char** argv){if(argc<3||argc>5){std::cerr<<"input candidate|baseline [--require-fixed] [NEW_EXPORT_DIR]\n";return 1;}int result=1;std::thread owner([&]{try{
    std::filesystem::path output;bool required=false;for(int i=3;i<argc;++i)if(std::string(argv[i])=="--require-fixed")required=true;else output=argv[i];
    const bool passed=probe(argv[1],std::string(argv[2])=="baseline"?Preset::Baseline:Preset::Candidate,output);
    result=required&&!passed?2:0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});owner.join();return result;}
