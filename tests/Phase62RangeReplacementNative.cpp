// 同速度Range連続置換で、未使用の旧A保存点を現ownerが保持しないことを検査。
#define PHASE62_PLAYING_LEDGER_NO_MAIN 1
#include "Phase62PlayingLedgerNative.cpp"

namespace {
// 通常速度履歴を別入力の準備へ持ち越さないことを調べる。各Engineが専用の
// 最終監査sinkを持ち、ゲート解放をEngine破棄より必ず先に行う。
struct RetiredSummaryFixture {
 WorkerGate gate;
 FinalLedgerSink audit;
 std::vector<std::unique_ptr<NativeCapture>> captures;
 ProgressiveOptions options;
 std::unique_ptr<ProgressiveMacPlaybackEngine> engine=std::make_unique<ProgressiveMacPlaybackEngine>();
 RetiredSummaryFixture(Preset preset,RenderAllocationHooks hooks){
  options.preset=preset;options.initialSpeed=1;options.callbackRecordLimit=8192;options.allocationHooks=hooks;
  options.controlTestHooks={&gate,WorkerGate::event};options.finalLoopSpeedAuditContext=&audit;options.receiveFinalLoopSpeedAudit=FinalLedgerSink::receive;
  options.observeEpochPcm=NativeCapture::raw;options.observeOutputPcm=NativeCapture::output;
 }
 ~RetiredSummaryFixture(){gate.released=true;engine.reset();}
 template<class P> void until(P predicate,const char* why,bool allowFailed=false){
  const auto end=Tick::now()+std::chrono::seconds(30);
  while(!predicate()){
   require(!gate.expired.load(),"summary reset normal-worker gate expired");
   if(!allowFailed&&engine->getPlaybackState()==State::Failed)throw std::runtime_error(engine->getPlaybackDiagnostics().error);
   require(Tick::now()<end,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  require(!gate.expired.load(),"summary reset normal-worker gate expired");
 }
 void prepare(const std::filesystem::path& input,std::size_t channels){
  captures.push_back(std::make_unique<NativeCapture>(channels));options.observerContext=captures.back().get();
  require(engine->prepare(input,options),"summary reset prepare rejected");
 }
 std::uint64_t retire75(const std::filesystem::path& input,std::size_t channels){
  prepare(input,channels);until([&]{return engine->getPlaybackState()==State::Ready;},"summary reset initial Ready deadline");
  require(engine->play(),"summary reset non-Loop play rejected");until([&]{return captures.back()->frames.load()>0;},"summary reset first PCM deadline");
  const auto before=engine->getStateSnapshot();const auto speed=engine->setSpeed(.75,before.session,before.inputGeneration,before.renderEpoch);
  require(speed.result==ts::prototype::Phase39RequestResult::Accepted&&speed.id,"summary reset non-Loop 75 rejected");
  until([&]{const auto s=engine->getStateSnapshot();return s.lastResult&&s.lastResult->id==speed.id&&s.lastResult->state==ts::prototype::phase59::OperationState::Completed;},"summary reset non-Loop 75 completion deadline");
  const auto played=engine->getPlaybackDiagnostics();require(played.callbackCppNew&&!*played.callbackCppNew&&!played.missingFrames&&!played.underrunCalls&&!played.rejectedWrites,"summary reset old input callback/supply");
  engine->stop();const auto stopped=engine->getStateSnapshot();const auto d=engine->getPlaybackDiagnostics();
  require(stopped.state==State::Stopped&&stopped.appliedTargetSpeed==.75&&d.appliedTargetSpeed==.75&&stopped.lastResult&&stopped.lastResult->id==speed.id&&stopped.lastResult->target==750000&&stopped.lastResult->appliedS>=0&&!stopped.pending&&!stopped.active&&stopped.session&&stopped.inputGeneration&&stopped.renderEpoch,"summary reset retired 75 precondition");
  require(!engine->getLoopSnapshot().enabled&&engine->loopSpeedHistory().empty(),"summary reset precondition used Loop speed");return speed.id;
 }
 void close(const std::filesystem::path& path){
  gate.released=true;engine->stop();engine.reset();audit.save(path);
  require(!gate.expired.load()&&(!gate.entered.load()||gate.left.load()),"summary reset gate did not release");
  const auto owners=ph58::RealtimePipeline::executionOwnerCounts();require(audit.complete()&&audit.operations.empty()&&!owners.alive&&owners.peak<=2,"summary reset final owned audit/resources");
  for(const auto& capture:captures)require(!capture->audit.errors&&!capture->audit.nonfinite,"summary reset PCM audit");
  require(!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"summary reset callback heap");
 }
};
void summaryResetRow(std::ostream& rows,const std::string& id,const char* phase,std::uint64_t oldID,const ProgressiveStateSnapshot& s,const ProgressiveDiagnostics& d){
 const auto optionalID=[&](const auto& op){if(op)rows<<op->id;else rows<<"null";};
 rows<<"{\"id\":"<<ph58::jsonString(id)<<",\"phase\":"<<ph58::jsonString(phase)<<",\"old_speed_id\":"<<oldID<<",\"state\":"<<ph58::jsonString(progressive::name(s.state))
  <<",\"preparation\":"<<s.preparation<<",\"session\":"<<s.session<<",\"input_generation\":"<<s.inputGeneration<<",\"render_epoch\":"<<s.renderEpoch<<",\"requested_speed\":"<<s.requestedSpeed<<",\"applied_target_speed\":"<<s.appliedTargetSpeed<<",\"pending_id\":";optionalID(s.pending);
 rows<<",\"active_id\":";optionalID(s.active);rows<<",\"last_result_id\":";optionalID(s.lastResult);
 if(s.lastResult)rows<<",\"last_result_state\":"<<ph58::jsonString(ts::prototype::phase59::name(s.lastResult->state))<<",\"last_result_target\":"<<s.lastResult->target<<",\"last_result_applied_s\":"<<s.lastResult->appliedS<<",\"last_result_completed_s\":"<<s.lastResult->completedS;
 rows<<",\"diagnostics\":{\"preparation\":"<<d.preparation<<",\"session\":"<<d.session<<",\"input_generation\":"<<d.inputGeneration<<",\"render_epoch\":"<<d.renderEpoch<<",\"requested_speed\":"<<d.requestedSpeed<<",\"applied_target_speed\":"<<d.appliedTargetSpeed
  <<",\"transition_operations\":"<<d.pipeline.transitionOperations<<",\"transition_history\":"<<d.pipeline.transitionHistory<<",\"constructor_s\":"<<d.constructorS<<",\"reservation_bytes\":"<<d.reservationBytes<<",\"error\":"<<ph58::jsonString(d.error)<<"}}\n";rows.flush();require(bool(rows),"summary reset evidence write");
}
}
int main(int argc,char** argv){
 if(argc!=5){std::cerr<<"INPUT preset NEW_OUT SOURCE_SHA\n";return 2;}int result=1;
 std::thread thread([&]{std::filesystem::path out=argv[3];std::size_t done=0;try{
  require(std::filesystem::create_directories(out),"fresh output");ts::WavStreamReader wav(argv[1]);const auto rate=wav.sampleRate();require(wav.frames()>=rate*6ULL,"6s fixture");const std::string preset=argv[2];require(preset=="baseline"||preset=="candidate","preset");
  std::vector<std::string> ids;for(auto phase:{"ready","playing","paused","after_Clear"})for(unsigned i=0;i<4;++i)ids.push_back(std::string(phase)+"_"+std::to_string(i));ids.push_back("final_resources_and_owned_audit");ids.push_back("new_prepare100_clears_retired_speed_summary");ids.push_back("failed_prepare100_clears_retired_speed_summary");
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"expected\":19,\"required_ids\":[";for(std::size_t i=0;i<ids.size();++i)f<<(i?",":"")<<ph58::jsonString(ids[i]);f<<"],\"source\":"<<ph58::jsonString(argv[4])<<",\"input_sha256\":"<<ph58::jsonString(fileHash(argv[1]))<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(argv[0]))<<",\"independent_DSP\":false}\n";}
  NativeCapture capture(wav.channels());FinalLedgerSink audit;ProgressiveOptions o;o.allowExperimentalLoops=true;o.initialSpeed=1;o.preset=preset=="candidate"?Preset::Candidate:Preset::Baseline;o.callbackRecordLimit=8192;o.observerContext=&capture;o.observeEpochPcm=NativeCapture::raw;o.observeOutputPcm=NativeCapture::output;o.finalLoopSpeedAuditContext=&audit;o.receiveFinalLoopSpeedAudit=FinalLedgerSink::receive;
  phase61_heap_reset();o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();hostCallbackCppNew.fetch_add(callbackNew);callbackCounting=false;},[]()noexcept{return callbackNew;}};
  auto e=std::make_unique<ProgressiveMacPlaybackEngine>();require(e->prepare(argv[1],o),"prepare");
  const auto wait=[&](auto predicate){const auto end=Tick::now()+std::chrono::seconds(30);while(!predicate()){require(e->getPlaybackState()!=State::Failed,e->getPlaybackDiagnostics().error.c_str());require(Tick::now()<end,"Range repeat deadline");std::this_thread::sleep_for(std::chrono::milliseconds(1));}};
  wait([&]{return e->getPlaybackState()==State::Ready&&e->getPlaybackDiagnostics().pipeline.analysisDoneS>=0;});std::ofstream checks(out/"checks.jsonl"),rows(out/"measurements.jsonl");std::uint64_t loop=0;
  for(unsigned phase=0;phase<4;++phase){
   if(phase==1)require(e->play(),"play");if(phase==2)require(e->pause(),"pause");
   if(phase==3){const auto c=e->getStateSnapshot();require(e->requestClearLoop(loop,{c.inputGeneration,c.session,c.renderEpoch}).accepted,"Clear");wait([&]{return !e->getLoopSnapshot().clearPending&&!e->getPlaybackDiagnostics().retiringPipeline;});require(e->getPlaybackState()==State::Paused,"Clear resumed");}
   for(unsigned i=0;i<4;++i){const auto old=e->getStateSnapshot();const auto frames=capture.frames.load();const auto r=e->requestLoopRange(rate/2,rate/2+rate,{old.inputGeneration,old.session,old.renderEpoch});require(r.accepted,"range repeat rejected");loop=r.id;wait([&]{return e->getLoopSnapshot().initialPositionComplete&&!e->getPlaybackDiagnostics().retiringPipeline;});const auto d=e->getPlaybackDiagnostics();
    require(d.pipeline.loopReuse.checkpointStates==1&&d.pipeline.loopReuse.checkpointPeak<=2,"unused checkpoint retained after old owner retirement");require(ph58::RealtimePipeline::executionOwnerCounts().peak<=2&&!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites,"supply/owner cap");
    if(phase!=1){require(capture.frames.load()==frames&&e->getPlaybackState()==(phase?State::Paused:State::Ready)&&e->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(rate/2),"stationary A/PCM/state advanced");}
    else wait([&]{return capture.frames.load()>frames;});
    rows<<"{\"id\":"<<ph58::jsonString(ids[done])<<",\"loop_id\":"<<r.id<<",\"session\":"<<d.session<<",\"checkpoint_states\":"<<d.pipeline.loopReuse.checkpointStates<<",\"checkpoint_peak\":"<<d.pipeline.loopReuse.checkpointPeak<<"}\n";checks<<"{\"id\":"<<ph58::jsonString(ids[done++])<<",\"pass\":true}\n";
   }
  }
  const auto d=e->getPlaybackDiagnostics();writePhase62Trace(out/"callbacks.jsonl",e->loopCallbackRecords());e.reset();audit.save(out/"final_owned_audit.jsonl");const auto owners=ph58::RealtimePipeline::executionOwnerCounts();require(audit.complete()&&audit.operations.empty()&&!owners.alive&&owners.peak<=2&&!capture.audit.errors&&!capture.audit.nonfinite&&!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees()&&d.callbackCppNew&&!*d.callbackCppNew,"final audit/heap/PCM/resources");checks<<"{\"id\":"<<ph58::jsonString(ids[done++])<<",\"pass\":true}\n";
  const auto resetCase=[&](bool failBeforeCreation){
   const auto id=ids[done];RetiredSummaryFixture fixture(o.preset,o.allocationHooks);const auto oldID=fixture.retire75(argv[1],wav.channels());const auto old=fixture.engine->getStateSnapshot();summaryResetRow(rows,id,"stopped75",oldID,old,fixture.engine->getPlaybackDiagnostics());
   if(failBeforeCreation){const auto missing=out/"summary_reset_missing.wav";require(!std::filesystem::exists(missing),"summary reset missing fixture exists");fixture.prepare(missing,wav.channels());fixture.until([&]{return fixture.engine->getPlaybackState()==State::Failed;},"summary reset generated-before-failure deadline",true);}
   else{fixture.gate.arm(ProgressiveControlTestPoint::AcquiringResources);fixture.prepare(argv[1],wav.channels());fixture.until([&]{return fixture.gate.entered.load();},"summary reset AcquiringResources deadline");}
   const auto s=fixture.engine->getStateSnapshot();const auto current=fixture.engine->getPlaybackDiagnostics();summaryResetRow(rows,id,failBeforeCreation?"failed_before_creation":"preparing_before_creation",oldID,s,current);
   const bool pass=s.state==(failBeforeCreation?State::Failed:State::Preparing)&&s.preparation==old.preparation+1&&current.preparation==s.preparation&&s.requestedSpeed==1&&s.appliedTargetSpeed==1&&current.requestedSpeed==1&&current.appliedTargetSpeed==1
    &&!s.pending&&!s.active&&!s.lastResult&&!s.session&&!s.inputGeneration&&!s.renderEpoch&&!current.session&&!current.inputGeneration&&!current.renderEpoch&&!current.pipeline.transitionOperations&&!current.pipeline.transitionHistory&&fixture.engine->operationHistory().empty()
    &&current.constructorS<0&&!current.reservationBytes&&(failBeforeCreation?!current.error.empty():current.error.empty());
   fixture.close(out/(id+"_final_owned_audit.jsonl"));checks<<"{\"id\":"<<ph58::jsonString(id)<<",\"pass\":"<<(pass?"true":"false")<<"}\n";checks.flush();++done;return pass;
  };
  // 両状態の観測を先に保存するので、旧製品でも2項目の差を独立に確認できる。
  const bool preparingReset=resetCase(false),failedReset=resetCase(true);checks.close();rows.close();require(bool(checks)&&bool(rows)&&done==19,"results incomplete");require(preparingReset&&failedReset,"new preparation retained previous non-Loop speed summary");
  std::ofstream f(out/"SUMMARY.json");f<<"{\"status\":\"PASS\",\"run_complete\":true,\"expected\":19,\"executed\":"<<done<<",\"owner_peak\":"<<ph58::RealtimePipeline::executionOwnerCounts().peak<<",\"independent_DSP\":false,\"RT_approval\":\"NOT_ASSESSED\"}\n";result=0;
 }catch(const std::exception& error){std::cerr<<error.what()<<'\n';std::ofstream f(out/"SUMMARY.json");f<<"{\"status\":\"FAIL\",\"run_complete\":false,\"expected\":19,\"executed\":"<<done<<",\"reason\":"<<ph58::jsonString(error.what())<<"}\n";}});thread.join();return result;
}
