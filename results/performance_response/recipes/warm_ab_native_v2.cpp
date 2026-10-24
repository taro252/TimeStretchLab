// 保存点warm再ON専用。INPUT candidate|baseline A_seconds NEW_OUTPUT SOURCE_SHA old|candidate
// 同じ本文を旧v3/候補v4のheaders/helpers/librariesへ単独compile/linkする。
// InitialCaptureだけを通常制御側で有限180秒/65536件へ正規化。callback gateなし。
// 初回ReturnToA→2自然周期→Playing Clear完了→Pause→保存/reset→通常Play実C>=B→別ID ON。
// warmは再ONのinitialCheckpointHit実値でだけ成立。missはNOT_EXERCISED（freshへ再分類しない）。
// setup/とwarm/へ全RAW/spansを保存。各folderをvalidate_capture.pyへ渡せる。
// 同validatorの8192行上限超過は監査不能を保持し、切捨てない。独立de70参照は別途必要。
// 初回setup/保存reset/通常Play/再ON/全体費用を分離。物理/UI/品質/RT承認を生成しない。
#define TS_PHASE62_INITIAL_NO_MAIN 1
#include "Phase62InitialLoopNative.cpp"
#include "prototype/Phase45PcmDigest.h"
#include <mach/mach_time.h>
#include <sys/resource.h>
#include <time.h>
#include <cctype>
#include <sstream>
#include <set>

namespace {
namespace wab58=ts::prototype::phase58;
constexpr std::array<const char*,12> wabChecks{
 "WAB01.Float32_mono48_300_fixture","WAB02.Ready_final_analysis",
 "WAB03.initial_ReturnToA","WAB04.two_natural_cycles",
 "WAB05.Playing_Clear_completed","WAB06.Pause_quiescent_capture_reset",
 "WAB07.normal_Play_actual_C_ge_B","WAB08.new_Loop_ID_first_A",
 "WAB09.fixed_Map_and_natural_cycles","WAB10.all_Accepted_terminal_close",
 "WAB11.owner_checkpoint_callback_supply","WAB12.full_capture_cost_SHA"};
struct WabCost {double wall=0,thread=0,process=0;};
WabCost wabCost(){
 timespec t{};rusage p{};require(!clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t)&&!getrusage(RUSAGE_SELF,&p),"cost clocks");
 return {double(initialNs())*1e-9,double(t.tv_sec)+double(t.tv_nsec)*1e-9,
  double(p.ru_utime.tv_sec)+double(p.ru_utime.tv_usec)*1e-6+double(p.ru_stime.tv_sec)+double(p.ru_stime.tv_usec)*1e-6};
}
void wabCostJson(std::ostream& f,const WabCost& a,const WabCost& z){
 const auto w=z.wall-a.wall,t=z.thread-a.thread,p=z.process-a.process;
 require(std::isfinite(w)&&std::isfinite(t)&&std::isfinite(p)&&w>=0&&t>=0&&p>=0,"finite cost delta");
 f<<"{\"wall_s\":"<<w<<",\"control_thread_cpu_s\":"<<t<<",\"process_cpu_s\":"<<p<<'}';
}
std::string wabHash(const std::filesystem::path& path){
 std::ifstream f(path,std::ios::binary);require(bool(f),"hash input");ts::prototype::Phase45PcmDigest h;std::array<char,65536> b{};
 while(f.read(b.data(),b.size())||f.gcount())h.update(b.data(),std::size_t(f.gcount()));require(f.eof(),"hash read");return h.finish();
}
void wabFloat32(const std::filesystem::path& path){
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
struct WabCapture {
 InitialCapture pcm;mach_timebase_info_data_t tb{};
 std::atomic<std::uint64_t> oldEpoch{0},firstA{0},firstAOutput{0},firstAEpoch{0};
 explicit WabCapture(std::size_t channels,std::size_t rate):pcm(channels,rate){
  // 同一有限観測memory。allocation/pretouchはprepareと計測より前の通常制御側だけ。
  pcm.rawPcm.resize(rate*180*channels);pcm.outputPcm.resize(rate*180*channels);
  pcm.rawRecords.resize(65536);pcm.spans.resize(65536);
  require(mach_timebase_info(&tb)==KERN_SUCCESS,"Mach timebase");
  static_assert(std::atomic<std::uint64_t>::is_always_lock_free);
 }
 std::uint64_t ns()const noexcept{return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*tb.numer/tb.denom);}
 static void raw(void* p,const float*const* pcm,std::size_t n,std::size_t at,std::uint64_t g,std::uint64_t epoch,std::uint64_t session)noexcept{
  auto& a=*static_cast<WabCapture*>(p);InitialCapture::raw(&a.pcm,pcm,n,at,g,epoch,session);
  const auto old=a.oldEpoch.load(std::memory_order_acquire);
  // 同じ直列callbackだけが書く。座標を書き終えてから時刻をrelease公開する。
  if(n&&old&&epoch!=old&&!a.firstA.load(std::memory_order_relaxed)){
   const auto observed=a.ns();a.firstAOutput=at;a.firstAEpoch=epoch;a.firstA.store(observed,std::memory_order_release);
  }
 }
 static void output(void* p,const float*const* pcm,const ProgressiveOutputSpan& s)noexcept{InitialCapture::output(&static_cast<WabCapture*>(p)->pcm,pcm,s);}
 void resetQuiescent(){
  // 呼出し側がPause同期成功と実C/PCM/周回の静止を確認済み。bufferは確保し直さない。
  pcm.rawFrames=0;pcm.outputFrames=0;pcm.rawCount=0;pcm.spanCount=0;pcm.errors=0;pcm.nonfinite=0;pcm.affected=0;pcm.firstNs=0;
  oldEpoch=0;firstA=0;firstAOutput=0;firstAEpoch=0;
 }
};
std::string wabBoundary(const progressive::LoopBoundaryEvent& p){
 std::ostringstream f;f<<"{\"loop_id\":"<<p.loopID<<",\"cycle\":"<<p.cycle<<",\"setting_cycle\":"<<p.settingCycle
  <<",\"old_epoch\":"<<p.oldEpoch<<",\"new_epoch\":"<<p.newEpoch<<",\"A\":"<<p.inputA<<",\"B\":"<<p.inputBExclusive
  <<",\"old_output_end\":"<<p.oldOutputEnd<<",\"new_output_start\":"<<p.newOutputStart<<",\"callback_frame\":"<<p.callbackFrame
  <<",\"render_ns\":"<<p.renderNs<<",\"hal_boundary_estimate_ns\":"<<p.halBoundaryEstimateNs<<",\"overlap_frames\":"<<p.overlapFrames
  <<",\"boundary_processing_frames\":"<<p.boundaryProcessingFrames<<'}';return f.str();
}
template<class T>std::string wabLoop(const T& p){
 std::ostringstream f;f<<std::setprecision(17)<<'{';
#define WAB_N(key,field) f<<"\"" key "\":"<<p.field<<','
 WAB_N("id",id);WAB_N("input_generation",inputGeneration);WAB_N("session",session);WAB_N("source_epoch",sourceRenderEpoch);WAB_N("current_epoch",currentRenderEpoch);
 WAB_N("A",startFrame);WAB_N("B",endFrameExclusive);WAB_N("cycles",cycles);
 f<<"\"state\":"<<wab58::jsonString(progressive::name(p.state))<<',';
 WAB_N("enabled",enabled);WAB_N("initial_position_complete",initialPositionComplete);WAB_N("clear_pending",clearPending);
 WAB_N("requested_speed",requestedSpeed);WAB_N("applied_speed",appliedSpeed);WAB_N("speed_request_id",speedRequestID);WAB_N("accepted_ns",acceptedNs);WAB_N("ready_ns",readyNs);WAB_N("preparation_count",preparationCount);
 if constexpr(requires{p.preparationRequestID;}){WAB_N("preparation_request_id",preparationRequestID);}else f<<"\"preparation_request_id\":null,";
 WAB_N("dynamic_operation_id",dynamicOperationID);WAB_N("dynamic_cycle",dynamicCycle);WAB_N("map_version",mapVersion);WAB_N("dynamic_output_end",dynamicOutputEnd);
 WAB_N("dynamic_speed_request_id",dynamicSpeedRequestID);WAB_N("speed_failure_request_id",speedFailureRequestID);WAB_N("speed_preparation_failed",speedPreparationFailed);
 f<<"\"speed_defer_reason\":"<<wab58::jsonString(p.speedDeferReason)<<',';
 WAB_N("last_preparation_ns",lastPreparationNs);WAB_N("last_ready_ns",lastReadyNs);WAB_N("max_preparation_ns",maxPreparationNs);WAB_N("safety_stop_frames",safetyStopFrames);
 WAB_N("old_missing",oldMissingFrames);WAB_N("new_missing",newMissingFrames);WAB_N("affected",outputAffectedFrames);WAB_N("failure_padding",failurePaddingFrames);
 WAB_N("reusable",reusable);WAB_N("period_frames",periodFrames);WAB_N("cache_bytes",cacheBytes);WAB_N("reuse_count",reuseCount);WAB_N("seed_restores",seedRestores);WAB_N("map_builds",mapBuilds);WAB_N("worker_creations",workerCreations);
 WAB_N("cold_discarded_frames",coldDiscardedFrames);WAB_N("warm_discarded_frames",warmDiscardedFrames);WAB_N("paused_clear_discarded",pausedClearDiscardedFrames);WAB_N("paused_clear_input",pausedClearInputFrame);
#undef WAB_N
 f<<"\"last_boundary\":"<<(p.lastBoundary?wabBoundary(*p.lastBoundary):"null")<<",\"reason\":"<<wab58::jsonString(p.reason)<<'}';return f.str();
}
struct WabEpoch {std::uint64_t serial=0,preparation=0,sequence=0,epoch=0,session=0,generation=0;std::size_t ordinary=0;bool prepared=false,joined=false,released=false;};
struct WabAudit {
 std::uint64_t calls=0,serial=0,preparation=0,epochCalls=0,epochRejected=0;
 bool failed=false,callback=false,joined=false,retired=false,configured=false;
 std::vector<WabEpoch> epochs;std::size_t seeks=0,stopped=0,speeds=0,preparations=0;
 WabAudit(){epochs.reserve(16);}
 static bool epoch(void* p,const EpochOperationAudit& a)noexcept{
  auto& x=*static_cast<WabAudit*>(p);try{x.callback|=callbackCounting;x.epochs.push_back({a.engineSerial,a.preparation,a.sequence,a.renderEpoch,a.session,a.inputGeneration,a.ordinarySpeeds.size(),a.preparedOnly,a.workersJoined,a.callbackReleased});return true;}catch(...){x.failed=true;return false;}
 }
 static bool final(void* p,const FinalOperationAudit& a)noexcept{
  auto& x=*static_cast<WabAudit*>(p);try{++x.calls;x.serial=a.engineSerial;x.preparation=a.preparation;x.joined=a.workersJoined;x.retired=a.retirementComplete;x.configured=a.epochAuditConfigured;
   x.epochCalls=a.epochAuditCalls;x.epochRejected=a.epochAuditRejected;x.callback|=callbackCounting;
   x.seeks=a.seeks.size();x.stopped=a.stoppedSpeeds.size();x.speeds=a.loopSpeeds.size();x.preparations=a.loopPreparations.size();
   // 外部seek/速度/先行準備は要求しない。空spanという結果を所有値として保存。
   if(x.seeks||x.stopped||x.speeds||x.preparations)x.failed=true;return !x.failed;
  }catch(...){x.failed=true;return false;}
 }
};
template<class F>void wabUntil(ProgressiveMacPlaybackEngine& e,F predicate,const char* why){
 const auto end=InitialClock::now()+std::chrono::seconds(180);
 while(!predicate()){const auto s=e.getStateSnapshot();if(s.state==State::Failed)throw std::runtime_error(s.error);require(InitialClock::now()<end,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
}
progressive::LoopContext wabContext(ProgressiveMacPlaybackEngine& e){const auto s=e.getStateSnapshot();return {s.inputGeneration,s.session,s.renderEpoch};}
void wabCaptureGood(const InitialCapture& c){require(!c.errors.load()&&!c.nonfinite.load()&&!c.affected.load()&&c.rawCount.load()&&c.spanCount.load(),"capture capacity/finite/affected/empty");}
void wabProfilesOff(const wab58::Diagnostics& d){require(!d.workerProfileRecords&&!d.detailRecords&&!d.threadSamplingRequested&&!d.threadSamples,"detailed profile active");}
void wabSegment(const std::filesystem::path& out,const InitialCapture& c,std::uint64_t a,std::uint64_t b,const std::string& inputSha,const std::string& binarySha,const std::string& preset,const char* phase,std::uint64_t firstEpoch=0,std::uint64_t firstAt=0){
 std::ofstream f(out/"EXPECTED.json");f<<"{\"A\":"<<a<<",\"B\":"<<b<<",\"speed\":1,\"speed_micros\":1000000,\"preset\":"<<wab58::jsonString(preset)<<",\"phase\":"<<wab58::jsonString(phase)
  <<",\"input_sha256\":"<<wab58::jsonString(inputSha)<<",\"binary_sha256\":"<<wab58::jsonString(binarySha)<<",\"final_gain_applied\":false,\"independent_PCM\":\"PENDING\"}\n";f.close();require(bool(f),"capture expected write");
 std::ofstream s(out/"SUMMARY.json");s<<"{\"run_complete\":true,\"functional\":true,\"input_sha256\":"<<wab58::jsonString(inputSha)<<",\"raw_records\":"<<c.rawCount.load()<<",\"output_spans\":"<<c.spanCount.load()
  <<",\"raw_frames\":"<<c.rawFrames.load()<<",\"output_frames\":"<<c.outputFrames.load()<<",\"validator_row_limit_exercised\":"<<(c.rawCount<=8192&&c.spanCount<=8192?"true":"false");
 if(firstEpoch)s<<",\"first_A_epoch\":"<<firstEpoch<<",\"first_A_output\":"<<firstAt;
 s<<",\"quality_approval\":false,\"RT_deadline_approval\":false,\"physical_audio\":null,\"application_F\":null}\n";s.close();require(bool(s),"capture summary write");
}
void wabMap(const std::filesystem::path& out,const ts::TimeMap& m,std::uint64_t a,std::uint64_t b,std::uint64_t frames){
 require(!m.empty(),"final Map empty");std::ofstream nodes(out/"final_map.nodes.i64",std::ios::binary);nodes.write(reinterpret_cast<const char*>(m.starts().data()),m.starts().size()*sizeof(long long));nodes.close();require(bool(nodes),"Map nodes write");
 std::ofstream events(out/"final_map.events.jsonl");events<<std::setprecision(9);for(const auto& e:m.events())events<<"{\"onset\":"<<e.onsetFrame<<",\"peak\":"<<e.peakFrame<<",\"attack_end\":"<<e.attackEndFrame<<",\"end\":"<<e.endFrame<<",\"strength\":"<<e.strength<<"}\n";events.close();require(bool(events),"Map events write");
 std::ofstream f(out/"PRODUCT_MAP.json");f<<"{\"scope\":\"joined final product Map evidence; not independent oracle\",\"source_hop\":"<<m.sourceHop()<<",\"node_count\":"<<m.starts().size()<<",\"event_count\":"<<m.events().size()<<",\"input_frames\":"<<frames
  <<",\"A\":"<<a<<",\"B\":"<<b<<",\"OA\":"<<std::llround(m.outputPositionForInputSample(double(a)))<<",\"OB\":"<<std::llround(m.outputPositionForInputSample(double(b)))<<",\"nodes_sha256\":"<<wab58::jsonString(wabHash(out/"final_map.nodes.i64"))<<",\"events_sha256\":"<<wab58::jsonString(wabHash(out/"final_map.events.jsonl"))<<"}\n";f.close();require(bool(f),"Map metadata write");
}
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
 p.before=wab58::RealtimePipeline::executionOwnerCounts().alive;
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
  p.atReady=wab58::RealtimePipeline::executionOwnerCounts().alive;
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
  engine.reset();const auto owners=wab58::RealtimePipeline::executionOwnerCounts();p.after=owners.alive;p.peak=owners.peak;
  require(p.stopped&&p.identities&&p.calls==1&&p.joined&&p.retired&&p.configured&&!p.callback&&
   p.epochCalls==p.epochObserved&&p.epochObserved==1&&!p.epochRejected&&p.epochJoined&&p.epochReleased&&
   !p.operationRows&&!p.after&&p.peak<=2,"probe own audit/owner0 after close");p.passed=true;
 }catch(const std::exception& e){p.error=e.what();if(engine){try{engine->stop();}catch(...){}engine.reset();}
  const auto owners=wab58::RealtimePipeline::executionOwnerCounts();p.after=owners.alive;p.peak=owners.peak;
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
  <<",\"identities_match\":"<<p.identities<<",\"input_sha256\":"<<wab58::jsonString(p.inputSha)<<",\"operation_rows\":"<<p.operationRows<<",\"callback_calls\":"<<p.callbackCalls<<",\"first_PCM_ns\":"<<p.firstPcm
  <<",\"missing_frames\":"<<p.missing<<",\"rejected_writes\":"<<p.rejected<<",\"worker_deadlines\":"<<p.workerDeadlines<<",\"workgroup_errors\":"<<p.workgroupErrors
  <<",\"checkpoint_states\":"<<p.checkpointStates<<",\"checkpoint_peak\":"<<p.checkpointPeak
  <<",\"callback_cpp_measured\":"<<p.cppMeasured<<",\"callback_cpp_new\":"<<p.cppNew
  <<",\"callback_heap_allocations\":"<<p.heapAllocations<<",\"callback_heap_frees\":"<<p.heapFrees
  <<",\"same_process\":true,\"explicit_Play\":false,\"separate_sink\":true,\"primary_cost_excludes_probe\":true,\"reservation_is_live_counter\":false,\"error\":"<<wab58::jsonString(p.error)<<"}\n";
 f.close();require(bool(f),"probe evidence write");return p;
}
int wabMain(int argc,char** argv){
 require(argc==7,"INPUT PRESET A_seconds NEW_OUTPUT SOURCE_SHA old|candidate");
 const std::filesystem::path input=argv[1],out=argv[4];const std::string preset=argv[2],source=argv[5],version=argv[6];
 require((preset=="candidate"||preset=="baseline")&&(version=="old"||version=="candidate"),"preset/version");
 require(progressive::contractVersion==(version=="old"?3u:4u),"old v3 / candidate v4 headers");
 require(source.size()==64&&std::all_of(source.begin(),source.end(),[](unsigned char c){return std::isxdigit(c);}),"source SHA");
 const auto seconds=std::stod(argv[3]);require(seconds==30||seconds==270,"A30 or A270 only");
 require(!std::filesystem::exists(out)&&std::filesystem::create_directories(out),"fresh output required");
 const auto setupFolder=out/"setup",warmFolder=out/"warm";std::filesystem::create_directory(setupFolder);std::filesystem::create_directory(warmFolder);
 wabFloat32(input);ts::WavStreamReader info(input);const auto rate=info.sampleRate();require(rate==48000&&info.channels()==1&&info.frames()==std::uint64_t(rate)*300,"actual Float32 mono48k 300s required");
 const auto a=std::uint64_t(seconds*rate),b=a+rate/10;const auto inputSha=wabHash(input),binarySha=wabHash(std::filesystem::absolute(argv[0]));
 WabCapture capture(info.channels(),rate);WabAudit audit;std::unique_ptr<ProgressiveMacPlaybackEngine> engine;
 std::ofstream checks(out/"checks.jsonl"),receipts(out/"receipts.jsonl"),observations(out/"observations.jsonl");checks<<std::boolalpha;receipts<<std::boolalpha;
 std::size_t passed=0;std::string error;bool hit=false,rt=false,completed=false,setupSaved=false,warmSaved=false;
 std::uint64_t firstID=0,warmID=0,clearID=0,generation=0,serial=0,cAtOn=0,firstNative=0,firstAt=0,firstEpoch=0,acceptedNs=0,alignedNs=0;
 std::uint64_t setupRaw=0,setupOutput=0,setupRawRecords=0,setupSpans=0;progressive::LoopSnapshot firstClear{},warmTerminal{},warmActive{};
 ProgressiveDiagnostics final{},warmDiagnostics{};ProgressiveNativeDiagnostics native{};
 WabCost wholeBegin=wabCost(),prepareBegin{},analysisReady{},initialOn{},initialAligned{},setupPaused{},archiveBegin{},archiveEnd{},normalPlay{},atC{},on{},firstObserved{},finish{},wholeEnd{};
 bool haveAnalysis=false,haveSetup=false,haveArchive=false,haveC=false,haveFirst=false,haveFinish=false;
 WabCost primaryEnd{},probeBegin{},probeEnd{};bool primaryComplete=false,haveProbe=false;ReservationProbe probe;
 const auto pass=[&]{require(passed<wabChecks.size(),"extra check");checks<<"{\"id\":"<<wab58::jsonString(wabChecks[passed++])<<",\"pass\":true}\n";checks.flush();require(bool(checks),"checks write");};
 const auto snapshot=[&](const char* phase){observations<<"{\"phase\":"<<wab58::jsonString(phase)<<",\"snapshot\":"<<wabLoop(engine->getLoopSnapshot())<<"}\n";observations.flush();require(bool(observations),"snapshot write");};
 const auto receipt=[&](const char* action,const progressive::LoopReceipt& r,const progressive::LoopContext& c){receipts<<"{\"action\":"<<wab58::jsonString(action)<<",\"id\":"<<r.id<<",\"accepted\":"<<r.accepted<<",\"code\":"<<int(r.code)<<",\"reason\":"<<wab58::jsonString(r.reason)
  <<",\"context\":{\"generation\":"<<c.inputGeneration<<",\"session\":"<<c.session<<",\"epoch\":"<<c.renderEpoch<<"}}\n";receipts.flush();require(bool(receipts),"receipt write");};
 try{
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"schema\":\"performance-warm-ab-v1\",\"expected\":12,\"required_ids\":[";for(std::size_t i=0;i<wabChecks.size();++i)f<<(i?",":"")<<wab58::jsonString(wabChecks[i]);
   f<<"],\"A\":"<<a<<",\"B\":"<<b<<",\"speed\":1,\"preset\":"<<wab58::jsonString(preset)<<",\"source\":"<<wab58::jsonString(source)<<",\"version\":"<<wab58::jsonString(version)<<",\"contract_version\":"<<progressive::contractVersion
    <<",\"input_sha256\":"<<wab58::jsonString(inputSha)<<",\"binary_sha256\":"<<wab58::jsonString(binarySha)<<",\"unique_Loop_IDs\":[1,2],\"accepted_receipts\":[{\"action\":\"initial_ON\",\"id\":1},{\"action\":\"Playing_Clear\",\"id\":1},{\"action\":\"warm_reON\",\"id\":2}],\"seek_checkpoints\":false,\"prewarm_requests\":0,\"warm_target_ms\":250,\"capture_seconds\":180,\"capture_records\":65536,\"callback_gate\":false}\n";f.close();require(bool(f),"expected write");}pass();
  phase61_heap_reset();ProgressiveOptions options;options.preset=preset=="baseline"?Preset::Baseline:Preset::Candidate;options.initialSpeed=1;options.allowExperimentalLoops=true;options.seekCheckpoints=false;options.callbackRecordLimit=256;
  options.observerContext=&capture;options.observeEpochPcm=WabCapture::raw;options.observeOutputPcm=WabCapture::output;
  options.finalOperationAuditContext=&audit;options.receiveFinalOperationAudit=WabAudit::final;options.finalEpochAuditContext=&audit;options.receiveFinalEpochAudit=WabAudit::epoch;
  options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
  engine=std::make_unique<ProgressiveMacPlaybackEngine>();prepareBegin=wabCost();require(engine->prepare(input,options),"prepare");
  wabUntil(*engine,[&]{return engine->getPlaybackState()==State::Ready;},"initial Ready watchdog");wabUntil(*engine,[&]{return engine->getPlaybackDiagnostics().pipeline.analysisDone;},"final analysis watchdog");analysisReady=wabCost();haveAnalysis=true;
  const auto initial=engine->getStateSnapshot();const auto original=engine->getPlaybackDiagnostics();generation=initial.inputGeneration;serial=original.engineSerial;
  require(generation&&serial&&engine->loopPreparationHistory().empty()&&engine->seekHistory().empty()&&!capture.pcm.rawFrames.load(),"fresh engine unexpected work");wabProfilesOff(original.pipeline);pass();
  auto context=wabContext(*engine);initialOn=wabCost();const auto first=engine->requestLoopRange(a,b,context);firstID=first.id;receipt("initial_ON",first,context);require(first.accepted&&firstID==1,"initial Loop ID/admission");
  wabUntil(*engine,[&]{const auto l=engine->getLoopSnapshot();require(l.state!=progressive::LoopState::Failed,l.reason.c_str());return l.initialPositionComplete&&!engine->getPlaybackDiagnostics().retiringPipeline;},"initial ReturnToA watchdog");initialAligned=wabCost();
  const auto firstReady=engine->getLoopSnapshot();require(engine->getPlaybackState()==State::Ready&&firstReady.id==firstID&&firstReady.startFrame==a&&firstReady.endFrameExclusive==b&&!firstReady.cycles&&engine->getCurrentPlaybackPosition().inputFrame==std::optional<std::uint64_t>(a)&&!engine->getPlaybackDiagnostics().pipeline.loopReuse.initialCheckpointHit,"initial ReturnToA/fresh identity");snapshot("initial_ReturnToA_Ready");pass();
  require(engine->play(),"initial explicit Play");wabUntil(*engine,[&]{return engine->getLoopSnapshot().cycles>=2;},"two initial natural cycles watchdog");
  const auto loopBeforeClear=engine->getLoopSnapshot();require(loopBeforeClear.lastBoundary&&loopBeforeClear.lastBoundary->loopID==firstID&&loopBeforeClear.lastBoundary->settingCycle==loopBeforeClear.cycles&&loopBeforeClear.lastBoundary->inputA==a&&loopBeforeClear.lastBoundary->inputBExclusive==b,"initial actual boundary identity");snapshot("initial_two_natural_cycles");pass();
  require(engine->getPlaybackState()==State::Playing,"Clear must be accepted while Playing");context=wabContext(*engine);const auto cleared=engine->requestClearLoop(firstID,context);clearID=cleared.id;receipt("Playing_Clear",cleared,context);require(cleared.accepted&&clearID==firstID,"Playing Clear identity");
  wabUntil(*engine,[&]{const auto l=engine->getLoopSnapshot();return !l.enabled&&!l.clearPending&&!engine->getPlaybackDiagnostics().retiringPipeline;},"Playing Clear join watchdog");
  firstClear=engine->getLoopSnapshot();require(firstClear.id==firstID&&firstClear.state==progressive::LoopState::Cancelled&&firstClear.cycles>=loopBeforeClear.cycles&&firstClear.lastBoundary&&firstClear.lastBoundary->settingCycle==firstClear.cycles&&engine->getPlaybackState()==State::Playing,"Clear terminal/normal continuation/cycle");snapshot("first_Loop_Clear_terminal_owned");pass();
  require(engine->pause(),"Pause after Clear");const auto paused=engine->getCurrentPlaybackPosition();const auto stableLoop=engine->getLoopSnapshot();
  setupRaw=capture.pcm.rawFrames;setupOutput=capture.pcm.outputFrames;setupRawRecords=capture.pcm.rawCount;setupSpans=capture.pcm.spanCount;
  std::this_thread::sleep_for(std::chrono::milliseconds(30));
  require(engine->getPlaybackState()==State::Paused&&engine->getCurrentPlaybackPosition().inputFrame==paused.inputFrame&&engine->getCurrentPlaybackPosition().outputFrame==paused.outputFrame&&capture.pcm.rawFrames==setupRaw&&capture.pcm.outputFrames==setupOutput&&capture.pcm.rawCount==setupRawRecords&&capture.pcm.spanCount==setupSpans&&engine->getLoopSnapshot().cycles==stableLoop.cycles,"Pause did not quiesce callback/C/cycle");
  wabCaptureGood(capture.pcm);setupPaused=wabCost();haveSetup=true;archiveBegin=wabCost();initialSave(setupFolder,capture.pcm);wabSegment(setupFolder,capture.pcm,a,b,inputSha,binarySha,preset,"initial_Loop_and_Playing_Clear");
  writePhase62Trace(setupFolder/"callbacks.jsonl",engine->loopCallbackRecords());writePhase62Trace(setupFolder/"clock_anomaly.jsonl",engine->loopClockAnomalyRecords());
  {std::ofstream f(setupFolder/"boundaries.jsonl");for(const auto& p:engine->loopHistory())f<<wabBoundary(p)<<'\n';f.close();require(bool(f),"setup boundaries write");}setupSaved=true;
  capture.resetQuiescent();require(!capture.pcm.rawFrames&&!capture.pcm.outputFrames&&!capture.pcm.rawCount&&!capture.pcm.spanCount,"quiescent reset");archiveEnd=wabCost();haveArchive=true;pass();
  normalPlay=wabCost();require(engine->play(),"normal explicit Play after reset");
  wabUntil(*engine,[&]{const auto p=engine->getCurrentPlaybackPosition();return capture.pcm.rawFrames.load()>0&&capture.pcm.outputFrames.load()>0&&p.inputFrame&&*p.inputFrame>=b;},"normal actual C>=B watchdog");
  const auto pos=engine->getCurrentPlaybackPosition();const auto normal=engine->getStateSnapshot();atC=wabCost();haveC=true;cAtOn=pos.inputFrame.value_or(0);
  require(engine->getPlaybackState()==State::Playing&&cAtOn>=b&&!engine->getLoopSnapshot().enabled&&!engine->getLoopSnapshot().clearPending&&normal.inputGeneration==generation&&normal.requestedSpeed==1&&normal.appliedTargetSpeed==1&&capture.pcm.spans[0].newEpoch==normal.renderEpoch&&!capture.pcm.spans[0].periodicBoundary,"normal C>=B/state/speed/nonperiodic PCM");snapshot("normal_Play_actual_C_ge_B");pass();
  context=wabContext(*engine);capture.oldEpoch.store(context.renderEpoch,std::memory_order_release);on=wabCost();const auto second=engine->requestLoopRange(a,b,context);warmID=second.id;receipt("warm_reON",second,context);require(second.accepted&&warmID==2&&warmID!=firstID,"new same-range Loop ID/admission");
  wabUntil(*engine,[&]{const auto l=engine->getLoopSnapshot();require(l.state!=progressive::LoopState::Failed,l.reason.c_str());return l.initialPositionComplete;},"reON alignment watchdog");alignedNs=capture.ns();
  wabUntil(*engine,[&]{return capture.firstA.load(std::memory_order_acquire)!=0;},"reON first A callback watchdog");firstObserved=wabCost();haveFirst=true;
  firstNative=capture.firstA.load(std::memory_order_acquire);firstAt=capture.firstAOutput;firstEpoch=capture.firstAEpoch;warmActive=engine->getLoopSnapshot();acceptedNs=warmActive.acceptedNs;
  warmDiagnostics=engine->getPlaybackDiagnostics();hit=warmDiagnostics.pipeline.loopReuse.initialCheckpointHit;
  require(warmActive.id==warmID&&warmActive.startFrame==a&&warmActive.endFrameExclusive==b&&warmActive.inputGeneration==generation&&warmActive.requestedSpeed==1&&warmActive.appliedSpeed==1&&firstNative>=acceptedNs&&firstEpoch!=context.renderEpoch&&acceptedNs,"new Loop accepted/first-A identity/order");snapshot("warm_reON_first_A_observed");pass();
  wabUntil(*engine,[&]{return engine->getLoopSnapshot().cycles>=2&&!engine->getPlaybackDiagnostics().retiringPipeline;},"warm natural cycles/join watchdog");require(engine->pause(),"final Pause");
  warmActive=engine->getLoopSnapshot();warmDiagnostics=engine->getPlaybackDiagnostics();native=engine->getNativeDiagnostics();finish=wabCost();haveFinish=true;
  require(warmActive.cycles>=2&&warmActive.lastBoundary&&warmActive.lastBoundary->loopID==warmID&&warmActive.lastBoundary->settingCycle==warmActive.cycles&&warmActive.lastBoundary->inputA==a&&warmActive.lastBoundary->inputBExclusive==b&&!warmActive.safetyStopFrames&&!warmActive.failurePaddingFrames&&!warmActive.outputAffectedFrames,"warm actual natural cycles/supply");
  require(engine->seekHistory().empty()&&engine->loopPreparationHistory().empty()&&engine->loopSpeedHistory().empty()&&engine->stoppedSpeedHistory().empty()&&engine->operationHistory().empty(),"unrequested external operation/Map change");wabProfilesOff(warmDiagnostics.pipeline);snapshot("warm_two_cycles_Paused");pass();
  {std::ofstream f(setupFolder/"first_Loop_terminal.json");f<<wabLoop(firstClear)<<'\n';f.close();require(bool(f),"first terminal write");}
  {std::ofstream f(warmFolder/"boundaries.jsonl");for(const auto& p:engine->loopHistory())f<<wabBoundary(p)<<'\n';f.close();require(bool(f),"boundaries write");}
  writePhase62Trace(warmFolder/"callbacks.jsonl",engine->loopCallbackRecords());writePhase62Trace(warmFolder/"clock_anomaly.jsonl",engine->loopClockAnomalyRecords());
  engine->stop();final=engine->getPlaybackDiagnostics();warmTerminal=engine->getLoopSnapshot();require(warmTerminal.id==warmID&&!warmTerminal.enabled&&!warmTerminal.clearPending&&warmTerminal.state==progressive::LoopState::Cancelled,"Stop Loop terminal");snapshot("second_Loop_Stop_terminal_owned");
  const auto map=engine->finalTimeMap();wabMap(out,map,a,b,info.frames());require(firstAt==std::uint64_t(std::llround(map.outputPositionForInputSample(double(a))))&&warmActive.periodFrames==std::uint64_t(std::llround(map.outputPositionForInputSample(double(b))))-firstAt,"first A/period differs from joined fixed Map");
  {std::ofstream f(out/"owned_Loop_terminals.jsonl");f<<wabLoop(firstClear)<<'\n'<<wabLoop(warmTerminal)<<'\n';f.close();require(bool(f),"owned Loop terminals write");}
  const auto terminalBeforeClose=wabLoop(warmTerminal);require(wabLoop(engine->getLoopSnapshot())==terminalBeforeClose,"terminal Loop changed before close");
  {std::ofstream f(out/"EPOCHS.jsonl");f<<std::setprecision(17)<<std::boolalpha;
   const auto epoch=[&](const wab58::Diagnostics& p,std::uint64_t epochID,bool prepared){
    const auto& s=p.scheduling;require(p.finalDataAvailable&&!s.active&&s.joins==s.leaves&&s.leaves==s.restores&&p.loopReuse.checkpointStates<=2&&p.loopReuse.checkpointPeak<=2,"joined epoch/Workgroup/checkpoint");
    wabProfilesOff(p);f<<"{\"session\":"<<p.session<<",\"generation\":"<<p.inputGeneration<<",\"epoch\":"<<epochID<<",\"prepared_only\":"<<prepared<<",\"final_data_available\":"<<p.finalDataAvailable
     <<",\"input_sha256\":"<<wab58::jsonString(p.inputSha256)<<",\"analysis_final\":"<<p.analysisDone<<",\"output_start\":"<<p.outputStartFrame<<",\"output_frames\":"<<p.outputFrames<<",\"generated\":"<<p.generated<<",\"published\":"<<p.published<<",\"consumed_coordinate\":"<<p.consumed
     <<",\"reused_input\":"<<p.reusedInput<<",\"reused_analysis\":"<<p.reusedAnalysis<<",\"source_hash_passes\":"<<p.sourceHashPasses<<",\"source_snapshot_creations\":"<<p.sourceSnapshotCreations<<",\"resident_lock_calls\":"<<p.residentLockCalls
     <<",\"initial_checkpoint_hit\":"<<p.loopReuse.initialCheckpointHit<<",\"checkpoint_states_at_join_snapshot\":"<<p.loopReuse.checkpointStates<<",\"checkpoint_peak\":"<<p.loopReuse.checkpointPeak
     <<",\"cold_prefix_cpu_s\":"<<p.loopReuse.coldPrefixCpuS<<",\"warm_cpu_s\":"<<p.loopReuse.warmCpuS<<",\"dsp_worker_cpu_s\":"<<p.dspWorkerCpuS<<",\"joins\":"<<s.joins<<",\"leaves\":"<<s.leaves<<",\"restores\":"<<s.restores<<"}\n";
   };
   for(const auto& p:engine->closedEpochs())epoch(p.pipeline,p.renderEpoch,p.preparedOnly);epoch(final.pipeline,final.renderEpoch,false);
   f.close();require(bool(f),"joined epochs write");
  }
  engine.reset();require(audit.calls==1&&audit.serial==serial&&audit.joined&&audit.retired&&audit.configured&&!audit.failed&&!audit.callback&&!audit.epochRejected&&audit.epochCalls==audit.epochs.size()&&audit.epochs.size()>=4&&!audit.seeks&&!audit.stopped&&!audit.speeds&&!audit.preparations,"close final owned scope/joins");
  std::set<std::uint64_t> sequences;for(const auto& ep:audit.epochs)require(ep.serial==serial&&ep.generation==generation&&ep.joined&&ep.released&&!ep.ordinary&&sequences.insert(ep.sequence).second,"epoch join/identity/duplicate/ordinary speed");pass();
  wabCaptureGood(capture.pcm);initialSave(warmFolder,capture.pcm);wabSegment(warmFolder,capture.pcm,a,b,inputSha,binarySha,preset,"normal_C_ge_B_to_same_range_reON",firstEpoch,firstAt);warmSaved=true;
  require(wabHash(input)==inputSha&&wabHash(std::filesystem::absolute(argv[0]))==binarySha,"input/binary changed");
  const auto owners=wab58::RealtimePipeline::executionOwnerCounts();
  require(!owners.alive&&owners.peak<=2&&warmDiagnostics.pipeline.loopReuse.checkpointPeak<=2&&final.pipeline.loopReuse.checkpointStates<=2&&final.pipeline.checkpointResidentStates==0&&!capture.pcm.errors&&!capture.pcm.nonfinite&&!capture.pcm.affected&&!final.missingFrames&&!final.underrunCalls&&!final.rejectedWrites&&!final.workgroupErrors&&final.callbackCppNew&&!*final.callbackCppNew&&!phase61_heap_allocations()&&!phase61_heap_frees(),"owner/checkpoint/reservation/callback/supply audit");
  require(final.pipeline.finalDataAvailable&&final.pipeline.sourceHashPasses==1&&final.pipeline.sourceSnapshotCreations==1&&final.pipeline.residentLockCalls==1,"joined final pipeline/shared input lease");wabProfilesOff(final.pipeline);
  primaryEnd=wabCost();primaryComplete=true;probeBegin=primaryEnd;
  probe=reservationProbe(input,preset,serial,generation,inputSha,out);probeEnd=wabCost();haveProbe=true;
  require(probe.passed,probe.error.c_str());require(audit.calls==1&&audit.serial==serial,"probe polluted original audit");pass();
  require(setupSaved&&warmSaved,"complete capture metadata");pass();completed=true;
 }catch(const std::exception& e){
  error=e.what();checks<<"{\"id\":"<<wab58::jsonString(passed<wabChecks.size()?wabChecks[passed]:"UNEXPECTED")<<",\"pass\":false,\"reason\":"<<wab58::jsonString(error)<<"}\n";checks.flush();
  if(engine){try{engine->stop();final=engine->getPlaybackDiagnostics();native=engine->getNativeDiagnostics();snapshot("failure_after_Stop");}catch(...){}engine.reset();}
  try{if(!warmSaved&&haveFinish){wabCaptureGood(capture.pcm);initialSave(warmFolder,capture.pcm);wabSegment(warmFolder,capture.pcm,a,b,inputSha,binarySha,preset,"normal_C_ge_B_to_same_range_reON",firstEpoch,firstAt);warmSaved=true;}}catch(...){}
 }
 wholeEnd=wabCost();rt=completed&&!native.deadlineMisses&&!final.workerDeadlineMisses&&!native.hostMissing&&!native.hostBackwards&&!native.hostCadenceErrors&&!native.sampleErrors&&!native.halWindowMisses&&!final.workgroupErrors;
 const bool warmExercised=completed&&hit,latencyPass=warmExercised&&firstNative>=acceptedNs&&double(firstNative-acceptedNs)/1e6<=250;
 {std::ofstream f(out/"SUMMARY.json");const auto owners=wab58::RealtimePipeline::executionOwnerCounts();f<<std::setprecision(17)<<std::boolalpha
  <<"{\"schema\":\"performance-warm-ab-v1\",\"run_complete\":"<<completed<<",\"functional\":"<<completed<<",\"expected\":12,\"executed\":"<<passed<<",\"source\":"<<wab58::jsonString(source)<<",\"version\":"<<wab58::jsonString(version)<<",\"contract_version\":"<<progressive::contractVersion
  <<",\"input_sha256\":"<<wab58::jsonString(inputSha)<<",\"binary_sha256\":"<<wab58::jsonString(binarySha)<<",\"preset\":"<<wab58::jsonString(preset)<<",\"source_rate\":"<<rate<<",\"channels\":1,\"input_frames\":"<<info.frames()<<",\"speed\":1,\"A\":"<<a<<",\"B\":"<<b
  <<",\"accepted_receipts\":{\"initial_ON\":"<<firstID<<",\"Playing_Clear\":"<<clearID<<",\"warm_reON\":"<<warmID<<"},\"unique_Loop_IDs_expected\":[1,2],\"observed_terminal_Loop_IDs\":["<<firstClear.id<<','<<warmTerminal.id<<"]"
  <<",\"first_A_epoch\":"<<firstEpoch<<",\"first_A_output\":"<<firstAt<<",\"first_A_callback_ns\":"<<firstNative<<",\"reON_accepted_ns\":"<<acceptedNs<<",\"C_at_reON\":"<<cAtOn<<",\"C_at_or_after_B\":"<<(cAtOn>=b)
  <<",\"initial_checkpoint_hit\":"<<hit<<",\"warm_status\":"<<wab58::jsonString(warmExercised?"EXERCISED":"NOT_EXERCISED")<<",\"warm_miss_reclassified_fresh\":false,\"performance_exercised\":"<<warmExercised<<",\"performance_pass\":";
  if(warmExercised)f<<latencyPass;else f<<"null";
  f<<",\"warm_target_ms\":250,\"accepted_to_first_A_ms\":";if(haveFirst&&firstNative>=acceptedNs)f<<double(firstNative-acceptedNs)/1e6;else f<<"null";
  f<<",\"accepted_to_alignment_observed_ms\":";if(haveFirst&&alignedNs>=acceptedNs)f<<double(alignedNs-acceptedNs)/1e6;else f<<"null";
  f<<",\"warm_latency_ms\":";if(warmExercised)f<<double(firstNative-acceptedNs)/1e6;else f<<"null";
  f<<",\"rt_pass\":"<<rt<<",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"callback_deadlines\":"<<native.deadlineMisses<<",\"host_missing\":"<<native.hostMissing<<",\"host_backwards\":"<<native.hostBackwards<<",\"host_cadence\":"<<native.hostCadenceErrors<<",\"sample_errors\":"<<native.sampleErrors<<",\"hal_window_misses\":"<<native.halWindowMisses
  <<",\"missing_frames\":"<<final.missingFrames<<",\"underrun_calls\":"<<final.underrunCalls<<",\"rejected_writes\":"<<final.rejectedWrites<<",\"workgroup_errors\":"<<final.workgroupErrors<<",\"callback_cpp_new\":";if(final.callbackCppNew)f<<*final.callbackCppNew;else f<<"null";
  f<<",\"callback_heap_allocations\":"<<phase61_heap_allocations()<<",\"callback_heap_frees\":"<<phase61_heap_frees()<<",\"owners_alive\":"<<owners.alive<<",\"owners_peak\":"<<owners.peak<<",\"checkpoint_peak\":"<<warmDiagnostics.pipeline.loopReuse.checkpointPeak<<",\"seek_checkpoint_states_final_snapshot\":"<<final.pipeline.checkpointResidentStates<<",\"loop_checkpoint_states_final_snapshot\":"<<final.pipeline.loopReuse.checkpointStates<<",\"reservation_after_Stop\":"<<final.reservationBytes<<",\"reservation_after_Stop_is_saved_estimate\":true,\"reservation_reacquired\":"<<probe.passed
  <<",\"initial_cycles_at_Clear\":"<<firstClear.cycles<<",\"reON_cycles\":"<<warmActive.cycles<<",\"setup_raw_frames\":"<<setupRaw<<",\"setup_output_frames\":"<<setupOutput<<",\"setup_raw_records\":"<<setupRawRecords<<",\"setup_output_spans\":"<<setupSpans<<",\"warm_raw_frames\":"<<capture.pcm.rawFrames.load()<<",\"warm_output_frames\":"<<capture.pcm.outputFrames.load()<<",\"warm_raw_records\":"<<capture.pcm.rawCount.load()<<",\"warm_output_spans\":"<<capture.pcm.spanCount.load()
  <<",\"setup_capture_saved\":"<<setupSaved<<",\"warm_capture_saved\":"<<warmSaved<<",\"device\":"<<native.deviceId<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames
  <<",\"initial_checkpoint_start\":"<<warmDiagnostics.pipeline.checkpointStartFrame<<",\"cold_discarded\":"<<warmDiagnostics.pipeline.loopReuse.coldDiscardedFrames<<",\"cold_prefix_cpu_s\":"<<warmDiagnostics.pipeline.loopReuse.coldPrefixCpuS<<",\"analysis_wait_s\":"<<warmDiagnostics.pipeline.loopReuse.analysisWaitS<<",\"map_cpu_s\":"<<warmDiagnostics.pipeline.loopReuse.mapCpuS
  <<",\"final_audit_calls\":"<<audit.calls<<",\"epoch_audit_calls\":"<<audit.epochCalls<<",\"epoch_audit_rejected\":"<<audit.epochRejected<<",\"past_Loop_snapshot_requery_API\":false,\"Loop_terminal_evidence\":\"client-owned Clear/Stop snapshots; FinalOperationAudit has no Loop request span\",\"seek_checkpoints\":false,\"prewarm_requests\":0,\"callback_gate\":false,\"detailed_profile\":\"OFF\",\"stage_hash\":\"library default, separate from detailed profile\",\"independent_PCM\":\"PENDING\",\"quality_approval\":false,\"RT_deadline_approval\":false,\"public_approved\":false,\"physical_audio\":null,\"application_F\":null,\"error\":"<<wab58::jsonString(error)<<"}\n";f.close();require(bool(f),"summary write");}
 {std::ofstream f(out/"PROCESS_COST.json");f<<std::setprecision(17)<<"{\"whole_client_through_close_and_capture\":";wabCostJson(f,wholeBegin,primaryComplete?primaryEnd:wholeEnd);
  const auto cost=[&](const char* key,bool have,const WabCost& begin,const WabCost& end){f<<",\""<<key<<"\":";if(have)wabCostJson(f,begin,end);else f<<"null";};
  cost("prepare_to_final_analysis",haveAnalysis,prepareBegin,analysisReady);cost("initial_ReturnToA",haveSetup,initialOn,initialAligned);cost("initial_setup_to_Paused_Clear",haveSetup,prepareBegin,setupPaused);
  cost("setup_capture_archive_and_reset",haveArchive,archiveBegin,archiveEnd);cost("normal_Play_to_C_ge_B",haveC,normalPlay,atC);cost("reON_to_first_A_observed",haveFirst,on,firstObserved);cost("reON_through_two_cycles_Paused",haveFinish,on,finish);
  cost("reservation_reacquisition_probe",haveProbe,probeBegin,probeEnd);cost("whole_client_including_probe",true,wholeBegin,wholeEnd);
  f<<",\"reservation_probe_excluded_from_primary_costs\":true,\"reservation_after_Stop_is_saved_estimate\":true";
  f<<",\"clock\":\"native accepted/first callback use mach monotonic ns; interval wall uses steady_clock; no cross-clock subtraction\",\"thread_CPU\":\"control thread only\",\"process_CPU\":\"RUSAGE_SELF all process threads\",\"whole_scope\":\"after preflight SHA and host capture allocation through original close, RAW export and postflight SHA ending before separate reservation probe; final JSON/artifact hashing excluded\",\"includes_capture_IO_in_whole\":true,\"setup_excluded_from_warm_latency\":true,\"physical_audio\":null}\n";f.close();require(bool(f),"cost write");}
 {std::ofstream f(out/"FINAL_AUDIT.json");f<<std::boolalpha<<"{\"calls\":"<<audit.calls<<",\"engine_serial\":"<<audit.serial<<",\"preparation\":"<<audit.preparation<<",\"workers_joined\":"<<audit.joined<<",\"retirement_complete\":"<<audit.retired<<",\"callback_delivery\":"<<audit.callback<<",\"failed\":"<<audit.failed<<",\"configured\":"<<audit.configured<<",\"seek_rows\":"<<audit.seeks<<",\"stopped_rows\":"<<audit.stopped<<",\"Loop_speed_rows\":"<<audit.speeds<<",\"preparation_rows\":"<<audit.preparations<<",\"epoch_calls\":"<<audit.epochCalls<<",\"epoch_rejected\":"<<audit.epochRejected<<",\"epochs\":[";
  for(std::size_t i=0;i<audit.epochs.size();++i){const auto& p=audit.epochs[i];f<<(i?",":"")<<"{\"engine_serial\":"<<p.serial<<",\"preparation\":"<<p.preparation<<",\"sequence\":"<<p.sequence<<",\"epoch\":"<<p.epoch<<",\"session\":"<<p.session<<",\"generation\":"<<p.generation<<",\"ordinary_speed_rows\":"<<p.ordinary<<",\"prepared_only\":"<<p.prepared<<",\"workers_joined\":"<<p.joined<<",\"callback_released\":"<<p.released<<'}';}f<<"]}\n";f.close();require(bool(f),"final audit write");}
 {std::ofstream f(out/"REFERENCE_RECIPE.json");f<<"{\"capture_folders\":[\"setup\",\"warm\"],\"validator\":\"results/progressive_adoption/recipes/validate_capture.py\",\"required_reference_binary_sha256\":\"de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748\",\"input\":"<<wab58::jsonString(std::filesystem::absolute(input).string())<<",\"input_sha256\":"<<wab58::jsonString(inputSha)<<",\"preset\":"<<wab58::jsonString(preset)<<",\"speed_micros\":1000000,\"queries\":["<<a<<','<<b<<"],\"reference_map_input_positions\":["<<a<<','<<b<<"],\"reference_raw_scope\":\"independent fixed full INPUT RAW, not loop-only RAW\",\"reference_generation\":\"separate process using saved frozen oracle; never product finalMap\",\"row_capacity\":65536,\"unchanged_validator_row_limit\":8192,\"over_validator_limit\":\"BLOCKED, not PASS; do not truncate raw/spans\",\"quality_approval\":false}\n";f.close();require(bool(f),"reference recipe write");}
 {std::vector<std::filesystem::path> paths;for(const auto& p:std::filesystem::recursive_directory_iterator(out))if(p.is_regular_file()&&p.path().filename()!="ARTIFACTS.json")paths.push_back(p.path());std::sort(paths.begin(),paths.end());std::ofstream f(out/"ARTIFACTS.json");f<<"{\"schema\":1,\"artifacts\":[";for(std::size_t i=0;i<paths.size();++i)f<<(i?",":"")<<"{\"path\":"<<wab58::jsonString(std::filesystem::relative(paths[i],out).string())<<",\"bytes\":"<<std::filesystem::file_size(paths[i])<<",\"sha256\":"<<wab58::jsonString(wabHash(paths[i]))<<'}';f<<"]}\n";f.close();require(bool(f),"artifact hashes write");}
 if(!completed)return 1;if(!warmExercised)return 3;return rt&&latencyPass?0:2;
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=wabMain(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return result;}
