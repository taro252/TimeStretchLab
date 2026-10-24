// D3専用: INPUT PRESET SECONDS(20) NEW_OUTPUT SOURCE_SHA old|candidate
// 同じ本文を対応する旧/新headers/libsへ単独compileする。CMake/製品は変更しない。
// 正常SwitchPublished hookと公開B延期/座標/未開始の事実からRequested待機を検査。
// private handoff.phaseを直接読む診断ではない。callback gate/追加ログ/音声合格なし。
#define main armedIncludedLimitMain
#include "ProgressiveAdoptionLimitNative.cpp"
#undef main
#include "Phase61CallbackMallocProbe.h"
#include <mach/mach.h>
#include <pthread.h>
#include <libproc.h>
#include <sys/resource.h>

namespace {
constexpr std::array<const char*,8> armedIds{
 "D3A01_chain300_final_Ready", "D3A02_first_A_PCM_and_old_join",
 "D3A03_accepted_075_identity", "D3A04_fixed_B_Armed_precondition",
 "D3A05_full_20s_Armed_CPU_window", "D3A06_B_adopts_075_PCM_and_old_join",
 "D3A07_Stop_terminal_and_owner_release", "D3A08_callback_allocation_and_supply"};
constexpr const char* chainSha="13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0";

double armedWall(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
struct ArmedProcess {double wall=0,cpu=0;std::uint64_t wakeups=0;};
ArmedProcess armedProcess(){
 rusage usage{};rusage_info_v4 info{};require(!getrusage(RUSAGE_SELF,&usage),"process rusage");
 require(!proc_pid_rusage(getpid(),RUSAGE_INFO_V4,reinterpret_cast<rusage_info_t*>(&info)),"process interrupt wakeups");
 return {armedWall(),usage.ru_utime.tv_sec+usage.ru_utime.tv_usec*1e-6+usage.ru_stime.tv_sec+usage.ru_stime.tv_usec*1e-6,info.ri_interrupt_wkups};
}
double armedThreadCpu(mach_port_t port){
 require(port!=MACH_PORT_NULL,"seek thread port unavailable");thread_basic_info_data_t info{};mach_msg_type_number_t count=THREAD_BASIC_INFO_COUNT;
 require(thread_info(port,THREAD_BASIC_INFO,reinterpret_cast<thread_info_t>(&info),&count)==KERN_SUCCESS,"seek thread CPU query failed");
 return info.user_time.seconds+info.user_time.microseconds*1e-6+info.system_time.seconds+info.system_time.microseconds*1e-6;
}
struct ArmedHook {
 std::atomic<std::uint64_t> published{0},started{0},threadID{0};std::atomic<mach_port_t> port{MACH_PORT_NULL};
 static void event(void* context,ProgressiveControlTestPoint point)noexcept{
  auto& h=*static_cast<ArmedHook*>(context);
  if(point==ProgressiveControlTestPoint::SwitchPublished){std::uint64_t tid=0;pthread_threadid_np(nullptr,&tid);
   h.threadID.store(tid,std::memory_order_relaxed);h.port.store(pthread_mach_thread_np(pthread_self()),std::memory_order_release);h.published.fetch_add(1,std::memory_order_release);}
  if(point==ProgressiveControlTestPoint::SwitchStartedOrDone)h.started.fetch_add(1,std::memory_order_release);
 }
};
struct ArmedPcm {
 struct Slot {std::atomic<std::uint64_t> session{0},frames{0},end{0};};
 std::array<Slot,8> slots;std::atomic<std::uint64_t> errors{0},nonfinite{0};std::size_t channels=0;
 static void receive(void* context,const float*const* p,std::size_t n,std::size_t at,
                     std::uint64_t,std::uint64_t,std::uint64_t session)noexcept{
  auto& s=*static_cast<ArmedPcm*>(context);Slot* slot=nullptr;
  for(auto& item:s.slots)if(item.session.load(std::memory_order_relaxed)==session){slot=&item;break;}
  if(!slot)for(auto& item:s.slots)if(!item.session.load(std::memory_order_relaxed)){item.session.store(session,std::memory_order_release);slot=&item;break;}
  if(!slot||!session){++s.errors;return;}
  bool bad=false;for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<s.channels;++c)bad|=!std::isfinite(p[c][i]);
  if(bad)++s.nonfinite;slot->frames.fetch_add(n,std::memory_order_relaxed);slot->end.store(at+n,std::memory_order_release);
 }
 std::uint64_t frames(std::uint64_t session)const{for(const auto& slot:slots)if(slot.session.load(std::memory_order_acquire)==session)return slot.frames.load();return 0;}
};
progressive::LoopSpeedOperation armedSpeed(ProgressiveMacPlaybackEngine& e,std::uint64_t id){
 for(const auto& op:e.loopSpeedHistory())if(op.id==id)return op;throw std::runtime_error("speed ID absent");
}
template<class Predicate>void armedUntil(ProgressiveMacPlaybackEngine& e,Predicate predicate,const char* why,double seconds=15){
 const auto deadline=armedWall()+seconds;
 while(!predicate()){if(e.getPlaybackState()==State::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);
  require(armedWall()<deadline,why);std::this_thread::sleep_for(std::chrono::milliseconds(2));}
}

int armedMain(int argc,char** argv){
 require(argc==7,"INPUT PRESET SECONDS(20) NEW_OUTPUT SOURCE_SHA old|candidate");
 const std::filesystem::path input=std::filesystem::absolute(argv[1]),out=std::filesystem::absolute(argv[4]);
 const std::string presetName=argv[2],source=argv[5],version=argv[6];const auto seconds=std::stod(argv[3]);
 require(presetName=="candidate"||presetName=="baseline","preset");require(version=="old"||version=="candidate","version");
 require(std::isfinite(seconds)&&seconds==20,"fixed full 20 second measurement required");
 require(source.size()==64&&source.find_first_not_of("0123456789abcdef")==std::string::npos,"source SHA");
 require(!std::filesystem::exists(out)&&std::filesystem::create_directories(out),"new output directory required");
 ArmedHook hook;ArmedPcm pcm;std::unique_ptr<ProgressiveMacPlaybackEngine> engine;
 std::ofstream checks(out/"checks.jsonl"),observations(out/"observations.jsonl");
 std::size_t executed=0,polls=0;bool exercised=false,rt=false,complete=false;std::string reason;
 std::uint64_t loopID=0,speedID=0,session=0,cycle=0,publishedBase=0,startedBase=0,framesBefore=0;
 ArmedProcess begin{},end{};double seekBegin=0,seekEnd=0;ProgressiveDiagnostics final{};ProgressiveNativeDiagnostics native{};
 const auto pass=[&]{require(executed<armedIds.size(),"extra Armed check");checks<<"{\"id\":"<<limit58::jsonString(armedIds[executed++])<<",\"status\":\"PASS\"}\n";checks.flush();require(bool(checks),"checks write");};
 try{
  limitFloat32(input);const ts::WavStreamReader wav(input);const auto rate=wav.sampleRate();pcm.channels=wav.channels();
  require(rate==48000&&wav.channels()==1&&wav.frames()==300ULL*rate&&limitHash(input)==chainSha,"exact chain300 48k mono Float32 fixture required");
  const auto b=std::uint64_t(rate)*30;
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"schema\":1,\"suite\":\"D3_scheduled_boundary_Armed\",\"expected\":8,\"required_ids\":[";
   for(std::size_t i=0;i<armedIds.size();++i)f<<(i?",":"")<<limit58::jsonString(armedIds[i]);
   f<<"],\"input_sha256\":"<<limit58::jsonString(chainSha)<<",\"binary_sha256\":"<<limit58::jsonString(limitHash(std::filesystem::absolute(argv[0])))
    <<",\"source\":"<<limit58::jsonString(source)<<",\"version\":"<<limit58::jsonString(version)<<",\"preset\":"<<limit58::jsonString(presetName)
    <<",\"contract_version\":"<<progressive::contractVersion<<",\"A\":0,\"B\":"<<b<<",\"initial_speed\":1,\"target_speed\":0.75,\"CPU_window_s\":20"
    <<",\"callback_gate\":false,\"normal_hook_blocks\":false,\"history_copy_in_CPU_window\":false,\"direct_private_phase_read\":false"
    <<",\"required_state_evidence\":\"SwitchPublished normal hook + Armed + ProtectedFrontier fixed B + unchanged cycle/session/speed + B ahead; source-path inference, no private phase counter\""
    <<",\"CPU_formula\":\"seek: Mach THREAD_BASIC_INFO user+system delta; process: RUSAGE_SELF delta; 1 core=100%; steady_clock wall\""
    <<",\"independent_PCM\":\"NOT_RUN\",\"RT_approval\":false,\"physical_audio\":null,\"application_F\":null}\n";
   f.close();require(bool(f),"expected write");}
  ProgressiveOptions options;options.preset=presetName=="candidate"?Preset::Candidate:Preset::Baseline;options.initialSpeed=1;
  options.allowExperimentalLoops=true;options.seekCheckpoints=false;options.callbackRecordLimit=256;
  options.controlTestHooks={&hook,ArmedHook::event};options.observerContext=&pcm;options.observeEpochPcm=ArmedPcm::receive;
  phase61_heap_reset();options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},
   []()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
  engine=std::make_unique<ProgressiveMacPlaybackEngine>();auto& e=*engine;limitPrepare(e,input,options);pass();
  const auto initial=e.getStateSnapshot();require(e.play(),"explicit initial Play");firstPcm(e);
  const auto context=e.getStateSnapshot();const auto loop=e.requestLoopRange(0,b,{context.inputGeneration,context.session,context.renderEpoch});
  require(loop.accepted,"30 second Loop rejected");loopID=loop.id;
  armedUntil(e,[&]{const auto s=e.getStateSnapshot();const auto d=e.getPlaybackDiagnostics();const auto l=e.getLoopSnapshot();
   return l.id==loopID&&l.initialPositionComplete&&s.session!=initial.session&&!d.retiringPipeline&&pcm.frames(s.session)>0;},"first A PCM/old join",40);
  require(e.getLoopSnapshot().cycles==0&&e.getLoopSnapshot().periodFrames==b,"first Loop period/cycle");pass();
  publishedBase=hook.published.load(std::memory_order_acquire);startedBase=hook.started.load(std::memory_order_acquire);
  const auto current=e.getStateSnapshot();const auto speed=e.requestLoopSpeed(.75,{current.inputGeneration,current.session,current.renderEpoch});
  require(speed.accepted&&!speed.duplicate&&speed.id,"0.75 request rejected/duplicate");speedID=speed.id;pass();
  armedUntil(e,[&]{const auto l=e.getLoopSnapshot();const auto op=armedSpeed(e,speedID);
   require(op.state!=progressive::LoopSpeedState::Failed&&op.state!=progressive::LoopSpeedState::Cancelled,"0.75 preparation failed/cancelled");
   return hook.published.load(std::memory_order_acquire)==publishedBase+1&&l.state==progressive::LoopState::Armed&&
    op.state==progressive::LoopSpeedState::FixedBoundaryCommitted&&op.fixedBoundaryCommitted&&op.deferral==progressive::LoopSpeedDeferral::ProtectedFrontier&&
    !op.committed&&!op.outputStarted;},"NOT_EXERCISED: no protected fixed-B Armed wait",10);
  const auto armedState=e.getStateSnapshot();const auto armedLoop=e.getLoopSnapshot();session=armedState.session;cycle=armedLoop.cycles;
  require(armedState.state==State::Playing&&armedLoop.appliedSpeed==1&&armedLoop.requestedSpeed==.75&&
   hook.started.load(std::memory_order_acquire)==startedBase,"Armed already started/changed output");
  const auto position=e.getCurrentPlaybackPosition();require(position.outputFrame+std::uint64_t((seconds+1)*rate)<b,"NOT_EXERCISED: full CPU window lacks B margin");
  framesBefore=pcm.frames(session);require(hook.port.load(std::memory_order_acquire)!=MACH_PORT_NULL&&hook.threadID.load(),"seek hook did not record its live thread");pass();
  begin=armedProcess();seekBegin=armedThreadCpu(hook.port.load(std::memory_order_acquire));
  while(armedWall()-begin.wall<seconds){
   std::this_thread::sleep_for(std::chrono::milliseconds(200));++polls;
   const auto s=e.getStateSnapshot();const auto l=e.getLoopSnapshot();
   require(s.state==State::Playing&&s.session==session&&l.id==loopID&&l.enabled&&!l.clearPending&&l.cycles==cycle&&
    l.state==progressive::LoopState::Armed&&l.appliedSpeed==1&&l.requestedSpeed==.75&&
    hook.published.load(std::memory_order_acquire)==publishedBase+1&&hook.started.load(std::memory_order_acquire)==startedBase,
    "Armed CPU window changed state/phase evidence");
   require(!pcm.errors.load()&&!pcm.nonfinite.load(),"observer nonfinite/overflow");
  }
  seekEnd=armedThreadCpu(hook.port.load(std::memory_order_acquire));end=armedProcess();
  require(std::isfinite(seekEnd-seekBegin)&&seekEnd>=seekBegin&&end.cpu>=begin.cpu&&end.wall-begin.wall>=seconds&&
   end.wall-begin.wall<=seconds+.5&&end.wakeups>=begin.wakeups&&pcm.frames(session)>framesBefore,"invalid/incomplete CPU window or no actual old PCM");
  exercised=true;pass();
  const auto afterWindow=e.getLoopSnapshot();observations<<"{\"record\":\"window_end\",\"loop_id\":"<<loopID<<",\"speed_id\":"<<speedID
   <<",\"old_session\":"<<session<<",\"cycle\":"<<cycle<<",\"published_hook\":"<<hook.published.load()<<",\"start_hook\":"<<hook.started.load()
   <<",\"defer_reason\":"<<limit58::jsonString(afterWindow.speedDeferReason)<<",\"old_RAW_frames_during_window\":"<<pcm.frames(session)-framesBefore<<"}\n";
  armedUntil(e,[&]{const auto s=e.getStateSnapshot();const auto l=e.getLoopSnapshot();const auto d=e.getPlaybackDiagnostics();const auto op=armedSpeed(e,speedID);
   return op.state==progressive::LoopSpeedState::Completed&&op.outputStarted&&l.cycles==cycle+1&&l.appliedSpeed==.75&&
    s.session!=session&&pcm.frames(s.session)>0&&!d.retiringPipeline;},"fixed B did not adopt actual 0.75 PCM/retire old",15);pass();
  const auto boundaries=e.loopHistory();require(boundaries.size()==cycle+1&&boundaries.back().oldOutputEnd==b,"fixed B coordinates");
  const auto completed=armedSpeed(e,speedID);e.stop();final=e.getPlaybackDiagnostics();native=e.getNativeDiagnostics();
  const auto stopped=armedSpeed(e,speedID);require(stopped.state==completed.state&&stopped.terminalNs==completed.terminalNs&&
   stopped.outputStarted&&stopped.completedNs==completed.completedNs,"Stop changed completed request facts");
  engine.reset();const auto owners=limit58::RealtimePipeline::executionOwnerCounts();require(!owners.alive&&owners.peak<=2,"owner release/2-owner bound");pass();
  require(!pcm.errors.load()&&!pcm.nonfinite.load()&&!final.missingFrames&&!final.rejectedWrites&&!final.underrunCalls&&
   !final.workerNewCalls&&final.callbackCppNew&&!*final.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees()&&
   final.pipeline.loopReuse.checkpointPeak<=2,"supply/callback allocation/checkpoint bound");pass();
  rt=!final.workerDeadlineMisses&&!native.deadlineMisses&&!native.sampleErrors&&!native.hostMissing&&!native.hostBackwards&&
     !native.hostCadenceErrors&&!native.halWindowMisses&&!final.workgroupErrors;complete=true;
 }catch(const std::exception& error){reason=error.what();if(engine){try{engine->stop();final=engine->getPlaybackDiagnostics();native=engine->getNativeDiagnostics();}catch(...){}engine.reset();}}
 const auto wall=end.wall-begin.wall,cpu=end.cpu-begin.cpu,seek=seekEnd-seekBegin;const auto owners=limit58::RealtimePipeline::executionOwnerCounts();
 std::ofstream summary(out/"SUMMARY.json");summary<<std::setprecision(15)<<"{\"schema\":1,\"status\":\""<<(complete?"PASS":"INCOMPLETE_OR_FAIL")<<"\",\"run_complete\":"<<(complete?"true":"false")
  <<",\"expected\":8,\"executed\":"<<executed<<",\"Armed_exercised\":"<<(exercised?"true":"false")<<",\"rt_pass\":"<<(rt?"true":"false")
  <<",\"source\":"<<limit58::jsonString(source)<<",\"version\":"<<limit58::jsonString(version)<<",\"preset\":"<<limit58::jsonString(presetName)
  <<",\"window_wall_s\":"<<wall<<",\"seek_thread_cpu_s\":"<<seek<<",\"seek_thread_cpu_percent\":"<<(wall>0?100*seek/wall:0)
  <<",\"process_cpu_s\":"<<cpu<<",\"process_cpu_percent\":"<<(wall>0?100*cpu/wall:0)<<",\"process_interrupt_wakeups\":"<<(end.wakeups>=begin.wakeups?end.wakeups-begin.wakeups:0)
  <<",\"seek_thread_ID\":"<<hook.threadID.load()<<",\"polls\":"<<polls<<",\"loop_id\":"<<loopID<<",\"speed_id\":"<<speedID
  <<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak<<",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"callback_deadlines\":"<<native.deadlineMisses
  <<",\"missing\":"<<final.missingFrames<<",\"callback_cpp_new\":"<<final.callbackCppNew.value_or(UINT64_MAX)<<",\"callback_heap_allocations\":"<<phase61_heap_allocations()<<",\"callback_heap_frees\":"<<phase61_heap_frees()
  <<",\"source_rate\":48000,\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames<<",\"direct_private_phase_read\":false"
  <<",\"performance_improvement_approval\":false,\"quality_approval\":false,\"RT_approval\":false,\"physical_audio\":null,\"application_F\":null,\"reason\":"<<limit58::jsonString(reason)<<"}\n";
 summary.close();require(bool(summary),"summary write");return complete?(rt?0:2):1;
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=armedMain(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});control.join();return result;}
