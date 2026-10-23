// Explicit AB preparation performance host. Normal control work is serialized.
#define TS_PHASE62_INITIAL_NO_MAIN 1
#include "Phase62InitialLoopNative.cpp"
#include <mach/mach_time.h>
namespace {
struct AbCapture {
    InitialCapture pcm;
    mach_timebase_info_data_t tb{};
    std::atomic<std::uint64_t> oldEpoch{0},firstA{0},firstAOutput{0},firstAEpoch{0};
    explicit AbCapture(std::size_t c,std::size_t r):pcm(c,r){mach_timebase_info(&tb);}
    std::uint64_t ns()const noexcept{return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*tb.numer/tb.denom);}
    static void raw(void* ctx,const float*const* p,std::size_t n,std::size_t at,std::uint64_t g,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& a=*static_cast<AbCapture*>(ctx);InitialCapture::raw(&a.pcm,p,n,at,g,epoch,session);
        if(n&&a.oldEpoch.load()&&epoch!=a.oldEpoch.load()){
            std::uint64_t zero=0;if(a.firstA.compare_exchange_strong(zero,a.ns())){a.firstAOutput=at;a.firstAEpoch=epoch;}
        }
    }
    static void output(void* ctx,const float*const* p,const ProgressiveOutputSpan& s)noexcept{InitialCapture::output(&static_cast<AbCapture*>(ctx)->pcm,p,s);}
};
int runAb(int argc,char** argv){
    require(argc==10,"input preset A_seconds duration_seconds speed fresh|prewarm|early_on Ready|Playing|Paused C_seconds NEW_OUTPUT");
    const std::string mode=argv[6],state=argv[7];require(mode=="fresh"||mode=="prewarm"||mode=="early_on","mode");require(state=="Ready"||state=="Playing"||state=="Paused","state");
    const std::filesystem::path out=argv[9];require(std::filesystem::create_directories(out),"fresh evidence required");
    ts::WavStreamReader w(argv[1]);const auto rate=w.sampleRate();const auto a=std::uint64_t(std::llround(std::stod(argv[3])*rate));const auto b=a+std::uint64_t(std::llround(std::stod(argv[4])*rate));const auto c=std::uint64_t(std::llround(std::stod(argv[8])*rate));
    require(b<=w.frames()&&c<=w.frames(),"input coordinates");
    AbCapture capture(w.channels(),rate);ProgressiveMacPlaybackEngine e;ProgressiveOptions o;
    o.preset=std::string(argv[2])=="baseline"?Preset::Baseline:Preset::Candidate;o.initialSpeed=std::stod(argv[5]);o.allowExperimentalLoops=true;o.seekCheckpoints=false;o.callbackRecordLimit=256;
    o.observerContext=&capture;o.observeEpochPcm=AbCapture::raw;o.observeOutputPcm=AbCapture::output;
    phase61_heap_reset();o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    std::ofstream plan(out/"EXPECTED.json");plan<<"{\"mode\":\""<<mode<<"\",\"state\":\""<<state<<"\",\"A\":"<<a<<",\"B\":"<<b<<",\"requested_C\":"<<c<<",\"seek_checkpoints\":false,\"cold_target_ms\":1000,\"warm_target_ms\":250,\"accepted_ids\":1,\"physical_audio\":null}\n";plan.close();
    const auto prepareBegin=capture.ns();require(e.prepare(argv[1],o),"prepare");initialWait(e,[&]{return e.getPlaybackState()==State::Ready;});const auto initialReady=capture.ns();initialWait(e,[&]{return e.getPlaybackDiagnostics().pipeline.analysisDone;});const auto analysisReady=capture.ns();
    if(c){auto s=e.getStateSnapshot();auto seek=e.requestSeekToInputFrame(c,s.inputGeneration,s.renderEpoch);require(seek.accepted,"initial C Exact seek");initialWait(e,[&]{return e.getSeekSnapshot().latest.state==progressive::SeekState::Completed;});}
    if(state!="Ready"){require(e.play(),"play at C");initialWait(e,[&]{return capture.pcm.rawFrames.load()!=0;});if(state=="Paused")require(e.pause(),"pause at C");}
    const auto before=e.getStateSnapshot();const auto position=e.getCurrentPlaybackPosition();progressive::LoopPreparationOperation prep;bool hasPreparation=false;
    if(mode!="fresh"){
        auto r=e.requestLoopPreparation(a,b,{before.inputGeneration,before.session,before.renderEpoch});require(r.accepted,r.reason.c_str());hasPreparation=true;
        initialWait(e,[&]{auto s=e.loopPreparationSnapshot();if(s.latest)prep=*s.latest;require(prep.state!=progressive::LoopPreparationState::Failed,prep.reason.c_str());return mode=="prewarm"?prep.state==progressive::LoopPreparationState::Ready:prep.state==progressive::LoopPreparationState::Preparing;});
    }
    const auto onState=e.getStateSnapshot();capture.oldEpoch=onState.renderEpoch;const auto onControl=capture.ns();auto receipt=e.requestLoopRange(a,b,{onState.inputGeneration,onState.session,onState.renderEpoch});require(receipt.accepted,receipt.reason.c_str());
    initialWait(e,[&]{auto l=e.getLoopSnapshot();require(l.state!=progressive::LoopState::Failed,l.reason.c_str());return l.initialPositionComplete;});const auto aligned=capture.ns();
    if(state=="Ready")require(e.play(),"explicit Play after Ready");else if(state=="Paused")require(e.getPlaybackState()==State::Paused&&e.resume(),"explicit Resume after Paused preparation");
    initialWait(e,[&]{return capture.firstA.load()!=0;});initialWait(e,[&]{return e.getLoopSnapshot().cycles>=2;});require(e.pause(),"pause after two natural boundaries");
    const auto l=e.getLoopSnapshot();const auto d=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();auto preparations=e.loopPreparationHistory();if(hasPreparation)prep=preparations.front();
    e.stop();const auto final=e.getPlaybackDiagnostics();initialSave(out,capture.pcm);writePhase62Trace(out/"callbacks.jsonl",e.loopCallbackRecords());writePhase62Trace(out/"clock_anomaly.jsonl",e.loopClockAnomalyRecords());
    const auto owners=ts::prototype::phase58::RealtimePipeline::executionOwnerCounts();
    require(!owners.alive&&owners.peak<=2&&d.pipeline.loopReuse.checkpointPeak<=2,"owner/checkpoint budget");
    require(!capture.pcm.errors&&!capture.pcm.nonfinite&&!capture.pcm.affected&&!final.missingFrames&&!final.rejectedWrites&&!final.underrunCalls&&!phase61_heap_allocations()&&!phase61_heap_frees()&&final.callbackCppNew&&!*final.callbackCppNew,"PCM/supply/callback audit");
    const bool hit=d.pipeline.loopReuse.initialCheckpointHit;
    if(mode=="fresh")require(!hit,"fresh was a checkpoint hit");if(mode=="prewarm")require(hit&&prep.workersJoined,"prewarm did not use the completed inert A state");
    const double delay=double(capture.firstA.load()-l.acceptedNs)/1e6;const bool eligible=state=="Playing";
    const bool rt=!n.deadlineMisses&&!final.workerDeadlineMisses&&!n.hostMissing&&!n.hostBackwards&&!n.hostCadenceErrors&&!n.sampleErrors&&!n.halWindowMisses&&!final.workgroupErrors;
    const bool target=eligible&&delay<=(mode=="prewarm"?250:1000);
    std::ofstream result(out/"SUMMARY.json");result<<std::setprecision(12)<<"{\"run_complete\":true,\"functional\":true,\"rt_pass\":"<<(rt?"true":"false")<<",\"performance_exercised\":"<<(eligible?"true":"false")<<",\"performance_pass\":"<<(target?"true":"false")<<",\"accepted_to_first_A_ms\":"<<delay<<",\"accepted_to_alignment_ms\":"<<double(aligned-l.acceptedNs)/1e6<<",\"control_to_native_accept_ms\":"<<double(l.acceptedNs-onControl)/1e6<<",\"prepare_total_to_ready_ms\":"<<double(initialReady-prepareBegin)/1e6<<",\"prepare_total_to_analysis_ms\":"<<double(analysisReady-prepareBegin)/1e6<<",\"first_A_output\":"<<capture.firstAOutput<<",\"first_A_epoch\":"<<capture.firstAEpoch<<",\"C_input\":"<<(position.inputFrame?std::to_string(*position.inputFrame):"null")<<",\"C_output\":"<<position.outputFrame<<",\"C_before_A\":"<<(position.inputFrame&&*position.inputFrame<a?"true":"false")<<",\"initial_checkpoint_hit\":"<<(hit?"true":"false")<<",\"checkpoint_start\":"<<d.pipeline.checkpointStartFrame<<",\"cold_discarded\":"<<d.pipeline.loopReuse.coldDiscardedFrames<<",\"cold_prefix_cpu_s\":"<<d.pipeline.loopReuse.coldPrefixCpuS<<",\"analysis_wait_s\":"<<d.pipeline.loopReuse.analysisWaitS<<",\"map_cpu_s\":"<<d.pipeline.loopReuse.mapCpuS<<",\"preparation_state\":\""<<progressive::name(prep.state)<<"\",\"preparation_cpu_s\":"<<prep.prefixCpuS<<",\"preparation_wall_s\":"<<prep.prefixWallS<<",\"preparation_discarded\":"<<prep.discardedFrames<<",\"preparation_joined\":"<<(prep.workersJoined?"true":"false")<<",\"owners_peak\":"<<owners.peak<<",\"checkpoint_peak\":"<<d.pipeline.loopReuse.checkpointPeak<<",\"device\":"<<n.deviceId<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"source_rate\":"<<rate<<",\"channels\":"<<w.channels()<<",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"sample_errors\":"<<n.sampleErrors<<",\"host_errors\":"<<n.hostMissing+n.hostBackwards+n.hostCadenceErrors<<",\"hal_misses\":"<<n.halWindowMisses<<",\"input_sha256\":\""<<final.pipeline.inputSha256<<"\",\"independent_pcm\":\"PENDING\",\"acoustic\":null}\n";
    return rt?0:2;
}
}
int main(int argc,char** argv){int code=1;std::thread q([&]{try{code=runAb(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});q.join();return code;}
