// D5 ordinary-speed full epoch audit. One ordinary control thread owns APIs.
// INPUT PRESET NEW_OUT SOURCE_SHA [accept|reject]. No callback gate or DSP oracle.
// Link phase61_callback_heap_probe. The normal planner gate only fixes the
// replacement/cancellation cohort; it is not a normal-RT performance trial.
#define PHASE61_SANDBOX_APP 1
#include "Phase61NativeTests.cpp"
#include "Phase61CallbackMallocProbe.h"
#include "prototype/Phase45PcmDigest.h"
#include <algorithm>
#include <array>
#include <bit>
#include <cstring>
#include <iomanip>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <type_traits>

namespace {
namespace ep58=ts::prototype::phase58;
namespace ep59=ts::prototype::phase59;
using EOperation=ep59::SpeedOperation;
using EState=ep59::OperationState;
using EReceipt=ts::prototype::Phase39RequestResult;
constexpr std::size_t burstCount=300;
constexpr std::array<const char*,14> epochChecks{
 "D5E01_fixture_and_configured_sink","D5E02_normal_Playing_identity",
 "D5E03_300_Accepted_ids","D5E04_Replaced_terminal_fields_frozen",
 "D5E05_manual_Exact_switch","D5E06_joined_full_epoch_owned_copy",
 "D5E07_closed_history_stays_256","D5E08_all_terminal_fields_and_IDs",
 "D5E09_Stop_last_owner_once","D5E10_reprepare_preserves_audit_counters",
 "D5E11_direct_close_empty_owner_once","D5E12_sequence_identity_and_deep_copy",
 "D5E13_callback_and_worker_allocation_zero","D5E14_final_audit_counters_and_lifetime"};
std::string ehash(const std::filesystem::path& p){
 std::ifstream f(p,std::ios::binary);require(bool(f),"hash input missing");
 ts::prototype::Phase45PcmDigest h;std::array<char,65536> b{};
 while(f.read(b.data(),b.size())||f.gcount())h.update(b.data(),std::size_t(f.gcount()));
 require(f.eof(),"incomplete hash read");return h.finish();
}
void floatFixture(const std::filesystem::path& p){
 std::ifstream f(p,std::ios::binary);std::array<unsigned char,16> b{};f.read(reinterpret_cast<char*>(b.data()),12);
 require(bool(f)&&!std::memcmp(b.data(),"RIFF",4)&&!std::memcmp(b.data()+8,"WAVE",4),"RIFF/WAVE input");
 while(f){f.read(reinterpret_cast<char*>(b.data()),8);require(bool(f),"fmt missing");
  auto n=std::uint32_t(b[4])|(std::uint32_t(b[5])<<8)|(std::uint32_t(b[6])<<16)|(std::uint32_t(b[7])<<24);const auto at=f.tellg();
  if(!std::memcmp(b.data(),"fmt ",4)){require(n>=16,"fmt size");f.read(reinterpret_cast<char*>(b.data()),16);
   require(bool(f)&&b[0]==3&&!b[1]&&b[14]==32&&!b[15],"product IEEE Float32 input required");return;}
  f.seekg(at+std::streamoff(n)+std::streamoff(n&1));}
 throw std::runtime_error("Float32 fmt absent");
}
bool terminal(EState s){return s==EState::Completed||s==EState::Replaced||s==EState::Duplicate||s==EState::Rejected||s==EState::Cancelled;}
// A field-wise canonical value, not a memcmp of padding or a borrowed span.
// Float/double fields retain every bit, including signed zero. Nested vectors
// are deep-owned by SpeedOperation's value copy; every current member is emitted.
struct Tokens {
 std::ostringstream f;bool first=true;
 Tokens(){f<<'[';}
 template<class T>void add(T v){
  static_assert(std::is_arithmetic_v<T>||std::is_enum_v<T>);
  if(!first)f<<',';first=false;
  if constexpr(std::is_same_v<T,float>){require(std::isfinite(v),"nonfinite operation float");f<<std::bit_cast<std::uint32_t>(v);}
  else if constexpr(std::is_same_v<T,double>){require(std::isfinite(v),"nonfinite operation double");f<<std::bit_cast<std::uint64_t>(v);}
  else if constexpr(std::is_enum_v<T>)f<<static_cast<std::underlying_type_t<T>>(v)+0;
  else f<<v;
 }
 template<class T,std::size_t N>void add(const std::array<T,N>& a){for(const auto& x:a)add(x);}
 std::string finish(){f<<']';return f.str();}
};
std::string fields(const EOperation& o){
 Tokens t;
 t.add(o.id);t.add(o.session);t.add(o.inputGeneration);t.add(o.generation);t.add(o.target);t.add(o.state);t.add(o.workerState);t.add(o.acceptance);
 t.add(o.logicalPresented);t.add(o.acceptedLogicalPresented);t.add(o.publishedAtPlan);t.add(o.consumedAtApply);t.add(o.analysisNodesAtPlan);t.add(o.receivedInputAtPlan);t.add(o.planningDecided);t.add(o.finalAnalysisAtPlan);
 const auto& f=o.frontier;t.add(f.preparedOutput);t.add(f.nextInput);t.add(f.lastProcessedInput);t.add(f.finalizedOla);t.add(f.firstUnprocessedFirSource);t.add(f.recentFrameInput);t.add(f.recentFrameOutput);t.add(f.recentFrameCount);t.add(f.actualWeightSample);t.add(f.actualWeight);
 const auto& c=o.change;const auto& p=c.plan;
 t.add(p.outcome);t.add(p.requestedFrame);t.add(p.appliedFrame);t.add(p.rampEndFrame);t.add(p.appliedOutputSample);t.add(p.completionOutputSample);t.add(p.protectedEventsSkipped);t.add(p.protectedEventsPaused);t.add(p.firstMutableFrame);t.add(p.firstSafeFrame);t.add(p.nextEventFrame);t.add(p.protectionEndFrame);t.add(p.safeFramesUsed);t.add(p.heldFrames);
 const auto& r=c.request;t.add(r.generation);t.add(r.target.micros);t.add(r.requestedInputSample);t.add(r.publishedOutputSample);t.add(r.transitionOutputMs);
 const auto& d=c.density;t.add(d.safe);t.add(d.inputSample);t.add(d.maximumHop);t.add(d.maximumHopStep);t.add(d.minimumWeight);t.add(d.minimumLocalSpeed);t.add(d.maximumLocalSpeed);t.add(d.reconstructedHistoryMismatches);t.add(d.reconstructedHistoryMaxDifference);t.add(d.actualWeight);t.add(d.predictedActualWeight);t.add(d.weightPredictionAbsoluteError);t.add(d.candidatesTried);t.add(d.guardWallSeconds);t.add(d.guardThreadCpuSeconds);t.add(d.candidateTimings.size());
 for(const auto& q:d.candidateTimings){t.add(q.inputSample);t.add(q.accepted);t.add(q.probed);t.add(q.wallSeconds);t.add(q.threadCpuSeconds);t.add(q.weightCheckSeconds);}
 const auto& b=c.boundary;t.add(b.legacy);t.add(b.precise);t.add(b.processedNode);t.add(b.consumedOla);t.add(b.consumedFir);
 t.add(c.outputFrames);t.add(c.densityInput);t.add(c.statePreserved);t.add(c.changesDensity);
 t.add(o.acceptedS);t.add(o.plannerSeenS);t.add(o.workerSeenS);t.add(o.planStartedS);t.add(o.planFinishedS);t.add(o.appliedS);t.add(o.completedS);t.add(o.planCpuS);t.add(o.planWallS);t.add(o.attempts);t.add(o.staleReplans);t.add(o.analysisDeferrals);
 return t.finish();
}
std::vector<std::string> freeze(const std::vector<EOperation>& rows){std::vector<std::string> f;f.reserve(rows.size());for(const auto& o:rows)f.push_back(fields(o));return f;}
struct OwnedEpoch {
 std::uint64_t engine=0,preparation=0,sequence=0,epoch=0,session=0,generation=0;
 bool preparedOnly=false,joined=false,released=false;std::vector<EOperation> rows;
};
struct EpochSink {
 std::mutex mutex;std::vector<OwnedEpoch> values;bool reject=false;std::uint64_t calls=0,copyErrors=0,callbackCalls=0;
 explicit EpochSink(bool r):reject(r){values.reserve(16);}
 static bool receive(void* context,const EpochOperationAudit& a)noexcept{
  auto& x=*static_cast<EpochSink*>(context);try{
   std::lock_guard lock(x.mutex);++x.calls;if(callbackCounting)++x.callbackCalls;
   if(x.values.size()>=16||a.ordinarySpeeds.size()>4096){++x.copyErrors;return false;}
   OwnedEpoch v;v.engine=a.engineSerial;v.preparation=a.preparation;v.sequence=a.sequence;v.epoch=a.renderEpoch;v.session=a.session;v.generation=a.inputGeneration;v.preparedOnly=a.preparedOnly;v.joined=a.workersJoined;v.released=a.callbackReleased;
   v.rows.assign(a.ordinarySpeeds.begin(),a.ordinarySpeeds.end());x.values.push_back(std::move(v));return !x.reject;
  }catch(...){++x.copyErrors;return false;}
 }
 std::vector<OwnedEpoch> copy(){std::lock_guard lock(mutex);return values;}
 OwnedEpoch at(std::uint64_t session){std::lock_guard lock(mutex);const auto i=std::find_if(values.begin(),values.end(),[&](const auto& v){return v.session==session;});require(i!=values.end(),"owned epoch missing");return *i;}
 std::size_t size(){std::lock_guard lock(mutex);return values.size();}
};
struct FinalSink {
 std::uint64_t calls=0,engine=0,preparation=0,epochCalls=0,rejected=0,seeks=0;bool joined=false,released=false,callback=false,configured=false;
 static bool receive(void* context,const FinalOperationAudit& a)noexcept{
  auto& x=*static_cast<FinalSink*>(context);++x.calls;x.engine=a.engineSerial;x.preparation=a.preparation;x.epochCalls=a.epochAuditCalls;x.rejected=a.epochAuditRejected;x.seeks=a.seeks.size();x.joined=a.workersJoined;x.released=a.retirementComplete;x.callback=callbackCounting;x.configured=a.epochAuditConfigured;return true;
 }
};
struct PlannerGate {
 std::atomic<std::uint64_t> session{0};std::atomic<bool> entered{false},release{false},timedOut{false};
 static void control(void* context,ep58::ControlTestPoint point,std::uint64_t session,std::uint64_t)noexcept{
  auto& g=*static_cast<PlannerGate*>(context);if(point!=ep58::ControlTestPoint::PlannerBeforePlan||session!=g.session.load()||g.entered.exchange(true))return;
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(15);
  while(!g.release.load()){if(std::chrono::steady_clock::now()>deadline){g.timedOut=true;break;}std::this_thread::sleep_for(std::chrono::microseconds(100));}
 }
 static void lifecycle(void* context,ep58::LifecycleTestPoint point,std::uint64_t session)noexcept{
  auto& g=*static_cast<PlannerGate*>(context);if(point==ep58::LifecycleTestPoint::BeforeJoin&&session==g.session.load())g.release=true;
 }
};
template<class P>void until(ProgressiveMacPlaybackEngine& e,P p,const char* why){
 const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(30);
 while(!p()){if(e.getPlaybackState()==State::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);require(std::chrono::steady_clock::now()<end,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
}
void auditMetadata(const OwnedEpoch& a,std::uint64_t engine,std::uint64_t preparation,std::uint64_t generation){
 require(a.engine==engine&&a.preparation==preparation&&a.session&&a.generation==generation&&a.sequence&&a.joined&&a.released,"epoch delivery identity/join/callback release");
 require(a.preparedOnly?!a.epoch:bool(a.epoch),"preparedOnly renderEpoch contract");
}
void saveEpochs(const std::filesystem::path& out,const std::vector<OwnedEpoch>& epochs){
 std::ofstream a(out/"epoch_audits.jsonl"),r(out/"owned_operations.jsonl");
 for(const auto& e:epochs){a<<"{\"engine_serial\":"<<e.engine<<",\"preparation\":"<<e.preparation<<",\"sequence\":"<<e.sequence<<",\"render_epoch\":"<<e.epoch<<",\"session\":"<<e.session<<",\"input_generation\":"<<e.generation<<",\"prepared_only\":"<<e.preparedOnly<<",\"workers_joined\":"<<e.joined<<",\"callback_released\":"<<e.released<<",\"ordinary_speed_count\":"<<e.rows.size()<<"}\n";
  for(const auto& op:e.rows)r<<"{\"engine_serial\":"<<e.engine<<",\"sequence\":"<<e.sequence<<",\"session\":"<<e.session<<",\"id\":"<<op.id<<",\"state\":"<<ep58::jsonString(ep59::name(op.state))<<",\"full_fields\":"<<fields(op)<<"}\n";}
 a.close();r.close();require(bool(a)&&bool(r),"owned audit export");
}
int epochMain(int argc,char** argv){
 require(argc==5||argc==6,"INPUT PRESET NEW_OUT SOURCE_SHA [accept|reject]");
 const std::filesystem::path input=std::filesystem::absolute(argv[1]),out=std::filesystem::absolute(argv[3]);const std::string presetName=argv[2],mode=argc==6?argv[5]:"accept";
 require(presetName=="candidate"||presetName=="baseline","preset");require(mode=="accept"||mode=="reject","sink mode");require(!std::filesystem::exists(out)&&std::filesystem::create_directories(out),"new evidence directory required");
 EpochSink sink(mode=="reject");FinalSink finalSink;PlannerGate gate;std::unique_ptr<ProgressiveMacPlaybackEngine> engine;
 std::ofstream checks(out/"checks.jsonl"),receipts(out/"receipts.jsonl");std::size_t done=0,actualAccepted=0;std::string reason;
 std::uint64_t serial=0,firstPrep=0,firstGeneration=0,firstSession=0,secondSession=0,lastSession=0,lastPrep=0;
 std::vector<std::string> beforeTerminal,ownedFrozen;std::vector<EOperation> before;
 std::optional<ProgressiveDiagnostics> stopped;std::uint64_t cppNew=0,workerNew=0;bool cppMeasured=false,workerMeasured=false;
 const auto pass=[&]{require(done<epochChecks.size(),"extra check");checks<<"{\"id\":"<<ep58::jsonString(epochChecks[done++])<<",\"pass\":true}\n";checks.flush();require(bool(checks),"check write");};
 try{
  floatFixture(input);ts::WavStreamReader w(input);const auto rate=w.sampleRate();require((rate==44100||rate==48000)&&(w.channels()==1||w.channels()==2)&&w.frames()>=rate*16ULL&&w.frames()<=rate*20ULL,"bounded 16..20s product fixture");
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"schema\":1,\"suite\":\"progressive_adoption_full_epoch_audit\",\"mode\":"<<ep58::jsonString(mode)<<",\"expected\":14,\"required_ids\":[";for(std::size_t i=0;i<epochChecks.size();++i)f<<(i?",":"")<<ep58::jsonString(epochChecks[i]);
   f<<"],\"source\":"<<ep58::jsonString(argv[4])<<",\"input\":"<<ep58::jsonString(input.string())<<",\"input_sha256\":"<<ep58::jsonString(ehash(input))<<",\"binary_sha256\":"<<ep58::jsonString(ehash(std::filesystem::absolute(argv[0])))<<",\"preset\":"<<ep58::jsonString(presetName)<<",\"accepted_ordinary_speeds\":300,\"maximum_internal_plans\":512,\"closed_retention\":256,\"expected_epoch_deliveries\":3,\"sink_rejects\":"<<(sink.reject?"true":"false")<<",\"callback_gate\":false,\"normal_planner_gate\":true,\"D07_H_used\":false,\"physical_audio\":null,\"PCM_oracle\":\"NOT_RUN\",\"operation_field_encoding\":\"declared-member-order flat array; floats IEEE bits, vector count before elements; no padding\"}\n";require(bool(f),"EXPECTED write");}
  phase61_heap_reset();ProgressiveOptions o=ProgressiveOptions::macOSProduct();o.preset=presetName=="baseline"?Preset::Baseline:Preset::Candidate;o.initialSpeed=1;o.callbackRecordLimit=2048;o.measureControlCosts=true;
  o.finalEpochAuditContext=&sink;o.receiveFinalEpochAudit=EpochSink::receive;o.finalOperationAuditContext=&finalSink;o.receiveFinalOperationAudit=FinalSink::receive;
  o.pipelineControlTestHooks.context=&gate;o.pipelineControlTestHooks.event=PlannerGate::control;
  o.pipelineLifecycleTestHooks.context=&gate;o.pipelineLifecycleTestHooks.event=PlannerGate::lifecycle;
  o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
  engine=std::make_unique<ProgressiveMacPlaybackEngine>();require(engine->prepare(input,o),"prepare");
  until(*engine,[&]{return engine->getPlaybackState()==State::Ready&&engine->getPlaybackDiagnostics().pipeline.analysisDone;},"Ready/final analysis");
  auto initial=engine->getStateSnapshot();auto d=engine->getPlaybackDiagnostics();serial=d.engineSerial;firstPrep=initial.preparation;firstGeneration=initial.inputGeneration;firstSession=initial.session;
  require(serial&&firstPrep&&firstGeneration&&firstSession&&initial.renderEpoch&&d.epochAuditConfigured&&!d.epochAuditCalls&&!d.epochAuditRejected,"initial sink identity/counters");pass();
  require(engine->play(),"play");firstPcm(*engine);require(engine->getPlaybackState()==State::Playing&&!engine->getLoopSnapshot().enabled,"ordinary Playing required");gate.session=firstSession;pass();
  std::set<std::uint64_t> accepted;
  const auto request=[&](double speed){const auto r=engine->setSpeed(speed,firstSession,firstGeneration,initial.renderEpoch);require(r.result==EReceipt::Accepted&&r.id&&accepted.insert(r.id).second,"ordinary speed not Accepted/unique");++actualAccepted;receipts<<"{\"session\":"<<firstSession<<",\"id\":"<<r.id<<",\"target_micros\":"<<std::llround(speed*1000000)<<",\"result\":\"Accepted\"}\n";};
  request(.75);until(*engine,[&]{return gate.entered.load();},"normal planner did not enter bounded gate");
  for(std::size_t i=1;i<burstCount;++i)request(i%2?.76:.75);
  require(accepted.size()==burstCount&&*accepted.begin()==1&&*accepted.rbegin()==burstCount,"accepted ID set 1..300");pass();
  before=engine->operationHistory();require(before.size()==300&&before.front().state==EState::Submitted&&before.back().state==EState::Pending,"fixed in-flight cohort");
  for(std::size_t i=1;i+1<before.size();++i)require(before[i].state==EState::Replaced,"pending replacement terminal missing");beforeTerminal=freeze(before);pass();
  const auto seek=engine->requestSeekToInputFrame(4ULL*rate,firstGeneration,initial.renderEpoch);require(seek.accepted&&seek.id,"manual Exact admission");const auto completed=waitSeek(*engine,seek.id);require(completed.mode==progressive::SeekMode::Exact&&completed.session!=firstSession&&completed.renderEpoch!=initial.renderEpoch,"Exact did not change owner identity");secondSession=completed.session;pass();
  until(*engine,[&]{return sink.size()==1&&!engine->getPlaybackDiagnostics().retiringPipeline;},"old owner final audit/join");
  auto old=sink.at(firstSession);auditMetadata(old,serial,firstPrep,firstGeneration);require(old.rows.size()==300&&!old.preparedOnly&&old.epoch==initial.renderEpoch&&gate.release&&!gate.timedOut,"full old joined audit");pass();
  const auto closed=engine->closedEpochs();const auto ci=std::find_if(closed.begin(),closed.end(),[&](const auto& v){return v.pipeline.session==firstSession;});
  require(ci!=closed.end()&&ci->pipeline.finalDataAvailable&&ci->operations.size()==256&&ci->droppedOperations==44&&ci->pipeline.transitionHistory<=512,"closed history/plan bound changed");
  for(std::size_t i=0;i<256;++i)require(fields(ci->operations[i])==fields(old.rows[i+44]),"closed tail differs from full owned audit");pass();
  std::size_t replaced=0,cancelled=0;
  for(std::size_t i=0;i<old.rows.size();++i){const auto& op=old.rows[i];require(op.id==i+1&&op.session==firstSession&&op.inputGeneration==firstGeneration&&op.acceptance==EReceipt::Accepted&&terminal(op.state),"Accepted ID lost or nonterminal");replaced+=op.state==EState::Replaced;cancelled+=op.state==EState::Cancelled;if(before[i].state==EState::Replaced)require(fields(op)==beforeTerminal[i],"Replaced terminal field mutated after retirement");}
  require(replaced==298&&cancelled==2,"fixed Replaced/Cancelled cohort");ownedFrozen=freeze(old.rows);pass();
  until(*engine,[&]{const auto q=engine->getPlaybackDiagnostics().pipeline.scheduling;return q.active&&q.intervalStarts>0;},"Exact owner did not execute a Workgroup interval");
  const auto now=engine->getStateSnapshot();const auto r=engine->setSpeed(.9,now.session,now.inputGeneration,now.renderEpoch);require(r.result==EReceipt::Accepted&&r.id==1,"new owner ordinary ID1");engine->stop();stopped=engine->getPlaybackDiagnostics();
  require(sink.size()==2&&stopped->epochAuditCalls==2&&stopped->epochAuditRejected==(sink.reject?2u:0u),"Stop delivery/counters");auto second=sink.at(secondSession);auditMetadata(second,serial,firstPrep,firstGeneration);require(second.rows.size()==1&&second.rows.front().id==1&&terminal(second.rows.front().state),"Stop owner whole ledger");
  engine->stop();require(sink.size()==2&&engine->getPlaybackDiagnostics().epochAuditCalls==2,"duplicate Stop redelivered epoch");pass();
  cppMeasured=stopped->callbackCppNew.has_value();cppNew=stopped->callbackCppNew.value_or(0);workerNew=stopped->workerNewCalls;workerMeasured=stopped->pipeline.realtimeAllocationsMeasured;
  require(engine->prepare(input,o),"reprepare");until(*engine,[&]{return engine->getPlaybackState()==State::Ready&&engine->getPlaybackDiagnostics().pipeline.analysisDone;},"reprepare Ready");
  auto last=engine->getStateSnapshot();lastSession=last.session;lastPrep=last.preparation;const auto lastDiag=engine->getPlaybackDiagnostics();
  require(lastSession!=firstSession&&lastSession!=secondSession&&last.inputGeneration!=firstGeneration&&lastPrep!=firstPrep&&lastDiag.engineSerial==serial&&lastDiag.epochAuditConfigured&&lastDiag.epochAuditCalls==2&&lastDiag.epochAuditRejected==(sink.reject?2u:0u),"prepare reset/identity/counter latch");require(engine->operationHistory().empty()&&engine->closedEpochs().empty(),"new owner ledger not empty");pass();
  engine.reset();require(sink.size()==3,"direct close empty owner missing or duplicate");auto lastOwned=sink.at(lastSession);auditMetadata(lastOwned,serial,lastPrep,last.inputGeneration);require(lastOwned.rows.empty()&&!lastOwned.preparedOnly&&lastOwned.epoch==last.renderEpoch,"empty final owner metadata");pass();
  const auto all=sink.copy();std::set<std::uint64_t> sessions,sequences;
  for(std::size_t i=0;i<all.size();++i){require(all[i].engine==serial&&all[i].sequence==i+1&&sessions.insert(all[i].session).second&&sequences.insert(all[i].sequence).second,"session delivered twice/sequence discontinuity");}
  require(freeze(sink.at(firstSession).rows)==ownedFrozen&&!sink.copyErrors&&!sink.callbackCalls,"owned deep copy changed or callback delivery");pass();
  require(cppMeasured&&!cppNew&&workerMeasured&&!workerNew&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback/worker allocation probe must measure zero");
  require(stopped&&!stopped->missingFrames&&!stopped->underrunCalls&&!stopped->rejectedWrites,"ordinary supply failure");pass();
  const auto owners=ep58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"owner cap/final join");
  require(finalSink.calls==1&&finalSink.engine==serial&&finalSink.preparation==lastPrep&&finalSink.epochCalls==3&&finalSink.rejected==(sink.reject?3u:0u)&&finalSink.joined&&finalSink.released&&finalSink.configured&&!finalSink.callback&&finalSink.seeks==1&&sink.calls==3,"final destructor audit call/rejection counters");pass();
 }catch(const std::exception& e){reason=e.what();gate.release=true;try{engine.reset();}catch(...) {}}
 try{saveEpochs(out,sink.copy());}catch(const std::exception& e){if(!reason.empty())reason+="; ";reason+=e.what();}
 std::ofstream result(out/"SUMMARY.json");const auto owners=ep58::RealtimePipeline::executionOwnerCounts();const bool ok=reason.empty()&&done==epochChecks.size();
 result<<"{\"schema\":1,\"suite\":\"progressive_adoption_full_epoch_audit\",\"mode\":"<<ep58::jsonString(mode)<<",\"status\":\""<<(ok?"PASS":"FAIL")<<"\",\"run_complete\":"<<(ok?"true":"false")<<",\"expected\":14,\"executed\":"<<done<<",\"passed\":"<<done<<",\"source\":"<<ep58::jsonString(argv[4])<<",\"engine_serial\":"<<serial<<",\"accepted_ordinary_ids\":"<<actualAccepted<<",\"epoch_audit_calls\":"<<sink.calls<<",\"epoch_audit_rejected_expected\":"<<(sink.reject?sink.calls:0)<<",\"final_reported_calls\":"<<finalSink.epochCalls<<",\"final_audit_configured\":"<<(finalSink.configured?"true":"false")<<",\"final_reported_rejected\":"<<finalSink.rejected<<",\"copy_errors\":"<<sink.copyErrors<<",\"sink_callback_calls\":"<<sink.callbackCalls<<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak<<",\"callback_cpp_new_measured\":"<<(cppMeasured?"true":"false")<<",\"worker_new_measured\":"<<(workerMeasured?"true":"false")<<",\"callback_cpp_new\":"<<(cppMeasured?std::to_string(cppNew):"null")<<",\"worker_new\":"<<(workerMeasured?std::to_string(workerNew):"null")<<",\"callback_heap_allocations\":"<<phase61_heap_allocations()<<",\"callback_heap_frees\":"<<phase61_heap_frees()<<",\"callback_gate\":false,\"normal_planner_gate\":true,\"native_control_threads\":1,\"D07_H_used\":false,\"PCM_quality\":\"NOT_ASSESSED\",\"normal_RT_approval\":\"NOT_ASSESSED\",\"physical_audio\":null,\"reason\":"<<ep58::jsonString(reason)<<"}\n";result.close();require(bool(result),"summary write");
 std::ofstream artifacts(out/"ARTIFACTS.json");artifacts<<"{\"artifacts\":[";bool first=true;for(const auto* name:{"EXPECTED.json","checks.jsonl","receipts.jsonl","epoch_audits.jsonl","owned_operations.jsonl","SUMMARY.json"}){auto p=out/name;if(!std::filesystem::exists(p))continue;artifacts<<(first?"":",")<<"{\"path\":"<<ep58::jsonString(name)<<",\"bytes\":"<<std::filesystem::file_size(p)<<",\"sha256\":"<<ep58::jsonString(ehash(p))<<'}';first=false;}artifacts<<"]}\n";artifacts.close();require(bool(artifacts),"artifacts write");return ok?0:2;
}
}
int main(int argc,char** argv){int code=1;std::thread control([&]{try{code=epochMain(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return code;}
