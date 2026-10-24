// D1: Preparing中の同一先行準備を明示ONへ引き継ぐ公開API回帰。
// MODE INPUT PRESET NEW_OUT SOURCE_SHA。1 mode/process、専用通常制御thread。
// 時刻は証拠だけであり、このgate付きhostを性能の合否には用いない。
#define PROGRESSIVE_ADOPTION_NATIVE_NO_MAIN 1
#include "ProgressiveAdoptionNativeTests.cpp"
#include <sstream>

namespace {
const std::array<const char*,20> performancePreparationModes{
 "on_early","on_mid","on_before_ready","on_ready","mismatch_range","mismatch_context",
 "pause_transferred","stop_transferred","speed_transferred","replace_transferred",
 "input_transferred","close_transferred","unclaimed_pause","unclaimed_play",
 "unclaimed_resume","unclaimed_cancel","resume_retiring",
 "speed_transferred_play","speed_transferred_resume","speed_transferred_latest_A"};
const std::array<const char*,8> performancePreparationChecks{
 "fixture_contract","preparation_gate","action_receipt","held_state",
 "terminal_history","observable_behavior","resources","final_owned_audit"};

std::string performancePreparationJson(const progressive::LoopPreparationOperation& op){
 auto value=preparationJson(op);value.pop_back();
 return value+",\"transferred_to_loop_id\":"+std::to_string(op.transferredToLoopID)+"}";
}
std::string performanceStoppedJson(const StoppedSpeedOperation& op){
 std::ostringstream value;
 value<<"{\"id\":"<<op.id<<",\"input_generation\":"<<op.inputGeneration<<",\"source_session\":"<<op.sourceSession
  <<",\"source_epoch\":"<<op.sourceRenderEpoch<<",\"source_map_version\":"<<op.mapVersion<<",\"source_consumed_output\":"<<op.consumedOutputFrame
  <<",\"resume_input\":"<<op.resumeInputFrame<<",\"session\":"<<op.session<<",\"epoch\":"<<op.renderEpoch<<",\"output_start\":"<<op.outputStartFrame
  <<",\"accepted_ns\":"<<op.acceptedNs<<",\"ready_ns\":"<<op.readyNs<<",\"loop_id\":"<<op.loopID<<",\"cycle\":"<<op.cycle
  <<",\"preparation_version\":"<<op.preparationVersion<<",\"discarded_frames\":"<<op.discardedForStoppedSpeedFrames<<",\"speed_micros\":"<<op.speedMicros
  <<",\"state\":"<<ph58::jsonString(name(op.state))<<",\"position_captured\":"<<op.positionCaptured<<",\"output_started\":"<<op.outputStarted
  <<",\"mode\":"<<ph58::jsonString(op.mode==progressive::SeekMode::Exact?"Exact":"FastLocal")<<",\"reason\":"<<ph58::jsonString(op.reason)<<'}';
 return value.str();
}
struct PrefixProgressGate {
 enum class Position {Early,Middle,BeforeReady};
 std::atomic<Position> selected{Position::Middle};
 std::atomic<bool> armed{false},entered{false},released{false},left{false},expired{false};
 std::atomic<std::uint64_t> ignoredSession{0},workerSession{0},outputPosition{0},outputA{0};
 std::atomic<bool> retireArmed{false},retireEntered{false},retireReleased{false},retireLeft{false},retireExpired{false};
 std::atomic<std::uint64_t> retireCalls{0},retireCleanups{0},retireEnteredNs{0},retireReleasedNs{0},retireLeftNs{0};
 static std::uint64_t steadyNs()noexcept{return std::chrono::duration_cast<std::chrono::nanoseconds>(Tick::now().time_since_epoch()).count();}
 void armRetirement(){require(!retireEntered.load(),"retirement gate rearmed");retireArmed=true;}
 void releaseRetirement()noexcept{retireReleasedNs=steadyNs();retireReleased=true;}
 void arm(Position where,std::uint64_t ignored,std::uint64_t a){
  require(!entered.load()||left.load(),"prefix gate rearm before leave");selected=where;ignoredSession=ignored;outputA=a;
  workerSession=0;outputPosition=0;entered=false;released=false;left=false;expired=false;armed=true;
 }
 static void event(void* context,ph58::ControlTestPoint point,std::uint64_t session,std::uint64_t position)noexcept{
  auto& gate=*static_cast<PrefixProgressGate*>(context);
  if(point!=ph58::ControlTestPoint::LoopPreparationPrefixProgress||!gate.armed.load()||session==gate.ignoredSession.load())return;
  const auto a=gate.outputA.load();bool match=false;
  switch(gate.selected.load()){
   case Position::Early:match=position==0;break;
   case Position::Middle:match=position>=a/2&&position+2048<=a;break;
   case Position::BeforeReady:match=position<=a&&position+2048>a;break;
  }
  if(!match||!gate.armed.exchange(false))return;
  gate.workerSession=session;gate.outputPosition=position;gate.entered=true;
  const auto deadline=Tick::now()+std::chrono::seconds(10);
  while(!gate.released.load()&&Tick::now()<deadline)std::this_thread::sleep_for(std::chrono::milliseconds(1));
  if(!gate.released.load())gate.expired=true;gate.left=true;
 }
 static void engineEvent(void* context,ProgressiveControlTestPoint point)noexcept{
  auto& gate=*static_cast<PrefixProgressGate*>(context);
  // Stop/close/input変更は失効を公開してから通常側join待ちhookで解放する。
  if(point==ProgressiveControlTestPoint::SeekCleanupWait){gate.released=true;gate.releaseRetirement();}
  if(point==ProgressiveControlTestPoint::SeekCleanupComplete&&gate.retireEntered.load())++gate.retireCleanups;
  if(point!=ProgressiveControlTestPoint::RetiringOld)return;
  ++gate.retireCalls;
  if(!gate.retireArmed.exchange(false))return;
  gate.retireEnteredNs=steadyNs();gate.retireEntered=true;
  const auto deadline=Tick::now()+std::chrono::seconds(10);
  while(!gate.retireReleased.load()&&Tick::now()<deadline)std::this_thread::sleep_for(std::chrono::milliseconds(1));
  if(!gate.retireReleased.load())gate.retireExpired=true;
  gate.retireLeftNs=steadyNs();gate.retireLeft=true;
 }
};
struct PerformanceEpochCopy {
 struct Value {
  std::uint64_t engine=0,preparation=0,sequence=0,epoch=0,session=0,generation=0;
  bool preparedOnly=false,joined=false,released=false;
  std::vector<ts::prototype::phase59::SpeedOperation> operations;
 };
 std::vector<Value> values;bool error=false;std::uint64_t calls=0;
 PerformanceEpochCopy(){values.reserve(16);}
 static bool receive(void* context,const EpochOperationAudit& audit)noexcept{
  auto& sink=*static_cast<PerformanceEpochCopy*>(context);++sink.calls;
  try{
   if(callbackCounting||!audit.engineSerial||!audit.sequence||!audit.session||!audit.inputGeneration||!audit.workersJoined||!audit.callbackReleased){sink.error=true;return false;}
   for(const auto& old:sink.values)if(old.session==audit.session){sink.error=true;return false;}
   Value value{audit.engineSerial,audit.preparation,audit.sequence,audit.renderEpoch,audit.session,audit.inputGeneration,audit.preparedOnly,audit.workersJoined,audit.callbackReleased,{}};
   value.operations.assign(audit.ordinarySpeeds.begin(),audit.ordinarySpeeds.end());sink.values.push_back(std::move(value));return true;
  }catch(...){sink.error=true;return false;}
 }
};
struct PerformanceFinalCopy {
 OwnedOperations* destination=nullptr;std::uint64_t epochCalls=0,epochRejected=0;bool epochConfigured=false;
 static bool receive(void* context,const FinalOperationAudit& audit)noexcept{
  auto& sink=*static_cast<PerformanceFinalCopy*>(context);sink.epochCalls=audit.epochAuditCalls;sink.epochRejected=audit.epochAuditRejected;sink.epochConfigured=audit.epochAuditConfigured;
  return OwnedOperations::receive(sink.destination,audit);
 }
};
struct PerformancePreparationFixture:AdoptionNativeFixture {
 PrefixProgressGate progress;PerformanceEpochCopy epochs;PerformanceFinalCopy finalCopy;
 std::map<std::uint64_t,std::string> completeFrozen;
 std::map<std::uint64_t,std::string> stoppedFrozen;
 std::ofstream receipts,progressObservations;
 std::uint64_t retiringSourceSession=0,retiringAdoptedSession=0;
 std::uint64_t retiringCallsBefore=0;std::size_t retiringExpectedEpochs=3;
 PerformancePreparationFixture(const std::filesystem::path& file,Preset preset,const std::filesystem::path& folder,unsigned rate,std::size_t channels)
 :AdoptionNativeFixture(file,preset,folder,rate,channels),receipts(folder/"receipts.jsonl"),progressObservations(folder/"preparation_observations.jsonl"){
  options.pipelineControlTestHooks={&progress,PrefixProgressGate::event,nullptr};
  options.controlTestHooks={&progress,PrefixProgressGate::engineEvent};
  options.finalEpochAuditContext=&epochs;options.receiveFinalEpochAudit=PerformanceEpochCopy::receive;
  finalCopy.destination=&allAudit;options.finalOperationAuditContext=&finalCopy;options.receiveFinalOperationAudit=PerformanceFinalCopy::receive;
 }
 ~PerformancePreparationFixture(){progress.released=true;progress.releaseRetirement();gate.released=true;engine.reset();}
 template<class P>void wait(P predicate,const char* why){
  until([&]{require(!progress.expired.load()&&!progress.retireExpired.load(),"normal-worker gate expired");return predicate();},why);
  require(!progress.expired.load()&&!progress.retireExpired.load(),"normal-worker gate expired");
 }
 std::uint64_t hold(PrefixProgressGate::Position position){
  progress.arm(position,engine->getStateSnapshot().session,a);const auto id=request();
  wait([&]{return progress.entered.load();},"prefix progress gate not reached");
  const auto op=operation(id);require(op.state==Prep::Preparing&&!op.workersJoined&&!op.transferredToLoopID&&op.version&&progress.workerSession.load()!=op.session,"actual preparation owner not held");
  return id;
 }
 void releaseProgress(){progress.released=true;if(progress.entered.load())wait([&]{return progress.left.load();},"prefix gate did not leave");}
 void observe(const char* label){
  record(label);const auto loop=engine->getLoopSnapshot();const auto prep=engine->loopPreparationSnapshot();const auto d=engine->getPlaybackDiagnostics();
  progressObservations<<"{\"label\":"<<ph58::jsonString(label)<<",\"gate_entered\":"<<progress.entered.load()<<",\"gate_position\":"<<progress.outputPosition.load()
   <<",\"gate_worker_session\":"<<progress.workerSession.load()<<",\"loop_id\":"<<loop.id<<",\"preparation_request_id\":"<<loop.preparationRequestID
   <<",\"available\":"<<prep.available<<",\"initial_checkpoint_hit\":"<<d.pipeline.loopReuse.initialCheckpointHit<<",\"checkpoint_start\":"<<d.pipeline.checkpointStartFrame
   <<",\"retirement_gate_entered\":"<<progress.retireEntered.load()<<",\"retirement_gate_left\":"<<progress.retireLeft.load()<<",\"retiring_pipeline\":"<<d.retiringPipeline.has_value()<<",\"resume_pending\":"<<engine->getStateSnapshot().resumePending
   <<",\"cold_discarded_frames\":"<<d.pipeline.loopReuse.coldDiscardedFrames<<",\"cold_prefix_cpu_s\":"<<std::setprecision(17)<<d.pipeline.loopReuse.coldPrefixCpuS
   <<",\"latest\":"<<(prep.latest?performancePreparationJson(*prep.latest):"null")<<"}\n";
  progressObservations.flush();require(bool(progressObservations),"preparation observation write");
 }
 progressive::LoopReceipt on(std::uint64_t first,std::uint64_t end,progressive::LoopContext context){
  const auto result=engine->requestLoopRange(first,end,context);
  receipts<<"{\"kind\":\"loop_range\",\"id\":"<<result.id<<",\"accepted\":"<<result.accepted<<",\"A\":"<<first<<",\"B\":"<<end
   <<",\"code\":"<<ph58::jsonString(progressive::name(result.code))<<",\"reason\":"<<ph58::jsonString(result.reason)<<"}\n";receipts.flush();require(bool(receipts),"range receipt write");return result;
 }
 void audioStationary(const Stationary& before){
  const auto now=sample();require(now.state.state==before.state.state&&now.position.inputFrame==before.position.inputFrame&&now.position.outputFrame==before.position.outputFrame&&now.raw==before.raw&&now.output==before.output&&!now.state.resumePending,"held preparation consumed/resumed/moved C");
  require(now.state.session==before.state.session&&now.state.renderEpoch==before.state.renderEpoch&&now.state.inputGeneration==before.state.inputGeneration&&now.diagnostics.consumedFrames==before.diagnostics.consumedFrames,"held preparation changed current owner");
 }
 void resumeHeld(const Stationary& before,std::uint64_t nativeStart){
  const auto now=sample();
  require(progress.retireEntered.load()&&!progress.retireLeft.load()&&!progress.retireExpired.load(),"old-owner retirement gate not held");
  require(now.state.state==State::Paused&&now.state.resumePending&&now.state.session==before.state.session&&
   now.state.inputGeneration==before.state.inputGeneration&&now.state.renderEpoch==before.state.renderEpoch,
   "Resume started/changed owner before old retirement");
  require(now.position.inputFrame==before.position.inputFrame&&now.position.outputFrame==before.position.outputFrame&&
   now.raw==before.raw&&now.output==before.output&&now.diagnostics.consumedFrames==before.diagnostics.consumedFrames&&
   now.diagnostics.currentEpochPresentedFrame==before.diagnostics.currentEpochPresentedFrame,
   "Resume consumed PCM or moved A while old owner retained");
  require(now.diagnostics.retiringPipeline&&engine->getNativeDiagnostics().playCalledSteadyNs==nativeStart,
   "Resume called native start before retirement completion");
  const auto owners=ph58::RealtimePipeline::executionOwnerCounts();require(owners.alive==2&&owners.peak<=2,"held retirement must retain exactly old/new execution owners");
  require(!engine->loopPreparationSnapshot().available,"transferred Ready republished optional availability");
 }
 void terminal(std::uint64_t id,Prep expected){
  wait([&]{const auto op=operation(id);require(op.state!=Prep::Failed,op.reason.c_str());return op.state==expected&&op.workersJoined;},"preparation did not settle/join");
  freezeComplete();
 }
 void freezeComplete(){
  freeze();for(const auto& op:engine->loopPreparationHistory())if(progressive::terminal(op.state)){
   const auto value=performancePreparationJson(op);auto [it,added]=completeFrozen.emplace(op.id,value);require(added||it->second==value,"full terminal preparation row changed");
  }
  for(const auto& op:engine->stoppedSpeedHistory())if(op.state==StoppedSpeedState::Replaced||op.state==StoppedSpeedState::Cancelled||op.state==StoppedSpeedState::Failed){
   const auto value=performanceStoppedJson(op);auto [it,added]=stoppedFrozen.emplace(op.id,value);require(added||it->second==value,"full terminal stopped-speed row changed");
  }
 }
 void adopted(std::uint64_t loopID,std::uint64_t at,std::uint64_t preparationID,bool hit){
  wait([&]{return engine->getLoopSnapshot().id==loopID&&engine->getLoopSnapshot().initialPositionComplete&&!engine->getPlaybackDiagnostics().retiringPipeline;},"explicit Loop not adopted");
  const auto loop=engine->getLoopSnapshot();const auto d=engine->getPlaybackDiagnostics();
  require(loop.preparationRequestID==preparationID&&d.pipeline.loopReuse.initialCheckpointHit==hit,"ON preparation lineage/checkpoint hit mismatch");
  require(d.pipeline.sourceHashPasses==1&&d.pipeline.sourceSnapshotCreations==1&&d.pipeline.residentLockCalls==1,"ON repeated input preparation");
  if(preparationID){const auto preparation=operation(preparationID);require(d.pipeline.checkpointStartFrame==preparation.checkpointOutput&&d.pipeline.loopReuse.coldDiscardedFrames<2048&&engine->getStateSnapshot().inputGeneration==preparation.inputGeneration,"ON discarded completed prefix work or changed input lineage");}
  require(engine->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(at)&&(engine->getPlaybackState()==State::Ready||engine->getPlaybackState()==State::Paused)&&!engine->getStateSnapshot().resumePending,"explicit ON position/static state");
  require(!engine->loopPreparationSnapshot().available,"ON left optional preparation available");lead();freezeComplete();
 }
 void fullFinalCheck(){
  finalCheck();require(!progress.expired.load()&&(!progress.entered.load()||progress.left.load())&&
   !progress.retireExpired.load()&&(!progress.retireEntered.load()||progress.retireLeft.load()),"normal gate lifetime leak");
  require(finalCopy.epochConfigured&&!finalCopy.epochRejected&&!epochs.error&&finalCopy.epochCalls==epochs.calls&&epochs.calls==epochs.values.size(),"epoch sink incomplete/rejected/duplicated");
  for(const auto& row:epochs.values)require(row.engine==serial&&row.sequence&&row.joined&&row.released&&row.operations.empty(),"unexpected ordinary speed record or unfinished epoch");
  if(progress.entered.load())require(std::count_if(epochs.values.begin(),epochs.values.end(),[&](const auto& row){return row.session==progress.workerSession.load()&&row.preparedOnly&&!row.epoch;})==1,"actual held preparation owner was not audited exactly once");
  if(retiringAdoptedSession){
   require(progress.retireCalls.load()==retiringCallsBefore+1&&progress.retireCleanups.load()==1&&epochs.values.size()==retiringExpectedEpochs,
    "resume retirement/cleanup/epoch delivery count");
   for(const auto session:{retiringSourceSession,retiringAdoptedSession})require(std::count_if(epochs.values.begin(),epochs.values.end(),[&](const auto& row){return row.session==session&&!row.preparedOnly&&row.epoch&&row.joined&&row.released;})==1,
    "old/adopted execution owner missing or duplicated in final joined audit");
  }
  for(const auto& op:allAudit.preparations)if(auto it=completeFrozen.find(op.id);it!=completeFrozen.end())require(it->second==performancePreparationJson(op),"final full preparation copy changed");
  for(const auto& op:allAudit.stopped)if(auto it=stoppedFrozen.find(op.id);it!=stoppedFrozen.end())require(it->second==performanceStoppedJson(op),"final terminal stopped-speed copy changed");
 }
 void savePerformance(){
  save();std::ofstream preparations(out/"final_preparations_full.jsonl"),epochFile(out/"epoch_owned_audits.jsonl"),stopped(out/"final_stopped_speeds_full.jsonl");
  for(const auto& op:allAudit.preparations)preparations<<performancePreparationJson(op)<<'\n';
  for(const auto& op:allAudit.stopped)stopped<<performanceStoppedJson(op)<<'\n';
  for(const auto& row:epochs.values)epochFile<<"{\"engine\":"<<row.engine<<",\"preparation\":"<<row.preparation<<",\"sequence\":"<<row.sequence<<",\"epoch\":"<<row.epoch<<",\"session\":"<<row.session<<",\"generation\":"<<row.generation<<",\"prepared_only\":"<<row.preparedOnly<<",\"joined\":"<<row.joined<<",\"callback_released\":"<<row.released<<",\"ordinary_operations\":"<<row.operations.size()<<"}\n";
  preparations.close();epochFile.close();stopped.close();require(bool(preparations)&&bool(epochFile)&&bool(stopped),"full audit evidence write");
 }
};

int performancePreparationMain(int argc,char** argv){
 require(argc==6,"MODE INPUT PRESET NEW_OUT SOURCE_SHA");
 const std::string mode=argv[1],presetName=argv[3];
 const bool resumeRetiring=mode=="resume_retiring";
 const bool speedPlay=mode=="speed_transferred_play",speedResume=mode=="speed_transferred_resume",latestA=mode=="speed_transferred_latest_A";
 const bool speedRetiring=speedPlay||speedResume||latestA,speedReplacement=mode=="speed_transferred"||speedRetiring;
 const bool retirementGate=resumeRetiring||speedRetiring,initialSeek=speedReplacement&&!latestA;
 require(std::find(performancePreparationModes.begin(),performancePreparationModes.end(),mode)!=performancePreparationModes.end(),"unknown performance-preparation mode");
 require(presetName=="baseline"||presetName=="candidate","preset");
 const std::filesystem::path out=argv[4];require(!std::filesystem::exists(out),"fresh evidence directory required");require(std::filesystem::create_directories(out),"create evidence directory");
 std::size_t done=0;std::unique_ptr<PerformancePreparationFixture> f;std::ofstream checks(out/"checks.jsonl");
 const auto pass=[&]{require(done<performancePreparationChecks.size(),"extra check");checks<<"{\"id\":"<<ph58::jsonString(mode+"."+performancePreparationChecks[done++])<<",\"pass\":true}\n";checks.flush();require(bool(checks),"check write");};
 const auto finish=[&](bool ok,const std::string& reason){
  std::ofstream summary(out/"SUMMARY.json");const auto owners=ph58::RealtimePipeline::executionOwnerCounts();
  summary<<"{\"status\":\""<<(ok?"PASS":"FAIL")<<"\",\"run_complete\":"<<(ok?"true":"false")<<",\"expected\":8,\"executed\":"<<done
   <<",\"mode\":"<<ph58::jsonString(mode)<<",\"source\":"<<ph58::jsonString(argv[5])<<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak
   <<",\"callback_gate\":false,\"normal_prefix_gate\":"<<(mode=="on_ready"?"false":"true")<<",\"normal_retirement_gate\":"<<(retirementGate?"true":"false")<<",\"performance\":\"NOT_ASSESSED\",\"independent_PCM\":\"NOT_RUN\",\"reason\":"<<ph58::jsonString(reason)<<"}\n";
  summary.close();require(bool(summary),"summary write");
  std::ofstream manifest(out/"ARTIFACTS.json");manifest<<"{\"artifacts\":[";bool first=true;
  for(const auto* name:{"EXPECTED.json","MANIFEST.json","checks.jsonl","receipts.jsonl","observations.jsonl","preparation_observations.jsonl","final_loop_owned_audit.jsonl","final_operation_owned_audit.jsonl","final_preparations_full.jsonl","final_stopped_speeds_full.jsonl","epoch_owned_audits.jsonl","raw.f32","raw_records.jsonl","output_before_gain.f32","spans.jsonl","replacement_input.wav","resume_retiring.json","speed_transferred_resume.json","SUMMARY.json"}){
   const auto path=out/name;if(!std::filesystem::exists(path))continue;
   manifest<<(first?"":",")<<"{\"path\":"<<ph58::jsonString(name)<<",\"bytes\":"<<std::filesystem::file_size(path)<<",\"sha256\":"<<ph58::jsonString(fileHash(path))<<'}';first=false;
  }
  manifest<<"]}\n";manifest.close();require(bool(manifest),"artifact manifest write");
 };
 try{
  require(progressive::contractVersion==4&&progressive::featureApprovals.exactSeek&&!progressive::featureApprovals.interactiveSeek&&!progressive::featureApprovals.nativeLoops&&!progressive::featureApprovals.currentCycleSpeed,"v4/Exact-only approval contract");
  requireFloat32Fixture(argv[2]);ts::WavStreamReader wav(argv[2]);const auto rate=wav.sampleRate();
  require(wav.frames()>=16ULL*rate&&wav.frames()<=20ULL*rate&&(rate==44100||rate==48000)&&(wav.channels()==1||wav.channels()==2),"bounded Float32 16..20s fixture required");
  {std::ofstream expected(out/"EXPECTED.json");expected<<"{\"schema\":1,\"expected\":8,\"required_ids\":[";for(std::size_t i=0;i<performancePreparationChecks.size();++i)expected<<(i?",":"")<<ph58::jsonString(mode+"."+performancePreparationChecks[i]);expected<<"],\"accepted_preparation_ids\":[1],\"accepted_seek_ids\":"<<(initialSeek?"[1]":"[]")<<",\"accepted_stopped_speed_ids\":"<<(latestA?"[9223372036854775809,9223372036854775810]":speedReplacement?"[9223372036854775809]":"[]")<<",\"mode\":"<<ph58::jsonString(mode)<<",\"callback_gate\":false,\"normal_retirement_gate\":"<<(retirementGate?"true":"false")<<",\"retirement_resume_requests_expected\":"<<(retirementGate?1:0)<<",\"start_intent_while_retiring\":"<<(speedPlay||resumeRetiring?"true":"false")<<",\"coordinate_contract\":"<<ph58::jsonString(speedRetiring?"unfinished ReturnToA survives stopped-speed replacement; source C retained as evidence, new PCM starts at A":"existing mode")<<"}\n";expected.close();require(bool(expected),"expected write");}
  {std::ofstream manifest(out/"MANIFEST.json");manifest<<"{\"schema\":1,\"source\":"<<ph58::jsonString(argv[5])<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::absolute(argv[0])))
   <<",\"input\":"<<ph58::jsonString(std::filesystem::absolute(argv[2]).string())<<",\"input_sha256\":"<<ph58::jsonString(fileHash(argv[2]))<<",\"preset\":"<<ph58::jsonString(presetName)
   <<",\"contract_version\":4,\"sample_rate\":"<<rate<<",\"channels\":"<<wav.channels()<<",\"frames\":"<<wav.frames()<<",\"A\":"<<2ULL*rate<<",\"B\":"<<2ULL*rate+rate/2
   <<",\"mode\":"<<ph58::jsonString(mode)<<",\"speed_micros\":1000000,\"one_native_control_thread\":true,\"callback_gate\":false,\"normal_prefix_gate\":"<<(mode=="on_ready"?"false":"true")<<",\"normal_retirement_gate\":"<<(retirementGate?"true":"false")<<",\"performance\":\"NOT_ASSESSED\",\"independent_PCM\":\"NOT_RUN\",\"capture_limit_frames\":96000}\n";manifest.close();require(bool(manifest),"manifest write");}
  phase61_heap_reset();f=std::make_unique<PerformancePreparationFixture>(argv[2],presetName=="baseline"?Preset::Baseline:Preset::Candidate,out,rate,wav.channels());
  // 旧速度試験と新ReadyはC=A、新PausedはA<C<B、latest_AはC=0<A。
  // 新modeは未完了ReturnToAを速度置換後も保持し、再開先Aを明示検査する。
  // 保存点を無効にして先行jobが途中gateを飛び越すことを防ぐ。
  if(speedReplacement)f->options.seekCheckpoints=false;
  f->prepare();if(initialSeek)f->seek(f->a);
  if(speedResume)f->paused();
  if(mode=="unclaimed_pause"||mode=="unclaimed_resume"||resumeRetiring)f->paused();
  if(mode=="pause_transferred"){
   require(f->engine->play(),"initial Playing for real Pause");f->wait([&]{return f->capture.outputFrames.load()>=rate/20;},"initial first PCM before transfer/Pause");
  }
  const auto feature=f->engine->loopAvailability();require(feature.contractVersion==4&&feature.allowed&&feature.nativeLoops.research&&!feature.nativeLoops.approved&&!feature.publicLoopApproved,"Research admission/approval changed");
  f->lead();f->availabilityConsistent();f->observe("initial");pass();

  const auto before=f->sample();const auto firstRawAfterIntent=f->capture.rawCount.load();const bool alreadyReady=mode=="on_ready";
  if(speedRetiring){
   require(before.position.inputFrame&&before.state.state==(speedResume?State::Paused:State::Ready),"stopped speed C/state fixture missing");
   if(latestA)require(*before.position.inputFrame==0&&*before.position.inputFrame<f->a,"latest A fixture must begin outside AB at C0");
   else require(*before.position.inputFrame>=f->a&&*before.position.inputFrame<f->b,"stopped speed C fixture outside AB");
   if(speedResume)require(*before.position.inputFrame>f->a,"Paused fixture did not distinguish source C from ReturnToA");
  }
  std::uint64_t preparationID=0,loopID=0,replacementLoopID=0;std::optional<Stationary> paused;
  std::optional<Stationary> retiringHeld;std::uint64_t retiringNativeStart=0,retiringClockEpoch=0;
  std::size_t retiringFirstRaw=0,retiringFirstCallback=0,retiringHoldSamples=0;
  std::uint64_t replacementStoppedID=0,replacedStoppedID=0;
  if(alreadyReady){preparationID=f->request();f->ready(preparationID);f->freezeComplete();}
  else{
   auto where=PrefixProgressGate::Position::Middle;
   if(mode=="on_early")where=PrefixProgressGate::Position::Early;
   if(mode=="on_before_ready")where=PrefixProgressGate::Position::BeforeReady;
   preparationID=f->hold(where);
   const auto position=f->progress.outputPosition.load();
   if(where==PrefixProgressGate::Position::Early)require(!position,"early gate already synthesized prefix");
   else if(where==PrefixProgressGate::Position::Middle)require(position>=f->a/2&&position+2048<=f->a,"middle gate not in real prefix");
   else require(position<=f->a&&position+2048>f->a,"before-ready gate did not hold final prefix block");
  }
  require(preparationID==1,"preparation ID did not start at 1");const auto preparationVersion=f->operation(preparationID).version;
  if(mode!="pause_transferred")f->audioStationary(before);
  f->observe("preparation_held_or_Ready");pass();

  const bool unclaimed=mode.starts_with("unclaimed_");const bool contextMismatch=mode=="mismatch_context";const bool rangeMismatch=mode=="mismatch_range";
  if(contextMismatch){auto stale=f->context();++stale.session;const auto rejected=f->on(f->a,f->b,stale);require(!rejected.accepted&&rejected.code==AR::StaleContext,"stale ON accepted");}
  else if(!unclaimed){
   const auto receipt=f->on(f->a+(rangeMismatch?rate:0),f->b+(rangeMismatch?rate:0),f->context());require(receipt.accepted&&receipt.id,"explicit ON rejected");loopID=receipt.id;
   const auto op=f->operation(preparationID);const auto loop=f->engine->getLoopSnapshot();
   if(rangeMismatch)require(!op.transferredToLoopID&&!loop.preparationRequestID,"different range claimed old prefix");
   else if(alreadyReady)require(!op.transferredToLoopID&&loop.preparationRequestID==preparationID&&performancePreparationJson(op)==f->completeFrozen.at(preparationID),"ON rewrote past Ready or lost its ID");
   else require(op.state==Prep::Preparing&&!op.workersJoined&&op.transferredToLoopID==loopID&&loop.preparationRequestID==preparationID&&!f->progress.left.load(),"same Preparing job was cancelled/restarted instead of transferred");
  }
  else{
   if(mode=="unclaimed_pause")require(f->engine->pause(),"unclaimed re-Pause rejected");
   else if(mode=="unclaimed_play")require(f->engine->play(),"unclaimed Play rejected");
   else if(mode=="unclaimed_resume")require(f->engine->resume(),"unclaimed Resume rejected");
   else f->engine->cancelLoopPreparation();
  }
  f->observe("action_accepted");pass();

  if(resumeRetiring){
   f->progress.armRetirement();f->releaseProgress();
   f->wait([&]{return f->progress.retireEntered.load();},"old-owner retirement hook not reached");
   retiringHeld=f->sample();const auto& held=*retiringHeld;
   require(held.state.state==State::Paused&&!held.state.resumePending&&held.loop.id==loopID&&held.loop.initialPositionComplete&&
    held.loop.preparationRequestID==preparationID&&held.diagnostics.retiringPipeline&&held.state.session!=before.state.session&&
    held.position.inputFrame==std::optional<std::uint64_t>(f->a)&&held.raw==before.raw&&held.output==before.output,
    "retirement hook did not hold adopted A/Paused before old join");
   require(held.diagnostics.pipeline.loopReuse.initialCheckpointHit&&held.diagnostics.pipeline.loopReuse.coldDiscardedFrames<2048&&
    held.diagnostics.pipeline.sourceHashPasses==1&&held.diagnostics.pipeline.sourceSnapshotCreations==1&&held.diagnostics.pipeline.residentLockCalls==1,
    "retiring adoption lost complete A checkpoint/input lease");
   f->retiringSourceSession=before.state.session;f->retiringAdoptedSession=held.state.session;
   retiringNativeStart=f->engine->getNativeDiagnostics().playCalledSteadyNs;require(retiringNativeStart,"initial native start not recorded");
   const auto callbacks=f->engine->callbackRecords();retiringFirstCallback=callbacks.size();
   require(!callbacks.empty(),"initial Paused has no callback evidence");
   for(const auto& callback:callbacks)retiringClockEpoch=std::max(retiringClockEpoch,callback.epoch);
   require(retiringClockEpoch,"initial callback clock epoch missing");
   retiringFirstRaw=f->capture.rawCount.load();const bool accepted=f->engine->resume();
   f->receipts<<"{\"kind\":\"resume_while_retiring\",\"accepted\":"<<accepted<<",\"source_session\":"<<f->retiringSourceSession
    <<",\"adopted_session\":"<<f->retiringAdoptedSession<<"}\n";f->receipts.flush();require(bool(f->receipts),"Resume receipt write");
   require(accepted,"Resume intent rejected while old owner retiring");
   const auto deadline=Tick::now()+std::chrono::milliseconds(40);
   do{f->resumeHeld(held,retiringNativeStart);++retiringHoldSamples;std::this_thread::sleep_for(std::chrono::milliseconds(1));}while(Tick::now()<deadline);
   f->resumeHeld(held,retiringNativeStart);require(retiringHoldSamples>=2,"retirement hold lacked repeated observations");
   require(f->capture.rawCount.load()==retiringFirstRaw&&f->engine->callbackRecords().size()==retiringFirstCallback,
    "Resume produced callbacks/RAW before old retirement");
   f->freezeComplete();f->observe("Resume_pending_old_retirement_held");
  }else if(mode=="pause_transferred"){
   require(f->engine->pause(),"Pause during transferred prefix rejected");paused=f->sample();require(paused->state.state==State::Paused&&paused->position.inputFrame.has_value(),"Pause did not capture real C");
   const auto op=f->operation(preparationID);require(op.state==Prep::Preparing&&op.transferredToLoopID==loopID&&!op.workersJoined&&!f->progress.left.load(),"Pause cancelled transferred explicit preparation");f->audioStationary(*paused);
  }else if(mode=="stop_transferred"){
   f->engine->stop();require(f->engine->getPlaybackState()==State::Stopped&&f->operation(preparationID).state==Prep::Cancelled&&f->progress.left.load(),"Stop did not cancel/join claimed preparation");
  }else if(mode=="close_transferred"){
   f->close(true);require(f->allAudit.copied&&f->progress.left.load(),"close did not join claimed preparation");
  }else if(speedReplacement){
   const auto c=f->context();const auto receipt=f->engine->setSpeed(.75,c.session,c.inputGeneration,c.renderEpoch);require(receipt.id&&receipt.result==ts::prototype::Phase39RequestResult::Accepted,"new speed rejected");f->acceptedStopped.insert(receipt.id);
   replacementStoppedID=receipt.id;
   f->receipts<<"{\"kind\":\"stopped_speed\",\"id\":"<<receipt.id<<",\"speed_micros\":750000,\"accepted\":true,\"source_input\":"<<*before.position.inputFrame
    <<",\"source_output\":"<<before.position.outputFrame<<",\"loop_id\":"<<loopID<<"}\n";
   if(latestA){
    replacedStoppedID=receipt.id;
    const auto latest=f->engine->setSpeed(1.0,c.session,c.inputGeneration,c.renderEpoch);
    require(latest.id&&latest.id!=receipt.id&&latest.result==ts::prototype::Phase39RequestResult::Accepted,"100 to 75 to 100 latest request rejected/duplicated");
    f->acceptedStopped.insert(latest.id);replacementStoppedID=latest.id;
    f->receipts<<"{\"kind\":\"stopped_speed\",\"id\":"<<latest.id<<",\"speed_micros\":1000000,\"accepted\":true,\"source_input\":"<<*before.position.inputFrame
     <<",\"source_output\":"<<before.position.outputFrame<<",\"loop_id\":"<<loopID<<",\"replaces\":"<<receipt.id<<"}\n";
    const auto history=f->engine->stoppedSpeedHistory();
    require(history.size()==2&&history[0].id==receipt.id&&history[0].state==StoppedSpeedState::Replaced&&history[1].id==latest.id&&history[1].state==StoppedSpeedState::Preparing,
     "latest stopped speed did not replace unstarted 75 operation");
   }
   f->receipts.flush();require(bool(f->receipts),"stopped speed receipt write");f->freezeComplete();
   require(f->operation(preparationID).state==Prep::Cancelling&&f->operation(preparationID).transferredToLoopID==loopID,"new speed did not invalidate transferred prefix");f->audioStationary(before);
   if(speedRetiring){f->retiringCallsBefore=f->progress.retireCalls.load();f->retiringExpectedEpochs=initialSeek?4:3;f->progress.armRetirement();}
  }else if(mode=="replace_transferred"){
   const auto receipt=f->on(f->a+rate,f->b+rate,f->context());require(receipt.accepted&&receipt.id!=loopID,"replacement ON rejected/reused Loop ID");replacementLoopID=receipt.id;
   require(f->operation(preparationID).state==Prep::Cancelling&&f->operation(preparationID).transferredToLoopID==loopID,"new range did not cancel old transferred prefix");f->audioStationary(before);
  }else if(mode=="input_transferred"){
   const auto replacement=out/"replacement_input.wav";require(std::filesystem::copy_file(argv[2],replacement),"copy second input");
   require(f->engine->prepare(replacement,f->options),"new input rejected");
   f->wait([&]{const auto d=f->engine->getPlaybackDiagnostics();return f->engine->getPlaybackState()==State::Ready&&d.pipeline.analysisDone;},"new input Ready");
   require(f->engine->getStateSnapshot().inputGeneration!=before.state.inputGeneration&&f->operation(preparationID).state==Prep::Cancelled&&f->progress.left.load(),"input change retained old prefix/identity");
  }else if(unclaimed||rangeMismatch){
   require(f->operation(preparationID).state==Prep::Cancelling&&!f->operation(preparationID).workersJoined&&!f->operation(preparationID).transferredToLoopID&&!f->engine->loopPreparationSnapshot().available,"optional/nonmatching preparation cancellation changed");
  }else if(contextMismatch){require(f->operation(preparationID).state==Prep::Preparing&&!f->operation(preparationID).transferredToLoopID&&!f->progress.left.load(),"rejected ON disturbed valid prefix");f->audioStationary(before);}
  else if(!alreadyReady){f->audioStationary(before);require(f->operation(preparationID).state==Prep::Preparing&&!f->engine->loopPreparationSnapshot().available,"claimed preparation published Ready before gate release");}
  if(f->engine)f->observe("held_state_after_interrupt");pass();

  if(f->engine){
   f->releaseProgress();
   const bool cancelled=unclaimed||rangeMismatch||mode=="stop_transferred"||speedReplacement||mode=="replace_transferred"||mode=="input_transferred";
   f->terminal(preparationID,cancelled?Prep::Cancelled:Prep::Ready);
   const auto op=f->operation(preparationID);
   require(op.version==preparationVersion,"preparation job was restarted under another version");
   if(!unclaimed&&!rangeMismatch&&!contextMismatch&&!alreadyReady)require(op.transferredToLoopID==loopID,"terminal row lost transfer fact");
   else require(!op.transferredToLoopID,"unclaimed/past Ready terminal row gained transfer fact");
   f->checkHistory();f->observe("terminal_preparation_joined");
  }else{
   require(f->allAudit.preparations.size()==1&&f->allAudit.preparations.front().id==preparationID&&f->allAudit.preparations.front().state==Prep::Cancelled&&f->allAudit.preparations.front().workersJoined&&f->allAudit.preparations.front().transferredToLoopID==loopID,"close lost claimed operation/terminal/join");
  }
  pass();

  if(resumeRetiring){
   require(retiringHeld.has_value(),"retirement stationary baseline missing");
   f->resumeHeld(*retiringHeld,retiringNativeStart);f->progress.releaseRetirement();
   f->wait([&]{const auto s=f->engine->getStateSnapshot();const auto d=f->engine->getPlaybackDiagnostics();
    return f->progress.retireLeft.load()&&f->progress.retireCleanups.load()==1&&!d.retiringPipeline&&
     s.state==State::Playing&&!s.resumePending&&f->capture.rawCount.load()>retiringFirstRaw&&
     f->capture.outputFrames.load()>retiringHeld->output&&d.consumedFrames>retiringHeld->diagnostics.consumedFrames;
   },"retirement release did not adopt accepted Resume exactly after cleanup");
   const auto resumedNativeStart=f->engine->getNativeDiagnostics().playCalledSteadyNs;
   require(resumedNativeStart>retiringNativeStart&&resumedNativeStart>=f->progress.retireLeftNs.load(),
    "native Resume start preceded retirement gate release");
   require(ph58::RealtimePipeline::executionOwnerCounts().alive==1&&f->progress.retireCalls.load()==1,
    "Resume started before old execution owner destruction or duplicated retirement");
   const auto stableUntil=Tick::now()+std::chrono::milliseconds(40);
   do{
    const auto s=f->engine->getStateSnapshot();require(s.state==State::Playing&&!s.resumePending&&s.session==f->retiringAdoptedSession&&
     !f->engine->getPlaybackDiagnostics().retiringPipeline&&f->engine->getNativeDiagnostics().playCalledSteadyNs==resumedNativeStart,
     "accepted Resume repeated native start or revived retirement/pending intent");
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
   }while(Tick::now()<stableUntil);
   require(f->engine->pause(),"Pause after resumed A rejected");
   const auto resumed=f->sample();const auto& raw=f->capture.rawRecords[retiringFirstRaw];
   require(resumed.state.state==State::Paused&&!resumed.state.resumePending&&resumed.state.session==f->retiringAdoptedSession&&
    raw.session==f->retiringAdoptedSession&&raw.epoch==retiringHeld->state.renderEpoch&&
    raw.at==retiringHeld->diagnostics.pipeline.outputStartFrame&&raw.frames,
    "first resumed RAW did not begin at adopted A/new owner");
   const auto callbacks=f->engine->callbackRecords();std::size_t resumedCallbacks=0;
   require(callbacks.size()>retiringFirstCallback&&!f->engine->getNativeDiagnostics().callbackRecordsDropped,
    "resumed callback records missing/dropped");
   for(std::size_t i=retiringFirstCallback;i<callbacks.size();++i){
    require(callbacks[i].epoch==retiringClockEpoch+1,"Resume did not create exactly one new callback clock epoch");++resumedCallbacks;
   }
   f->freezeComplete();f->lead();f->observe("Resume_once_after_old_retirement");
   std::ofstream evidence(out/"resume_retiring.json");
   evidence<<"{\"schema\":1,\"callback_gate\":false,\"normal_retirement_gate\":true,\"resume_requests\":1,\"held_ms\":40,\"held_observations\":"<<retiringHoldSamples
    <<",\"old_session\":"<<f->retiringSourceSession<<",\"adopted_session\":"<<f->retiringAdoptedSession
    <<",\"gate_entered_steady_ns\":"<<f->progress.retireEnteredNs.load()<<",\"gate_release_steady_ns\":"<<f->progress.retireReleasedNs.load()
    <<",\"gate_left_steady_ns\":"<<f->progress.retireLeftNs.load()<<",\"retirement_calls\":"<<f->progress.retireCalls.load()<<",\"cleanup_calls\":"<<f->progress.retireCleanups.load()
    <<",\"native_start_before\":"<<retiringNativeStart<<",\"native_start_after\":"<<resumedNativeStart
    <<",\"clock_epoch_before\":"<<retiringClockEpoch<<",\"clock_epoch_after\":"<<retiringClockEpoch+1<<",\"resumed_callback_records\":"<<resumedCallbacks
    <<",\"first_new_raw_offset\":"<<raw.at<<",\"first_new_raw_frames\":"<<raw.frames<<",\"consumed_at_hold\":"<<retiringHeld->diagnostics.consumedFrames
    <<",\"consumed_after_resume\":"<<resumed.diagnostics.consumedFrames<<",\"resume_pending_after\":false,\"performance\":\"NOT_ASSESSED\",\"independent_PCM\":\"NOT_RUN\"}\n";
   evidence.close();require(bool(evidence),"retirement Resume evidence write");
  }else if(speedRetiring){
   const auto expectedSpeed=latestA?1000000u:750000u;
   f->wait([&]{return f->progress.retireEntered.load();},"replacement stopped speed did not reach old-owner retirement");
   const auto held=f->sample();
   require(held.state.state==before.state.state&&!held.state.resumePending&&held.state.session!=before.state.session&&
    held.state.inputGeneration==before.state.inputGeneration&&held.diagnostics.retiringPipeline&&held.loop.id==loopID&&held.loop.enabled&&
    held.loop.initialPositionComplete&&held.loop.preparationRequestID==preparationID,
    "stopped speed replacement did not retain initial Loop intent/new stationary owner");
   require(held.position.inputFrame==std::optional<std::uint64_t>(f->a)&&held.position.outputFrame==held.diagnostics.pipeline.outputStartFrame&&
    held.state.stoppedSpeed&&held.state.stoppedSpeed->id==replacementStoppedID&&held.state.stoppedSpeed->state==StoppedSpeedState::Preparing&&
    held.state.stoppedSpeed->resumeInputFrame==f->a&&held.state.stoppedSpeed->sourceSession==before.state.session&&
    held.state.stoppedSpeed->sourceRenderEpoch==before.state.renderEpoch&&held.state.stoppedSpeed->consumedOutputFrame==before.position.outputFrame&&
    held.state.stoppedSpeed->loopID==loopID&&held.state.stoppedSpeed->speedMicros==expectedSpeed,
    "unfinished ReturnToA was replaced by source C or source evidence was overwritten");
   require(held.raw==before.raw&&held.output==before.output&&!held.diagnostics.pipeline.fastLocalSeek&&
    held.diagnostics.pipeline.sourceHashPasses==1&&held.diagnostics.pipeline.sourceSnapshotCreations==1&&held.diagnostics.pipeline.residentLockCalls==1,
    "replacement used local approximation, repeated input preparation or emitted PCM before start");
   f->retiringSourceSession=before.state.session;f->retiringAdoptedSession=held.state.session;
   const auto oldJoined=[&]{const auto epochs=f->engine->closedEpochs();return std::count_if(epochs.begin(),epochs.end(),[&](const auto& e){
    return e.pipeline.session==f->retiringSourceSession&&!e.preparedOnly&&e.pipeline.finalDataAvailable&&e.pipeline.lifecycle==ph58::LifecycleState::Finalized;
   });};
   require(oldJoined()==0,"old owner was archived before held retirement join");
   retiringNativeStart=f->engine->getNativeDiagnostics().playCalledSteadyNs;
   const auto originalCallbacks=f->engine->callbackRecords();retiringFirstCallback=originalCallbacks.size();
   for(const auto& callback:originalCallbacks)retiringClockEpoch=std::max(retiringClockEpoch,callback.epoch);
   require(speedResume?retiringClockEpoch!=0:originalCallbacks.empty(),"initial Ready/Paused callback fixture changed");
   retiringFirstRaw=f->capture.rawCount.load();
   if(speedPlay){
    require(f->engine->play(),"Play intent rejected while replacement old owner retiring");
    f->receipts<<"{\"kind\":\"play_while_replacement_retiring\",\"accepted\":true,\"stopped_speed_id\":"<<replacementStoppedID<<"}\n";
   }
   const auto holdUntil=Tick::now()+std::chrono::milliseconds(40);
   do{
    const auto now=f->sample();const auto owners=ph58::RealtimePipeline::executionOwnerCounts();
    require(!f->progress.retireLeft.load()&&now.state.state==held.state.state&&now.state.resumePending==speedPlay&&
     now.state.session==held.state.session&&now.state.renderEpoch==held.state.renderEpoch&&now.state.inputGeneration==held.state.inputGeneration&&
     now.position.inputFrame==held.position.inputFrame&&now.position.outputFrame==held.position.outputFrame&&now.raw==held.raw&&now.output==held.output&&
     now.diagnostics.consumedFrames==held.diagnostics.consumedFrames&&now.diagnostics.currentEpochPresentedFrame==held.diagnostics.currentEpochPresentedFrame&&
     now.diagnostics.retiringPipeline&&f->engine->getNativeDiagnostics().playCalledSteadyNs==retiringNativeStart&&
     now.state.stoppedSpeed&&now.state.stoppedSpeed->id==replacementStoppedID&&now.state.stoppedSpeed->state==StoppedSpeedState::Preparing,
     "replacement started/moved A/published ReadyForResume before old join");
    require(owners.alive==2&&owners.peak<=2&&oldJoined()==0&&!f->engine->loopPreparationSnapshot().available,
     "replacement retirement lost old/new owner bound or republished optional preparation");
    require(f->engine->callbackRecords().size()==retiringFirstCallback&&f->capture.rawCount.load()==retiringFirstRaw,
     "replacement emitted callback/RAW while old retirement held");
    ++retiringHoldSamples;std::this_thread::sleep_for(std::chrono::milliseconds(1));
   }while(Tick::now()<holdUntil);
   require(retiringHoldSamples>=2,"replacement retirement lacked repeated observations");
   f->freezeComplete();f->observe("replacement_A_held_before_old_join");f->progress.releaseRetirement();
   f->wait([&]{const auto s=f->engine->getStateSnapshot();return f->progress.retireLeft.load()&&f->progress.retireCleanups.load()==1&&
    !f->engine->getPlaybackDiagnostics().retiringPipeline&&s.stoppedSpeed&&s.stoppedSpeed->id==replacementStoppedID&&
    s.stoppedSpeed->state==StoppedSpeedState::ReadyForResume;},"replacement ReadyForResume after old join missing");
   require(oldJoined()==1&&ph58::RealtimePipeline::executionOwnerCounts().alive==1,"replacement ReadyForResume preceded old join/destruction");
   const auto prepared=f->engine->getStateSnapshot();
   require(prepared.stoppedSpeed&&prepared.stoppedSpeed->resumeInputFrame==f->a&&prepared.stoppedSpeed->consumedOutputFrame==before.position.outputFrame&&
    prepared.stoppedSpeed->sourceSession==before.state.session&&prepared.stoppedSpeed->sourceRenderEpoch==before.state.renderEpoch&&
    prepared.stoppedSpeed->session==held.state.session&&prepared.stoppedSpeed->renderEpoch==held.state.renderEpoch&&
    prepared.stoppedSpeed->readyNs>prepared.stoppedSpeed->acceptedNs&&prepared.stoppedSpeed->loopID==loopID,
    "replacement ReadyForResume lost source C, A target or operation lineage");
   if(!speedPlay){
    f->audioStationary(held);require(!prepared.resumePending&&!prepared.stoppedSpeed->outputStarted,"replacement auto-started without explicit intent");
    require(speedResume?f->engine->resume():f->engine->play(),"explicit Resume/Play after replacement ReadyForResume rejected");
    f->receipts<<"{\"kind\":"<<ph58::jsonString(speedResume?"resume_after_replacement_ready":"play_after_latest_A_ready")
     <<",\"accepted\":true,\"stopped_speed_id\":"<<replacementStoppedID<<"}\n";
   }
   f->receipts.flush();require(bool(f->receipts),"replacement start receipt write");
   f->wait([&]{const auto s=f->engine->getStateSnapshot();const auto d=f->engine->getPlaybackDiagnostics();return
    s.state==State::Playing&&!s.resumePending&&s.session==held.state.session&&s.stoppedSpeed&&s.stoppedSpeed->id==replacementStoppedID&&
    s.stoppedSpeed->outputStarted&&f->capture.rawCount.load()>retiringFirstRaw&&f->capture.outputFrames.load()>=held.output+rate/20&&
    d.consumedFrames>held.diagnostics.consumedFrames&&!d.retiringPipeline;},"accepted replacement start remained pending or produced no actual PCM");
   const auto startAfter=f->engine->getNativeDiagnostics().playCalledSteadyNs;
   require(startAfter>retiringNativeStart&&startAfter>=f->progress.retireLeftNs.load(),"replacement native start preceded old retirement release");
   const auto stableUntil=Tick::now()+std::chrono::milliseconds(40);
   do{const auto s=f->engine->getStateSnapshot();require(s.state==State::Playing&&!s.resumePending&&s.session==held.state.session&&
    s.renderEpoch==held.state.renderEpoch&&f->engine->getLoopSnapshot().id==loopID&&
    f->engine->getNativeDiagnostics().playCalledSteadyNs==startAfter&&!f->engine->getPlaybackDiagnostics().retiringPipeline,
    "replacement repeated native start or changed Loop/epoch after cleanup");std::this_thread::sleep_for(std::chrono::milliseconds(1));
   }while(Tick::now()<stableUntil);
   require(f->engine->pause(),"Pause after replacement real PCM rejected");const auto resumed=f->sample();
   const auto& firstRaw=f->capture.rawRecords[retiringFirstRaw];
   require(resumed.state.state==State::Paused&&!resumed.state.resumePending&&resumed.state.session==held.state.session&&
    firstRaw.session==held.state.session&&firstRaw.epoch==held.state.renderEpoch&&firstRaw.at==held.diagnostics.pipeline.outputStartFrame&&firstRaw.frames,
    "replacement first actual RAW did not start at adopted A/new owner");
   const auto callbacks=f->engine->callbackRecords();require(callbacks.size()>retiringFirstCallback&&!f->engine->getNativeDiagnostics().callbackRecordsDropped,
    "replacement callback evidence missing/dropped");
   const auto expectedClock=speedResume?retiringClockEpoch+1:1;
   for(std::size_t i=retiringFirstCallback;i<callbacks.size();++i)require(callbacks[i].epoch==expectedClock,"replacement repeated callback clock start");
   if(latestA){const auto stopped=f->engine->stoppedSpeedHistory();require(stopped.size()==2&&stopped[0].id==replacedStoppedID&&
    stopped[0].state==StoppedSpeedState::Replaced&&!stopped[0].outputStarted&&stopped[1].id==replacementStoppedID&&stopped[1].speedMicros==1000000&&
    stopped[1].resumeInputFrame==f->a&&stopped[1].outputStarted,"latest A replacement resurrected 75 or lost final 100 target");}
   f->freezeComplete();f->lead();f->observe("replacement_A_once_after_old_join");
   std::ofstream evidence(out/"speed_transferred_resume.json");
   evidence<<"{\"schema\":1,\"mode\":"<<ph58::jsonString(mode)<<",\"callback_gate\":false,\"normal_retirement_gate\":true,\"start_requests\":1"
    <<",\"intent_while_retiring\":"<<speedPlay<<",\"source_input\":"<<*before.position.inputFrame<<",\"source_output\":"<<before.position.outputFrame
    <<",\"source_outside_AB\":"<<(*before.position.inputFrame<f->a||*before.position.inputFrame>=f->b)<<",\"A\":"<<f->a<<",\"B\":"<<f->b
    <<",\"adopted_input\":"<<*held.position.inputFrame<<",\"adopted_output\":"<<held.position.outputFrame<<",\"loop_id\":"<<loopID
    <<",\"preparation_id\":"<<preparationID<<",\"stopped_speed_id\":"<<replacementStoppedID<<",\"replaced_stopped_speed_id\":"<<replacedStoppedID
    <<",\"initial_position_complete_at_A\":"<<held.loop.initialPositionComplete<<",\"source_session\":"<<before.state.session<<",\"adopted_session\":"<<held.state.session
    <<",\"hold_observations\":"<<retiringHoldSamples<<",\"gate_release_ns\":"<<f->progress.retireReleasedNs.load()<<",\"gate_left_ns\":"<<f->progress.retireLeftNs.load()
    <<",\"native_start_before\":"<<retiringNativeStart<<",\"native_start_after\":"<<startAfter<<",\"old_joined_deliveries\":"<<oldJoined()
    <<",\"first_new_raw_offset\":"<<firstRaw.at<<",\"first_new_raw_frames\":"<<firstRaw.frames<<",\"target_speed_micros\":"<<expectedSpeed
    <<",\"ready_stopped_operation\":"<<performanceStoppedJson(*prepared.stoppedSpeed)<<",\"performance\":\"NOT_ASSESSED\",\"independent_PCM\":\"NOT_RUN\"}\n";
   evidence.close();require(bool(evidence),"replacement Resume coordinate evidence write");
  }else if(mode.starts_with("on_")||mode=="pause_transferred"){
   f->adopted(loopID,f->a,preparationID,true);const auto staticAtA=f->sample();
   require(staticAtA.output==(paused?paused->output:before.output)&&staticAtA.raw==(paused?paused->raw:before.raw),"claimed ON auto-consumed output");f->audioStationary(staticAtA);f->observe("ON_A_static_before_explicit_start");
   if(mode=="on_mid"||mode=="pause_transferred"){
    const auto first=f->capture.rawCount.load();const auto at=f->engine->getPlaybackDiagnostics().pipeline.outputStartFrame;
    require(mode=="pause_transferred"?f->engine->resume():f->engine->play(),"explicit start after claimed ON rejected");
    f->wait([&]{return f->engine->getLoopSnapshot().cycles>=2;},"two real claimed-Loop cycles");require(f->engine->pause(),"postcapture Pause");
    require(f->capture.rawCount.load()>first&&f->capture.rawRecords[first].at==at&&f->capture.rawRecords[first].session!=before.state.session,"first adopted RAW did not start at A/new owner");f->observe("claimed_A_PCM_and_two_cycles");
   }
  }else if(rangeMismatch||mode=="replace_transferred"){
   f->adopted(replacementLoopID?replacementLoopID:loopID,f->a+rate,0,false);require(f->capture.outputFrames.load()==before.output,"new range auto-played");f->observe("latest_range_A_static");
  }else if(mode=="speed_transferred"){
   f->wait([&]{const auto s=f->engine->getStateSnapshot();return s.stoppedSpeed&&s.stoppedSpeed->state==StoppedSpeedState::ReadyForResume&&!f->engine->getPlaybackDiagnostics().retiringPipeline;},"latest stopped speed ReadyForResume");
   require(f->engine->getPlaybackState()==State::Ready&&f->engine->getCurrentPlaybackPosition().inputFrame==before.position.inputFrame&&!f->engine->getStateSnapshot().resumePending&&f->capture.outputFrames.load()==before.output,"speed cancellation changed C/auto-resumed");f->observe("latest_speed_C_static");
  }else if(mode=="unclaimed_play"||mode=="unclaimed_resume"){
   f->wait([&]{return f->capture.outputFrames.load()>before.output;},"original FIFO did not start");require(f->engine->pause(),"Pause after optional cancellation/start");
   require(f->capture.rawCount.load()>firstRawAfterIntent,"original FIFO RAW not observed after intent");
   const auto& raw=f->capture.rawRecords[firstRawAfterIntent];require(raw.session==before.state.session&&raw.epoch==before.state.renderEpoch&&raw.at==before.position.outputFrame&&!f->engine->getLoopSnapshot().enabled,"optional preparation stole original FIFO start");f->observe("unclaimed_original_FIFO_started");
  }else if(contextMismatch||mode=="unclaimed_pause"||mode=="unclaimed_cancel"){
   f->audioStationary(before);require(!f->engine->getLoopSnapshot().enabled,"optional cancellation/rejected ON enabled Loop");
   require(f->engine->loopPreparationSnapshot().available==contextMismatch,"optional availability after cancel/rejected ON");f->observe("optional_C_static");
  }else if(mode=="input_transferred"){
   require(f->engine->getPlaybackState()==State::Ready&&!f->engine->getLoopSnapshot().enabled&&!f->engine->loopPreparationSnapshot().available&&f->engine->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(0)&&!f->capture.outputFrames.load(),"input change retained Loop/cache/C");f->observe("new_input_static_origin");
  }else if(mode=="stop_transferred"){
   require(f->engine->getCurrentPlaybackPosition().inputFrame==before.position.inputFrame&&!f->capture.outputFrames.load(),"Stop changed captured C/played");f->observe("stopped_C_preserved");
  }else require(!f->engine&&!f->capture.outputFrames.load(),"close emitted PCM");
  pass();

  if(f->engine){f->resources();f->freezeComplete();f->observe("before_close");}
  else require(!ph58::RealtimePipeline::executionOwnerCounts().alive&&ph58::RealtimePipeline::executionOwnerCounts().peak<=2&&f->finalDiagnostics.pipeline.loopReuse.checkpointPeak<=2,"direct close resource bound");
  require(!f->progress.expired.load()&&!f->progress.retireExpired.load(),"normal gate expired");pass();
  f->close(false);f->savePerformance();f->fullFinalCheck();pass();require(done==8,"incomplete fixed check set");
  checks.close();f->receipts.close();f->observations.close();f->progressObservations.close();finish(true,"");return 0;
 }catch(const std::exception& error){
  if(f){f->progress.released=true;f->progress.releaseRetirement();f->gate.released=true;try{f->close(true);f->savePerformance();f->receipts.close();f->observations.close();f->progressObservations.close();}catch(...){}}
  checks.close();finish(false,error.what());std::cerr<<error.what()<<'\n';return 1;
 }
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=performancePreparationMain(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});control.join();return result;}

