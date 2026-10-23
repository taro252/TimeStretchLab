// 同一prepareのOFF->ONを通常制御threadで測る。有限callback観測は事前確保。
#define TS_PHASE62_INITIAL_NO_MAIN
#include "Phase62InitialLoopNative.cpp"
#undef TS_PHASE62_INITIAL_NO_MAIN
#include <set>
namespace {
struct WarmCapture {
    InitialCapture pcm;std::atomic<std::uint64_t> afterSession{0},firstSession{0},firstAt{0},firstTime{0};
    WarmCapture(std::size_t ch,std::size_t rate):pcm(ch,rate){}
    static void raw(void* ctx,const float*const* p,std::size_t n,std::size_t at,std::uint64_t g,std::uint64_t e,std::uint64_t s)noexcept{
        auto& c=*static_cast<WarmCapture*>(ctx);InitialCapture::raw(&c.pcm,p,n,at,g,e,s);
        if(n&&s>c.afterSession.load(std::memory_order_acquire)&&c.afterSession.load()){
            std::uint64_t zero=0;if(c.firstSession.compare_exchange_strong(zero,s)){c.firstAt=at;c.firstTime.store(initialNs(),std::memory_order_release);}}
    }
    static void output(void* ctx,const float*const* p,const ProgressiveOutputSpan& span)noexcept{InitialCapture::output(&static_cast<WarmCapture*>(ctx)->pcm,p,span);}
};
int warmMain(int argc,char** argv){
    require(argc==6,"INPUT serial|replace A_seconds NEW_OUT SOURCE_SHA");const std::string mode=argv[2];require(mode=="serial"||mode=="replace","mode");
    const std::filesystem::path out=argv[4];require(std::filesystem::create_directories(out),"fresh output");ts::WavStreamReader wav(argv[1]);const auto a=std::uint64_t(std::llround(std::stod(argv[3])*wav.sampleRate())),b=a+2*wav.sampleRate();require(b<wav.frames(),"range");
    WarmCapture capture(wav.channels(),wav.sampleRate());ProgressiveOptions o;o.allowExperimentalLoops=true;o.preset=Preset::Candidate;o.initialSpeed=1;o.callbackRecordLimit=256;o.observerContext=&capture;o.observeEpochPcm=WarmCapture::raw;o.observeOutputPcm=WarmCapture::output;
    phase61_heap_reset();o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    {std::ofstream f(out/"EXPECTED.json");f<<"{\"expected\":1,\"A\":"<<a<<",\"B\":"<<b<<",\"mode\":\""<<mode<<"\",\"source\":\""<<argv[5]<<"\",\"preset\":\"candidate\",\"speed\":1,\"separate_cold_initial\":true,\"callback_gate\":false}\n";}
    ProgressiveMacPlaybackEngine e;require(e.prepare(argv[1],o),"prepare");initialWait(e,[&]{return e.getPlaybackState()==State::Ready;});initialWait(e,[&]{return e.getPlaybackDiagnostics().pipeline.analysisDoneS>=0;});
    auto c=e.getStateSnapshot();const auto coldBegin=initialNs();auto r=e.requestLoopRange(a,b,{c.inputGeneration,c.session,c.renderEpoch});require(r.accepted,"initial request");initialWait(e,[&]{return e.getLoopSnapshot().initialPositionComplete&&!e.getPlaybackDiagnostics().retiringPipeline;});const auto coldEnd=initialNs();
    require(e.play(),"play");initialWait(e,[&]{return capture.pcm.rawFrames>0;});std::this_thread::sleep_for(std::chrono::milliseconds(400));
    const auto oldSession=e.getStateSnapshot().session;const auto offBegin=initialNs();c=e.getStateSnapshot();require(e.requestClearLoop(r.id,{c.inputGeneration,c.session,c.renderEpoch}).accepted,"Clear");const auto offReceipt=initialNs();
    // 同一のクリック間隔。serial側だけclearPendingを待つ既存接続を再現。
    std::this_thread::sleep_for(std::chrono::milliseconds(100));const auto onIntent=initialNs();
    if(mode=="serial")initialWait(e,[&]{return !e.getLoopSnapshot().clearPending;});
    const auto send=initialNs();c=e.getStateSnapshot();capture.afterSession.store(c.session,std::memory_order_release);
    const auto re=e.requestLoopRange(a,b,{c.inputGeneration,c.session,c.renderEpoch});const auto receipt=initialNs();require(re.accepted,"reON");
    initialWait(e,[&]{const auto l=e.getLoopSnapshot();require(l.state!=progressive::LoopState::Failed,l.reason.c_str());return l.id==re.id&&l.initialPositionComplete&&!e.getPlaybackDiagnostics().retiringPipeline;});const auto adopted=initialNs();const auto l=e.getLoopSnapshot();const auto d=e.getPlaybackDiagnostics();
    initialWait(e,[&]{return capture.firstTime.load(std::memory_order_acquire)!=0;});const auto first=capture.firstTime.load();const auto session=e.getStateSnapshot().session;require(capture.firstSession==session&&capture.firstAt==d.pipeline.outputStartFrame,"first A belongs to intermediate/stale owner");
    initialWait(e,[&]{return e.getLoopSnapshot().cycles>=2;});require(e.pause(),"pause");const auto final=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();const auto finalLoop=e.getLoopSnapshot();
    std::set<std::uint64_t> newEpochs;for(std::size_t i=0;i<capture.pcm.rawCount;++i)if(capture.pcm.rawRecords[i].session==session)newEpochs.insert(capture.pcm.rawRecords[i].epoch);
    std::uint64_t natural=0;for(std::size_t i=0;i<capture.pcm.spanCount;++i){const auto& span=capture.pcm.spans[i];if(newEpochs.contains(span.newEpoch)&&span.periodicBoundary&&span.periodOffset+span.frames==span.periodFrames)++natural;}
    require(finalLoop.cycles==natural&&natural>=2,"new natural cycle count vs PCM span mismatch");
    e.stop();initialSave(out,capture.pcm);const auto owners=ts::prototype::phase58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2&&d.pipeline.loopReuse.checkpointPeak<=2&&!capture.pcm.errors&&!capture.pcm.nonfinite&&!capture.pcm.affected&&!final.missingFrames&&!final.underrunCalls&&!final.rejectedWrites&&final.callbackCppNew&&!*final.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees(),"supply/heap/resource");
    std::ofstream f(out/"SUMMARY.json");f<<std::setprecision(12)<<"{\"status\":\"PASS\",\"run_complete\":true,\"expected\":1,\"executed\":1,\"mode\":\""<<mode<<"\",\"cold_initial_s\":"<<double(coldEnd-coldBegin)/1e9<<",\"Clear_receipt_s\":"<<double(offReceipt-offBegin)/1e9<<",\"on_intent_to_send_s\":"<<double(send-onIntent)/1e9<<",\"send_to_receipt_s\":"<<double(receipt-send)/1e9<<",\"send_to_adoption_s\":"<<double(adopted-send)/1e9<<",\"on_intent_to_first_A_PCM_s\":"<<double(first-onIntent)/1e9<<",\"send_to_first_A_PCM_s\":"<<double(first-send)/1e9<<",\"first_A_at\":"<<capture.firstAt<<",\"first_A_session\":"<<session<<",\"old_session\":"<<oldSession<<",\"new_loop_id\":"<<re.id<<",\"warm_hit\":"<<d.pipeline.loopReuse.initialCheckpointHit<<",\"checkpoint_start\":"<<d.pipeline.checkpointStartFrame<<",\"cold_discarded\":"<<d.pipeline.loopReuse.coldDiscardedFrames<<",\"owner_peak\":"<<owners.peak<<",\"checkpoint_peak\":"<<d.pipeline.loopReuse.checkpointPeak<<",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"worker_new\":"<<final.workerNewCalls<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"adoption_cycles\":"<<l.cycles<<",\"final_cycles\":"<<finalLoop.cycles<<",\"natural_boundary_spans\":"<<natural<<",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"physical_audio\":false}\n";require(bool(f),"summary write");return 0;
}
}
int main(int argc,char** argv){int result=1;std::thread t([&]{try{result=warmMain(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});t.join();return result;}
