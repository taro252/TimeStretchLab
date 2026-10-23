// 公開v3先行準備・失効・資源・互換性。MODE INPUT PRESET NEW_OUT SOURCE_SHA。
// 1 mode/process。全制御は専用通常thread、gateも通常workerだけ。
#define PHASE62_PLAYING_LEDGER_NO_MAIN 1
#include "Phase62PlayingLedgerNative.cpp"
#include <cstring>
#include <iomanip>
#include <map>
#include <utility>
namespace {
using Prep=progressive::LoopPreparationState;
using AR=progressive::AvailabilityReason;
using Policy=progressive::FeaturePolicy;
constexpr std::size_t captureLimit=96000;
const std::array<const char*,22> adoptionModes{
 "prewarm_ready","cancel_preparing","cancel_ready","pause_preparing","pause_ready",
 "stop_preparing","stop_ready","speed_preparing","speed_ready","seek_preparing","seek_ready",
 "replace_preparing","replace_ready","close_preparing","close_ready","invalid_context",
 "legacy_disabled","policy_precedence","reservation_delta","legacy_api","play_preparing","resume_preparing"};
const std::array<const char*,8> adoptionChecks{
 "feature_configuration","initial_ready_lead","preparation_receipt","action_state",
 "preparation_history","stationary_or_adoption","resources","final_owned_audit"};

std::string preparationJson(const progressive::LoopPreparationOperation& p){
 std::ostringstream s;s<<std::setprecision(17)<<"{\"id\":"<<p.id<<",\"input_generation\":"<<p.inputGeneration<<",\"session\":"<<p.session<<",\"source_epoch\":"<<p.sourceRenderEpoch
 <<",\"version\":"<<p.version<<",\"A\":"<<p.inputA<<",\"B\":"<<p.inputBExclusive<<",\"accepted_ns\":"<<p.acceptedNs<<",\"started_ns\":"<<p.startedNs
 <<",\"checkpoint_ready_ns\":"<<p.checkpointReadyNs<<",\"ready_ns\":"<<p.readyNs<<",\"checkpoint_output\":"<<p.checkpointOutput<<",\"discarded_frames\":"<<p.discardedFrames
 <<",\"speed_micros\":"<<p.speedMicros<<",\"state\":"<<ph58::jsonString(progressive::name(p.state))<<",\"code\":"<<ph58::jsonString(progressive::name(p.code))
 <<",\"prefix_cpu_s\":"<<p.prefixCpuS<<",\"prefix_wall_s\":"<<p.prefixWallS<<",\"workers_joined\":"<<(p.workersJoined?"true":"false")<<",\"reason\":"<<ph58::jsonString(p.reason)<<'}';return s.str();
}
struct PreparationGate{
 std::atomic<bool> armed{false},entered{false},released{false},left{false},expired{false};
 std::atomic<std::uint64_t> ignoredSession{0},workerSession{0};
 void arm(std::uint64_t ignored){require(!entered.load()||left.load(),"gate rearm before leave");ignoredSession=ignored;workerSession=0;entered=false;released=false;left=false;expired=false;armed=true;}
 static void event(void* context,ph58::ControlTestPoint point,std::uint64_t session,std::uint64_t)noexcept{
  auto& g=*static_cast<PreparationGate*>(context);
  if(point!=ph58::ControlTestPoint::CheckpointPermit||session==g.ignoredSession.load()||!g.armed.exchange(false))return;
  g.workerSession=session;g.entered=true;const auto deadline=Tick::now()+std::chrono::seconds(10);
  while(!g.released.load()&&Tick::now()<deadline)std::this_thread::sleep_for(std::chrono::milliseconds(1));
  if(!g.released.load())g.expired=true;g.left=true;
 }
 static void engineEvent(void* context,ProgressiveControlTestPoint point)noexcept{
  // Stopが失効を公開した後、join待機へ入る通常制御hookで解放する。
  if(point==ProgressiveControlTestPoint::SeekCleanupWait)static_cast<PreparationGate*>(context)->released=true;
 }
};
struct AdoptionRaw{std::uint64_t session=0,epoch=0,at=0,frames=0,offset=0;};
struct AdoptionCapture{
 NativeCapture audit;std::size_t channels;
 std::vector<float> rawPcm,outputPcm;std::vector<AdoptionRaw> rawRecords;std::vector<ProgressiveOutputSpan> spans;
 std::atomic<std::size_t> rawFrames{0},outputFrames{0},rawCount{0},spanCount{0},errors{0};
 explicit AdoptionCapture(std::size_t ch):audit(ch),channels(ch),rawPcm(captureLimit*ch),outputPcm(captureLimit*ch),rawRecords(4096),spans(4096){}
 static void raw(void* context,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
  auto& c=*static_cast<AdoptionCapture*>(context);NativeCapture::raw(&c.audit,pcm,n,at,generation,epoch,session);
  const auto frames=c.rawFrames.load(),index=c.rawCount.load();if(index>=c.rawRecords.size()||frames+n>captureLimit){++c.errors;return;}
  c.rawRecords[index]={session,epoch,at,n,frames};for(std::size_t i=0;i<n;++i)for(std::size_t ch=0;ch<c.channels;++ch)c.rawPcm[(frames+i)*c.channels+ch]=pcm[ch][i];
  c.rawFrames=frames+n;c.rawCount=index+1;
 }
 static void output(void* context,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
  auto& c=*static_cast<AdoptionCapture*>(context);NativeCapture::output(&c.audit,pcm,span);
  const auto frames=c.outputFrames.load(),index=c.spanCount.load();if(index>=c.spans.size()||frames+span.frames>captureLimit){++c.errors;return;}
  c.spans[index]=span;for(std::size_t i=0;i<span.frames;++i)for(std::size_t ch=0;ch<c.channels;++ch)c.outputPcm[(frames+i)*c.channels+ch]=pcm[ch][i];
  c.outputFrames=frames+span.frames;c.spanCount=index+1;
 }
 void save(const std::filesystem::path& out){
  std::ofstream raw(out/"raw.f32",std::ios::binary),output(out/"output_before_gain.f32",std::ios::binary),records(out/"raw_records.jsonl"),spanFile(out/"spans.jsonl");
  raw.write(reinterpret_cast<const char*>(rawPcm.data()),rawFrames.load()*channels*sizeof(float));output.write(reinterpret_cast<const char*>(outputPcm.data()),outputFrames.load()*channels*sizeof(float));
  for(std::size_t i=0;i<rawCount.load();++i){const auto& r=rawRecords[i];records<<"{\"session\":"<<r.session<<",\"epoch\":"<<r.epoch<<",\"at\":"<<r.at<<",\"frames\":"<<r.frames<<",\"raw_offset\":"<<r.offset<<"}\n";}
  spanFile<<std::setprecision(9);
  for(std::size_t i=0;i<spanCount.load();++i){const auto& s=spans[i];spanFile<<"{\"callback_frame\":"<<s.callbackFrame<<",\"new_epoch\":"<<s.newEpoch<<",\"old_epoch\":"<<s.oldEpoch<<",\"new_at\":"<<s.newOutputOffset<<",\"old_at\":"<<s.oldOutputOffset<<",\"frames\":"<<s.frames<<",\"new_received\":"<<s.newReceivedFrames<<",\"old_received\":"<<s.oldReceivedFrames<<",\"mixed\":"<<s.mixedFrames<<",\"transition_offset\":"<<s.transitionOffset<<",\"transition_length\":"<<s.transitionLength
   <<",\"periodic\":"<<s.periodicBoundary<<",\"head\":"<<s.correctionHead<<",\"tail\":"<<s.correctionTail<<",\"boundary_frames\":"<<s.boundaryFrames<<",\"period_frames\":"<<s.periodFrames<<",\"period_offset\":"<<s.periodOffset<<",\"boundary_last\":["<<s.boundaryLast[0]<<','<<s.boundaryLast[1]<<"],\"boundary_first\":["<<s.boundaryFirst[0]<<','<<s.boundaryFirst[1]<<"],\"correction_before_mix\":"<<s.correctionBeforeMix
   <<",\"old_periodic\":"<<s.oldPeriodicBoundary<<",\"old_head\":"<<s.oldCorrectionHead<<",\"old_tail\":"<<s.oldCorrectionTail<<",\"old_boundary_frames\":"<<s.oldBoundaryFrames<<",\"old_period_frames\":"<<s.oldPeriodFrames<<",\"old_period_offset\":"<<s.oldPeriodOffset<<",\"old_boundary_last\":["<<s.oldBoundaryLast[0]<<','<<s.oldBoundaryLast[1]<<"],\"old_boundary_first\":["<<s.oldBoundaryFirst[0]<<','<<s.oldBoundaryFirst[1]<<"]}\n";}
  raw.close();output.close();records.close();spanFile.close();require(bool(raw)&&bool(output)&&bool(records)&&bool(spanFile),"capture write");
 }
};
struct OwnedOperations{
 std::vector<progressive::SeekOperation> seeks;
 std::vector<StoppedSpeedOperation> stopped;
 std::vector<progressive::LoopSpeedOperation> speeds;
 std::vector<progressive::LoopPreparationOperation> preparations;
 std::uint64_t calls=0,engineSerial=0,preparation=0;bool copied=false,joined=false,retired=false,error=false;
 OwnedOperations(){seeks.reserve(4096);stopped.reserve(4096);speeds.reserve(4096);preparations.reserve(4096);}
 static bool receive(void* context,const FinalOperationAudit& a)noexcept{
  auto& c=*static_cast<OwnedOperations*>(context);if(++c.calls!=1||!a.engineSerial||!a.workersJoined||!a.retirementComplete||a.seeks.size()>4096||a.stoppedSpeeds.size()>4096||a.loopSpeeds.size()>4096||a.loopPreparations.size()>4096){c.error=true;return false;}
  c.engineSerial=a.engineSerial;c.preparation=a.preparation;c.joined=a.workersJoined;c.retired=a.retirementComplete;
  try{c.seeks.assign(a.seeks.begin(),a.seeks.end());c.stopped.assign(a.stoppedSpeeds.begin(),a.stoppedSpeeds.end());c.speeds.assign(a.loopSpeeds.begin(),a.loopSpeeds.end());c.preparations.assign(a.loopPreparations.begin(),a.loopPreparations.end());c.copied=true;}catch(...){c.error=true;return false;}return true;
 }
};
struct Stationary{
 ProgressiveStateSnapshot state;ProgressivePosition position;ProgressiveDiagnostics diagnostics;progressive::LoopSnapshot loop;std::uint64_t raw=0,output=0;
};
struct AdoptionNativeFixture{
 PreparationGate gate;FinalLedgerSink loopAudit;OwnedOperations allAudit;AdoptionCapture capture;
 std::unique_ptr<ProgressiveMacPlaybackEngine> engine=std::make_unique<ProgressiveMacPlaybackEngine>();
 ProgressiveOptions options;std::filesystem::path input,out;unsigned rate;std::size_t channels;std::uint64_t a,b,serial=0;
 std::set<std::uint64_t> acceptedPreparations,acceptedSeeks,acceptedStopped;std::map<std::uint64_t,std::string> frozen;
 std::ofstream observations;ProgressiveDiagnostics finalDiagnostics;ProgressiveNativeDiagnostics finalNative;
 AdoptionNativeFixture(const std::filesystem::path& file,Preset preset,const std::filesystem::path& folder,unsigned sampleRate,std::size_t ch)
 :capture(ch),input(file),out(folder),rate(sampleRate),channels(ch),a(2ULL*rate),b(a+rate/2),observations(folder/"observations.jsonl"){
  options.preset=preset;options.initialSpeed=1;options.callbackRecordLimit=4096;
  options.featurePolicy=progressive::FeaturePolicyOptions{progressive::contractVersion,Policy::Research,Policy::Research,Policy::Research};
  options.controlTestHooks={&gate,PreparationGate::engineEvent};options.pipelineControlTestHooks={&gate,PreparationGate::event,nullptr};
  options.observerContext=&capture;options.observeEpochPcm=AdoptionCapture::raw;options.observeOutputPcm=AdoptionCapture::output;
  options.finalLoopSpeedAuditContext=&loopAudit;options.receiveFinalLoopSpeedAudit=FinalLedgerSink::receive;
  options.finalOperationAuditContext=&allAudit;options.receiveFinalOperationAudit=OwnedOperations::receive;
  options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();hostCallbackCppNew.fetch_add(callbackNew);callbackCounting=false;},[]()noexcept{return callbackNew;}};
 }
 ~AdoptionNativeFixture(){gate.released=true;engine.reset();}
 template<class P>void until(P predicate,const char* why){
  const auto deadline=Tick::now()+std::chrono::seconds(12);
  while(!predicate()){require(!gate.expired.load(),"normal-worker gate expired");if(engine&&engine->getPlaybackState()==State::Failed)throw std::runtime_error(engine->getPlaybackDiagnostics().error);require(Tick::now()<deadline,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
  require(!gate.expired.load(),"normal-worker gate expired");
 }
 std::size_t steadyLead()const{return options.preset==Preset::Candidate?16384:12288;}
 void prepare(){
  require(engine->prepare(input,options),"prepare rejected");until([&]{const auto d=engine->getPlaybackDiagnostics();return engine->getPlaybackState()==State::Ready&&d.pipeline.analysisDone&&d.publishedFrames-d.consumedFrames==steadyLead();},"normal Ready/final analysis/FIFO");
  const auto current=engine->getPlaybackDiagnostics().engineSerial;require(current&&(!serial||serial==current),"engine identity changed on prepare");serial=current;availabilityConsistent();
 }
 void availabilityConsistent(){
  const auto d=engine->getPlaybackDiagnostics();const auto seek=engine->seekAvailability();const auto loop=engine->loopAvailability();
  const auto same=[](const progressive::FeatureAvailability& a,const progressive::FeatureAvailability& b){return a.implemented==b.implemented&&a.approved==b.approved&&a.configured==b.configured&&a.effective==b.effective&&a.allowed==b.allowed&&a.research==b.research&&a.reason==b.reason;};
  require(same(d.features.exactSeek,seek.exact)&&same(d.features.interactiveSeek,seek.interactive)&&same(d.features.nativeLoops,loop.nativeLoops),"diagnostics vs runtime availability mismatch");
 }
 void lead(bool interactive=false){const auto d=engine->getPlaybackDiagnostics().pipeline;require(d.readyLeadFrames==steadyLead()&&d.steadyLeadFrames==steadyLead()&&d.fifoCapacityFrames==16384,"Ready/steady/capacity contract");}
 progressive::LoopContext context(){const auto s=engine->getStateSnapshot();return{s.inputGeneration,s.session,s.renderEpoch};}
 Stationary sample(){return{engine->getStateSnapshot(),engine->getCurrentPlaybackPosition(),engine->getPlaybackDiagnostics(),engine->getLoopSnapshot(),capture.rawFrames.load(),capture.outputFrames.load()};}
 void stationary(const Stationary& s,bool epoch=true){
  const auto now=sample();require(now.state.state==s.state.state&&now.position.inputFrame==s.position.inputFrame&&now.position.outputFrame==s.position.outputFrame&&now.raw==s.raw&&now.output==s.output&&!now.state.resumePending,"preparation consumed/moved/resumed");
  require(now.loop.id==s.loop.id&&now.loop.enabled==s.loop.enabled&&now.loop.state==s.loop.state&&now.loop.cycles==s.loop.cycles&&now.loop.clearPending==s.loop.clearPending,"preparation changed Loop");
  if(epoch)require(now.state.session==s.state.session&&now.state.inputGeneration==s.state.inputGeneration&&now.state.renderEpoch==s.state.renderEpoch&&now.diagnostics.publishedFrames==s.diagnostics.publishedFrames&&now.diagnostics.consumedFrames==s.diagnostics.consumedFrames,"preparation changed FIFO/epoch");
 }
 void record(const char* label){
  const auto s=engine->getStateSnapshot();const auto d=engine->getPlaybackDiagnostics();const auto p=engine->getCurrentPlaybackPosition();const auto l=engine->getLoopSnapshot();const auto prep=engine->loopPreparationSnapshot();const auto h=engine->historyUsage();
  observations<<"{\"label\":"<<ph58::jsonString(label)<<",\"engine_serial\":"<<d.engineSerial<<",\"preparation\":"<<s.preparation<<",\"state\":"<<ph58::jsonString(progressive::name(s.state))<<",\"generation\":"<<s.inputGeneration<<",\"session\":"<<s.session<<",\"epoch\":"<<s.renderEpoch<<",\"input\":";
  if(p.inputFrame)observations<<*p.inputFrame;else observations<<"null";
  observations<<",\"output\":"<<p.outputFrame<<",\"published\":"<<d.publishedFrames<<",\"consumed\":"<<d.consumedFrames<<",\"raw_frames\":"<<capture.rawFrames.load()<<",\"output_frames\":"<<capture.outputFrames.load()<<",\"loop_id\":"<<l.id<<",\"loop_enabled\":"<<l.enabled<<",\"cycles\":"<<l.cycles<<",\"available\":"<<prep.available<<",\"latest\":"<<(prep.latest?preparationJson(*prep.latest):"null")<<",\"reservation_bytes\":"<<d.reservationBytes<<",\"ready_lead\":"<<d.pipeline.readyLeadFrames<<",\"steady_lead\":"<<d.pipeline.steadyLeadFrames<<",\"fifo_capacity\":"<<d.pipeline.fifoCapacityFrames<<",\"checkpoint_states\":"<<d.pipeline.loopReuse.checkpointStates<<",\"checkpoint_peak\":"<<d.pipeline.loopReuse.checkpointPeak<<",\"owner_peak\":"<<ph58::RealtimePipeline::executionOwnerCounts().peak<<",\"history_seek\":"<<h.seek<<",\"history_preparation\":"<<h.loopPreparation<<"}\n";observations.flush();require(bool(observations),"observation write");
 }
 progressive::LoopPreparationOperation operation(std::uint64_t id){
  for(const auto& p:engine->loopPreparationHistory())if(p.id==id)return p;throw std::runtime_error("preparation ID absent");
 }
 std::uint64_t request(std::uint64_t first=0,std::uint64_t end=0){
  const auto r=engine->requestLoopPreparation(first?first:a,end?end:b,context());require(r.accepted&&r.id&&r.code==AR::Available,"preparation receipt");require(acceptedPreparations.insert(r.id).second,"preparation ID reused");return r.id;
 }
 void ready(std::uint64_t id){until([&]{const auto p=operation(id);require(p.state!=Prep::Failed,p.reason.c_str());return p.state==Prep::Ready&&p.workersJoined&&engine->loopPreparationSnapshot().available;},"prewarm Ready/join");freeze();}
 std::uint64_t preparing(){
  gate.arm(engine->getStateSnapshot().session);const auto id=request();until([&]{return gate.entered.load();},"prewarm Preparing gate");
  const auto p=operation(id);require(p.state==Prep::Preparing&&!p.workersJoined&&gate.workerSession.load()!=p.session,"gate did not hold actual preparation owner");return id;
 }
 void release(){gate.released=true;if(gate.entered.load())until([&]{return gate.left.load();},"gate release/join");}
 void freeze(){for(const auto& p:engine->loopPreparationHistory())if(progressive::terminal(p.state)){require(p.workersJoined,"terminal preparation without worker retirement");const auto value=preparationJson(p);auto [it,added]=frozen.emplace(p.id,value);require(added||it->second==value,"past terminal preparation changed");}}
 void checkHistory(){
  freeze();const auto h=engine->historyUsage();const auto history=engine->loopPreparationHistory();std::set<std::uint64_t> seen;
  for(const auto& p:history){require(seen.insert(p.id).second&&acceptedPreparations.contains(p.id),"unknown/duplicate preparation ID");require(progressive::terminal(p.state)&&p.workersJoined,"unsettled preparation");}
  require(seen==acceptedPreparations&&h.engineSerial==serial&&h.loopPreparation==history.size()&&h.seek==engine->seekHistory().size()&&h.stoppedSpeed==engine->stoppedSpeedHistory().size()&&h.loopSpeed==engine->loopSpeedHistory().size()&&!h.recreationRequired,"history usage/identity mismatch");
 }
 void paused(){
  require(engine->play(),"normal play");until([&]{return capture.outputFrames.load()>=rate/20;},"normal first PCM");require(engine->pause(),"normal pause");
  const auto stopped=sample();require(stopped.position.inputFrame.has_value(),"paused C unavailable");
  // 通常producerはPipelineのbackpressure条件 available+2048>lead で待機する。
  // 512単位の消費端でPauseすると lead-2047..lead が正当な静止帯となり、
  // FIFOの満杯一致は公開契約にない。容量16384と実C/消費端/欠落基準は維持する。
  std::uint64_t previousPublished=0;unsigned stable=0;
  until([&]{
   stationary(stopped,false);const auto d=engine->getPlaybackDiagnostics();const auto state=engine->getStateSnapshot();
   require(state.state==State::Paused&&state.session==stopped.state.session&&state.inputGeneration==stopped.state.inputGeneration&&state.renderEpoch==stopped.state.renderEpoch&&d.consumedFrames==stopped.diagnostics.consumedFrames,"Pause C/consumer/identity moved during refill");
   require(d.publishedFrames>=d.consumedFrames&&d.publishedFrames-d.consumedFrames<=steadyLead()&&d.pipeline.fifoCapacityFrames==16384&&!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites,"paused FIFO capacity/supply contract");
   if(d.publishedFrames-d.consumedFrames<steadyLead()-2047){stable=0;return false;}
   stable=d.publishedFrames==previousPublished?stable+1:1;previousPublished=d.publishedFrames;return stable>=3;
  },"paused block backpressure and actual C stationary");
 }
 void seek(std::uint64_t frame,bool interactive=false,bool legacy=false){
  const auto c=context();const auto r=interactive?(legacy?engine->requestFastLocalSeekToInputFrame(frame,c.inputGeneration,c.renderEpoch):engine->requestInteractiveSeekToInputFrame(frame,c.inputGeneration,c.renderEpoch,c.session)):engine->requestSeekToInputFrame(frame,c.inputGeneration,c.renderEpoch);
  require(r.accepted&&r.id,"explicit seek rejected");acceptedSeeks.insert(r.id);
  until([&]{for(const auto& p:engine->seekHistory())if(p.id==r.id){require(p.state!=Seek::Failed&&p.state!=Seek::Rejected&&p.state!=Seek::Cancelled,p.reason.c_str());return p.state==Seek::Completed&&!engine->getPlaybackDiagnostics().retiringPipeline;}return false;},"explicit seek adoption");
  lead(interactive);require(engine->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(frame),"explicit seek coordinate");
 }
 void rejectStaleSpeedAndPreserve(std::uint64_t id,Prep state,bool available){
  const auto old=preparationJson(operation(id));const auto c=context();const auto before=engine->getStateSnapshot();
  const std::array<progressive::LoopContext,3> bad{{{c.inputGeneration+1,c.session,c.renderEpoch},{c.inputGeneration,c.session+1,c.renderEpoch},{c.inputGeneration,c.session,c.renderEpoch+1}}};
  for(const auto& stale:bad){
   const auto r=engine->setSpeed(.75,stale.session,stale.inputGeneration,stale.renderEpoch);require(!r.id&&r.result==ts::prototype::Phase39RequestResult::Stopped,"stale speed accepted");
   const auto p=engine->loopPreparationSnapshot();const auto after=engine->getStateSnapshot();
   require(operation(id).state==state&&preparationJson(operation(id))==old&&p.latest&&p.latest->id==id&&preparationJson(*p.latest)==old&&p.available==available,"stale speed cancelled/invalidated preparation");
   require(after.state==before.state&&after.session==before.session&&after.renderEpoch==before.renderEpoch&&after.requestedSpeed==before.requestedSpeed&&after.appliedTargetSpeed==before.appliedTargetSpeed&&!after.resumePending,"stale speed changed playback");
  }
 }
 void resources(){
  const auto d=engine->getPlaybackDiagnostics();const auto owners=ph58::RealtimePipeline::executionOwnerCounts();
  require(owners.alive<=2&&owners.peak<=2&&d.pipeline.loopReuse.checkpointStates<=2&&d.pipeline.loopReuse.checkpointPeak<=2&&d.pipeline.fifoHighWater<=16384,"owner/checkpoint/FIFO bound");
  require(!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!d.workerNewCalls,"supply/worker allocation");
 }
 void close(bool direct){
  if(!engine)return;finalDiagnostics=engine->getPlaybackDiagnostics();finalNative=engine->getNativeDiagnostics();
  if(direct){
   // destructorが取消/exitを公開してから通常側SeekCleanupWait hookが解放する。
   engine.reset();
  }else{engine->stop();finalDiagnostics=engine->getPlaybackDiagnostics();gate.released=true;engine.reset();}
 }
 void save(){
  capture.save(out);loopAudit.save(out/"final_loop_owned_audit.jsonl");std::ofstream f(out/"final_operation_owned_audit.jsonl");
  f<<"{\"record\":\"audit_delivery\",\"calls\":"<<allAudit.calls<<",\"engine_serial\":"<<allAudit.engineSerial<<",\"preparation\":"<<allAudit.preparation<<",\"workers_joined\":"<<allAudit.joined<<",\"retired\":"<<allAudit.retired<<",\"copied\":"<<allAudit.copied<<",\"error\":"<<allAudit.error<<"}\n";
  for(const auto& p:allAudit.preparations)f<<preparationJson(p)<<'\n';
  for(const auto& s:allAudit.seeks)f<<"{\"record\":\"seek\",\"id\":"<<s.id<<",\"generation\":"<<s.inputGeneration<<",\"session\":"<<s.session<<",\"epoch\":"<<s.renderEpoch<<",\"state\":"<<ph58::jsonString(progressive::name(s.state))<<",\"code\":"<<ph58::jsonString(progressive::name(s.code))<<"}\n";
  for(const auto& s:allAudit.stopped)f<<"{\"record\":\"stopped_speed\",\"id\":"<<s.id<<",\"state\":"<<ph58::jsonString(name(s.state))<<"}\n";
  for(const auto& s:allAudit.speeds)f<<operationJson(s)<<'\n';f.close();require(bool(f),"final audit write");
 }
 void finalCheck(){
  require(!engine&&allAudit.calls==1&&allAudit.copied&&!allAudit.error&&allAudit.joined&&allAudit.retired&&allAudit.engineSerial==serial&&allAudit.preparation==finalDiagnostics.preparation&&loopAudit.complete(),"final owned audit marker");
  std::set<std::uint64_t> prepIDs,seekIDs,allSeekIDs,stoppedIDs;
  for(const auto& p:allAudit.preparations){require(prepIDs.insert(p.id).second&&progressive::terminal(p.state)&&p.workersJoined,"close preparation not terminal/joined");if(auto it=frozen.find(p.id);it!=frozen.end())require(it->second==preparationJson(p),"close rewrote terminal preparation");}
  for(const auto& p:allAudit.seeks){require(allSeekIDs.insert(p.id).second&&progressive::terminal(p.state),"close seek not terminal/unique");if(p.state!=Seek::Rejected)seekIDs.insert(p.id);}
  for(const auto& p:allAudit.stopped)require(stoppedIDs.insert(p.id).second,"duplicate stopped-speed ID");
  require(prepIDs==acceptedPreparations&&seekIDs==acceptedSeeks&&stoppedIDs==acceptedStopped,"final accepted ID set mismatch");
  require(allAudit.speeds.size()==loopAudit.operations.size(),"final audit delivery mismatch");for(std::size_t i=0;i<allAudit.speeds.size();++i)require(operationJson(allAudit.speeds[i])==operationJson(loopAudit.operations[i]),"final Loop row copy mismatch");
  for(const auto& p:allAudit.stopped)require(p.state!=StoppedSpeedState::Preparing&&(p.state!=StoppedSpeedState::ReadyForResume||p.outputStarted),"close stopped-speed not settled");
  const auto owners=ph58::RealtimePipeline::executionOwnerCounts();
  require(!owners.alive&&owners.peak<=2&&!gate.expired.load()&&(!gate.entered.load()||gate.left.load()),"close owner/gate leak");
  require(!capture.errors.load()&&!capture.audit.audit.errors&&!capture.audit.audit.nonfinite&&!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"capture/heap audit");
  require(!finalDiagnostics.missingFrames&&!finalDiagnostics.underrunCalls&&!finalDiagnostics.rejectedWrites&&!finalDiagnostics.workerNewCalls,"final supply/worker");
 }
};

// WavStreamReaderの寸法確認と別に、試験入力が製品対象のFloat32であることを固定する。
void requireFloat32Fixture(const std::filesystem::path& path){
 std::ifstream in(path,std::ios::binary);std::array<unsigned char,16> bytes{};in.read(reinterpret_cast<char*>(bytes.data()),12);
 require(bool(in)&&!std::memcmp(bytes.data(),"RIFF",4)&&!std::memcmp(bytes.data()+8,"WAVE",4),"fixture RIFF/WAVE");
 while(in){
  in.read(reinterpret_cast<char*>(bytes.data()),8);require(bool(in),"fixture fmt chunk absent");
  const auto size=std::uint32_t(bytes[4])|(std::uint32_t(bytes[5])<<8)|(std::uint32_t(bytes[6])<<16)|(std::uint32_t(bytes[7])<<24);
  const auto content=in.tellg();if(!std::memcmp(bytes.data(),"fmt ",4)){
   require(size>=16,"fixture fmt size");in.read(reinterpret_cast<char*>(bytes.data()),16);
   require(bool(in)&&bytes[0]==3&&bytes[1]==0&&bytes[14]==32&&bytes[15]==0,"fixture requires IEEE Float32");return;
  }
  in.seekg(content+std::streamoff(size)+std::streamoff(size&1));
 }
 throw std::runtime_error("fixture Float32 fmt absent");
}

int adoptionNativeMain(int argc,char** argv){
 require(argc==6,"MODE INPUT PRESET NEW_OUT SOURCE_SHA");
 const std::string mode=argv[1],presetName=argv[3];require(std::find(adoptionModes.begin(),adoptionModes.end(),mode)!=adoptionModes.end(),"unknown mode");
 require(presetName=="baseline"||presetName=="candidate","preset");
 const std::filesystem::path out=argv[4];require(!std::filesystem::exists(out),"fresh evidence directory required");require(std::filesystem::create_directories(out),"create evidence directory");
 std::size_t done=0;std::unique_ptr<AdoptionNativeFixture> f;
 std::ofstream checks(out/"checks.jsonl");
 const auto pass=[&]{require(done<adoptionChecks.size(),"extra check");checks<<"{\"id\":"<<ph58::jsonString(mode+"."+adoptionChecks[done++])<<",\"pass\":true}\n";checks.flush();require(bool(checks),"check write");};
 const auto summary=[&](bool success,const std::string& reason){
  std::ofstream s(out/"SUMMARY.json");const auto owners=ph58::RealtimePipeline::executionOwnerCounts();
  s<<"{\"status\":\""<<(success?"PASS":"FAIL")<<"\",\"run_complete\":"<<(success?"true":"false")<<",\"expected\":8,\"executed\":"<<done<<",\"mode\":"<<ph58::jsonString(mode)<<",\"source\":"<<ph58::jsonString(argv[5])
   <<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak<<",\"callback_gate\":false,\"independent_PCM\":\"NOT_RUN\",\"RT_deadline_approval\":\"NOT_ASSESSED\",\"reason\":"<<ph58::jsonString(reason)<<"}\n";
 };
 try{
  require(progressive::featureApprovals.exactSeek&&!progressive::featureApprovals.interactiveSeek&&!progressive::featureApprovals.nativeLoops&&!progressive::featureApprovals.currentCycleSpeed,"Exact-only engine approval table mismatch");
  requireFloat32Fixture(argv[2]);ts::WavStreamReader wav(argv[2]);const auto rate=wav.sampleRate();require(wav.frames()>=rate*16ULL&&wav.frames()<=rate*20ULL&&(wav.channels()==1||wav.channels()==2)&&(rate==44100||rate==48000),"requires bounded 16..20s product fixture");
  const auto preset=presetName=="baseline"?Preset::Baseline:Preset::Candidate;
  {std::ofstream e(out/"EXPECTED.json");e<<"{\"schema\":1,\"expected\":8,\"required_ids\":[";for(std::size_t i=0;i<adoptionChecks.size();++i)e<<(i?",":"")<<ph58::jsonString(mode+"."+adoptionChecks[i]);e<<"],\"mode\":"<<ph58::jsonString(mode)<<",\"source\":"<<ph58::jsonString(argv[5])<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(argv[0]))<<",\"input_sha256\":"<<ph58::jsonString(fileHash(argv[2]))<<",\"preset\":"<<ph58::jsonString(presetName)<<",\"A\":"<<2ULL*rate<<",\"B\":"<<2ULL*rate+rate/2<<",\"speed\":1,\"callback_gate\":false,\"capture_limit_frames\":96000,\"independent_PCM\":\"NOT_RUN\"}\n";require(bool(e),"expected write");}
  phase61_heap_reset();f=std::make_unique<AdoptionNativeFixture>(argv[2],preset,out,rate,wav.channels());
  if(mode=="legacy_disabled"){f->options.featurePolicy.reset();f->options.allowExperimentalLoops=false;f->options.allowUnvalidatedFastLocalSeek=false;}
  if(mode=="legacy_api"){f->options.featurePolicy.reset();f->options.allowExperimentalLoops=true;f->options.allowUnvalidatedFastLocalSeek=true;}
  if(mode=="policy_precedence"){f->options.featurePolicy=ProgressiveOptions::macOSProduct().featurePolicy;f->options.allowExperimentalLoops=true;f->options.allowUnvalidatedFastLocalSeek=true;}
  f->prepare();
  if(mode.starts_with("pause_")||mode=="resume_preparing")f->paused();
  const auto sa=f->engine->seekAvailability();const auto la=f->engine->loopAvailability();require(sa.contractVersion==3&&la.contractVersion==3&&!sa.publicSeekApproved&&!la.publicLoopApproved&&!la.currentCycleSpeedChanges,"v3 implementation vs approval");
  if(mode=="legacy_disabled")require(!la.allowed&&!sa.interactiveAllowed&&sa.exact.allowed&&la.nativeLoops.reason==AR::NotConfigured,"legacy false feature state");
  else if(mode=="policy_precedence")require(!la.allowed&&sa.exact.allowed&&sa.exact.approved&&!sa.exact.research&&!sa.interactiveAllowed&&la.nativeLoops.reason==AR::NotApproved&&sa.interactive.reason==AR::NotApproved,"ApprovedOnly overwritten by old true booleans");
  else require(la.allowed&&sa.exact.allowed&&sa.interactiveAllowed&&la.nativeLoops.research&&!la.nativeLoops.approved,"explicit Research/legacy feature link");
  pass();f->lead();require(f->engine->getPlaybackDiagnostics().engineSerial==f->serial,"diagnostic engine identity");pass();f->record("initial");

  if(mode=="prewarm_ready"){
   const auto before=f->sample();const auto id=f->request();f->ready(id);const auto p=f->operation(id);
   require(p.workersJoined&&p.acceptedNs&&p.startedNs>=p.acceptedNs&&p.checkpointReadyNs>=p.startedNs&&p.readyNs>=p.checkpointReadyNs&&p.speedMicros==1000000&&p.inputA==f->a&&p.inputBExclusive==f->b&&std::isfinite(p.prefixCpuS)&&std::isfinite(p.prefixWallS),"Ready preparation facts");pass();
   f->stationary(before);require(ph58::RealtimePipeline::executionOwnerCounts().alive==1,"Ready preparation retained execution owner");f->record("prewarm_Ready_no_resume");pass();
   f->checkHistory();require(f->engine->seekHistory().empty()&&f->engine->loopSpeedHistory().empty(),"preparation fabricated seek/speed event");pass();
   const auto loop=f->engine->requestLoopRange(f->a,f->b,f->context());require(loop.accepted,"prepared ON rejected");
   f->until([&]{return f->engine->getLoopSnapshot().initialPositionComplete&&!f->engine->getPlaybackDiagnostics().retiringPipeline;},"prepared ON adoption");
   const auto d=f->engine->getPlaybackDiagnostics();require(d.pipeline.loopReuse.initialCheckpointHit&&!d.pipeline.fastLocalSeek&&d.pipeline.loopReuse.checkpointStates<=2&&f->engine->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(f->a)&&f->capture.outputFrames==before.output&&f->engine->getPlaybackState()==before.state.state,"ON did not use exact A checkpoint while stationary");
   f->lead();require(!f->engine->loopPreparationSnapshot().available,"ON left preparation available");f->checkHistory();f->record("ON_ready_A_before_Play");
   require(f->engine->play(),"explicit Play");f->until([&]{return f->engine->getLoopSnapshot().cycles>=2;},"two natural cycles");require(f->engine->pause(),"postcapture pause");
   require(f->capture.rawFrames>0&&f->capture.outputFrames>0&&f->engine->getLoopSnapshot().cycles>=2,"no actual prepared A PCM");f->record("captured_prepared_A");pass();
  }else if(mode=="play_preparing"||mode=="resume_preparing"){
   const auto before=f->sample();const auto firstRaw=f->capture.rawCount.load(),firstSpan=f->capture.spanCount.load();const auto id=f->preparing();f->stationary(before);f->record("Preparing_before_explicit_start");pass();
   require(mode=="resume_preparing"?f->engine->resume():f->engine->play(),"explicit start rejected");
   const auto pending=f->engine->loopPreparationSnapshot();const auto cancelling=f->operation(id);
   require(pending.latest&&pending.latest->id==id&&pending.latest->state==Prep::Cancelling&&cancelling.state==Prep::Cancelling&&!cancelling.workersJoined&&!pending.available&&!f->gate.left.load(),"explicit start did not publish cancellation before normal gate release");f->record("explicit_start_Cancelling_gate_held");pass();
   f->release();f->until([&]{const auto p=f->operation(id);return p.state==Prep::Cancelled&&p.workersJoined;},"explicit start preparation join");f->checkHistory();require(!f->engine->loopPreparationSnapshot().available,"cancelled start left seed available");pass();
   f->until([&]{return f->capture.outputFrames.load()>before.output&&f->capture.rawCount.load()>firstRaw&&f->capture.spanCount.load()>firstSpan;},"original FIFO did not start after explicit intent");
   require(f->engine->pause(),"post explicit-start Pause");const auto after=f->sample();const auto& raw=f->capture.rawRecords[firstRaw];const auto& span=f->capture.spans[firstSpan];
   require(raw.session==before.state.session&&raw.epoch==before.state.renderEpoch&&raw.at==before.position.outputFrame&&span.newEpoch==before.state.renderEpoch&&span.newOutputOffset==before.position.outputFrame&&!span.mixedFrames,"explicit start jumped to prepared A or changed FIFO owner");
   require(after.state.state==State::Paused&&after.state.session==before.state.session&&after.state.renderEpoch==before.state.renderEpoch&&after.state.inputGeneration==before.state.inputGeneration&&after.position.outputFrame>before.position.outputFrame&&!after.state.resumePending&&!after.loop.enabled&&!after.loop.cycles&&f->engine->seekHistory().empty()&&f->engine->stoppedSpeedHistory().empty(),"explicit start changed epoch/Loop or fabricated operation");f->lead();f->availabilityConsistent();f->record("original_FIFO_started_after_preparation_cancel");pass();
  }else if(mode=="invalid_context"){
   const auto before=f->sample();const auto id=f->preparing();f->rejectStaleSpeedAndPreserve(id,Prep::Preparing,false);f->record("stale_speed_preserved_Preparing");f->release();f->ready(id);f->rejectStaleSpeedAndPreserve(id,Prep::Ready,true);const auto old=preparationJson(f->operation(id));const auto count=f->engine->loopPreparationHistory().size();const auto c=f->context();pass();
   const std::array<std::pair<progressive::LoopContext,AR>,6> bad{{
    {{0,c.session,c.renderEpoch},AR::InvalidContext},{{c.inputGeneration,0,c.renderEpoch},AR::InvalidContext},{{c.inputGeneration,c.session,0},AR::InvalidContext},
    {{c.inputGeneration+1,c.session,c.renderEpoch},AR::StaleContext},{{c.inputGeneration,c.session+1,c.renderEpoch},AR::StaleContext},{{c.inputGeneration,c.session,c.renderEpoch+1},AR::StaleContext}}};
   for(const auto& [context,code]:bad){const auto r=f->engine->requestLoopPreparation(f->a,f->b,context);require(!r.accepted&&!r.id&&r.code==code&&!r.reason.empty(),"invalid preparation context code");}
   const auto invalid=f->engine->requestLoopPreparation(f->b,f->a,c),shortRange=f->engine->requestLoopPreparation(f->a,f->a+rate/20,c);
   require(!invalid.accepted&&invalid.code==AR::InvalidRange&&!shortRange.accepted&&shortRange.code==AR::MinimumInput,"invalid preparation range code");
   const auto rejectedSeek=f->engine->requestSeekToInputFrame(rate,c.inputGeneration+1,c.renderEpoch);require(!rejectedSeek.accepted&&rejectedSeek.code==AR::StaleContext,"rejected seek reason");pass();
   require(f->engine->loopPreparationHistory().size()==count&&preparationJson(f->operation(id))==old&&f->engine->loopPreparationSnapshot().available,"rejection discarded/changed valid preparation");f->checkHistory();pass();
   f->stationary(before);f->record("rejections_preserved_Ready");pass();
  }else if(mode=="legacy_disabled"){
   const auto before=f->sample();const auto r=f->engine->requestLoopPreparation(f->a,f->b,f->context());require(!r.accepted&&!r.id&&r.code==AR::NotConfigured,"legacy false allowed preparation");pass();
   const auto loop=f->engine->requestLoopRange(f->a,f->b,f->context());const auto c=f->context();const auto seek=f->engine->requestInteractiveSeekToInputFrame(rate,c.inputGeneration,c.renderEpoch,c.session);
   require(!loop.accepted&&loop.code==AR::NotConfigured&&!seek.accepted&&seek.code==AR::NotConfigured&&!f->engine->seekToInputSeconds(.5),"legacy disabled API meaning");pass();
   require(f->engine->loopPreparationHistory().empty()&&!f->engine->loopPreparationSnapshot().available,"rejected preparation stored/available");f->checkHistory();pass();
   const auto now=f->sample();require(now.position.inputFrame==before.position.inputFrame&&now.position.outputFrame==before.position.outputFrame&&now.raw==before.raw&&now.output==before.output,"disabled API consumed PCM");f->record("legacy_disabled");pass();
  }else if(mode=="policy_precedence"){
   const auto base=progressive::reservationBytes(std::filesystem::file_size(f->input),wav.frames());const auto blocked=f->engine->requestLoopPreparation(f->a,f->b,f->context());
   require(!blocked.accepted&&blocked.code==AR::NotApproved&&f->engine->getPlaybackDiagnostics().reservationBytes==base,"ApprovedOnly old-boolean override or reservation");pass();
   f->engine->stop();f->options.featurePolicy=progressive::FeaturePolicyOptions{3,Policy::Disabled,Policy::Disabled,Policy::Disabled};f->prepare();
   const auto disabled=f->engine->requestLoopPreparation(f->a,f->b,f->context());require(!disabled.accepted&&disabled.code==AR::NotConfigured&&!f->engine->seekAvailability().exact.allowed&&!f->engine->loopAvailability().allowed&&f->engine->getPlaybackDiagnostics().reservationBytes==base,"explicit Disabled old-boolean override");pass();
   f->engine->stop();f->options.allowExperimentalLoops=false;f->options.allowUnvalidatedFastLocalSeek=false;f->options.featurePolicy=progressive::FeaturePolicyOptions{3,Policy::Research,Policy::Research,Policy::Research};f->prepare();
   const auto id=f->request();f->ready(id);require(f->engine->loopAvailability().allowed&&f->engine->seekAvailability().interactiveAllowed&&f->engine->getPlaybackDiagnostics().reservationBytes==base+24ULL*1024*1024,"explicit Research did not supersede old false");f->checkHistory();pass();
   const auto position=f->engine->getCurrentPlaybackPosition();require(position.inputFrame==std::optional<std::uint64_t>(0)&&position.outputFrame==0&&!f->capture.outputFrames.load(),"policy tests moved/played");f->record("policy_precedence");pass();
  }else if(mode=="reservation_delta"){
   const auto base=progressive::reservationBytes(std::filesystem::file_size(f->input),wav.frames());const auto on=f->engine->getPlaybackDiagnostics().reservationBytes;
   require(on==base+24ULL*1024*1024,"formal Research omitted 24MiB");pass();
   f->engine->stop();f->options.featurePolicy=progressive::FeaturePolicyOptions{3,Policy::Research,Policy::Research,Policy::Disabled};f->options.allowExperimentalLoops=true;f->prepare();
   const auto off=f->engine->getPlaybackDiagnostics().reservationBytes;require(off==base&&on-off==24ULL*1024*1024&&!f->engine->loopAvailability().allowed,"reservation difference vs effective loop");pass();
   require(f->engine->historyUsage().engineSerial==f->serial&&!f->engine->historyUsage().loopPreparation,"reservation reprepare changed identity/history");f->checkHistory();pass();
   require(!f->capture.outputFrames.load()&&f->engine->getCurrentPlaybackPosition().outputFrame==0,"reservation test consumed PCM");f->record("reservation_delta");pass();
  }else if(mode=="legacy_api"){
   const auto id=f->request();f->ready(id);f->engine->cancelLoopPreparation();require(!f->engine->loopPreparationSnapshot().available,"legacy cancel");pass();
   f->seek(rate/4);f->lead();f->seek(rate/2,true,true);f->lead(true);f->seek(rate,true,false);f->lead(true);
   require(!f->engine->seekToInputSeconds(.25)&&f->engine->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(rate),"legacy bool/async API compatibility");pass();
   f->checkHistory();const auto before=preparationJson(f->operation(id));require(before==f->frozen.at(id),"legacy methods rewrote past preparation");pass();
   const auto c=f->context();const auto loop=f->engine->requestLoopRange(f->a,f->b,c);require(loop.accepted,"legacy Loop Range");
   f->until([&]{return f->engine->getLoopSnapshot().initialPositionComplete&&!f->engine->getPlaybackDiagnostics().retiringPipeline;},"legacy Loop adoption");f->lead();
   require(f->engine->getPlaybackState()==State::Ready&&!f->capture.outputFrames.load()&&f->engine->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(f->a),"legacy Loop static A");f->record("legacy_api");pass();
  }else{
   const auto separator=mode.rfind('_');const auto action=mode.substr(0,separator);const bool wasReady=mode.substr(separator+1)=="ready";const auto before=f->sample();
   const auto id=wasReady?f->request():f->preparing();if(wasReady)f->ready(id);f->stationary(before);f->record("before_interrupt");pass();
   std::uint64_t nextID=0,seekID=0;
   if(action=="cancel")f->engine->cancelLoopPreparation();
   else if(action=="pause")require(f->engine->pause(),"re-Pause rejected");
   else if(action=="stop")f->engine->stop();
   else if(action=="speed"){const auto c=f->context();const auto speed=f->engine->setSpeed(.75,c.session,c.inputGeneration,c.renderEpoch);require(speed.result==ts::prototype::Phase39RequestResult::Accepted&&speed.id,"speed interrupt rejected");f->acceptedStopped.insert(speed.id);}
   else if(action=="seek"){const auto c=f->context();const auto seek=f->engine->requestSeekToInputFrame(rate/2,c.inputGeneration,c.renderEpoch);require(seek.accepted&&seek.id,"seek interrupt rejected");seekID=seek.id;f->acceptedSeeks.insert(seek.id);}
   else if(action=="replace")nextID=f->request(f->a+rate,f->b+rate);
   else if(action=="close")f->close(true);
   else throw std::runtime_error("unknown interrupt action");
   if(f->engine)f->release();
   pass();
   if(f->engine){
    if(action=="replace")f->ready(nextID);
    else{
     f->until([&]{const auto p=f->operation(id);return progressive::terminal(p.state)&&p.workersJoined;},"interrupt preparation retirement");
     require(!f->engine->loopPreparationSnapshot().available,"interrupted preparation remained available");
    }
    const auto previous=f->operation(id);require(previous.state==(wasReady?Prep::Ready:action=="replace"?Prep::Replaced:Prep::Cancelled),"wrong preparation interruption terminal");
    f->checkHistory();pass();
    if(action=="speed"){
     f->until([&]{const auto s=f->engine->getStateSnapshot();return s.stoppedSpeed&&s.stoppedSpeed->state==StoppedSpeedState::ReadyForResume&&!f->engine->getPlaybackDiagnostics().retiringPipeline;},"speed ReadyForResume");
     require(f->engine->getCurrentPlaybackPosition().inputFrame==before.position.inputFrame&&f->engine->getPlaybackState()==before.state.state&&!f->engine->getStateSnapshot().resumePending,"speed changed C/resumed");f->lead();
    }else if(action=="seek"){
     f->until([&]{for(const auto& s:f->engine->seekHistory())if(s.id==seekID)return s.state==Seek::Completed&&!f->engine->getPlaybackDiagnostics().retiringPipeline;return false;},"seek completed after cancellation");
     require(f->engine->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(rate/2)&&f->engine->getPlaybackState()==before.state.state,"seek target/state");f->lead();
    }else if(action=="stop")require(f->engine->getPlaybackState()==State::Stopped&&f->engine->getCurrentPlaybackPosition().inputFrame==before.position.inputFrame,"Stop C/state");
    else f->stationary(before);
    require(f->capture.rawFrames.load()==before.raw&&f->capture.outputFrames.load()==before.output,"interrupt produced unexpected PCM");f->record("after_interrupt");pass();
   }else{
    f->finalCheck();const auto found=std::find_if(f->allAudit.preparations.begin(),f->allAudit.preparations.end(),[&](const auto& p){return p.id==id;});
    require(found!=f->allAudit.preparations.end()&&found->state==(wasReady?Prep::Ready:Prep::Cancelled)&&found->workersJoined,"close did not settle preparing ID");pass();
    require(f->capture.rawFrames.load()==before.raw&&f->capture.outputFrames.load()==before.output,"close produced PCM");pass();
   }
  }
  require(done==6,"mode did not execute its six required checks");
  if(f->engine){f->resources();f->record("before_close");}else require(!ph58::RealtimePipeline::executionOwnerCounts().alive&&f->finalDiagnostics.pipeline.loopReuse.checkpointPeak<=2,"direct close resource bound");pass();
  f->close(false);f->save();f->finalCheck();pass();require(done==8,"incomplete mode");checks.close();require(bool(checks),"checks close");summary(true,"");return 0;
 }catch(const std::exception& error){
  if(f){f->gate.released=true;try{f->close(true);f->save();}catch(...){}}
  summary(false,error.what());std::cerr<<error.what()<<'\n';return 1;
 }
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=adoptionNativeMain(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});control.join();return result;}
