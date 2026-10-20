// LoopPcmAudit checks product RAW/correction arithmetic, not independent DSP.
#define main includedPhase62NativeMain
#include "Phase62NativeTests.cpp"
#undef main
#include "prototype/Phase45PcmDigest.h"

namespace {
namespace phase58=ts::prototype::phase58;
using SeekClock=std::chrono::steady_clock;
struct NativeSeekCapture {
    LoopPcmAudit audit;std::atomic<std::uint64_t> frames{0},naturalBs{0};
    explicit NativeSeekCapture(std::size_t channels):audit(channels){}
    static void raw(void* context,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        LoopPcmAudit::source(&static_cast<NativeSeekCapture*>(context)->audit,pcm,n,at,generation,epoch,session);
    }
    static void output(void* context,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& capture=*static_cast<NativeSeekCapture*>(context);LoopPcmAudit::output(&capture.audit,pcm,span);capture.frames.fetch_add(span.frames,std::memory_order_relaxed);
        if(span.periodicBoundary&&span.periodOffset+span.frames==span.periodFrames)capture.naturalBs.fetch_add(1,std::memory_order_relaxed);
    }
};
std::string seekFileSha(const std::filesystem::path& path){
    std::ifstream file(path,std::ios::binary);require(bool(file),"SHA input missing");ts::prototype::Phase45PcmDigest digest;std::array<char,65536> block{};
    while(file.read(block.data(),block.size())||file.gcount())digest.update(block.data(),std::size_t(file.gcount()));
    require(file.eof(),"SHA input read failed");return digest.finish();
}
struct NativeSeekFixture {
    const std::filesystem::path input,output;ts::WavStreamReader wav;std::unique_ptr<NativeSeekCapture> capture;ProgressiveOptions options;ProgressiveMacPlaybackEngine engine;
    std::uint64_t loopID=0,b=0,inputGeneration=0;std::size_t baselineSeeks=0,userSeeks=0,executed=0,r0Cases=0,speedPreparations=0;std::size_t* ledgerExecuted=nullptr;
    const bool r0Only;const std::size_t expected;
    NativeSeekFixture(const std::filesystem::path& source,Preset preset,const std::filesystem::path& folder,std::uint64_t r0B=0):input(source),output(folder),wav(source),capture(std::make_unique<NativeSeekCapture>(wav.channels())),r0Only(r0B!=0),expected(r0Only?1:21){
        require(wav.frames()>=std::uint64_t(wav.sampleRate())*9,"seek API requires input >=9 seconds");b=r0B?r0B:std::uint64_t(wav.sampleRate())*8;require(b<=wav.frames()&&b>=wav.sampleRate()/10,"R0 fixture B outside executable Loop range");
        options.initialSpeed=1;options.preset=preset;options.allowExperimentalLoops=true;options.allowUnvalidatedFastLocalSeek=true;options.callbackRecordLimit=4096;
        options.observerContext=capture.get();options.observeEpochPcm=NativeSeekCapture::raw;options.observeOutputPcm=NativeSeekCapture::output;
        options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
        phase61_heap_reset();engine.prepare(input,options);wait(engine,State::Ready);auto state=engine.getStateSnapshot();inputGeneration=state.inputGeneration;
        const auto receipt=engine.requestLoopRange(0,b,{state.inputGeneration,state.session,state.renderEpoch});require(receipt.accepted,"initial [0,8s) ReturnToA rejected");loopID=receipt.id;
        until([&]{return engine.getLoopSnapshot().initialPositionComplete&&!engine.getPlaybackDiagnostics().retiringPipeline;},"initial Loop preparation");
        baselineSeeks=engine.seekHistory().size();require(engine.play(),"initial play");firstPcm(engine);until([&]{return capture->frames.load()>=2048;},"initial PCM");require(engine.pause(),"initial pause");
    }
    ~NativeSeekFixture(){engine.stop();}
    void healthy(){
        const auto state=engine.getStateSnapshot();if(state.state==State::Failed)throw std::runtime_error(state.error);
        require(phase58::RealtimePipeline::executionOwnerCounts().peak<=2,"third execution owner");
    }
    template<class P> void until(P predicate,const char* reason){
        const auto deadline=SeekClock::now()+std::chrono::seconds(60);while(!predicate()){healthy();require(SeekClock::now()<deadline,reason);std::this_thread::sleep_for(std::chrono::milliseconds(1));}healthy();
    }
    void prepareSpeed(unsigned speed){
        require(engine.getPlaybackState()==State::Paused,"speed preparation needs Paused");const auto frozen=engine.getCurrentPlaybackPosition();require(frozen.inputFrame.has_value(),"missing paused C");
        const auto before=engine.getPlaybackDiagnostics();const auto frames=capture->frames.load(),cycles=engine.getLoopSnapshot().cycles;const auto seeks=engine.seekHistory().size();
        const auto receipt=engine.setSpeed(speed/1000000.);require((receipt.result==ts::prototype::Phase39RequestResult::Accepted||receipt.result==ts::prototype::Phase39RequestResult::Duplicate)&&receipt.id,"paused Exact speed preparation rejected");
        until([&]{
            const auto state=engine.getStateSnapshot();const auto diagnostics=engine.getPlaybackDiagnostics();const auto loop=engine.getLoopSnapshot();const auto position=engine.getCurrentPlaybackPosition();
            require(state.state==State::Paused&&!state.resumePending&&capture->frames.load()==frames&&loop.cycles==cycles&&loop.id==loopID,"paused speed preparation emitted output or changed loop");
            require(position.inputFrame==frozen.inputFrame&&engine.seekHistory().size()==seeks,"speed preparation moved C or fabricated user seek");
            if(diagnostics.renderEpoch==before.renderEpoch)require(diagnostics.consumedFrames==before.consumedFrames,"old FIFO consumed while Paused");
            else require(diagnostics.consumedFrames==diagnostics.pipeline.outputStartFrame&&diagnostics.currentEpochPresentedFrame==diagnostics.pipeline.outputStartFrame,"new FIFO consumed before Resume");
            require(state.stoppedSpeed&&state.stoppedSpeed->id==receipt.id&&state.stoppedSpeed->speedMicros==speed,"paused speed identity mismatch");
            require(state.stoppedSpeed->state!=StoppedSpeedState::Failed,"paused speed preparation failed");
            return state.stoppedSpeed->state==StoppedSpeedState::ReadyForResume&&!diagnostics.retiringPipeline;
        },"paused speed Ready before Resume");
        const auto prepared=*engine.getStateSnapshot().stoppedSpeed;require(prepared.mode==progressive::SeekMode::Exact&&!prepared.outputStarted,"paused speed preparation is not unplayed Exact");
        std::ofstream preparation(output/"preparations.jsonl",std::ios::app);preparation<<"{\"speed_micros\":"<<speed<<",\"id\":"<<prepared.id<<",\"resume_C\":"<<prepared.resumeInputFrame<<",\"ready_epoch\":"<<prepared.renderEpoch<<",\"loop_id\":"<<prepared.loopID<<",\"cycle\":"<<prepared.cycle<<",\"Ready_before_Resume\":true,\"user_seek_rows_added\":0,\"status\":\"PASS\"}\n";++speedPreparations;
    }
    progressive::SeekReceipt request(std::uint64_t frame,const std::string& api){
        const auto state=engine.getStateSnapshot();
        if(api=="FastLocal")return engine.requestFastLocalSeekToInputFrame(frame,state.inputGeneration,state.renderEpoch,500);
        if(api=="Interactive")return engine.requestInteractiveSeekToInputFrame(frame,state.inputGeneration,state.renderEpoch,state.session);
        return engine.requestSeekToInputFrame(frame,state.inputGeneration,state.renderEpoch);
    }
    void one(unsigned speed,const char* label,std::uint64_t requested,const std::string& api){
        require(engine.getPlaybackState()==State::Paused,"seek case must begin Paused");
        const auto before=engine.getPlaybackDiagnostics();const auto frames=capture->frames.load(),cycles=engine.getLoopSnapshot().cycles,natural=capture->naturalBs.load();
        const auto seeks=engine.seekHistory().size();const std::uint64_t acceptedC=requested>=b?0:requested;const auto receipt=request(requested,api);require(receipt.accepted,"user seek rejected");++userSeeks;
        require(engine.seekHistory().size()==seeks+1,"accepted API call did not add exactly one user seek");
        until([&]{
            const auto state=engine.getStateSnapshot();const auto diagnostics=engine.getPlaybackDiagnostics();const auto loop=engine.getLoopSnapshot();const auto seek=engine.getSeekSnapshot().latest;
            require(state.state==State::Paused&&!state.resumePending&&capture->frames.load()==frames&&loop.cycles==cycles&&capture->naturalBs.load()==natural,"seek preparation advanced paused output or cycles");
            require(loop.id==loopID&&loop.enabled&&state.inputGeneration==inputGeneration,"seek changed Loop or input identity");
            require(seek.id==receipt.id&&seek.state!=progressive::SeekState::Failed&&seek.state!=progressive::SeekState::Cancelled&&seek.state!=progressive::SeekState::Replaced,"accepted seek was lost");
            if(diagnostics.renderEpoch==before.renderEpoch)require(diagnostics.consumedFrames==before.consumedFrames,"old epoch consumed during seek");
            else require(diagnostics.consumedFrames==diagnostics.pipeline.outputStartFrame&&diagnostics.currentEpochPresentedFrame==diagnostics.pipeline.outputStartFrame,"new seek epoch consumed while Paused");
            const bool speedReady=!state.stoppedSpeed||state.stoppedSpeed->outputStarted||state.stoppedSpeed->state!=StoppedSpeedState::Preparing;
            return seek.state==progressive::SeekState::Completed&&!diagnostics.retiringPipeline&&speedReady;
        },"paused user seek completion/retirement");
        const auto operation=engine.getSeekSnapshot().latest;const auto position=engine.getCurrentPlaybackPosition();const auto ready=engine.getPlaybackDiagnostics();const auto loop=engine.getLoopSnapshot();
        require(operation.requestedInputFrame==acceptedC&&position.inputFrame&&*position.inputFrame==acceptedC,"requested C not preserved or B/outside not corrected to A");
        require(operation.mode==progressive::SeekMode::Exact&&operation.speedMicros==speed,"adopted seek mode/speed differs");
        if(api!="Exact")require(!operation.reason.empty()&&operation.reason.find("Exact")!=std::string::npos,"FastLocal/Interactive did not report actual Exact fallback");
        require(operation.outputStartFrame==ready.pipeline.outputStartFrame&&ready.consumedFrames==operation.outputStartFrame,"unconsumed seek output coordinate differs");
        const auto length=loop.periodFrames;require(length>=512&&operation.outputStartFrame<=length,"actual fixed Map loop range invalid");
        const auto remaining=length-operation.outputStartFrame;if(!remaining)++r0Cases;
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
        require(engine.getPlaybackState()==State::Paused&&capture->frames.load()==frames&&engine.getLoopSnapshot().cycles==cycles&&engine.getCurrentPlaybackPosition().inputFrame==acceptedC,"paused seek completion auto-played or lost C");
        require(engine.resume(),"seek case Resume rejected");std::this_thread::sleep_for(std::chrono::milliseconds(50));require(engine.pause(),"seek case final Pause");
        const auto after=engine.getPlaybackDiagnostics();const auto afterLoop=engine.getLoopSnapshot();const auto emitted=capture->frames.load()-frames;
        require(emitted>0,"Resume emitted no PCM");
        // The frame count is measured; no promise is tied to wall-clock 50 ms.
        // R=0 is a zero-PCM initial connection to A, never an initial cycle.
        const auto expectedBs=remaining?(emitted<remaining?0:1+(emitted-remaining)/length):emitted/length;
        const auto expectedPosition=remaining&&emitted<remaining?operation.outputStartFrame+emitted:(remaining?(emitted-remaining)%length:emitted%length);
        require(afterLoop.cycles-cycles==expectedBs&&capture->naturalBs.load()-natural==expectedBs,"natural B count differs from actual Map R and emitted PCM");
        require(after.consumedFrames==expectedPosition&&after.currentEpochPresentedFrame==expectedPosition,"post-Resume period position differs from actual PCM frame count");
        require(engine.seekHistory().size()==seeks+1&&engine.seekHistory().size()==baselineSeeks+userSeeks,"internal preparation/loop added user seek rows");
        require(afterLoop.id==loopID&&afterLoop.enabled&&after.inputGeneration==inputGeneration,"Resume lost Loop/input identity");
        std::ofstream row(output/"cases.jsonl",std::ios::app);row<<"{\"case\":"<<phase58::jsonString(label)<<",\"requested_API\":"<<phase58::jsonString(api)<<",\"adopted_mode\":\"Exact\",\"adopted_reason\":"<<phase58::jsonString(operation.reason)
            <<",\"speed_micros\":"<<speed<<",\"user_seek_id\":"<<receipt.id<<",\"supplied_input\":"<<requested<<",\"accepted_C\":"<<operation.requestedInputFrame<<",\"observed_paused_C\":"<<*position.inputFrame
            <<",\"output_start\":"<<operation.outputStartFrame<<",\"actual_Map_R\":"<<remaining<<",\"actual_Map_L\":"<<length<<",\"R0_realized\":"<<(!remaining?"true":"false")
            <<",\"measured_Resume_PCM_frames\":"<<emitted<<",\"expected_natural_Bs\":"<<expectedBs<<",\"observed_natural_Bs\":"<<afterLoop.cycles-cycles<<",\"post_pause_output\":"<<after.consumedFrames
            <<",\"explicit_user_seek_count\":"<<userSeeks<<",\"discarded_for_user_seek_frames\":"<<operation.discardedForSeekFrames<<",\"internal_seek_rows_added\":0,\"independent_DSP_comparison\":\"NOT_RUN\",\"status\":\"PASS\"}\n";row.close();++executed;if(ledgerExecuted)*ledgerExecuted=executed;
    }
    void run(){
        if(r0Only){prepareSpeed(2000000);one(2000000,"B_minus_1_R0",b-1,"Exact");require(r0Cases==1,"independent fixture did not realize actual R=0");return;}
        for(unsigned speed:{400000u,1000000u,2000000u}){
            prepareSpeed(speed);
            one(speed,"B_minus_1",b-1,"Exact");one(speed,"B",b,"Exact");one(speed,"B_plus_1",b+1,"Exact");one(speed,"A",0,"Exact");one(speed,"midpoint",b/2,"Exact");
            one(speed,"B_minus_1_fastlocal",b-1,"FastLocal");one(speed,"B_minus_1_interactive",b-1,"Interactive");
        }
    }
    void finish(){
        require(executed==expected&&userSeeks==expected&&speedPreparations==(r0Only?1u:3u),"expected/executed user seek count");const auto diagnostics=engine.getPlaybackDiagnostics();const auto native=engine.getNativeDiagnostics();engine.stop();
        require(!capture->audit.errors&&!capture->audit.nonfinite,"product RAW/correction audit failed");require(!diagnostics.missingFrames&&!diagnostics.underrunCalls&&!diagnostics.rejectedWrites,"unexpected FIFO supply failure");
        require(diagnostics.callbackCppNew&&!*diagnostics.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback allocation/free");
        const auto owners=phase58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"owner cap/retirement");
        writePhase62Trace(output/"callbacks_all_spans.jsonl",engine.loopCallbackRecords());writePhase62Trace(output/"clock_anomaly_window.jsonl",engine.loopClockAnomalyRecords());
        std::ofstream result(output/"SUMMARY.json");result<<"{\"suite\":\"phase62_dynamic_seek_API\",\"expected\":"<<expected<<",\"executed\":"<<executed<<",\"paused_Exact_speed_preparations_expected\":"<<(r0Only?1:3)<<",\"paused_Exact_speed_preparations_executed\":"<<speedPreparations<<",\"explicit_user_seeks\":"<<userSeeks<<",\"internal_seek_rows_added\":0,\"status\":\"PASS\",\"R0_cases\":"<<r0Cases
            <<",\"R0_fixture_status\":"<<phase58::jsonString(r0Cases?"REALIZED":"NOT_REALIZED_IN_THIS_INPUT_AND_8_SECOND_RANGE")<<",\"raw_mix_errors\":"<<capture->audit.errors<<",\"nonfinite\":"<<capture->audit.nonfinite
            <<",\"owner_peak\":"<<owners.peak<<",\"callback_cpp_new\":"<<*diagnostics.callbackCppNew<<",\"callback_heap_calls\":"<<phase61_heap_allocations()<<",\"callback_heap_frees\":"<<phase61_heap_frees()
            <<",\"callback_deadlines_observed\":"<<native.deadlineMisses<<",\"worker_deadlines_observed\":"<<diagnostics.workerDeadlineMisses<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames
            <<",\"source_rate\":"<<wav.sampleRate()<<",\"independent_DSP_comparison\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"physical_loopback\":\"NOT_RUN\"}\n";result.close();
    }
};
}
int main(int argc,char** argv){
    if(argc!=4&&argc!=5){std::cerr<<"INPUT candidate|baseline NEW_OUTPUT_DIR [R0_INPUT_B]\n";return 1;}
    int code=1;std::thread owner([&]{std::filesystem::path output;bool owned=false;std::size_t executed=0;const auto expectedCases=argc==5?1:21;std::uint64_t r0B=0;try{
        if(argc==5)r0B=std::stoull(argv[4]);
        const auto input=std::filesystem::absolute(argv[1]);output=std::filesystem::absolute(argv[3]);require(std::filesystem::create_directories(output),"new output directory required");owned=true;
        const std::string presetName=argv[2];require(presetName=="candidate"||presetName=="baseline","preset");const auto preset=presetName=="candidate"?Preset::Candidate:Preset::Baseline;
        std::ofstream expected(output/"EXPECTED.json");expected<<"{\"suite\":\"phase62_dynamic_seek_API\",\"expected\":"<<expectedCases<<",\"speeds_micros\":"<<(r0B?"[2000000]":"[400000,1000000,2000000]")<<",\"Exact_positions\":"<<(r0B?"[\"B-1\"]":"[\"B-1\",\"B\",\"B+1\",\"A\",\"midpoint\"]")<<",\"B_minus_1_extra_APIs\":"<<(r0B?"[]":"[\"FastLocal\",\"Interactive\"]")<<",\"input_A\":0,\"R0_only\":"<<(r0B?"true":"false")<<",\"preset\":"<<phase58::jsonString(presetName)
            <<",\"input_sha256\":"<<phase58::jsonString(seekFileSha(input))<<",\"binary_sha256\":"<<phase58::jsonString(seekFileSha(std::filesystem::absolute(argv[0])))<<",\"independent_DSP_comparison\":\"NOT_RUN\",\"actual_Map_R_and_L_only\":true,\"real_audio\":true}\n";expected.close();
        phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* memory=allocate(37);release(memory);phase61_heap_end();require(phase61_heap_allocations()&&phase61_heap_frees(),"heap probe self-test");
        NativeSeekFixture test(input,preset,output,r0B);test.ledgerExecuted=&executed;test.run();test.finish();std::ifstream report(output/"SUMMARY.json");std::cout<<report.rdbuf();code=0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';if(owned){std::ofstream result(output/"SUMMARY.json");result<<"{\"suite\":\"phase62_dynamic_seek_API\",\"expected\":"<<expectedCases<<",\"executed\":"<<executed<<",\"status\":\"FAIL\",\"reason\":"<<phase58::jsonString(error.what())<<"}\n";}}});owner.join();return code;
}
