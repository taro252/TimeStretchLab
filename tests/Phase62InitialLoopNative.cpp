// 初回OFF→ABを測る通常制御host。実出力は他の性能試験と直列に実行する。
#define main phase62InitialIncludedMain
#include "Phase62NativeTests.cpp"
#undef main
#include <iomanip>
namespace {
using InitialClock=std::chrono::steady_clock;
std::uint64_t initialNs(){return std::chrono::duration_cast<std::chrono::nanoseconds>(InitialClock::now().time_since_epoch()).count();}
struct InitialRaw {std::uint64_t session=0,epoch=0,at=0,count=0,offset=0;};
struct InitialCapture {
    std::size_t channels;std::vector<float> rawPcm,outputPcm;
    std::vector<InitialRaw> rawRecords;std::vector<ProgressiveOutputSpan> spans;
    std::atomic<std::size_t> rawFrames{0},outputFrames{0},rawCount{0},spanCount{0},errors{0},nonfinite{0},affected{0};
    std::atomic<std::uint64_t> firstNs{0};
    explicit InitialCapture(std::size_t ch,std::size_t rate):channels(ch),rawPcm(rate*40*ch),outputPcm(rate*40*ch),rawRecords(8192),spans(8192){}
    static void raw(void* ctx,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& c=*static_cast<InitialCapture*>(ctx);auto frames=c.rawFrames.load();auto index=c.rawCount.load();
        if(index>=c.rawRecords.size()||frames+n>c.rawPcm.size()/c.channels){++c.errors;return;}
        c.rawRecords[index]={session,epoch,at,n,frames};
        for(std::size_t i=0;i<n;++i)for(std::size_t ch=0;ch<c.channels;++ch){const auto v=pcm[ch][i];c.rawPcm[(frames+i)*c.channels+ch]=v;if(!std::isfinite(v))++c.nonfinite;}
        std::uint64_t zero=0;c.firstNs.compare_exchange_strong(zero,initialNs());c.rawFrames=frames+n;c.rawCount=index+1;
    }
    static void output(void* ctx,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& c=*static_cast<InitialCapture*>(ctx);const auto frames=c.outputFrames.load(),index=c.spanCount.load();
        if(index>=c.spans.size()||frames+span.frames>c.outputPcm.size()/c.channels){++c.errors;return;}
        c.spans[index]=span;c.affected+=span.outputAffectedFrames+span.failurePaddingFrames;
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t ch=0;ch<c.channels;++ch){const auto v=pcm[ch][i];c.outputPcm[(frames+i)*c.channels+ch]=v;if(!std::isfinite(v))++c.nonfinite;}
        c.outputFrames=frames+span.frames;c.spanCount=index+1;
    }
};
template<class F>void initialWait(ProgressiveMacPlaybackEngine& e,F f){const auto deadline=InitialClock::now()+std::chrono::seconds(180);while(!f()){const auto s=e.getStateSnapshot();require(s.state!=State::Failed,s.error.c_str());require(InitialClock::now()<deadline,"initial Loop watchdog");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
void initialSave(const std::filesystem::path& folder,InitialCapture& capture){
    std::ofstream raw(folder/"raw.f32",std::ios::binary),output(folder/"output_before_gain.f32",std::ios::binary);
    raw.write(reinterpret_cast<const char*>(capture.rawPcm.data()),capture.rawFrames.load()*capture.channels*4);
    output.write(reinterpret_cast<const char*>(capture.outputPcm.data()),capture.outputFrames.load()*capture.channels*4);
    std::ofstream records(folder/"raw_records.jsonl"),spans(folder/"spans.jsonl");
    for(std::size_t i=0;i<capture.rawCount;++i){const auto& r=capture.rawRecords[i];records<<"{\"session\":"<<r.session<<",\"epoch\":"<<r.epoch<<",\"at\":"<<r.at<<",\"frames\":"<<r.count<<",\"raw_offset\":"<<r.offset<<"}\n";}
    for(std::size_t i=0;i<capture.spanCount;++i){const auto& s=capture.spans[i];spans<<"{\"callback_frame\":"<<s.callbackFrame<<",\"new_epoch\":"<<s.newEpoch<<",\"old_epoch\":"<<s.oldEpoch<<",\"new_at\":"<<s.newOutputOffset<<",\"old_at\":"<<s.oldOutputOffset<<",\"frames\":"<<s.frames<<",\"new_received\":"<<s.newReceivedFrames<<",\"old_received\":"<<s.oldReceivedFrames<<",\"mixed\":"<<s.mixedFrames<<",\"transition_offset\":"<<s.transitionOffset<<",\"transition_length\":"<<s.transitionLength
        <<",\"periodic\":"<<s.periodicBoundary<<",\"head\":"<<s.correctionHead<<",\"tail\":"<<s.correctionTail<<",\"boundary_frames\":"<<s.boundaryFrames<<",\"period_frames\":"<<s.periodFrames<<",\"period_offset\":"<<s.periodOffset<<",\"boundary_last\":["<<std::setprecision(9)<<s.boundaryLast[0]<<','<<s.boundaryLast[1]<<"],\"boundary_first\":["<<s.boundaryFirst[0]<<','<<s.boundaryFirst[1]<<"],\"correction_before_mix\":"<<s.correctionBeforeMix<<",\"old_periodic\":"<<s.oldPeriodicBoundary<<",\"old_head\":"<<s.oldCorrectionHead<<",\"old_tail\":"<<s.oldCorrectionTail<<",\"old_boundary_frames\":"<<s.oldBoundaryFrames<<",\"old_period_frames\":"<<s.oldPeriodFrames<<",\"old_period_offset\":"<<s.oldPeriodOffset<<",\"old_boundary_last\":["<<s.oldBoundaryLast[0]<<','<<s.oldBoundaryLast[1]<<"],\"old_boundary_first\":["<<s.oldBoundaryFirst[0]<<','<<s.oldBoundaryFirst[1]<<"]}\n";}
    raw.close();output.close();records.close();spans.close();require(bool(raw)&&bool(output)&&bool(records)&&bool(spans),"initial capture export");
}
int initialLoopMain(int argc,char** argv){
    require(argc==10,"input preset A_seconds duration_seconds repeats early|final quality_cycles speed NEW_OUTPUT");
    const std::filesystem::path folder=argv[9];require(std::filesystem::create_directories(folder),"fresh output required");
    ts::WavStreamReader wav(argv[1]);const auto a=std::uint64_t(std::llround(std::stod(argv[3])*wav.sampleRate())),b=a+std::uint64_t(std::llround(std::stod(argv[4])*wav.sampleRate()));
    const auto repeats=std::stoul(argv[5]),qualityCycles=std::stoul(argv[7]);const auto speed=std::stod(argv[8]);require(repeats>0&&repeats<=4&&qualityCycles<=3&&b<=wav.frames(),"bounded initial conditions");
    InitialCapture capture(wav.channels(),wav.sampleRate());ProgressiveOptions options;options.preset=std::string(argv[2])=="baseline"?Preset::Baseline:Preset::Candidate;options.initialSpeed=speed;options.allowExperimentalLoops=true;options.callbackRecordLimit=256;
    options.observerContext=&capture;options.observeEpochPcm=InitialCapture::raw;options.observeOutputPcm=InitialCapture::output;
    phase61_heap_reset();options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    std::ofstream expected(folder/"EXPECTED.json");expected<<"{\"expected\":"<<repeats<<",\"A\":"<<a<<",\"B\":"<<b<<",\"speed\":"<<speed<<",\"quality_cycles\":"<<qualityCycles<<",\"analysis_policy\":\""<<argv[6]<<"\",\"clock\":\"accepted/Ready ns: native machNs; control alignment and PCM: steady_clock ns; no cross-clock subtraction\"}\n";expected.close();
    ProgressiveMacPlaybackEngine engine;require(engine.prepare(argv[1],options),"prepare");initialWait(engine,[&]{return engine.getPlaybackState()==State::Ready;});
    if(std::string(argv[6])=="final")initialWait(engine,[&]{return engine.getPlaybackDiagnostics().pipeline.analysisDoneS>=0;});
    std::ofstream rows(folder/"measurements.jsonl");
    for(std::size_t round=0;round<repeats;++round){
        const auto before=engine.getStateSnapshot();const auto analysisComplete=engine.getPlaybackDiagnostics().pipeline.analysisDoneS>=0;const auto controlAt=initialNs();
        const auto receipt=engine.requestLoopRange(a,b,{before.inputGeneration,before.session,before.renderEpoch});require(receipt.accepted,receipt.reason.c_str());
        initialWait(engine,[&]{const auto l=engine.getLoopSnapshot();require(l.state!=progressive::LoopState::Failed,l.reason.c_str());return l.initialPositionComplete;});
        const auto alignedAt=initialNs();const auto l=engine.getLoopSnapshot();const auto d=engine.getPlaybackDiagnostics();const auto pos=engine.getCurrentPlaybackPosition();const auto n=engine.getNativeDiagnostics();
        require(pos.inputFrame&&*pos.inputFrame==a,"ReturnToA did not align to A");const auto rawBefore=capture.rawFrames.load(),outBefore=capture.outputFrames.load();
        std::this_thread::sleep_for(std::chrono::milliseconds(30));require(engine.getCurrentPlaybackPosition().inputFrame==pos.inputFrame&&capture.rawFrames==rawBefore&&capture.outputFrames==outBefore&&engine.getLoopSnapshot().cycles==0,"Ready/Paused aligned A advanced without Play");
        capture.firstNs=0;const auto playAt=initialNs();require(engine.play(),"explicit play");initialWait(engine,[&]{return capture.firstNs.load()!=0;});
        if(qualityCycles)initialWait(engine,[&]{return engine.getLoopSnapshot().cycles>=qualityCycles;});
        require(engine.pause(),"pause after initial PCM");const auto after=engine.getPlaybackDiagnostics();const auto reuse=d.pipeline.loopReuse;
        rows<<std::setprecision(12)<<"{\"round\":"<<round<<",\"cache_condition\":\""<<(round?"same_prepare_re_request":"fresh_prepare")<<"\",\"input_generation\":"<<before.inputGeneration<<",\"loop_id\":"<<receipt.id<<",\"session\":"<<d.session<<",\"epoch\":"<<d.renderEpoch<<",\"final_analysis_before_request\":"<<analysisComplete<<",\"accepted_to_ready_s\":"<<double(l.lastReadyNs-l.acceptedNs)/1e9<<",\"accepted_to_A_alignment_s\":"<<double(alignedAt-controlAt)/1e9<<",\"Ready_observed_to_first_A_PCM_s\":"<<double(capture.firstNs.load()-alignedAt)/1e9<<",\"explicit_Play_to_first_A_PCM_s\":"<<double(capture.firstNs.load()-playAt)/1e9<<",\"analysis_wait_s\":"<<reuse.analysisWaitS<<",\"map_cpu_s\":"<<reuse.mapCpuS<<",\"cold_prefix_s\":"<<reuse.coldPrefixS<<",\"cold_prefix_cpu_s\":"<<reuse.coldPrefixCpuS<<",\"cold_discarded_frames\":"<<reuse.coldDiscardedFrames<<",\"seed_output\":"<<reuse.seedOutput<<",\"checkpoint_start\":"<<d.pipeline.checkpointStartFrame<<",\"checkpoint_peak\":"<<reuse.checkpointPeak<<",\"period_frames\":"<<l.periodFrames<<",\"output_start\":"<<d.pipeline.outputStartFrame<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"raw_begin\":"<<rawBefore<<",\"raw_end\":"<<capture.rawFrames<<",\"output_begin\":"<<outBefore<<",\"output_end\":"<<capture.outputFrames<<",\"cycles\":"<<engine.getLoopSnapshot().cycles<<",\"missing\":"<<after.missingFrames<<",\"callback_new\":"<<after.callbackCppNew.value_or(UINT64_MAX)<<"}\n";rows.flush();
        if(round+1<repeats){const auto s=engine.getStateSnapshot();const auto clear=engine.requestClearLoop(receipt.id,{s.inputGeneration,s.session,s.renderEpoch});require(clear.accepted,clear.reason.c_str());initialWait(engine,[&]{return !engine.getLoopSnapshot().clearPending;});require(engine.getPlaybackState()==State::Paused,"Clear auto-resumed");}
    }
    const auto diag=engine.getPlaybackDiagnostics();engine.stop();initialSave(folder,capture);
    const auto owners=ts::prototype::phase58::RealtimePipeline::executionOwnerCounts();require(!capture.errors&&!capture.nonfinite&&!capture.affected&&!diag.missingFrames&&!diag.rejectedWrites&&diag.callbackCppNew.has_value()&&*diag.callbackCppNew==0&&!phase61_heap_allocations()&&!phase61_heap_frees()&&!owners.alive&&owners.peak<=2,"PCM/supply/owner audit");
    std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"status\":\"PASS\",\"run_complete\":true,\"expected\":"<<repeats<<",\"executed\":"<<repeats<<",\"raw_records\":"<<capture.rawCount<<",\"output_spans\":"<<capture.spanCount<<",\"raw_frames\":"<<capture.rawFrames<<",\"output_frames\":"<<capture.outputFrames<<",\"owners_peak\":"<<owners.peak<<",\"owners_alive\":"<<owners.alive<<",\"RT_deadline_approval\":\"NOT_ASSESSED\"}\n";return 0;
}
}
int main(int argc,char** argv){int code=1;std::thread owner([&]{try{code=initialLoopMain(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});owner.join();return code;}
