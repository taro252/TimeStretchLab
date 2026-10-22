// 性能hostは変更せず、Playing中の初回進入混合だけを独立captureする。
#define TS_PHASE62_INITIAL_NO_MAIN
#include "Phase62InitialLoopNative.cpp"
#undef TS_PHASE62_INITIAL_NO_MAIN
namespace {
int entryMain(int argc,char** argv){
    require(argc==7,"INPUT preset A_seconds duration_seconds speed NEW_OUTPUT");
    const std::filesystem::path folder=argv[6];require(std::filesystem::create_directories(folder),"fresh output required");
    ts::WavStreamReader wav(argv[1]);const auto a=std::uint64_t(std::llround(std::stod(argv[3])*wav.sampleRate())),b=a+std::uint64_t(std::llround(std::stod(argv[4])*wav.sampleRate()));const auto speed=std::stod(argv[5]);
    require(a<b&&b<wav.frames(),"entry needs normal continuation after B");
    InitialCapture capture(wav.channels(),wav.sampleRate());ProgressiveOptions options;options.preset=std::string(argv[2])=="baseline"?Preset::Baseline:Preset::Candidate;options.initialSpeed=speed;options.allowExperimentalLoops=true;options.callbackRecordLimit=256;
    options.observerContext=&capture;options.observeEpochPcm=InitialCapture::raw;options.observeOutputPcm=InitialCapture::output;
    phase61_heap_reset();options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    {std::ofstream f(folder/"EXPECTED.json");f<<"{\"expected\":2,\"A\":"<<a<<",\"B\":"<<b<<",\"speed\":"<<speed<<",\"quality_cycles\":3,\"playing_entry\":true,\"timing_approval\":\"NOT_ASSESSED\"}\n";}
    ProgressiveMacPlaybackEngine engine;require(engine.prepare(argv[1],options),"prepare");initialWait(engine,[&]{return engine.getPlaybackState()==State::Ready;});initialWait(engine,[&]{return engine.getPlaybackDiagnostics().pipeline.analysisDoneS>=0;});
    std::ofstream rows(folder/"measurements.jsonl");
    for(std::size_t round=0;round<2;++round){
        const auto rawBegin=capture.rawFrames.load(),outputBegin=capture.outputFrames.load();
        require(engine.play(),"explicit Playing entry");initialWait(engine,[&]{return capture.rawFrames.load()>rawBegin;});
        const auto before=engine.getStateSnapshot();const auto receipt=engine.requestLoopRange(a,b,{before.inputGeneration,before.session,before.renderEpoch});require(receipt.accepted,receipt.reason.c_str());
        initialWait(engine,[&]{const auto l=engine.getLoopSnapshot();require(l.state!=progressive::LoopState::Failed,l.reason.c_str());return l.initialPositionComplete;});
        const auto d=engine.getPlaybackDiagnostics();const auto l=engine.getLoopSnapshot();const auto reuse=d.pipeline.loopReuse;
        initialWait(engine,[&]{return engine.getLoopSnapshot().cycles>=3;});require(engine.pause(),"pause after three natural cycles");const auto after=engine.getPlaybackDiagnostics();
        rows<<"{\"round\":"<<round<<",\"input_generation\":"<<before.inputGeneration<<",\"loop_id\":"<<receipt.id<<",\"session\":"<<d.session<<",\"epoch\":"<<d.renderEpoch<<",\"checkpoint_start\":"<<d.pipeline.checkpointStartFrame<<",\"initial_checkpoint_hit\":"<<reuse.initialCheckpointHit<<",\"cold_discarded_frames\":"<<reuse.coldDiscardedFrames<<",\"period_frames\":"<<l.periodFrames<<",\"output_start\":"<<d.pipeline.outputStartFrame<<",\"raw_begin\":"<<rawBegin<<",\"raw_end\":"<<capture.rawFrames<<",\"output_begin\":"<<outputBegin<<",\"output_end\":"<<capture.outputFrames<<",\"cycles\":"<<engine.getLoopSnapshot().cycles<<",\"missing\":"<<after.missingFrames<<",\"callback_new\":"<<after.callbackCppNew.value_or(UINT64_MAX)<<"}\n";rows.flush();
        if(!round){const auto state=engine.getStateSnapshot();require(engine.requestClearLoop(receipt.id,{state.inputGeneration,state.session,state.renderEpoch}).accepted,"Clear before same-prepare request");initialWait(engine,[&]{return !engine.getLoopSnapshot().clearPending;});require(engine.getPlaybackState()==State::Paused,"Clear auto-resumed");}
    }
    const auto d=engine.getPlaybackDiagnostics();engine.stop();initialSave(folder,capture);const auto owners=ts::prototype::phase58::RealtimePipeline::executionOwnerCounts();require(!capture.errors&&!capture.nonfinite&&!capture.affected&&!d.missingFrames&&!d.rejectedWrites&&d.callbackCppNew.has_value()&&*d.callbackCppNew==0&&!phase61_heap_allocations()&&!phase61_heap_frees()&&!owners.alive&&owners.peak<=2,"entry PCM/supply/owners");
    std::ofstream f(folder/"SUMMARY.json");f<<"{\"status\":\"PASS\",\"run_complete\":true,\"expected\":2,\"executed\":2,\"raw_records\":"<<capture.rawCount<<",\"output_spans\":"<<capture.spanCount<<",\"raw_frames\":"<<capture.rawFrames<<",\"output_frames\":"<<capture.outputFrames<<",\"owners_peak\":"<<owners.peak<<",\"owners_alive\":"<<owners.alive<<",\"RT_deadline_approval\":\"NOT_ASSESSED\"}\n";return 0;
}
}
int main(int argc,char** argv){int code=1;std::thread owner([&]{try{code=entryMain(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});owner.join();return code;}
