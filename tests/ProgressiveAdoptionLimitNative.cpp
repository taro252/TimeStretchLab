// D5: 公開APIの実4096件上限とEngine再作成。実音声/性能試験ではない。
// INPUT PRESET NEW_OUT SOURCE_SHA。全API/破棄は1本の通常制御thread。
#define PHASE61_SANDBOX_APP 1
#include "Phase61NativeTests.cpp"
#include "prototype/Phase45PcmDigest.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <iomanip>
#include <optional>
#include <set>
#include <sstream>

namespace {
namespace limit58=ts::prototype::phase58;
using LimitReason=progressive::AvailabilityReason;
constexpr std::size_t realSeekLimit=4096;
const std::array<const char*,10> limitChecks{
 "D5L01_initial_v3_fixture","D5L02_rejected_ids_1_to_4096",
 "D5L03_full_history_stationary","D5L04_limit_preserves_state",
 "D5L05_stop_prepare_keeps_history","D5L06_reprepared_limit",
 "D5L07_old_owned_final_audit","D5L08_new_engine_identity_and_id1",
 "D5L09_exact_completed_without_play","D5L10_new_owned_final_audit"};

std::string limitHash(const std::filesystem::path& path){
 std::ifstream in(path,std::ios::binary);require(bool(in),"hash input absent");
 ts::prototype::Phase45PcmDigest hash;std::array<char,65536> block{};
 while(in.read(block.data(),block.size())||in.gcount())hash.update(block.data(),std::size_t(in.gcount()));
 require(in.eof(),"hash read failed");return hash.finish();
}
void limitFloat32(const std::filesystem::path& path){
 std::ifstream in(path,std::ios::binary);std::array<unsigned char,16> bytes{};in.read(reinterpret_cast<char*>(bytes.data()),12);
 require(bool(in)&&!std::memcmp(bytes.data(),"RIFF",4)&&!std::memcmp(bytes.data()+8,"WAVE",4),"fixture RIFF/WAVE");
 while(in){
  in.read(reinterpret_cast<char*>(bytes.data()),8);require(bool(in),"fixture fmt absent");
  const auto size=std::uint32_t(bytes[4])|(std::uint32_t(bytes[5])<<8)|(std::uint32_t(bytes[6])<<16)|(std::uint32_t(bytes[7])<<24);
  const auto content=in.tellg();if(!std::memcmp(bytes.data(),"fmt ",4)){
   require(size>=16,"fixture fmt size");in.read(reinterpret_cast<char*>(bytes.data()),16);
   require(bool(in)&&bytes[0]==3&&bytes[1]==0&&bytes[14]==32&&bytes[15]==0,"fixture requires IEEE Float32");return;
  }
  in.seekg(content+std::streamoff(size)+std::streamoff(size&1));
 }
 throw std::runtime_error("fixture Float32 fmt absent");
}
std::string limitSeekJson(const progressive::SeekOperation& p){
 std::ostringstream s;s<<"{\"mode\":"<<int(p.mode)<<",\"preroll_ms\":"<<p.prerollMillis
 <<",\"id\":"<<p.id<<",\"input_generation\":"<<p.inputGeneration<<",\"source_epoch\":"<<p.sourceRenderEpoch
 <<",\"epoch\":"<<p.renderEpoch<<",\"session\":"<<p.session<<",\"requested_input\":"<<p.requestedInputFrame
 <<",\"output_start\":"<<p.outputStartFrame<<",\"state\":"<<limit58::jsonString(progressive::name(p.state))
 <<",\"reason\":"<<limit58::jsonString(p.reason)<<",\"code\":"<<limit58::jsonString(progressive::name(p.code))
 <<",\"speed_micros\":"<<p.speedMicros<<",\"replans\":"<<p.replans<<",\"accepted_ns\":"<<p.acceptedNs
 <<",\"preparing_ns\":"<<p.preparingNs<<",\"ready_ns\":"<<p.readyNs<<",\"switched_ns\":"<<p.switchedNs
 <<",\"first_callback_ns\":"<<p.firstCallbackNs<<",\"estimated_presentation_ns\":"<<p.estimatedPresentationNs
 <<",\"stage\":"<<limit58::jsonString(progressive::name(p.stage))<<",\"analysis_ready_ns\":"<<p.analysisReadyNs
 <<",\"switch_ready_ns\":"<<p.switchReadyNs<<",\"transition_begin_ns\":"<<p.transitionBeginNs<<",\"transition_end_ns\":"<<p.transitionEndNs
 <<",\"old_fifo_at_switch\":"<<p.oldFifoAtSwitchFrames<<",\"discarded_for_seek\":"<<p.discardedForSeekFrames
 <<",\"transition_frames\":"<<p.transitionFrames<<",\"waited_for_analysis\":"<<(p.waitedForAnalysis?"true":"false")<<'}';return s.str();
}
struct LimitOwnedAudit{
 std::vector<progressive::SeekOperation> rows;
 std::uint64_t calls=0,serial=0,preparation=0;bool copied=false,joined=false,retired=false,error=false;
 LimitOwnedAudit(){rows.reserve(realSeekLimit);}
 static bool receive(void* context,const FinalOperationAudit& a)noexcept{
  auto& s=*static_cast<LimitOwnedAudit*>(context);
  if(++s.calls!=1||!a.engineSerial||!a.workersJoined||!a.retirementComplete||a.seeks.size()>realSeekLimit||
     !a.stoppedSpeeds.empty()||!a.loopSpeeds.empty()||!a.loopPreparations.empty()){s.error=true;return false;}
  s.serial=a.engineSerial;s.preparation=a.preparation;s.joined=a.workersJoined;s.retired=a.retirementComplete;
  try{s.rows.assign(a.seeks.begin(),a.seeks.end());s.copied=true;}catch(...){s.error=true;return false;}return true;
 }
 void validate(std::uint64_t expectedSerial,std::uint64_t expectedPreparation,const std::vector<std::string>& frozen)const{
  require(calls==1&&copied&&joined&&retired&&!error&&serial==expectedSerial&&preparation==expectedPreparation,"owned final audit markers");
  require(rows.size()==frozen.size(),"owned final audit missing rows");
  for(std::size_t i=0;i<rows.size();++i)require(rows[i].id==i+1&&progressive::terminal(rows[i].state)&&limitSeekJson(rows[i])==frozen[i],"owned final audit ID/terminal/value mismatch");
 }
 void save(const std::filesystem::path& path)const{
  std::ofstream f(path);f<<"{\"record\":\"owned_audit\",\"calls\":"<<calls<<",\"engine_serial\":"<<serial
   <<",\"preparation\":"<<preparation<<",\"copied\":"<<copied<<",\"workers_joined\":"<<joined<<",\"retired\":"<<retired<<",\"error\":"<<error<<",\"rows\":"<<rows.size()<<"}\n";
  for(const auto& p:rows)f<<limitSeekJson(p)<<'\n';f.close();require(bool(f),"owned audit write");
 }
};
struct LimitObservation{
 ProgressiveStateSnapshot state;ProgressivePosition position;ProgressiveDiagnostics diagnostics;progressive::LoopSnapshot loop;progressive::HistoryUsage usage;ProgressiveNativeDiagnostics native;
};
LimitObservation limitObserve(ProgressiveMacPlaybackEngine& e){
 return{e.getStateSnapshot(),e.getCurrentPlaybackPosition(),e.getPlaybackDiagnostics(),e.getLoopSnapshot(),e.historyUsage(),e.getNativeDiagnostics()};
}
void limitNoAudio(const LimitObservation& o){
 require(!o.native.callbackCalls&&!o.native.firstPcmMachNs&&!o.state.resumePending&&o.diagnostics.consumedFrames==o.diagnostics.pipeline.outputStartFrame&&!o.diagnostics.presentedFrames,"limit host unexpectedly rendered audio");
 require(!o.diagnostics.missingFrames&&!o.diagnostics.underrunCalls&&!o.diagnostics.rejectedWrites&&!o.diagnostics.workerNewCalls,"limit host supply/allocation error");
}
void limitStationary(ProgressiveMacPlaybackEngine& e,const LimitObservation& before){
 const auto after=limitObserve(e);limitNoAudio(after);
 require(after.state.state==before.state.state&&after.state.session==before.state.session&&after.state.inputGeneration==before.state.inputGeneration&&after.state.renderEpoch==before.state.renderEpoch&&
         after.position.inputFrame==before.position.inputFrame&&after.position.outputFrame==before.position.outputFrame&&after.diagnostics.publishedFrames==before.diagnostics.publishedFrames&&after.diagnostics.consumedFrames==before.diagnostics.consumedFrames,
         "rejection changed C/FIFO/state/owner");
 require(after.loop.id==before.loop.id&&after.loop.enabled==before.loop.enabled&&after.loop.state==before.loop.state&&after.loop.startFrame==before.loop.startFrame&&after.loop.endFrameExclusive==before.loop.endFrameExclusive&&after.loop.cycles==before.loop.cycles&&after.loop.clearPending==before.loop.clearPending,"rejection changed Loop");
}
template<class P>void limitUntil(ProgressiveMacPlaybackEngine& e,P predicate,const char* why){
 const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(15);
 while(!predicate()){
  if(e.getPlaybackState()==State::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);
  require(std::chrono::steady_clock::now()<deadline,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));
 }
}
void limitPrepare(ProgressiveMacPlaybackEngine& e,const std::filesystem::path& input,const ProgressiveOptions& options){
 require(e.prepare(input,options),"limit prepare rejected");const auto lead=options.preset==Preset::Candidate?16384:12288;
 limitUntil(e,[&]{const auto d=e.getPlaybackDiagnostics();return e.getPlaybackState()==State::Ready&&d.pipeline.analysisDone&&d.publishedFrames-d.consumedFrames==std::uint64_t(lead);},"Ready/final analysis/initial FIFO");
 const auto o=limitObserve(e);limitNoAudio(o);
 require(o.position.inputFrame==std::optional<std::uint64_t>(0)&&o.state.session&&o.state.inputGeneration&&o.state.renderEpoch&&o.diagnostics.engineSerial&&o.diagnostics.pipeline.fifoCapacityFrames==16384,"initial identity/C/FIFO");
}
std::vector<std::string> limitFreeze(const std::vector<progressive::SeekOperation>& rows){
 std::vector<std::string> values;values.reserve(rows.size());
 for(const auto& p:rows)values.push_back(limitSeekJson(p));return values;
}
void limitRowsEqual(const std::vector<progressive::SeekOperation>& rows,const std::vector<std::string>& frozen){
 require(rows.size()==frozen.size(),"history count changed");for(std::size_t i=0;i<rows.size();++i)require(rows[i].id==i+1&&limitSeekJson(rows[i])==frozen[i],"terminal history changed");
}
void limitSaveRows(const std::filesystem::path& path,const std::vector<std::string>& rows){
 std::ofstream f(path);for(const auto& row:rows)f<<row<<'\n';f.close();require(bool(f),"history write");
}
void limitSaveObservation(std::ostream& f,const char* label,const LimitObservation& o){
 f<<"{\"label\":"<<limit58::jsonString(label)<<",\"engine_serial\":"<<o.diagnostics.engineSerial<<",\"preparation\":"<<o.state.preparation
  <<",\"state\":"<<limit58::jsonString(progressive::name(o.state.state))<<",\"input_generation\":"<<o.state.inputGeneration<<",\"session\":"<<o.state.session<<",\"epoch\":"<<o.state.renderEpoch<<",\"C\":";
 if(o.position.inputFrame)f<<*o.position.inputFrame;else f<<"null";
 f<<",\"output\":"<<o.position.outputFrame<<",\"published\":"<<o.diagnostics.publishedFrames<<",\"consumed\":"<<o.diagnostics.consumedFrames
  <<",\"loop_id\":"<<o.loop.id<<",\"loop_enabled\":"<<o.loop.enabled<<",\"loop_cycles\":"<<o.loop.cycles<<",\"seek_history\":"<<o.usage.seek<<",\"recreation_required\":"<<o.usage.recreationRequired
  <<",\"callback_calls\":"<<o.native.callbackCalls<<",\"first_PCM_ns\":"<<o.native.firstPcmMachNs<<",\"fifo_capacity\":"<<o.diagnostics.pipeline.fifoCapacityFrames<<"}\n";f.flush();require(bool(f),"observation write");
}

int runAdoptionLimit(int argc,char** argv){
 require(argc==5,"INPUT PRESET NEW_OUT SOURCE_SHA");const std::filesystem::path input=argv[1],out=argv[3];const std::string presetName=argv[2];
 require(presetName=="baseline"||presetName=="candidate","preset");require(!std::filesystem::exists(out)&&std::filesystem::create_directories(out),"fresh output directory required");
 std::ofstream checks(out/"checks.jsonl"),receipts(out/"receipts.jsonl"),observations(out/"observations.jsonl");
 std::size_t done=0;LimitOwnedAudit oldAudit,newAudit;std::unique_ptr<ProgressiveMacPlaybackEngine> oldEngine,newEngine;
 std::vector<std::string> oldFrozen,newFrozen;std::optional<LimitObservation> initial,reprepared,newInitial,newCompleted;
 const auto pass=[&]{require(done<limitChecks.size(),"extra check");checks<<"{\"id\":"<<limit58::jsonString(limitChecks[done++])<<",\"status\":\"PASS\"}\n";checks.flush();require(bool(checks),"check write");};
 const auto receipt=[&](const char* label,const progressive::SeekReceipt& r){receipts<<"{\"label\":"<<limit58::jsonString(label)<<",\"id\":"<<r.id<<",\"accepted\":"<<r.accepted<<",\"code\":"<<limit58::jsonString(progressive::name(r.code))<<",\"reason\":"<<limit58::jsonString(r.reason)<<"}\n";};
 const auto writeSummary=[&](bool ok,const std::string& reason){
  std::ofstream f(out/"SUMMARY.json");const auto owners=limit58::RealtimePipeline::executionOwnerCounts();
  f<<"{\"schema\":1,\"status\":\""<<(ok?"PASS":"FAIL")<<"\",\"run_complete\":"<<(ok?"true":"false")<<",\"expected\":10,\"executed\":"<<done<<",\"passed\":"<<done
   <<",\"source\":"<<limit58::jsonString(argv[4])<<",\"preset\":"<<limit58::jsonString(presetName)<<",\"real_seek_limit\":4096,\"old_recovered\":"<<oldAudit.rows.size()<<",\"new_recovered\":"<<newAudit.rows.size()
   <<",\"old_engine_serial\":"<<oldAudit.serial<<",\"new_engine_serial\":"<<newAudit.serial<<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak
   <<",\"audio_playback\":\"NOT_RUN\",\"performance\":\"NOT_ASSESSED\",\"native_control_threads\":1,\"callback_gate\":false,\"reason\":"<<limit58::jsonString(reason)<<"}\n";f.close();require(bool(f),"summary write");
 };
 const auto writeArtifacts=[&]{
  std::ofstream f(out/"ARTIFACTS.json");f<<"{\"schema\":1,\"artifacts\":[";bool first=true;
  for(const auto* name:{"EXPECTED.json","MANIFEST.json","checks.jsonl","receipts.jsonl","observations.jsonl","old_history_4096.jsonl","old_close_owned.jsonl","new_completed.jsonl","new_close_owned.jsonl","SUMMARY.json"}){
   const auto p=out/name;if(!std::filesystem::exists(p))continue;f<<(first?"":",")<<"{\"path\":"<<limit58::jsonString(name)<<",\"bytes\":"<<std::filesystem::file_size(p)<<",\"sha256\":"<<limit58::jsonString(limitHash(p))<<'}';first=false;
  }f<<"]}\n";f.close();require(bool(f),"artifact hashes write");
 };
 try{
  limitFloat32(input);const ts::WavStreamReader wav(input);const auto rate=wav.sampleRate();
  require((rate==44100||rate==48000)&&(wav.channels()==1||wav.channels()==2)&&wav.frames()>=16ULL*rate&&wav.frames()<=20ULL*rate,"bounded 16..20s product Float32 fixture");
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"schema\":1,\"expected\":10,\"required_ids\":[";for(std::size_t i=0;i<limitChecks.size();++i)f<<(i?",":"")<<limit58::jsonString(limitChecks[i]);f<<"],\"real_seek_limit\":4096,\"old_final_ids\":\"1..4096 Rejected\",\"new_final_ids\":[1],\"no_history_deletion\":true,\"no_limit_override\":true}\n";f.close();require(bool(f),"expected write");}
  {std::ofstream f(out/"MANIFEST.json");f<<"{\"schema\":1,\"purpose\":\"D5 public API actual lifetime limit; not audio/performance validation\",\"source\":"<<limit58::jsonString(argv[4])
    <<",\"binary\":{\"path\":"<<limit58::jsonString(std::filesystem::absolute(argv[0]).string())<<",\"bytes\":"<<std::filesystem::file_size(argv[0])<<",\"sha256\":"<<limit58::jsonString(limitHash(argv[0]))<<"},\"input\":{\"path\":"<<limit58::jsonString(std::filesystem::absolute(input).string())<<",\"bytes\":"<<std::filesystem::file_size(input)<<",\"sha256\":"<<limit58::jsonString(limitHash(input))<<",\"encoding\":\"IEEE Float32\",\"rate\":"<<rate<<",\"channels\":"<<wav.channels()<<",\"frames\":"<<wav.frames()
    <<"},\"preset\":"<<limit58::jsonString(presetName)<<",\"contract_version\":3,\"exact_policy\":\"Research\",\"loop_policy\":\"Research\",\"interactive_policy\":\"Disabled\",\"real_seek_limit\":4096,\"native_control_threads\":1,\"play_calls\":0,\"resume_calls\":0,\"audio_playback\":\"NOT_RUN\",\"performance\":\"NOT_ASSESSED\",\"callback_gate\":false}\n";f.close();require(bool(f),"manifest write");}
  ProgressiveOptions options;options.preset=presetName=="baseline"?Preset::Baseline:Preset::Candidate;options.initialSpeed=1;
  options.featurePolicy=progressive::FeaturePolicyOptions{3,progressive::FeaturePolicy::Research,progressive::FeaturePolicy::Disabled,progressive::FeaturePolicy::Research};
  options.finalOperationAuditContext=&oldAudit;options.receiveFinalOperationAudit=LimitOwnedAudit::receive;
  oldEngine=std::make_unique<ProgressiveMacPlaybackEngine>();limitPrepare(*oldEngine,input,options);initial=limitObserve(*oldEngine);
  require(initial->usage.seek==0&&!initial->usage.recreationRequired&&oldEngine->seekAvailability().exact.allowed&&oldEngine->loopAvailability().allowed&&ProgressiveMacPlaybackEngine::capabilities().maxSeekOperations==realSeekLimit,"v3 initial state/actual limit");
  limitSaveObservation(observations,"old_initial_Ready",*initial);pass();

  for(std::uint64_t id=1;id<=realSeekLimit;++id){
   const auto r=oldEngine->requestSeekToInputFrame(wav.frames()+1,initial->state.inputGeneration,initial->state.renderEpoch);
   receipt("out_of_range",r);require(!r.accepted&&r.id==id&&r.code==LimitReason::InvalidRange&&!r.reason.empty(),"Rejected receipt did not use exact 1..4096 slots");
  }receipts.flush();require(bool(receipts),"receipt write");pass();
  const auto history=oldEngine->seekHistory();require(history.size()==realSeekLimit,"Rejected history count");
  for(std::size_t i=0;i<history.size();++i){const auto& p=history[i];require(p.id==i+1&&p.state==Seek::Rejected&&p.code==LimitReason::InvalidRange&&progressive::terminal(p.state)&&p.inputGeneration==initial->state.inputGeneration&&p.sourceRenderEpoch==initial->state.renderEpoch&&p.requestedInputFrame==wav.frames()+1&&p.mode==progressive::SeekMode::Exact&&p.acceptedNs,"Rejected terminal row facts");}
  oldFrozen=limitFreeze(history);limitSaveRows(out/"old_history_4096.jsonl",oldFrozen);limitStationary(*oldEngine,*initial);
  require(oldEngine->historyUsage().seek==realSeekLimit&&oldEngine->historyUsage().recreationRequired,"Rejected slots absent from usage");
  limitSaveObservation(observations,"old_4096_Rejected",limitObserve(*oldEngine));pass();

  const auto full=oldEngine->requestSeekToInputFrame(rate/2,initial->state.inputGeneration,initial->state.renderEpoch);receipt("valid_at_limit",full);
  require(!full.accepted&&!full.id&&full.code==LimitReason::LimitReached&&!full.reason.empty(),"full history accepted valid request/allocated ID");
  limitRowsEqual(oldEngine->seekHistory(),oldFrozen);limitStationary(*oldEngine,*initial);pass();

  oldEngine->stop();require(oldEngine->getPlaybackState()==State::Stopped,"old Stop");limitRowsEqual(oldEngine->seekHistory(),oldFrozen);
  require(oldEngine->historyUsage().seek==realSeekLimit&&oldEngine->historyUsage().recreationRequired,"Stop reset lifetime slots");
  limitPrepare(*oldEngine,input,options);reprepared=limitObserve(*oldEngine);
  require(reprepared->diagnostics.engineSerial==initial->diagnostics.engineSerial&&reprepared->state.preparation>initial->state.preparation&&reprepared->state.session!=initial->state.session&&reprepared->state.inputGeneration!=initial->state.inputGeneration&&reprepared->usage.seek==realSeekLimit&&reprepared->usage.recreationRequired,"prepare reset history or reused input owner identity");
  limitRowsEqual(oldEngine->seekHistory(),oldFrozen);limitSaveObservation(observations,"old_reprepared_Ready",*reprepared);pass();

  const auto stillFull=oldEngine->requestSeekToInputFrame(rate/2,reprepared->state.inputGeneration,reprepared->state.renderEpoch);receipt("valid_after_reprepare_at_limit",stillFull);
  require(!stillFull.accepted&&!stillFull.id&&stillFull.code==LimitReason::LimitReached,"reprepare reopened lifetime slots");
  limitRowsEqual(oldEngine->seekHistory(),oldFrozen);limitStationary(*oldEngine,*reprepared);limitSaveObservation(observations,"old_reprepared_limit_preserved",limitObserve(*oldEngine));pass();

  oldEngine.reset();oldAudit.validate(reprepared->diagnostics.engineSerial,reprepared->state.preparation,oldFrozen);oldAudit.save(out/"old_close_owned.jsonl");
  require(!limit58::RealtimePipeline::executionOwnerCounts().alive,"old close owner leak");pass();

  options.finalOperationAuditContext=&newAudit;newEngine=std::make_unique<ProgressiveMacPlaybackEngine>();limitPrepare(*newEngine,input,options);newInitial=limitObserve(*newEngine);
  require(newInitial->diagnostics.engineSerial!=initial->diagnostics.engineSerial&&newInitial->diagnostics.engineSerial!=reprepared->diagnostics.engineSerial&&newInitial->state.inputGeneration!=initial->state.inputGeneration&&newInitial->state.inputGeneration!=reprepared->state.inputGeneration&&newInitial->state.session!=initial->state.session&&newInitial->state.session!=reprepared->state.session&&newInitial->usage.seek==0&&!newInitial->usage.recreationRequired,"new engine identity/lifetime slots not distinct");
  const auto fresh=newEngine->requestSeekToInputFrame(rate/2,newInitial->state.inputGeneration,newInitial->state.renderEpoch);receipt("new_engine_valid_id1",fresh);
  require(fresh.accepted&&fresh.id==1&&fresh.id==history.front().id&&fresh.code==LimitReason::Available,"new engine ID1 reuse missing");
  limitSaveObservation(observations,"new_engine_id1_Accepted",limitObserve(*newEngine));pass();

  limitUntil(*newEngine,[&]{const auto rows=newEngine->seekHistory();return rows.size()==1&&rows[0].state==Seek::Completed&&!newEngine->getPlaybackDiagnostics().retiringPipeline;},"new engine Exact Completed");
  const auto completed=newEngine->seekHistory();newCompleted=limitObserve(*newEngine);limitNoAudio(*newCompleted);
  require(completed.size()==1&&completed[0].id==1&&completed[0].state==Seek::Completed&&completed[0].mode==progressive::SeekMode::Exact&&completed[0].inputGeneration==newInitial->state.inputGeneration&&completed[0].session==newCompleted->state.session&&completed[0].renderEpoch==newCompleted->state.renderEpoch&&!completed[0].firstCallbackNs&&!completed[0].estimatedPresentationNs&&newCompleted->state.state==State::Ready&&!newCompleted->state.resumePending&&newCompleted->position.inputFrame==std::optional<std::uint64_t>(rate/2)&&newCompleted->diagnostics.consumedFrames==newCompleted->diagnostics.pipeline.outputStartFrame&&!newCompleted->loop.enabled&&!newCompleted->loop.cycles,"Ready Exact completion auto-played or wrong identity/position");
  require(newCompleted->usage.seek==1&&!newCompleted->usage.recreationRequired,"new lifetime count not one");
  newFrozen=limitFreeze(completed);limitSaveRows(out/"new_completed.jsonl",newFrozen);limitSaveObservation(observations,"new_Exact_Completed_without_Play",*newCompleted);pass();

  newEngine.reset();newAudit.validate(newInitial->diagnostics.engineSerial,newCompleted->state.preparation,newFrozen);newAudit.save(out/"new_close_owned.jsonl");oldAudit.validate(reprepared->diagnostics.engineSerial,reprepared->state.preparation,oldFrozen);
  const auto owners=limit58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2&&oldAudit.rows.size()==realSeekLimit&&newAudit.rows.size()==1,"final owners/full recovery");
  pass();require(done==limitChecks.size(),"incomplete fixed IDs");
  checks.close();receipts.close();observations.close();require(bool(checks)&&bool(receipts)&&bool(observations),"evidence close");writeSummary(true,"");writeArtifacts();return 0;
 }catch(const std::exception& error){
  oldEngine.reset();newEngine.reset();
  try{oldAudit.save(out/"old_close_owned.jsonl");newAudit.save(out/"new_close_owned.jsonl");}catch(...){}
  checks.close();receipts.close();observations.close();writeSummary(false,error.what());writeArtifacts();std::cerr<<error.what()<<'\n';return 1;
 }
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=runAdoptionLimit(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});control.join();return result;}
