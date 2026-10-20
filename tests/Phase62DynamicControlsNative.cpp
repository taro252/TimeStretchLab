// Explicit, serial native output host. Independent DSP verification is separate.
#define main includedPhase62NativeMain
#include "Phase62NativeTests.cpp"
#undef main
#include "prototype/Phase45PcmDigest.h"

namespace {
namespace phase58=ts::prototype::phase58;
namespace phase59=ts::prototype::phase59;
using Clock=std::chrono::steady_clock;
struct NativeControlGate {
    std::atomic<bool> armed{false},entered{false},release{false},expired{false};
    std::atomic<ProgressiveControlTestPoint> point{ProgressiveControlTestPoint::SeekPreparationStarted};
    static void event(void* context,ProgressiveControlTestPoint point)noexcept{
        auto& gate=*static_cast<NativeControlGate*>(context);
        if(point!=gate.point.load()||!gate.armed.exchange(false))return;
        gate.entered=true;const auto deadline=Clock::now()+std::chrono::seconds(30);
        while(!gate.release.load()&&Clock::now()<deadline)std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if(!gate.release.load())gate.expired=true;
    }
};
struct ObservedPcm {std::uint64_t session=0,epoch=0,end=0,callbackEnd=0;};
struct NativeControlCapture {
    LoopPcmAudit audit;
    phase59::ValueMailbox<ObservedPcm> rawPosition,outputPosition;
    std::atomic<std::uint64_t> frames{0},naturalBs{0},clearMixed{0},clearNewStart{UINT64_MAX},clearOldEnd{0};
    std::uint64_t rawSession=0; // callback writer only
    explicit NativeControlCapture(std::size_t channels):audit(channels){}
    static void raw(void* context,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& capture=*static_cast<NativeControlCapture*>(context);LoopPcmAudit::source(&capture.audit,pcm,n,at,generation,epoch,session);
        capture.rawSession=session;capture.rawPosition.publish({session,epoch,at+n,0});
    }
    static void output(void* context,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& capture=*static_cast<NativeControlCapture*>(context);LoopPcmAudit::output(&capture.audit,pcm,span);
        capture.frames.fetch_add(span.frames,std::memory_order_relaxed);
        capture.outputPosition.publish({capture.rawSession,span.newEpoch,span.newOutputOffset+span.newReceivedFrames,span.callbackFrame+span.frames});
        if(span.periodicBoundary&&span.periodOffset+span.frames==span.periodFrames)capture.naturalBs.fetch_add(1,std::memory_order_relaxed);
        if(span.mixedFrames){
            auto unset=UINT64_MAX;capture.clearNewStart.compare_exchange_strong(unset,span.newOutputOffset);
            capture.clearMixed.fetch_add(span.mixedFrames,std::memory_order_relaxed);capture.clearOldEnd=span.oldOutputOffset+span.oldReceivedFrames;
        }
    }
};
std::string nativeControlHash(const std::filesystem::path& path){
    std::ifstream file(path,std::ios::binary);require(bool(file),"hash input missing");ts::prototype::Phase45PcmDigest digest;std::array<char,65536> block{};
    while(file.read(block.data(),block.size())||file.gcount())digest.update(block.data(),std::size_t(file.gcount()));
    require(file.eof(),"hash read failed");return digest.finish();
}
struct NativeControlFixture {
    NativeControlGate gate;std::unique_ptr<NativeControlCapture> capture;ProgressiveOptions options;std::unique_ptr<ProgressiveMacPlaybackEngine> engine;
    std::filesystem::path folder;std::uint64_t loopID=0,b=0;unsigned rate=0;std::size_t initialSeeks=0;
    NativeControlFixture(const std::filesystem::path& input,Preset preset,const std::filesystem::path& output):capture(std::make_unique<NativeControlCapture>(ts::WavStreamReader(input).channels())),engine(std::make_unique<ProgressiveMacPlaybackEngine>()),folder(output){
        ts::WavStreamReader wav(input);rate=wav.sampleRate();b=std::uint64_t(rate)*8;require(wav.frames()>=std::uint64_t(rate)*9,"native controls require >=9 seconds; AB is [0,8 seconds)");
        require(std::filesystem::create_directories(folder),"case output directory exists");
        options.allowExperimentalLoops=true;options.initialSpeed=1;options.preset=preset;options.callbackRecordLimit=4096;
        options.observerContext=capture.get();options.observeEpochPcm=NativeControlCapture::raw;options.observeOutputPcm=NativeControlCapture::output;options.controlTestHooks={&gate,NativeControlGate::event};
        options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
        phase61_heap_reset();engine->prepare(input,options);wait(*engine,State::Ready);const auto state=engine->getStateSnapshot();
        const auto receipt=engine->requestLoopRange(0,b,{state.inputGeneration,state.session,state.renderEpoch});require(receipt.accepted,"initial ReturnToA rejected");loopID=receipt.id;
        until([&]{return engine->getLoopSnapshot().initialPositionComplete;},"initial loop preparation");
        initialSeeks=engine->seekHistory().size();require(engine->play(),"initial loop play");firstPcm(*engine);
        until([&]{return capture->frames.load()>=rate/5;},"first observable loop PCM");
    }
    ~NativeControlFixture(){gate.release=true;if(engine)engine->stop();}
    void healthy(){
        const auto snapshot=engine->getStateSnapshot();if(snapshot.state==State::Failed)throw std::runtime_error(snapshot.error);
        require(!gate.expired,"normal-worker gate watchdog expired");require(phase58::RealtimePipeline::executionOwnerCounts().peak<=2,"instantaneous third execution owner");
    }
    template<class Predicate> void until(Predicate predicate,const char* reason){
        const auto deadline=Clock::now()+std::chrono::seconds(60);while(!predicate()){healthy();require(Clock::now()<deadline,reason);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
        healthy();
    }
    progressive::LoopSnapshot commit75(){
        const auto request=engine->setSpeed(.75);require(request.result==ts::prototype::Phase39RequestResult::Accepted,"75 request rejected");
        until([&]{const auto loop=engine->getLoopSnapshot();return loop.dynamicOperationID&&loop.mapVersion&&loop.dynamicOutputEnd;},"75 current-cycle commit not observed");
        const auto loop=engine->getLoopSnapshot();const auto diagnostics=engine->getPlaybackDiagnostics();
        require(loop.cycles==0&&loop.dynamicCycle==0&&diagnostics.currentEpochPresentedFrame+4096<loop.dynamicOutputEnd,"75 commit did not leave the initial cycle");
        std::ofstream event(folder/"commit75.json");event<<"{\"loop_id\":"<<loop.id<<",\"request_id\":"<<request.id<<",\"dynamic_operation_id\":"<<loop.dynamicOperationID<<",\"cycle\":"<<loop.dynamicCycle<<",\"map_version\":"<<loop.mapVersion<<",\"dynamic_B\":"<<loop.dynamicOutputEnd<<",\"consumed\":"<<diagnostics.consumedFrames<<"}\n";
        return loop;
    }
    void finish(const char* name){
        if(engine->getPlaybackState()==State::Playing)require(engine->pause(),"final native pause");
        healthy();const auto loop=engine->getLoopSnapshot();const auto diagnostics=engine->getPlaybackDiagnostics();const auto native=engine->getNativeDiagnostics();
        require(engine->seekHistory().size()==initialSeeks,"internal handoff fabricated user seek");engine->stop();
        require(!capture->audit.errors&&!capture->audit.nonfinite,"RAW/boundary PCM audit failed");
        const auto final=engine->getPlaybackDiagnostics();require(!final.missingFrames&&!final.underrunCalls&&!final.rejectedWrites&&!loop.failurePaddingFrames&&!loop.outputAffectedFrames,"unexpected native supply failure");
        require(diagnostics.callbackCppNew&&!*diagnostics.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback allocation/free");
        const auto owners=phase58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"execution owner lifetime/peak");
        require(capture->naturalBs.load()==loop.cycles,"cycle count differs from observed PCM B completions");
        for(const auto& epoch:engine->closedEpochs())require(epoch.pipeline.finalDataAvailable,"unjoined retired owner");
        writePhase62Trace(folder/"callbacks_all_spans.jsonl",engine->loopCallbackRecords());writePhase62Trace(folder/"clock_anomaly_window.jsonl",engine->loopClockAnomalyRecords());
        std::ofstream result(folder/"result.json");result<<"{\"case\":"<<phase58::jsonString(name)<<",\"status\":\"PASS\",\"cycles\":"<<loop.cycles<<",\"PCM_natural_Bs\":"<<capture->naturalBs.load()
            <<",\"raw_mix_errors\":"<<capture->audit.errors<<",\"nonfinite\":"<<capture->audit.nonfinite<<",\"missing\":"<<final.missingFrames<<",\"padding\":"<<loop.failurePaddingFrames
            <<",\"owner_peak\":"<<owners.peak<<",\"owners_after_stop\":"<<owners.alive<<",\"callback_cpp_new\":"<<*diagnostics.callbackCppNew<<",\"callback_heap_calls\":"<<phase61_heap_allocations()<<",\"callback_heap_frees\":"<<phase61_heap_frees()
            <<",\"callback_deadlines_observed\":"<<native.deadlineMisses<<",\"worker_deadlines_observed\":"<<final.workerDeadlineMisses<<",\"host_clock_errors_observed\":"<<native.hostMissing+native.hostBackwards+native.hostCadenceErrors
            <<",\"sample_clock_errors_observed\":"<<native.sampleErrors<<",\"hal_window_misses_observed\":"<<native.halWindowMisses<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames
            <<",\"source_rate\":"<<rate<<",\"independent_DSP_comparison\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"physical_loopback\":\"NOT_RUN\"}\n";
    }
};
void committedLatest(const std::filesystem::path& input,Preset preset,const std::filesystem::path& folder){
    NativeControlFixture fixture(input,preset,folder);const auto committed=fixture.commit75();const auto initialSession=fixture.engine->getStateSnapshot().session;
    fixture.gate.armed=true;const auto newest=fixture.engine->setSpeed(2.0);require(newest.result==ts::prototype::Phase39RequestResult::Accepted,"200 replacement rejected");
    fixture.until([&]{return fixture.gate.entered.load();},"next 200 preparation did not enter normal gate");
    auto state=fixture.engine->getStateSnapshot();auto loop=fixture.engine->getLoopSnapshot();const auto diagnostics=fixture.engine->getPlaybackDiagnostics();
    require(loop.cycles==1&&state.session!=initialSession&&loop.appliedSpeed==.75&&state.appliedTargetSpeed==.75&&state.requestedSpeed==2.0,"mandatory committed 75 owner was replaced or mislabeled");
    const auto adoptedSession=state.session;
    fixture.until([&]{const auto value=fixture.capture->outputPosition.read();return value&&value->session==adoptedSession&&value->end>0;},"75 PCM not observed after mandatory B");
    const auto observed=fixture.capture->outputPosition.read();
    require(observed&&observed->session==adoptedSession&&observed->end>0,"75 PCM not observed after mandatory B");
    require(phase58::RealtimePipeline::executionOwnerCounts().alive==2,"current 75 and gated 200 do not occupy exactly two slots");
    const auto before=fixture.capture->frames.load();std::this_thread::sleep_for(std::chrono::milliseconds(150));fixture.healthy();
    loop=fixture.engine->getLoopSnapshot();require(loop.appliedSpeed==.75&&loop.cycles==1&&fixture.capture->frames.load()>before,"valid 75 output stopped while 200 preparation was delayed");
    const auto boundaries=fixture.engine->loopHistory();require(boundaries.size()==1&&boundaries.front().callbackFrame==committed.dynamicOutputEnd&&boundaries.front().oldOutputEnd==committed.dynamicOutputEnd,"dynamic first B/period coordinate changed");
    fixture.gate.release=true;std::optional<phase59::SpeedOperation> applied;
    fixture.until([&]{
        for(const auto& operation:fixture.engine->operationHistory())if(operation.target==2000000&&operation.completedS>=0){const auto raw=fixture.capture->rawPosition.read(),output=fixture.capture->outputPosition.read();
            if(raw&&output&&raw->session==operation.session&&output->session==operation.session&&raw->end>=std::uint64_t(operation.change.plan.completionOutputSample)&&output->end>=std::uint64_t(operation.change.plan.completionOutputSample)){applied=operation;return true;}}
        return false;
    },"200 plan did not complete in actual RAW/output PCM");
    state=fixture.engine->getStateSnapshot();require(state.appliedTargetSpeed==2.0&&fixture.engine->getLoopSnapshot().appliedSpeed==2.0,"200 audible completion lost applied-speed correlation");
    std::ofstream observation(folder/"replacement.json");observation<<"{\"committed_75_B\":"<<committed.dynamicOutputEnd<<",\"75_session\":"<<adoptedSession<<",\"latest_request_id\":"<<newest.id<<",\"200_operation_id\":"<<applied->id
        <<",\"200_session\":"<<applied->session<<",\"200_applied_output\":"<<applied->change.plan.appliedOutputSample<<",\"200_completion_output\":"<<applied->change.plan.completionOutputSample<<",\"actual_RAW_and_output_past_completion\":true,\"independent_DSP_comparison\":\"NOT_RUN\"}\n";
    fixture.finish("committed_75_then_latest_200");
}
void committedClear(const std::filesystem::path& input,Preset preset,const std::filesystem::path& folder){
    NativeControlFixture fixture(input,preset,folder);const auto committed=fixture.commit75();auto state=fixture.engine->getStateSnapshot();
    const auto clear=fixture.engine->requestClearLoop(fixture.loopID,{state.inputGeneration,state.session,state.renderEpoch});require(clear.accepted,"Clear after commit rejected");
    auto loop=fixture.engine->getLoopSnapshot();require(!loop.enabled&&loop.clearPending&&loop.cycles==0,"Clear did not disable the loop before B");
    state=fixture.engine->getStateSnapshot();const auto rejected=fixture.engine->requestLoopSpeed(.40,{state.inputGeneration,state.session,state.renderEpoch});
    require(!rejected.accepted&&!rejected.reason.empty()&&rejected.reason.find("解除")!=std::string::npos,"Clear-pending speed lacks explicit rejection/retry reason");
    fixture.until([&]{return !fixture.engine->getLoopSnapshot().clearPending;},"Clear continuation did not finish");
    require(fixture.engine->getPlaybackState()==State::Playing,"Clear did not connect to normal audible continuation");require(fixture.engine->pause(),"Clear continuation pause");
    loop=fixture.engine->getLoopSnapshot();const auto normal=fixture.engine->getPlaybackDiagnostics();const auto boundaries=fixture.engine->loopHistory();
    require(!loop.enabled&&!loop.clearPending&&!normal.pipeline.loopReuse.enabled&&!normal.pipeline.fastLocalSeek,"Clear revived Loop or silently used local seek");
    require(loop.cycles>=1&&loop.cycles==fixture.capture->naturalBs.load()&&boundaries.size()==loop.cycles,"Clear connection counted as a natural cycle");
    require(boundaries.front().callbackFrame==committed.dynamicOutputEnd&&boundaries.front().oldOutputEnd==committed.dynamicOutputEnd,"Clear lost dynamic first B");
    require(fixture.capture->clearMixed.load()==fixture.rate/200&&fixture.capture->clearNewStart.load()==normal.pipeline.outputStartFrame&&fixture.capture->clearOldEnd.load()==normal.pipeline.outputStartFrame,"Clear Exact continuation mixed wrong B ranges");
    const auto frozenFrames=fixture.capture->frames.load(),frozenCycles=loop.cycles;std::this_thread::sleep_for(std::chrono::milliseconds(100));
    require(fixture.engine->getPlaybackState()==State::Paused&&!fixture.engine->getLoopSnapshot().enabled&&fixture.engine->getLoopSnapshot().cycles==frozenCycles&&fixture.capture->frames.load()==frozenFrames,"completed Clear revived playback or loop");
    std::ofstream observation(folder/"clear.json");observation<<"{\"enabled_after_accept\":false,\"speed_rejection_reason\":"<<phase58::jsonString(rejected.reason)<<",\"natural_cycles\":"<<loop.cycles<<",\"PCM_natural_Bs\":"<<fixture.capture->naturalBs.load()
        <<",\"clear_mixed_frames\":"<<fixture.capture->clearMixed.load()<<",\"normal_Exact_output_start\":"<<normal.pipeline.outputStartFrame<<",\"clear_connection_counted_as_cycle\":false,\"mode\":\"explicit fixed Exact continuation\",\"independent_DSP_comparison\":\"NOT_RUN\"}\n";
    fixture.finish("committed_75_then_clear");
}
void cancelledPublishedThenPause(const std::filesystem::path& input,Preset preset,const std::filesystem::path& folder){
    NativeControlFixture fixture(input,preset,folder);
    fixture.gate.point=ProgressiveControlTestPoint::SwitchPublished;fixture.gate.armed=true;
    const auto oldRequest=fixture.engine->setSpeed(.75);require(oldRequest.result==ts::prototype::Phase39RequestResult::Accepted,"published 75 request rejected");
    fixture.until([&]{return fixture.gate.entered.load();},"75 handoff did not reach SwitchPublished gate");
    require(!fixture.engine->getLoopSnapshot().dynamicOperationID,"75 committed before pre-offer SwitchPublished gate");
    const auto replacement=fixture.engine->setSpeed(1.25);require(replacement.result==ts::prototype::Phase39RequestResult::Accepted,"uncommitted 75 replacement rejected");
    require(fixture.engine->pause(),"Pause after cancelling published 75");
    const auto frozen=fixture.engine->getCurrentPlaybackPosition();const auto before=fixture.engine->getPlaybackDiagnostics();const auto frozenLoop=fixture.engine->getLoopSnapshot();
    const auto frames=fixture.capture->frames.load();require(frozen.inputFrame&&frozen.sampledOutputFrame&&*frozen.sampledOutputFrame==before.consumedFrames,"Pause did not freeze a paired input/output coordinate");
    require(frozenLoop.id==fixture.loopID&&frozenLoop.cycles==0&&!fixture.engine->getStateSnapshot().resumePending,"published cancellation changed loop or Resume intent");
    const auto held=[&]{
        const auto state=fixture.engine->getStateSnapshot();const auto position=fixture.engine->getCurrentPlaybackPosition();const auto diagnostics=fixture.engine->getPlaybackDiagnostics();const auto loop=fixture.engine->getLoopSnapshot();
        require(state.state==State::Paused&&!state.resumePending&&state.renderEpoch==before.renderEpoch&&state.session==before.session,"cancelled published A owner adopted during Pause");
        require(position.inputFrame==frozen.inputFrame&&diagnostics.consumedFrames==before.consumedFrames&&diagnostics.currentEpochPresentedFrame==before.currentEpochPresentedFrame,"cancelled published preparation rewound paused C");
        require(loop.id==frozenLoop.id&&loop.enabled&&loop.cycles==frozenLoop.cycles&&fixture.capture->frames.load()==frames,"paused cancellation emitted audio or advanced loop");
        require(fixture.engine->seekHistory().size()==fixture.initialSeeks,"cancelled internal preparation fabricated user seek");
    };
    held();fixture.gate.release=true;
    fixture.until([&]{held();return fixture.engine->getPlaybackDiagnostics().archivedPreparedEpochCount>before.archivedPreparedEpochCount;},"cancelled 75 owner did not retire");
    std::this_thread::sleep_for(std::chrono::milliseconds(100));held();
    // A Playing request and an Exact paused preparation have separate IDs.
    // A repeated paused request may validly identify an already-current version.
    const auto latest=fixture.engine->setSpeed(1.25);
    require((latest.result==ts::prototype::Phase39RequestResult::Accepted||latest.result==ts::prototype::Phase39RequestResult::Duplicate)&&latest.id,"latest paused 125 request rejected");
    std::optional<StoppedSpeedOperation> prepared;
    fixture.until([&]{
        const auto state=fixture.engine->getStateSnapshot();const auto position=fixture.engine->getCurrentPlaybackPosition();const auto diagnostics=fixture.engine->getPlaybackDiagnostics();const auto loop=fixture.engine->getLoopSnapshot();
        require(state.state==State::Paused&&!state.resumePending&&position.inputFrame==frozen.inputFrame&&fixture.capture->frames.load()==frames,"latest paused preparation moved C or emitted audio");
        require(loop.id==frozenLoop.id&&loop.enabled&&loop.cycles==frozenLoop.cycles,"latest paused preparation changed loop/cycle");
        if(diagnostics.renderEpoch==before.renderEpoch)require(diagnostics.consumedFrames==before.consumedFrames,"old epoch consumed during latest preparation");
        else require(diagnostics.consumedFrames==diagnostics.pipeline.outputStartFrame&&diagnostics.currentEpochPresentedFrame==diagnostics.pipeline.outputStartFrame,"replacement epoch consumed before Resume");
        require(state.stoppedSpeed&&state.stoppedSpeed->id==latest.id&&state.stoppedSpeed->speedMicros==1250000,"stale 75 notification replaced latest paused request");
        require(state.stoppedSpeed->state!=StoppedSpeedState::Failed&&state.stoppedSpeed->state!=StoppedSpeedState::Cancelled&&state.stoppedSpeed->state!=StoppedSpeedState::Replaced,"latest paused request failed or became stale");
        if(state.stoppedSpeed->state!=StoppedSpeedState::ReadyForResume)return false;prepared=*state.stoppedSpeed;return true;
    },"latest 125 did not become Ready before Resume");
    const auto readyDiagnostics=fixture.engine->getPlaybackDiagnostics();
    require(prepared->resumeInputFrame==*frozen.inputFrame&&prepared->sourceRenderEpoch==before.renderEpoch&&prepared->sourceSession==before.session&&prepared->loopID==fixture.loopID&&prepared->cycle==frozenLoop.cycles,"latest Ready inherited cancelled 75 A coordinates");
    require(!prepared->outputStarted&&!readyDiagnostics.retiringPipeline&&prepared->mode==progressive::SeekMode::Exact,"Ready preceded retirement or audio restart");
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    const auto after=fixture.engine->getStateSnapshot();require(after.stoppedSpeed&&after.stoppedSpeed->id==latest.id&&after.renderEpoch==prepared->renderEpoch&&after.state==State::Paused&&!after.resumePending&&fixture.capture->frames.load()==frames,"old published 75 revived after latest Ready");
    require(fixture.engine->getCurrentPlaybackPosition().inputFrame==frozen.inputFrame&&fixture.engine->getLoopSnapshot().cycles==frozenLoop.cycles,"latest Ready lost paused C/cycle");
    std::ofstream observation(folder/"cancelled_published.json");observation<<"{\"cancelled_playing_75_request\":"<<oldRequest.id<<",\"replacement_playing_125_request\":"<<replacement.id<<",\"latest_paused_125_request\":"<<latest.id
        <<",\"paused_request_duplicate\":"<<(latest.result==ts::prototype::Phase39RequestResult::Duplicate?"true":"false")<<",\"frozen_C\":"<<*frozen.inputFrame<<",\"frozen_epoch\":"<<before.renderEpoch<<",\"frozen_consumed\":"<<before.consumedFrames
        <<",\"ready_epoch\":"<<prepared->renderEpoch<<",\"ready_output_start\":"<<prepared->outputStartFrame<<",\"cycles\":"<<frozenLoop.cycles<<",\"resume_calls\":0,\"cancelled_A_owner_adopted\":false,\"independent_DSP_comparison\":\"NOT_RUN\"}\n";
    fixture.finish("cancelled_published_75_pause_latest_125");
}
}
int main(int argc,char** argv){
    if(argc!=4){std::cerr<<"INPUT candidate|baseline NEW_OUTPUT_DIR\n";return 1;}
    int code=1;std::thread owner([&]{std::filesystem::path output;bool owned=false;std::size_t executed=0;try{
        const std::filesystem::path input=std::filesystem::absolute(argv[1]);output=std::filesystem::absolute(argv[3]);require(std::filesystem::create_directories(output),"new output directory required");owned=true;
        const std::string presetName=argv[2];require(presetName=="candidate"||presetName=="baseline","preset");const auto preset=presetName=="candidate"?Preset::Candidate:Preset::Baseline;
        std::ofstream expected(output/"EXPECTED.json");expected<<"{\"suite\":\"phase62_dynamic_controls_native\",\"expected\":3,\"preset\":"<<phase58::jsonString(presetName)<<",\"input_sha256\":"<<phase58::jsonString(nativeControlHash(input))<<",\"binary_sha256\":"<<phase58::jsonString(nativeControlHash(std::filesystem::absolute(argv[0])))<<",\"input_A\":0,\"loop_millis\":8000,\"independent_DSP_comparison\":\"NOT_RUN\",\"real_audio\":true}\n";expected.close();
        phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* memory=allocate(37);release(memory);phase61_heap_end();
        require(phase61_heap_allocations()&&phase61_heap_frees(),"heap allocation/free detector self-test");
        committedLatest(input,preset,output/"latest_after_commit");++executed;committedClear(input,preset,output/"clear_after_commit");++executed;cancelledPublishedThenPause(input,preset,output/"cancelled_published_pause");++executed;
        require(executed==3,"native control final case count");
        std::ofstream result(output/"SUMMARY.json");result<<"{\"suite\":\"phase62_dynamic_controls_native\",\"expected\":3,\"executed\":"<<executed<<",\"status\":\"PASS\",\"independent_DSP_comparison\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\"}\n";result.close();std::ifstream report(output/"SUMMARY.json");std::cout<<report.rdbuf();code=0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';if(owned){std::ofstream result(output/"SUMMARY.json");result<<"{\"suite\":\"phase62_dynamic_controls_native\",\"expected\":3,\"executed\":"<<executed<<",\"status\":\"FAIL\",\"reason\":"<<phase58::jsonString(error.what())<<"}\n";}}});owner.join();return code;
}
