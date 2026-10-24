// D3: 固定済み製品/既存helperへ単独compileする通常制御client。
// src/tests inventoryは変更しない。旧版も同一source、旧header/旧archive。
// INPUT PRESET HISTORY_N SECONDS NEW_OUTPUT SOURCE_SHA old|candidate
#define main d3IncludedLimitMain
#include "ProgressiveAdoptionLimitNative.cpp"
#undef main
#include "Phase61CallbackMallocProbe.h"
#include <sys/resource.h>
#include <libproc.h>
#ifndef TS_SEEK_HISTORY_LATCH_DIAGNOSTICS
#define TS_SEEK_HISTORY_LATCH_DIAGNOSTICS 0
#endif

namespace {
struct HistoryCpu {double wall=0,cpu=0;std::uint64_t wakeups=0;};
HistoryCpu historyCpu(){
 rusage u{};require(!getrusage(RUSAGE_SELF,&u),"history rusage");rusage_info_v4 p{};
 require(!proc_pid_rusage(getpid(),RUSAGE_INFO_V4,reinterpret_cast<rusage_info_t*>(&p)),"history wakeups");
 return {std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count(),
  u.ru_utime.tv_sec+u.ru_utime.tv_usec*1e-6+u.ru_stime.tv_sec+u.ru_stime.tv_usec*1e-6,p.ri_interrupt_wkups};
}
std::string historyTiming(const ProgressiveDiagnostics& d){
#if TS_SEEK_HISTORY_LATCH_DIAGNOSTICS
 return "{\"visits\":"+std::to_string(d.seekTimingVisits)+",\"latches\":"+std::to_string(d.seekTimingLatches)+"}";
#else
 (void)d;return "null";
#endif
}
constexpr std::array<const char*,10> historyChecks{
 "D3H01_empty_Ready_fixture","D3H02_N_Rejected_rows_stationary",
 "D3H03_explicit_Play_original_target","D3H04_Accepted_exact_ID_N_plus_1",
 "D3H05_first_callback_latch_and_target_identity","D3H06_CPU_window_latch_stops",
 "D3H07_Pause_C_stationary_terminal_immutable","D3H08_Stop_all_terminal_immutable",
 "D3H09_close_owned_all_IDs","D3H10_final_owner_checkpoint_heap_bounds"};

int historyMain(int argc,char** argv){
 require(argc==8,"INPUT PRESET HISTORY_N SECONDS NEW_OUTPUT SOURCE_SHA old|candidate");
 const std::filesystem::path input=argv[1],out=argv[5];const std::string preset=argv[2],version=argv[7];
 const auto count=std::stoull(argv[3]);const auto seconds=std::stod(argv[4]);
 require(preset=="candidate"||preset=="baseline","preset");require(version=="old"||version=="candidate","version");
 require(count==0||count==1||count==100||count==1000||count==4095,"fixed history stratum");
 require(std::isfinite(seconds)&&seconds>=5&&seconds<=30,"CPU window 5..30 seconds");
 require(!std::filesystem::exists(out)&&std::filesystem::create_directories(out),"fresh evidence required");
 limitFloat32(input);ts::WavStreamReader wav(input);const auto rate=wav.sampleRate();
 require((rate==44100||rate==48000)&&wav.frames()>std::uint64_t((seconds+6)*rate),"input too short for uninterrupted CPU window");
 LimitOwnedAudit audit;std::unique_ptr<ProgressiveMacPlaybackEngine> engine;
 std::ofstream checks(out/"checks.jsonl");std::size_t done=0;
 ProgressiveDiagnostics beforeWindow{},afterWindow{},final{};ProgressiveNativeDiagnostics native{};
 HistoryCpu begin{},end{};std::uint64_t polls=0;bool rt=false;std::string reason;
 const auto pass=[&]{require(done<historyChecks.size(),"extra history check");checks<<"{\"id\":"<<limit58::jsonString(historyChecks[done++])<<",\"status\":\"PASS\"}\n";checks.flush();require(bool(checks),"checks write");};
 const auto writeSummary=[&](bool functional){
  const auto owners=limit58::RealtimePipeline::executionOwnerCounts();std::ofstream f(out/"SUMMARY.json");
  const auto wall=end.wall-begin.wall,cpu=end.cpu-begin.cpu;
  f<<std::setprecision(15)<<"{\"schema\":1,\"functional\":"<<(functional?"true":"false")<<",\"complete\":"<<(functional?"true":"false")
   <<",\"expected\":10,\"executed\":"<<done<<",\"rt_pass\":"<<(rt?"true":"false")<<",\"history_N\":"<<count<<",\"accepted_id\":"<<count+1
   <<",\"preset\":"<<limit58::jsonString(preset)<<",\"version\":"<<limit58::jsonString(version)<<",\"source\":"<<limit58::jsonString(argv[6])
   <<",\"input_sha256\":"<<limit58::jsonString(limitHash(input))<<",\"binary_sha256\":"<<limit58::jsonString(limitHash(argv[0]))
   <<",\"cpu_s\":"<<cpu<<",\"wall_s\":"<<wall<<",\"cpu_percent\":"<<(wall>0?100*cpu/wall:0)
   <<",\"interrupt_wakeups\":"<<(end.wakeups>=begin.wakeups?end.wakeups-begin.wakeups:0)<<",\"polls\":"<<polls
   <<",\"timing_before\":"<<historyTiming(beforeWindow)<<",\"timing_after\":"<<historyTiming(afterWindow)
   <<",\"timing_diagnostics_compiled\":"<<(TS_SEEK_HISTORY_LATCH_DIAGNOSTICS?"true":"false")
   <<",\"source_rate\":"<<rate<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames
   <<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak<<",\"checkpoint_peak\":"<<afterWindow.pipeline.loopReuse.checkpointPeak
   <<",\"final_audit_rows\":"<<audit.rows.size()<<",\"worker_deadlines\":"<<final.workerDeadlineMisses
   <<",\"callback_deadlines\":"<<native.deadlineMisses<<",\"missing\":"<<final.missingFrames<<",\"rejected_writes\":"<<final.rejectedWrites
   <<",\"callback_cpp_new\":"<<final.callbackCppNew.value_or(UINT64_MAX)<<",\"callback_heap_allocations\":"<<phase61_heap_allocations()
   <<",\"callback_heap_frees\":"<<phase61_heap_frees()<<",\"reason\":"<<limit58::jsonString(reason)
   <<",\"cpu_formula\":\"100*(RUSAGE_SELF user+system delta)/steady_clock wall delta; 1 core=100%\",\"quality_approval\":false,\"physical_audio\":null,\"application_F\":null}\n";
  f.close();require(bool(f),"summary write");
 };
 try{
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"expected\":10,\"required_ids\":[";for(std::size_t i=0;i<historyChecks.size();++i)f<<(i?",":"")<<limit58::jsonString(historyChecks[i]);
   f<<"],\"history_N\":"<<count<<",\"rejected_IDs\":\"1..N\",\"Accepted_ID\":"<<count+1<<",\"real_lifetime_limit\":4096,\"expected_final_audit_rows\":"<<count+1
    <<",\"loop_enabled\":false,\"callback_gate\":false,\"cpu_window_min_s\":5,\"history_copy_in_cpu_window\":false,\"quality_approval\":false}\n";}
  ProgressiveOptions options;options.preset=preset=="candidate"?Preset::Candidate:Preset::Baseline;options.initialSpeed=1;
  options.allowExperimentalLoops=true;options.seekCheckpoints=false;options.callbackRecordLimit=256;
  options.finalOperationAuditContext=&audit;options.receiveFinalOperationAudit=LimitOwnedAudit::receive;
  phase61_heap_reset();options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
  engine=std::make_unique<ProgressiveMacPlaybackEngine>();auto& e=*engine;limitPrepare(e,input,options);
  const auto initial=limitObserve(e);require(e.seekHistory().empty(),"initial history not empty");pass();
  for(std::uint64_t id=1;id<=count;++id){const auto r=e.requestSeekToInputFrame(wav.frames()+1,initial.state.inputGeneration,initial.state.renderEpoch);
   require(!r.accepted&&r.id==id&&r.code==LimitReason::InvalidRange,"Rejected IDs/causes");}
  const auto rejected=e.seekHistory();require(rejected.size()==count,"Rejected count");
  for(const auto& row:rejected)require(row.state==Seek::Rejected&&row.code==LimitReason::InvalidRange,"Rejected terminal facts");
  const auto frozenRejected=limitFreeze(rejected);limitSaveRows(out/"before_rejected.jsonl",frozenRejected);limitStationary(e,initial);pass();
  require(e.play(),"explicit original Play");firstPcm(e);require(e.getPlaybackState()==State::Playing,"original did not start");
#if TS_SEEK_HISTORY_LATCH_DIAGNOSTICS
  {const auto d=e.getPlaybackDiagnostics();require(!d.seekTimingVisits&&!d.seekTimingLatches,"original no-seek target visited history");}
#endif
  pass();
  const auto c=e.getStateSnapshot();const auto receipt=e.requestSeekToInputFrame(rate*2,c.inputGeneration,c.renderEpoch);
  require(receipt.accepted&&receipt.id==count+1&&receipt.code==LimitReason::Available,"valid Exact ID/count");
  limitUntil(e,[&]{const auto s=e.getSeekSnapshot().latest;require(s.state!=Seek::Failed,"Exact failed");return s.id==receipt.id&&s.state==Seek::Completed&&!e.getPlaybackDiagnostics().retiringPipeline;},"Exact Completed/join");
  require(e.getPlaybackState()==State::Playing,"Playing Exact did not continue");pass();
  limitUntil(e,[&]{const auto s=e.getSeekSnapshot().latest;return s.id==receipt.id&&s.firstCallbackNs&&s.estimatedPresentationNs;},"first callback/presentation latch");
  const auto completed=e.getSeekSnapshot().latest;const auto current=e.getStateSnapshot();
  require(completed.mode==progressive::SeekMode::Exact&&completed.state==Seek::Completed&&completed.requestedInputFrame==rate*2&&completed.inputGeneration==c.inputGeneration&&completed.renderEpoch==current.renderEpoch&&completed.session==current.session&&completed.renderEpoch!=c.renderEpoch,"adopted target identity");
  const auto frozen=limitFreeze(e.seekHistory());require(frozen.size()==count+1,"all IDs after Accepted");
  for(std::size_t i=0;i<count;++i)require(frozen[i]==frozenRejected[i],"past mutated during adoption");limitSaveRows(out/"after_first_callback.jsonl",frozen);
  beforeWindow=e.getPlaybackDiagnostics();
#if TS_SEEK_HISTORY_LATCH_DIAGNOSTICS
  require(beforeWindow.seekTimingVisits>=1&&beforeWindow.seekTimingLatches==1,"target timing not latched exactly once");
#endif
  pass();
  // 履歴全量のquery/JSON化を測定窓へ入れず、実アプリ同様の位置照会だけを固定周期で行う。
  begin=historyCpu();const auto until=std::chrono::steady_clock::now()+std::chrono::duration<double>(seconds);
  while(std::chrono::steady_clock::now()<until){require(e.getStateSnapshot().state==State::Playing,"CPU window left Playing");(void)e.getCurrentPlaybackPosition();++polls;std::this_thread::sleep_for(std::chrono::milliseconds(200));}
  end=historyCpu();afterWindow=e.getPlaybackDiagnostics();require(end.wall-begin.wall>=seconds&&polls>=std::uint64_t(seconds*4),"CPU finite window");
#if TS_SEEK_HISTORY_LATCH_DIAGNOSTICS
  require(afterWindow.seekTimingVisits==beforeWindow.seekTimingVisits&&afterWindow.seekTimingLatches==beforeWindow.seekTimingLatches,"latched target was revisited");
#endif
  pass();
  require(e.pause(),"explicit Pause");const auto paused=e.getCurrentPlaybackPosition();std::this_thread::sleep_for(std::chrono::milliseconds(80));
  require(e.getPlaybackState()==State::Paused&&e.getCurrentPlaybackPosition().outputFrame==paused.outputFrame&&e.getCurrentPlaybackPosition().inputFrame==paused.inputFrame,"Pause consumed C");
  limitRowsEqual(e.seekHistory(),frozen);pass();
  e.stop();require(e.getPlaybackState()==State::Stopped,"explicit Stop");limitRowsEqual(e.seekHistory(),frozen);
  final=e.getPlaybackDiagnostics();native=e.getNativeDiagnostics();const auto serial=final.engineSerial,preparation=final.preparation;pass();
  engine.reset();audit.validate(serial,preparation,frozen);audit.save(out/"close_owned.jsonl");pass();
  const auto owners=limit58::RealtimePipeline::executionOwnerCounts();
  require(!owners.alive&&owners.peak<=2&&afterWindow.pipeline.checkpointResidentStates<=2&&afterWindow.pipeline.loopReuse.checkpointPeak<=2,"owner/checkpoint bound");
  require(!final.missingFrames&&!final.rejectedWrites&&!final.underrunCalls&&!final.workerNewCalls&&!phase61_heap_allocations()&&!phase61_heap_frees()&&final.callbackCppNew&&!*final.callbackCppNew,"supply/heap audit");
  rt=!final.workerDeadlineMisses&&!final.workgroupErrors&&!native.deadlineMisses&&!native.hostMissing&&!native.hostBackwards&&!native.hostCadenceErrors&&!native.sampleErrors&&!native.halWindowMisses;
  pass();require(done==historyChecks.size(),"fixed check set incomplete");writeSummary(true);return rt?0:2;
 }catch(const std::exception& error){
  reason=error.what();if(engine){engine->stop();final=engine->getPlaybackDiagnostics();native=engine->getNativeDiagnostics();engine.reset();}
  try{audit.save(out/"close_owned.jsonl");writeSummary(false);}catch(...){}std::cerr<<reason<<'\n';return 1;
 }
}
}
int main(int argc,char** argv){int code=1;std::thread control([&]{try{code=historyMain(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});control.join();return code;}
