// Step A(e): INPUT.wav candidate|baseline NEW_OUTPUT SOURCE_SHA old|candidate
// 旧v3/新v4共通API。同一sourceを各版のheaders/helpers/staticlibsへ単独link。
// 最初だけ短くPlay/Pauseし、ExactでC=270秒へ固定。その費用は準備欄へ分離。
// Pausedで .4 -> 1 -> 2、即時とReady後の同値再試行。明示Resumeは呼ばない。
// C=入力frameを固定。速度別Mapの絶対outputStart/epoch座標を同一視しない。
// FIFO破棄はdiscardedForStoppedSpeedFramesへ所属し、実音声消費と区別する。
// 詳細worker/control profile OFF。stage hashはlibrary既定（v3 ON/v4既定）。
// 新版専用stage設定は触らない。native accepted/Ready内差と観測wall/CPUは別。
// callbackのgate/待機なし。PCM品質/RT期限/実アプリFは別の承認条件。
#define TS_PHASE62_INITIAL_NO_MAIN 1
#include "Phase62InitialLoopNative.cpp"
#include "prototype/Phase45PcmDigest.h"
#include <sys/resource.h>
#include <time.h>
#include <cctype>
#include <map>
#include <set>
#include <sstream>

namespace {
namespace dp58=ts::prototype::phase58;
using DpState=StoppedSpeedState;
using DpResult=ts::prototype::Phase39RequestResult;
struct DpClock {double wall=0,thread=0,process=0;};
DpClock dpClock(){
 timespec t{};rusage p{};require(!clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t)&&!getrusage(RUSAGE_SELF,&p),"CPU clocks");
 return {double(initialNs())*1e-9,double(t.tv_sec)+double(t.tv_nsec)*1e-9,
  double(p.ru_utime.tv_sec)+double(p.ru_utime.tv_usec)*1e-6+double(p.ru_stime.tv_sec)+double(p.ru_stime.tv_usec)*1e-6};
}
void dpCost(std::ostream& f,const DpClock& a,const DpClock& z){
 const auto w=z.wall-a.wall,t=z.thread-a.thread,p=z.process-a.process;
 require(std::isfinite(w)&&std::isfinite(t)&&std::isfinite(p)&&w>=0&&t>=0&&p>=0,"finite CPU/wall costs");
 f<<"{\"wall_s\":"<<w<<",\"control_thread_cpu_s\":"<<t<<",\"process_cpu_s\":"<<p<<'}';
}
std::string dpHash(const std::filesystem::path& path){
 std::ifstream f(path,std::ios::binary);require(bool(f),"hash input");ts::prototype::Phase45PcmDigest h;std::array<char,65536> b{};
 while(f.read(b.data(),b.size())||f.gcount())h.update(b.data(),std::size_t(f.gcount()));require(f.eof(),"hash read");return h.finish();
}
void dpFloat32(const std::filesystem::path& path){
 std::ifstream f(path,std::ios::binary);char h[12]{};require(bool(f.read(h,12))&&std::string(h,4)=="RIFF"&&std::string(h+8,4)=="WAVE","RIFF input");
 for(;;){unsigned char c[8]{};require(bool(f.read(reinterpret_cast<char*>(c),8)),"fmt absent");
  const auto n=std::uint32_t(c[4])|(std::uint32_t(c[5])<<8)|(std::uint32_t(c[6])<<16)|(std::uint32_t(c[7])<<24);
  if(std::string(reinterpret_cast<char*>(c),4)=="fmt "){
   require(n>=16&&n<=4096,"fmt length");std::vector<unsigned char> v(n);require(bool(f.read(reinterpret_cast<char*>(v.data()),n)),"fmt read");
   const auto tag=unsigned(v[0])|(unsigned(v[1])<<8),bits=unsigned(v[14])|(unsigned(v[15])<<8);
   const std::array<unsigned char,16> ieee{3,0,0,0,0,0,16,0,128,0,0,170,0,56,155,113};
   require(bits==32&&(tag==3||(tag==65534&&v.size()>=40&&std::equal(ieee.begin(),ieee.end(),v.begin()+24))),"Float32 required");return;
  }f.seekg(std::streamoff(n)+(n&1),std::ios::cur);require(bool(f),"skip WAV chunk");
 }
}
std::string dpStopped(const StoppedSpeedOperation& o){
 std::ostringstream f;f<<"{\"id\":"<<o.id<<",\"input_generation\":"<<o.inputGeneration<<",\"source_session\":"<<o.sourceSession<<",\"source_epoch\":"<<o.sourceRenderEpoch
  <<",\"source_map_version\":"<<o.mapVersion<<",\"source_consumed_output\":"<<o.consumedOutputFrame<<",\"resume_input\":"<<o.resumeInputFrame<<",\"session\":"<<o.session<<",\"epoch\":"<<o.renderEpoch
  <<",\"output_start\":"<<o.outputStartFrame<<",\"accepted_ns\":"<<o.acceptedNs<<",\"ready_ns\":"<<o.readyNs<<",\"loop_id\":"<<o.loopID<<",\"cycle\":"<<o.cycle<<",\"preparation_version\":"<<o.preparationVersion
  <<",\"discarded_for_stopped_speed_frames\":"<<o.discardedForStoppedSpeedFrames<<",\"speed_micros\":"<<o.speedMicros<<",\"state\":"<<dp58::jsonString(name(o.state))
  <<",\"position_captured\":"<<(o.positionCaptured?"true":"false")<<",\"output_started\":"<<(o.outputStarted?"true":"false")<<",\"mode\":"<<int(o.mode)<<",\"reason\":"<<dp58::jsonString(o.reason)<<'}';return f.str();
}
std::string dpSeek(const progressive::SeekOperation& o){
 std::ostringstream f;f<<"{\"id\":"<<o.id<<",\"mode\":"<<int(o.mode)<<",\"preroll_ms\":"<<o.prerollMillis<<",\"input_generation\":"<<o.inputGeneration<<",\"source_epoch\":"<<o.sourceRenderEpoch
  <<",\"epoch\":"<<o.renderEpoch<<",\"session\":"<<o.session<<",\"requested_input\":"<<o.requestedInputFrame<<",\"output_start\":"<<o.outputStartFrame<<",\"state\":"<<dp58::jsonString(progressive::name(o.state))
  <<",\"reason\":"<<dp58::jsonString(o.reason)<<",\"code\":"<<int(o.code)<<",\"speed_micros\":"<<o.speedMicros<<",\"replans\":"<<o.replans<<",\"accepted_ns\":"<<o.acceptedNs<<",\"preparing_ns\":"<<o.preparingNs
  <<",\"ready_ns\":"<<o.readyNs<<",\"switched_ns\":"<<o.switchedNs<<",\"first_callback_ns\":"<<o.firstCallbackNs<<",\"estimated_presentation_ns\":"<<o.estimatedPresentationNs<<",\"stage\":"<<int(o.stage)
  <<",\"analysis_ready_ns\":"<<o.analysisReadyNs<<",\"switch_ready_ns\":"<<o.switchReadyNs<<",\"transition_begin_ns\":"<<o.transitionBeginNs<<",\"transition_end_ns\":"<<o.transitionEndNs
  <<",\"old_fifo_at_switch\":"<<o.oldFifoAtSwitchFrames<<",\"discarded_for_seek_frames\":"<<o.discardedForSeekFrames<<",\"transition_frames\":"<<o.transitionFrames<<",\"waited_for_analysis\":"<<(o.waitedForAnalysis?"true":"false")<<'}';return f.str();
}
bool dpTerminal(DpState s){return s==DpState::Replaced||s==DpState::Cancelled||s==DpState::Failed;}
struct DpCapture {
 std::atomic<std::uint64_t> rawFrames{0},rawCalls{0},outputFrames{0},outputCalls{0},nonfinite{0},affected{0};
 static void raw(void* p,const float*const* pcm,std::size_t n,std::size_t,std::uint64_t,std::uint64_t,std::uint64_t)noexcept{
  auto& x=*static_cast<DpCapture*>(p);for(std::size_t i=0;i<n;++i)if(!std::isfinite(pcm[0][i]))++x.nonfinite;x.rawFrames+=n;++x.rawCalls;
 }
 static void output(void* p,const float*const* pcm,const ProgressiveOutputSpan& s)noexcept{
  auto& x=*static_cast<DpCapture*>(p);for(std::size_t i=0;i<s.frames;++i)if(!std::isfinite(pcm[0][i]))++x.nonfinite;
  x.outputFrames+=s.frames;++x.outputCalls;x.affected+=s.outputAffectedFrames+s.failurePaddingFrames;
 }
};
struct DpEpoch {std::uint64_t engine=0,preparation=0,sequence=0,epoch=0,session=0,generation=0;bool prepared=false,joined=false,released=false;std::size_t speeds=0;};
struct DpAudit {
 std::size_t calls=0;bool failed=false,joined=false,retired=false,configured=false,callback=false;std::uint64_t serial=0,preparation=0,epochCalls=0,epochRejected=0;
 std::vector<StoppedSpeedOperation> stopped;std::vector<progressive::SeekOperation> seeks;std::vector<DpEpoch> epochs;std::size_t loops=0,preparations=0;
 DpAudit(){stopped.reserve(4);seeks.reserve(2);epochs.reserve(16);}
 static bool receive(void* p,const FinalOperationAudit& a)noexcept{
  auto& x=*static_cast<DpAudit*>(p);try{++x.calls;x.serial=a.engineSerial;x.preparation=a.preparation;x.joined=a.workersJoined;x.retired=a.retirementComplete;x.callback|=callbackCounting;
   x.stopped.assign(a.stoppedSpeeds.begin(),a.stoppedSpeeds.end());x.seeks.assign(a.seeks.begin(),a.seeks.end());x.loops=a.loopSpeeds.size();x.preparations=a.loopPreparations.size();
   x.epochCalls=a.epochAuditCalls;x.epochRejected=a.epochAuditRejected;x.configured=a.epochAuditConfigured;return true;}catch(...){x.failed=true;return false;}
 }
 static bool epoch(void* p,const EpochOperationAudit& a)noexcept{
  auto& x=*static_cast<DpAudit*>(p);try{x.callback|=callbackCounting;x.epochs.push_back({a.engineSerial,a.preparation,a.sequence,a.renderEpoch,a.session,a.inputGeneration,a.preparedOnly,a.workersJoined,a.callbackReleased,a.ordinarySpeeds.size()});return true;}catch(...){x.failed=true;return false;}
 }
};
constexpr std::array<const char*,12> dpChecks{
 "PAE01.Float32_mono48_300_fixture","PAE02.Ready_final_analysis","PAE03.short_Play_Pause","PAE04.Exact_C270_completed_without_audio",
 "PAE05.speed040_ready_duplicate_stationary","PAE06.speed100_ready_duplicate_stationary","PAE07.speed200_ready_duplicate_stationary",
 "PAE08.no_Resume_stationary_terminal_immutable","PAE09.Stop_all_requests_terminal","PAE10.all_epoch_joins_profiles_off",
 "PAE11.close_owned_all_IDs","PAE12.owner_heap_cost_SHA_audit"};
template<class F>void dpUntil(ProgressiveMacPlaybackEngine& e,F predicate,const char* why){
 const auto end=InitialClock::now()+std::chrono::seconds(180);
 while(!predicate()){const auto s=e.getStateSnapshot();if(s.state==State::Failed)throw std::runtime_error(s.error);require(InitialClock::now()<end,why);std::this_thread::sleep_for(std::chrono::milliseconds(2));}
}
template<class T,class F>void dpSave(const std::filesystem::path& p,const std::vector<T>& rows,F encode){std::ofstream f(p);for(const auto& o:rows)f<<encode(o)<<'\n';f.close();require(bool(f),"rows write");}
void dpFrozen(const std::vector<StoppedSpeedOperation>& rows,const std::map<std::uint64_t,std::string>& frozen){
 for(const auto& [id,value]:frozen){auto at=std::find_if(rows.begin(),rows.end(),[&](const auto& r){return r.id==id;});require(at!=rows.end()&&dpStopped(*at)==value,"terminal stopped fields changed");}
}
void dpProfilesOff(const dp58::Diagnostics& d){require(!d.workerProfileRecords&&!d.detailRecords&&!d.threadSamplingRequested&&!d.threadSamples,"detailed profile active");}
// 保存予約見積はlive量ではない。main測定外で別engineへ実予約を取り直す。
struct ReservationProbe {
 bool passed=false,ready=false,stopped=false,joined=false,retired=false,configured=false;
 bool callback=false,epochJoined=true,epochReleased=true,identities=true,cppMeasured=false;
 std::uint64_t originalSerial=0,originalGeneration=0,serial=0,generation=0,session=0;
 std::uint64_t calls=0,epochCalls=0,epochRejected=0,epochObserved=0,operationRows=0;
 std::uint64_t before=0,atReady=0,after=0,peak=0,reservationReady=0,reservationStopEstimate=0;
 std::uint64_t callbackCalls=0,firstPcm=0,missing=0,rejected=0,workerDeadlines=0,workgroupErrors=0;
 std::uint64_t checkpointStates=0,checkpointPeak=0,cppNew=0,heapAllocations=0,heapFrees=0;
 std::string error,inputSha;
 static bool final(void* p,const FinalOperationAudit& a)noexcept{
  auto& x=*static_cast<ReservationProbe*>(p);++x.calls;x.identities&=a.engineSerial==x.serial;
  x.joined=a.workersJoined;x.retired=a.retirementComplete;x.configured=a.epochAuditConfigured;
  x.epochCalls=a.epochAuditCalls;x.epochRejected=a.epochAuditRejected;x.callback|=callbackCounting;
  x.operationRows+=a.seeks.size()+a.stoppedSpeeds.size()+a.loopSpeeds.size()+a.loopPreparations.size();return true;
 }
 static bool epoch(void* p,const EpochOperationAudit& a)noexcept{
  auto& x=*static_cast<ReservationProbe*>(p);++x.epochObserved;x.callback|=callbackCounting;
  x.epochJoined&=a.workersJoined;x.epochReleased&=a.callbackReleased;
  x.identities&=a.engineSerial==x.serial&&a.inputGeneration==x.generation&&a.session==x.session;
  x.operationRows+=a.ordinarySpeeds.size();return true;
 }
};
ReservationProbe reservationProbe(const std::filesystem::path& input,const std::string& preset,
 std::uint64_t originalSerial,std::uint64_t originalGeneration,const std::string& expectedInputSha,const std::filesystem::path& out){
 ReservationProbe p;p.originalSerial=originalSerial;p.originalGeneration=originalGeneration;
 p.before=dp58::RealtimePipeline::executionOwnerCounts().alive;
 std::unique_ptr<ProgressiveMacPlaybackEngine> engine;
 try{
  require(p.before==0,"probe needs original owner0 after close");
  ProgressiveOptions o;o.preset=preset=="candidate"?Preset::Candidate:Preset::Baseline;
  o.initialSpeed=1;o.allowExperimentalLoops=true;o.seekCheckpoints=false;
  o.finalOperationAuditContext=&p;o.receiveFinalOperationAudit=ReservationProbe::final;
  o.finalEpochAuditContext=&p;o.receiveFinalEpochAudit=ReservationProbe::epoch;
  o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},
   []()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
  engine=std::make_unique<ProgressiveMacPlaybackEngine>();require(engine->prepare(input,o),"probe prepare");
  const auto deadline=InitialClock::now()+std::chrono::seconds(180);
  while(engine->getPlaybackState()!=State::Ready){
   const auto s=engine->getStateSnapshot();require(s.state!=State::Failed,s.error.c_str());
   require(InitialClock::now()<deadline,"probe Ready watchdog");std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  const auto d=engine->getPlaybackDiagnostics();p.ready=true;p.serial=d.engineSerial;
  p.generation=d.inputGeneration;p.session=d.session;p.reservationReady=d.reservationBytes;p.inputSha=d.pipeline.inputSha256;
  p.atReady=dp58::RealtimePipeline::executionOwnerCounts().alive;
  require(p.serial&&p.serial!=originalSerial&&p.generation&&p.generation!=originalGeneration&&
   p.session&&p.inputSha==expectedInputSha&&p.reservationReady>0&&p.atReady==1,"probe identity/actual reservation/one owner");
  engine->stop();p.stopped=engine->getPlaybackState()==State::Stopped;
  const auto stopped=engine->getPlaybackDiagnostics();const auto native=engine->getNativeDiagnostics();
  p.reservationStopEstimate=stopped.reservationBytes;p.callbackCalls=native.callbackCalls;p.firstPcm=native.firstPcmMachNs;
  p.missing=stopped.missingFrames;p.rejected=stopped.rejectedWrites;
  p.workerDeadlines=stopped.workerDeadlineMisses;p.workgroupErrors=stopped.workgroupErrors;
  p.checkpointStates=stopped.pipeline.loopReuse.checkpointStates;p.checkpointPeak=stopped.pipeline.loopReuse.checkpointPeak;
  p.cppMeasured=bool(stopped.callbackCppNew);if(p.cppMeasured)p.cppNew=*stopped.callbackCppNew;
  p.heapAllocations=phase61_heap_allocations();p.heapFrees=phase61_heap_frees();
  require(p.checkpointStates<=2&&p.checkpointPeak<=2,"probe checkpoint bounds");
  require(stopped.pipeline.finalDataAvailable&&!stopped.pipeline.scheduling.active&&
   stopped.pipeline.scheduling.joins==stopped.pipeline.scheduling.leaves&&
   stopped.pipeline.scheduling.leaves==stopped.pipeline.scheduling.restores,"probe joined workers");
  require(!p.callbackCalls&&!p.firstPcm&&!p.missing&&!p.rejected&&!p.workerDeadlines&&!p.workgroupErrors&&
   stopped.callbackCppNew&&!*stopped.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees(),"probe no audio/callback failures");
  engine.reset();const auto owners=dp58::RealtimePipeline::executionOwnerCounts();p.after=owners.alive;p.peak=owners.peak;
  require(p.stopped&&p.identities&&p.calls==1&&p.joined&&p.retired&&p.configured&&!p.callback&&
   p.epochCalls==p.epochObserved&&p.epochObserved==1&&!p.epochRejected&&p.epochJoined&&p.epochReleased&&
   !p.operationRows&&!p.after&&p.peak<=2,"probe own audit/owner0 after close");p.passed=true;
 }catch(const std::exception& e){p.error=e.what();if(engine){try{engine->stop();}catch(...){}engine.reset();}
  const auto owners=dp58::RealtimePipeline::executionOwnerCounts();p.after=owners.alive;p.peak=owners.peak;
 }
 std::ofstream f(out/"RESERVATION_PROBE.json");f<<std::boolalpha<<"{\"schema\":\"reservation-reacquisition-v1\",\"passed\":"<<p.passed
  <<",\"original_engine_serial\":"<<p.originalSerial<<",\"original_input_generation\":"<<p.originalGeneration
  <<",\"engine_serial\":"<<p.serial<<",\"input_generation\":"<<p.generation<<",\"session\":"<<p.session
  <<",\"owners_before\":"<<p.before<<",\"owners_at_Ready\":"<<p.atReady<<",\"owners_after\":"<<p.after<<",\"owners_peak\":"<<p.peak
  <<",\"Ready\":"<<p.ready<<",\"Stopped\":"<<p.stopped<<",\"reservation_at_Ready\":"<<p.reservationReady
  <<",\"reservation_after_Stop_estimate\":"<<p.reservationStopEstimate<<",\"final_audit_calls\":"<<p.calls
  <<",\"workers_joined\":"<<p.joined<<",\"retirement_complete\":"<<p.retired<<",\"epoch_audit_configured\":"<<p.configured
  <<",\"epoch_audit_calls\":"<<p.epochCalls<<",\"epoch_audit_observed\":"<<p.epochObserved<<",\"epoch_audit_rejected\":"<<p.epochRejected
  <<",\"epochs_joined\":"<<p.epochJoined<<",\"callbacks_released\":"<<p.epochReleased<<",\"audit_in_callback\":"<<p.callback
  <<",\"identities_match\":"<<p.identities<<",\"input_sha256\":"<<dp58::jsonString(p.inputSha)<<",\"operation_rows\":"<<p.operationRows<<",\"callback_calls\":"<<p.callbackCalls<<",\"first_PCM_ns\":"<<p.firstPcm
  <<",\"missing_frames\":"<<p.missing<<",\"rejected_writes\":"<<p.rejected<<",\"worker_deadlines\":"<<p.workerDeadlines<<",\"workgroup_errors\":"<<p.workgroupErrors
  <<",\"checkpoint_states\":"<<p.checkpointStates<<",\"checkpoint_peak\":"<<p.checkpointPeak
  <<",\"callback_cpp_measured\":"<<p.cppMeasured<<",\"callback_cpp_new\":"<<p.cppNew
  <<",\"callback_heap_allocations\":"<<p.heapAllocations<<",\"callback_heap_frees\":"<<p.heapFrees
  <<",\"same_process\":true,\"explicit_Play\":false,\"separate_sink\":true,\"primary_cost_excludes_probe\":true,\"reservation_is_live_counter\":false,\"error\":"<<dp58::jsonString(p.error)<<"}\n";
 f.close();require(bool(f),"probe evidence write");return p;
}
int dpMain(int argc,char** argv){
 require(argc==6,"INPUT PRESET NEW_OUTPUT SOURCE_SHA old|candidate");const std::filesystem::path input=argv[1],out=argv[3];const std::string preset=argv[2],source=argv[4],version=argv[5];
 require((preset=="candidate"||preset=="baseline")&&(version=="old"||version=="candidate"),"preset/version");
 require(progressive::contractVersion==(version=="old"?3u:4u),"old v3 / candidate v4 headers required");
 require(source.size()==64&&std::all_of(source.begin(),source.end(),[](unsigned char c){return std::isxdigit(c);}),"source SHA");
 require(!std::filesystem::exists(out)&&std::filesystem::create_directories(out),"fresh output required");
 dpFloat32(input);ts::WavStreamReader info(input);const auto rate=info.sampleRate();require(rate==48000&&info.channels()==1&&info.frames()==std::uint64_t(rate)*300,"actual Float32 mono48k 300s required");
 const auto inputSha=dpHash(input),binarySha=dpHash(std::filesystem::absolute(argv[0]));const auto C=std::uint64_t(rate)*270;
 DpCapture capture;DpAudit audit;std::unique_ptr<ProgressiveMacPlaybackEngine> engine;std::size_t passed=0,accepted=0,duplicates=0;std::string reason;
 std::ofstream checks(out/"checks.jsonl"),measurements(out/"measurements.jsonl");measurements<<std::setprecision(17);
 std::vector<StoppedSpeedOperation> finalStopped;std::vector<progressive::SeekOperation> finalSeeks;std::map<std::uint64_t,std::string> terminal;
 ProgressiveDiagnostics final{};ProgressiveNativeDiagnostics native{};DpClock prepBegin{},prepReady{},seekBegin{},seekReturned{},seekReady{},wholeBegin=dpClock(),wholeEnd{};bool prepCost=false,seekCost=false;
 DpClock primaryEnd{},probeBegin{},probeEnd{};bool primaryComplete=false,haveProbe=false;ReservationProbe probe;
 const auto pass=[&]{require(passed<dpChecks.size(),"extra check");checks<<"{\"id\":"<<dp58::jsonString(dpChecks[passed++])<<",\"status\":\"PASS\"}\n";checks.flush();require(bool(checks),"check write");};
 const auto writeSummary=[&](bool success){
  wholeEnd=dpClock();const auto owners=dp58::RealtimePipeline::executionOwnerCounts();std::ofstream f(out/"SUMMARY.json");f<<std::setprecision(17)
   <<"{\"schema\":\"performance-paused-deep-v1\",\"status\":"<<dp58::jsonString(success?"PASS":"FAIL")<<",\"functional\":"<<(success?"true":"false")<<",\"run_complete\":"<<(success?"true":"false")
   <<",\"expected\":12,\"executed\":"<<passed<<",\"expected_speed_requests\":3,\"accepted_speed_requests\":"<<accepted<<",\"duplicate_requests\":"<<duplicates<<",\"preset\":"<<dp58::jsonString(preset)<<",\"version\":"<<dp58::jsonString(version)<<",\"contract_version\":"<<progressive::contractVersion
   <<",\"source\":"<<dp58::jsonString(source)<<",\"input_sha256\":"<<dp58::jsonString(inputSha)<<",\"binary_sha256\":"<<dp58::jsonString(binarySha)<<",\"source_rate\":"<<rate<<",\"channels\":1,\"input_frames\":"<<info.frames()<<",\"C_input_frame\":"<<C
   <<",\"owners_alive\":"<<owners.alive<<",\"owners_peak\":"<<owners.peak<<",\"checkpoint_states\":"<<final.pipeline.checkpointResidentStates<<",\"checkpoint_peak\":"<<final.pipeline.loopReuse.checkpointPeak<<",\"reservation_bytes\":"<<final.reservationBytes<<",\"reservation_after_Stop_is_saved_estimate\":true,\"reservation_reacquired\":"<<(probe.passed?"true":"false")
   <<",\"raw_frames\":"<<capture.rawFrames.load()<<",\"raw_calls\":"<<capture.rawCalls.load()<<",\"output_frames\":"<<capture.outputFrames.load()<<",\"output_calls\":"<<capture.outputCalls.load()<<",\"nonfinite\":"<<capture.nonfinite.load()<<",\"affected_frames\":"<<capture.affected.load()
   <<",\"final_audit_calls\":"<<audit.calls<<",\"final_stopped_rows\":"<<audit.stopped.size()<<",\"final_seek_rows\":"<<audit.seeks.size()<<",\"epoch_audit_calls\":"<<audit.epochCalls<<",\"epoch_audit_rejected\":"<<audit.epochRejected
   <<",\"callback_cpp_new\":";if(final.callbackCppNew)f<<*final.callbackCppNew;else f<<"null";
  f<<",\"callback_heap_allocations\":"<<phase61_heap_allocations()<<",\"callback_heap_frees\":"<<phase61_heap_frees()<<",\"missing\":"<<final.missingFrames<<",\"rejected_writes\":"<<final.rejectedWrites<<",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"workgroup_errors\":"<<final.workgroupErrors
   <<",\"callback_deadlines\":"<<native.deadlineMisses<<",\"host_missing\":"<<native.hostMissing<<",\"host_backwards\":"<<native.hostBackwards<<",\"host_cadence\":"<<native.hostCadenceErrors<<",\"sample_errors\":"<<native.sampleErrors<<",\"hal_window_misses\":"<<native.halWindowMisses
   <<",\"device_id\":"<<native.deviceId<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames<<",\"reason\":"<<dp58::jsonString(reason)
   <<",\"control_and_worker_profile\":\"OFF\",\"stage_hash\":\"library default: v3 fixed ON, v4 default; distinct from detailed profiling\",\"seek_checkpoints\":false,\"callback_gate\":false,\"explicit_Resume\":false,\"quality_approval\":false,\"RT_deadline_approval\":false,\"physical_audio\":null,\"application_F\":null}\n";
  f.close();require(bool(f),"summary write");
  std::ofstream p(out/"PROCESS_COST.json");p<<std::setprecision(17)<<"{\"scope\":\"control host through original Stop/close and final SHA before separate reservation probe; includes polls/JSON/audit, excludes initial external file SHA\",\"whole_program\":";dpCost(p,wholeBegin,primaryComplete?primaryEnd:wholeEnd);
  p<<",\"prepare_to_final_analysis\":";if(prepCost)dpCost(p,prepBegin,prepReady);else p<<"null";
  p<<",\"initial_Exact_call\":";if(seekCost)dpCost(p,seekBegin,seekReturned);else p<<"null";
  p<<",\"initial_Exact_request_to_Completed_observed\":";if(seekCost)dpCost(p,seekBegin,seekReady);else p<<"null";
  p<<",\"reservation_reacquisition_probe\":";if(haveProbe)dpCost(p,probeBegin,probeEnd);else p<<"null";
  p<<",\"whole_program_including_probe\":";dpCost(p,wholeBegin,wholeEnd);
  p<<",\"reservation_probe_excluded_from_primary_costs\":true,\"reservation_after_Stop_is_saved_estimate\":true";
  p<<",\"thread_cpu\":\"control thread only, not worker CPU\",\"process_cpu\":\"RUSAGE_SELF user+system delta, all process threads\",\"wall\":\"steady_clock intervals; no subtraction across clocks\",\"native_Ready\":\"readyNs-acceptedNs within native Mach monotonic ns\",\"initial_Exact_is_speed_response\":false}\n";p.close();require(bool(p),"process cost write");
 };
 try{
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"checks\":[";for(std::size_t i=0;i<dpChecks.size();++i)f<<(i?",":"")<<dp58::jsonString(dpChecks[i]);
   f<<"],\"expected\":12,\"accepted_stopped_IDs\":[9223372036854775809,9223372036854775810,9223372036854775811],\"accepted_seek_IDs\":[1],\"speeds_micros\":[400000,1000000,2000000],\"duplicate_requests\":6,\"final_states\":[\"Replaced\",\"Replaced\",\"Cancelled\"],\"C_input_frame\":"<<C
    <<",\"loop_enabled\":false,\"seek_checkpoints\":false,\"analysis_final_required\":true,\"source\":"<<dp58::jsonString(source)<<",\"input_sha256\":"<<dp58::jsonString(inputSha)<<",\"binary_sha256\":"<<dp58::jsonString(binarySha)<<",\"callback_gate\":false,\"quality_approval\":false,\"RT_deadline_approval\":false}\n";require(bool(f),"expected write");}
  pass();ProgressiveOptions o;o.preset=preset=="candidate"?Preset::Candidate:Preset::Baseline;o.initialSpeed=1;o.allowExperimentalLoops=true;o.seekCheckpoints=false;o.measureControlCosts=false;o.callbackRecordLimit=256;
  o.observerContext=&capture;o.observeEpochPcm=DpCapture::raw;o.observeOutputPcm=DpCapture::output;
  o.finalOperationAuditContext=&audit;o.receiveFinalOperationAudit=DpAudit::receive;o.finalEpochAuditContext=&audit;o.receiveFinalEpochAudit=DpAudit::epoch;
  phase61_heap_reset();o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
  engine=std::make_unique<ProgressiveMacPlaybackEngine>();auto& e=*engine;prepBegin=dpClock();require(e.prepare(input,o),"prepare acceptance");
  dpUntil(e,[&]{return e.getPlaybackState()==State::Ready&&e.getPlaybackDiagnostics().pipeline.analysisDone;},"final analysis watchdog");prepReady=dpClock();prepCost=true;
  {const auto d=e.getPlaybackDiagnostics();require(d.pipeline.analysisDone&&d.pipeline.receivedInput==info.frames()&&!d.controlCostsMeasured&&d.pipeline.inputSha256==inputSha,"final analysis/config/source");dpProfilesOff(d.pipeline);}pass();
  require(e.play(),"short explicit Play");dpUntil(e,[&]{return capture.rawFrames.load()>=1024;},"initial PCM");require(e.pause()&&e.getPlaybackState()==State::Paused,"initial Pause");pass();
  const auto context=e.getStateSnapshot();seekBegin=dpClock();const auto seek=e.requestSeekToInputFrame(C,context.inputGeneration,context.renderEpoch);seekReturned=dpClock();require(seek.accepted&&seek.id==1,"initial Exact receipt");
  dpUntil(e,[&]{const auto op=e.getSeekSnapshot().latest;require(op.state!=Seek::Failed,op.reason.c_str());return op.id==seek.id&&op.state==Seek::Completed&&!e.getPlaybackDiagnostics().retiringPipeline;},"initial Exact Completed");seekReady=dpClock();seekCost=true;
  const auto exact=e.getSeekSnapshot().latest;const auto exactFrozen=dpSeek(exact);const auto generation=e.getStateSnapshot().inputGeneration;
  require(exact.mode==progressive::SeekMode::Exact&&exact.requestedInputFrame==C&&!exact.firstCallbackNs&&!exact.estimatedPresentationNs&&e.getCurrentPlaybackPosition().inputFrame==C&&e.getPlaybackState()==State::Paused,"Exact no autoplay/target");
  const auto rawFrozen=capture.rawFrames.load(),rawCallsFrozen=capture.rawCalls.load(),outputFrozen=capture.outputFrames.load(),outputCallsFrozen=capture.outputCalls.load(),presentedFrozen=e.getPlaybackDiagnostics().presentedFrames;
  const auto stationary=[&]{const auto st=e.getStateSnapshot();const auto pos=e.getCurrentPlaybackPosition();const auto loop=e.getLoopSnapshot();
   require(st.state==State::Paused&&!st.resumePending&&st.inputGeneration==generation&&pos.inputFrame==C,"C/Paused/resume changed");
   require(!loop.enabled&&!loop.cycles&&e.loopHistory().empty(),"Loop/cycle changed");
   require(capture.rawFrames==rawFrozen&&capture.rawCalls==rawCallsFrozen&&capture.outputFrames==outputFrozen&&capture.outputCalls==outputCallsFrozen&&e.getPlaybackDiagnostics().presentedFrames==presentedFrozen,"actual audio consumed while Paused");
  };stationary();dpSave(out/"initial_Exact.jsonl",std::vector<progressive::SeekOperation>{exact},dpSeek);
  {std::ofstream f(out/"initial_preparation.json");f<<std::setprecision(17)<<"{\"initial_Exact\":"<<exactFrozen<<",\"analysis_final\":true,\"C_after\":"<<C<<",\"raw_frames_before_speed\":"<<rawFrozen<<",\"presented_frames_before_speed\":"<<presentedFrozen<<",\"initial_prepare\":";dpCost(f,prepBegin,prepReady);f<<",\"initial_Exact_request_to_Completed_observed\":";dpCost(f,seekBegin,seekReady);f<<"}\n";}pass();
  constexpr std::array<std::uint32_t,3> speeds{400000,1000000,2000000};
  for(std::size_t i=0;i<speeds.size();++i){
   stationary();const auto before=e.getPlaybackDiagnostics();const auto st=e.getStateSnapshot();const auto beforePos=e.getCurrentPlaybackPosition();const auto begin=dpClock();
   const auto receipt=e.setSpeed(double(speeds[i])/1e6,st.session,st.inputGeneration,st.renderEpoch);const auto returned=dpClock();const auto expectedID=(std::uint64_t(1)<<63)|(i+1);
   require(receipt.result==DpResult::Accepted&&receipt.id==expectedID,"speed Accepted ID");++accepted;
   const auto immediateBegin=dpClock();const auto dupImmediate=e.setSpeed(double(speeds[i])/1e6);const auto immediateEnd=dpClock();require(dupImmediate.result==DpResult::Duplicate&&dupImmediate.id==receipt.id,"immediate duplicate ID");++duplicates;
   const auto immediate=e.getStateSnapshot();std::uint64_t polls=0;StoppedSpeedOperation op;
   dpUntil(e,[&]{++polls;stationary();const auto now=e.getStateSnapshot();require(now.stoppedSpeed&&now.stoppedSpeed->id==receipt.id,"stopped operation identity");op=*now.stoppedSpeed;
    require(op.state==DpState::Preparing||op.state==DpState::ReadyForResume,op.reason.c_str());const auto d=e.getPlaybackDiagnostics();if(d.renderEpoch==before.renderEpoch)require(d.consumedFrames==before.consumedFrames,"old FIFO consumed during preparation");
    return op.state==DpState::ReadyForResume&&!d.retiringPipeline;},"ReadyForResume watchdog");const auto observed=dpClock();
   const auto after=e.getPlaybackDiagnostics();const auto afterPos=e.getCurrentPlaybackPosition();const auto latest=e.getStateSnapshot();
   require(op.positionCaptured&&!op.outputStarted&&op.resumeInputFrame==C&&op.sourceSession==st.session&&op.sourceRenderEpoch==st.renderEpoch&&op.inputGeneration==generation&&op.consumedOutputFrame==before.consumedFrames,"source C/identity/capture");
   require(op.mode==progressive::SeekMode::Exact&&op.speedMicros==speeds[i]&&!op.loopID&&!op.cycle&&op.session==latest.session&&op.renderEpoch==latest.renderEpoch&&op.readyNs>=op.acceptedNs&&op.acceptedNs>0,"Ready identity/time");
   require(afterPos.inputFrame==C&&afterPos.outputFrame==op.outputStartFrame&&after.pipeline.consumed==op.outputStartFrame&&after.currentEpochPresentedFrame==op.outputStartFrame,"new epoch consumed/outputStart mismatch");
   require(after.pipeline.analysisDone&&after.pipeline.receivedInput==info.frames()&&after.pipeline.reusedAnalysis&&!after.pipeline.checkpointUsed&&!after.controlCostsMeasured,"final analysis/reuse/checkpoint/profile");dpProfilesOff(after.pipeline);
   const auto closed=e.closedEpochs();auto old=std::find_if(closed.begin(),closed.end(),[&](const auto& p){return p.renderEpoch==op.sourceRenderEpoch&&p.pipeline.session==op.sourceSession;});
   require(old!=closed.end()&&old->pipeline.finalDataAvailable&&old->pipeline.consumed==before.consumedFrames&&old->pipeline.published>=old->pipeline.consumed&&old->pipeline.published-old->pipeline.consumed==op.discardedForStoppedSpeedFrames,"discard ownership/counted as consumption");
   const auto readyJson=dpStopped(op);const auto duplicateBegin=dpClock();const auto duplicate=e.setSpeed(double(speeds[i])/1e6);const auto duplicateEnd=dpClock();
   require(duplicate.result==DpResult::Duplicate&&duplicate.id==receipt.id&&e.getStateSnapshot().stoppedSpeed&&dpStopped(*e.getStateSnapshot().stoppedSpeed)==readyJson,"Ready duplicate changed operation");++duplicates;
   const auto history=e.stoppedSpeedHistory();require(history.size()==i+1&&e.seekHistory().size()==1&&dpSeek(e.seekHistory()[0])==exactFrozen,"duplicate fabricated ID/changed terminal Exact");dpFrozen(history,terminal);
   for(const auto& past:history)if(dpTerminal(past.state))terminal.emplace(past.id,dpStopped(past));
   measurements<<"{\"ordinal\":"<<i+1<<",\"id\":"<<receipt.id<<",\"receipt_result\":\"Accepted\",\"speed_micros\":"<<speeds[i]<<",\"Ready_operation\":"<<readyJson<<",\"analysis_final_before\":"<<(before.pipeline.analysisDone?"true":"false")<<",\"analysis_final_after\":"<<(after.pipeline.analysisDone?"true":"false")
    <<",\"C_before\":"<<*beforePos.inputFrame<<",\"C_after\":"<<*afterPos.inputFrame<<",\"source_output_before\":"<<beforePos.outputFrame<<",\"new_Map_output_start\":"<<op.outputStartFrame<<",\"audio_consumed_frames_during_request\":0,\"discarded_is_not_audio_consumption\":true,\"retired_source_consumed\":"<<old->pipeline.consumed
    <<",\"retired_source_published\":"<<old->pipeline.published<<",\"discarded_for_stopped_speed_frames\":"<<op.discardedForStoppedSpeedFrames<<",\"accepted_to_Ready_native_ms\":"<<double(op.readyNs-op.acceptedNs)/1e6<<",\"request_call\":";dpCost(measurements,begin,returned);
   measurements<<",\"request_begin_to_Ready_observed\":";dpCost(measurements,begin,observed);measurements<<",\"accepted_return_to_Ready_observed\":";dpCost(measurements,returned,observed);
   measurements<<",\"immediate_duplicate_call\":";dpCost(measurements,immediateBegin,immediateEnd);measurements<<",\"Ready_duplicate_call\":";dpCost(measurements,duplicateBegin,duplicateEnd);measurements<<",\"immediate_duplicate_id\":"<<dupImmediate.id<<",\"immediate_duplicate_observed_state\":"<<(immediate.stoppedSpeed?dp58::jsonString(name(immediate.stoppedSpeed->state)):"null")
    <<",\"immediate_duplicate_result\":\"Duplicate\",\"Ready_duplicate_id\":"<<duplicate.id<<",\"Ready_duplicate_result\":\"Duplicate\",\"duplicate_creates_new_ID_or_timestamp\":false,\"polls\":"<<polls<<",\"quality_approval\":false,\"RT_deadline_approval\":false}\n";measurements.flush();require(bool(measurements),"measurement write");
   dpSave(out/("history_ready_"+std::to_string(i+1)+".jsonl"),history,dpStopped);pass();
  }
  const auto hold=InitialClock::now()+std::chrono::milliseconds(40);while(InitialClock::now()<hold){stationary();dpFrozen(e.stoppedSpeedHistory(),terminal);std::this_thread::sleep_for(std::chrono::milliseconds(2));}pass();
  e.stop();require(e.getPlaybackState()==State::Stopped,"Stop state");final=e.getPlaybackDiagnostics();native=e.getNativeDiagnostics();finalStopped=e.stoppedSpeedHistory();finalSeeks=e.seekHistory();
  require(finalStopped.size()==3&&finalStopped[0].state==DpState::Replaced&&finalStopped[1].state==DpState::Replaced&&finalStopped[2].state==DpState::Cancelled,"stopped terminal outcomes");dpFrozen(finalStopped,terminal);
  for(const auto& row:finalStopped){require(dpTerminal(row.state)&&!row.outputStarted&&row.resumeInputFrame==C,"stopped final facts");terminal[row.id]=dpStopped(row);}
  require(finalSeeks.size()==1&&dpSeek(finalSeeks[0])==exactFrozen,"Exact terminal changed");dpSave(out/"stopped_after_Stop.jsonl",finalStopped,dpStopped);dpSave(out/"seek_after_Stop.jsonl",finalSeeks,dpSeek);pass();
  std::map<std::uint64_t,dp58::Diagnostics> joined;for(const auto& p:e.closedEpochs())joined.emplace(p.pipeline.session,p.pipeline);joined.emplace(final.pipeline.session,final.pipeline);
  {std::ofstream f(out/"epochs.jsonl");f<<std::setprecision(17);for(const auto& [session,p]:joined){
   const auto& w=p.scheduling;require(p.finalDataAvailable&&!w.active&&w.joins==w.leaves&&w.leaves==w.restores,"all epoch joins");dpProfilesOff(p);
   require(p.checkpointResidentStates<=2&&p.loopReuse.checkpointPeak<=2,"all epoch checkpoint bounds");
   require(std::isfinite(p.dspWorkerCpuS)&&p.dspWorkerCpuS>=0&&std::isfinite(p.analysisWorkerCpuS)&&p.analysisWorkerCpuS>=0,"finite final worker CPU");
   f<<"{\"session\":"<<session<<",\"final_data_available\":true,\"analysis_done\":"<<(p.analysisDone?"true":"false")<<",\"received_input\":"<<p.receivedInput<<",\"output_start\":"<<p.outputStartFrame<<",\"published\":"<<p.published<<",\"consumed\":"<<p.consumed<<",\"discarded_prefix\":"<<p.discardedFrames
    <<",\"dsp_worker_cpu_s\":"<<p.dspWorkerCpuS<<",\"analysis_worker_cpu_s\":"<<p.analysisWorkerCpuS<<",\"analysis_worker_CPU_scope\":\"library diagnostic semantics; v4 shared producer is separate\",\"worker_profile_records\":"<<p.workerProfileRecords<<",\"detail_records\":"<<p.detailRecords<<",\"thread_sampling\":false,\"checkpoint_used\":"<<(p.checkpointUsed?"true":"false")<<",\"checkpoint_states\":"<<p.checkpointResidentStates<<",\"checkpoint_peak\":"<<p.loopReuse.checkpointPeak<<"}\n";
  }f.close();require(bool(f),"epoch cost write");}require(joined.size()>=5,"epoch audit coverage");pass();
  const auto serial=final.engineSerial,preparation=final.preparation;engine.reset();
  require(audit.calls==1&&!audit.failed&&!audit.callback&&audit.joined&&audit.retired&&audit.serial==serial&&audit.preparation==preparation&&audit.configured&&!audit.epochRejected&&audit.epochCalls==audit.epochs.size(),"final owned audit delivery/join");
  require(audit.stopped.size()==3&&audit.seeks.size()==1&&!audit.loops&&!audit.preparations,"final Accepted ID count");dpFrozen(audit.stopped,terminal);require(dpSeek(audit.seeks[0])==exactFrozen,"owned Exact changed");
  dpSave(out/"close_owned_stopped.jsonl",audit.stopped,dpStopped);dpSave(out/"close_owned_seek.jsonl",audit.seeks,dpSeek);
  {std::set<std::uint64_t> sequences;std::ofstream f(out/"close_owned_epochs.jsonl");for(const auto& p:audit.epochs){require(p.joined&&p.released&&!p.speeds&&p.engine==serial&&p.preparation==preparation&&sequences.insert(p.sequence).second,"epoch audit ownership/duplicate");
   f<<"{\"engine_serial\":"<<p.engine<<",\"preparation\":"<<p.preparation<<",\"sequence\":"<<p.sequence<<",\"epoch\":"<<p.epoch<<",\"session\":"<<p.session<<",\"input_generation\":"<<p.generation<<",\"prepared_only\":"<<(p.prepared?"true":"false")<<",\"workers_joined\":true,\"callback_released\":true,\"ordinary_speed_rows\":0}\n";}
   require(audit.epochs.size()>=5,"all epoch audit count");f.close();require(bool(f),"epoch owned write");}pass();
  const auto owners=dp58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2&&final.pipeline.checkpointResidentStates<=2&&final.pipeline.loopReuse.checkpointPeak<=2,"owner/reservation/checkpoint bounds");
  require(!capture.nonfinite&&!capture.affected&&capture.rawFrames==rawFrozen&&capture.outputFrames==outputFrozen&&!final.missingFrames&&!final.underrunCalls&&!final.rejectedWrites&&final.callbackCppNew&&!*final.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees(),"callback/actual consumption/heap audit");
  require(dpHash(input)==inputSha&&dpHash(std::filesystem::absolute(argv[0]))==binarySha,"input/binary changed");
  primaryEnd=dpClock();primaryComplete=true;probeBegin=primaryEnd;
  probe=reservationProbe(input,preset,serial,generation,inputSha,out);probeEnd=dpClock();haveProbe=true;
  require(probe.passed,probe.error.c_str());require(audit.calls==1&&audit.serial==serial&&audit.stopped.size()==3&&audit.seeks.size()==1,"probe polluted original audit");
  pass();require(passed==dpChecks.size(),"fixed check set");writeSummary(true);
  checks.close();measurements.close();require(bool(checks)&&bool(measurements),"evidence close");
  {std::vector<std::filesystem::path> paths;for(const auto& p:std::filesystem::directory_iterator(out))if(p.is_regular_file()&&p.path().filename()!="ARTIFACTS.json")paths.push_back(p.path());std::sort(paths.begin(),paths.end());
   std::ofstream f(out/"ARTIFACTS.json");f<<"{\"files\":[";for(std::size_t i=0;i<paths.size();++i)f<<(i?",":"")<<"{\"path\":"<<dp58::jsonString(paths[i].filename().string())<<",\"bytes\":"<<std::filesystem::file_size(paths[i])<<",\"sha256\":"<<dp58::jsonString(dpHash(paths[i]))<<'}';f<<"]}\n";f.close();require(bool(f),"artifacts write");}return 0;
 }catch(const std::exception& error){reason=error.what();if(engine){try{engine->stop();final=engine->getPlaybackDiagnostics();native=engine->getNativeDiagnostics();}catch(...){}engine.reset();}
  try{dpSave(out/"close_owned_stopped.jsonl",audit.stopped,dpStopped);dpSave(out/"close_owned_seek.jsonl",audit.seeks,dpSeek);writeSummary(false);}catch(...){}std::cerr<<reason<<'\n';return 1;}
}
}
int main(int argc,char** argv){int code=1;std::thread control([&]{try{code=dpMain(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});control.join();return code;}
