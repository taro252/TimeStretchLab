// C1 isolated planning client draft. ビルド/反復実行は主担当が行う。
// CLI: INPUT.wav candidate|baseline 0|4|8 30|300|600 NEW_OUTPUT SOURCE_SHA
// 入力先頭の指定秒を、一つのProgressiveAnalysisSessionへ32768フレームずつ供給。
// 例: bench chain_600s.wav candidate 4 300 B/new_case <64桁source SHA>
// TS_INCREMENTAL_PLANNER_METRICS=0: B04旧header/旧archive、constructor 5引数。
// TS_INCREMENTAL_PLANNER_METRICS=1: C1候補header/archive、6引数(diag replay=false)。
// 同一sourceを二通りcompileする。旧版にない統計はnull。0として代用しない。
// update/planのthread CPUとwallだけを合計。解析append/finish/入力copy/hash/JSONは除外。
// page/index copyとmaterializeは各対象の計数。Phase39内部の全copy量ではない。
// planning scratchは保守payload推定上限。RSS/allocator実測ではない。
// confirmPlanは別計測。後の別process n3 driverで全process費用も記録できる。
// Frontierは全0の座標専用fixture。実DSPのOLA/FIR/PCM状態を再現していない。
// published=前completion+8192、logicalPresented=published。全target>=.5。
// 4件は10/30/50/70%で要求。8件は各閾値2件を順次。Pendingは次snapshotで同ID再試行。
// PCM、実時間、音質、主観、実アプリFの承認はすべてfalse。
#include "prototype/Phase59ProgressiveTransition.h"
#include "prototype/Phase45PcmDigest.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <bit>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <time.h>
#include <type_traits>
#include <vector>
#ifndef TS_INCREMENTAL_PLANNER_METRICS
#error "TS_INCREMENTAL_PLANNER_METRICS must be explicitly 0 or 1"
#endif
#if TS_INCREMENTAL_PLANNER_METRICS != 0 && TS_INCREMENTAL_PLANNER_METRICS != 1
#error "TS_INCREMENTAL_PLANNER_METRICS must be 0 or 1"
#endif

namespace {
namespace fs=std::filesystem;
namespace p56=ts::prototype::phase56;
namespace p59=ts::prototype::phase59;
using ts::prototype::Phase45PcmDigest;
constexpr std::uint64_t inputGeneration=73;
constexpr std::uint32_t initialSpeed=1000000;
constexpr std::size_t chunk=32768;
void need(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
std::string quote(const std::string& value){
 std::ostringstream f;f<<'"';for(unsigned char c:value){if(c=='"'||c=='\\')f<<'\\'<<char(c);else if(c<32)f<<"\\u00"<<std::hex<<std::setw(2)<<std::setfill('0')<<unsigned(c)<<std::dec;else f<<char(c);}f<<'"';return f.str();
}
std::string fileSha(const fs::path& path){
 std::ifstream f(path,std::ios::binary);need(bool(f),"SHA input absent");Phase45PcmDigest h;std::array<char,65536> b{};
 while(f.read(b.data(),b.size())||f.gcount())h.update(b.data(),std::size_t(f.gcount()));need(f.eof(),"SHA read");return h.finish();
}
double threadCpu(){timespec t{};need(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t)==0,"thread CPU clock");return double(t.tv_sec)+double(t.tv_nsec)*1e-9;}
double wall(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
struct Cost{std::size_t calls=0;double cpu=0,elapsed=0,maxCpu=0,maxWall=0;};
template<class F>void measure(Cost& cost,F&& fn){
 const auto c=threadCpu(),w=wall();
 const auto finish=[&]{const auto dw=wall()-w,dc=threadCpu()-c;need(std::isfinite(dw)&&std::isfinite(dc)&&dw>=0&&dc>=0,"nonfinite/negative clocks");++cost.calls;cost.cpu+=dc;cost.elapsed+=dw;cost.maxCpu=std::max(cost.maxCpu,dc);cost.maxWall=std::max(cost.maxWall,dw);};
 try{fn();}catch(...){finish();throw;}finish();
}
void costJson(std::ostream& f,const Cost& c){f<<"{\"calls\":"<<c.calls<<",\"thread_cpu_s\":"<<c.cpu<<",\"wall_s\":"<<c.elapsed<<",\"max_thread_cpu_s\":"<<c.maxCpu<<",\"max_wall_s\":"<<c.maxWall<<'}';}
template<class T,std::size_t N>void arrayJson(std::ostream& f,const std::array<T,N>& a){f<<'[';for(std::size_t i=0;i<N;++i){f<<(i?",":"");if constexpr(std::is_floating_point_v<T>){need(std::isfinite(a[i]),"nonfinite decision value");f<<std::bit_cast<std::uint64_t>(a[i]);}else f<<a[i];}f<<']';}
void u64(Phase45PcmDigest& h,std::uint64_t value){std::array<unsigned char,8> b{};for(std::size_t i=0;i<b.size();++i)b[i]=static_cast<unsigned char>(value>>(8*i));h.update(b.data(),b.size());}
void eventHash(Phase45PcmDigest& h,const ts::TransientEvent& e){u64(h,e.onsetFrame);u64(h,e.peakFrame);u64(h,e.attackEndFrame);u64(h,e.endFrame);u64(h,std::bit_cast<std::uint32_t>(e.strength));}
template<class Map>std::string nodesSha(const Map& map){const auto& n=map.starts();Phase45PcmDigest h;for(std::size_t i=0;i<n.size();++i)u64(h,static_cast<std::uint64_t>(n[i]));return h.finish();}
template<class Map>std::string eventsSha(const Map& map){
 Phase45PcmDigest h;
#if TS_INCREMENTAL_PLANNER_METRICS
 for(std::size_t i=0;i<map.eventSeries().size();++i)eventHash(h,map.eventSeries().borrowedAt(i));
#else
 for(const auto& e:map.events())eventHash(h,e);
#endif
 return h.finish();
}
void decisionJson(std::ostream& f,const p59::PlanningResult& r){
 const auto& c=r.change;const auto& p=c.plan;const auto& q=c.request;const auto& b=c.boundary;const auto& d=c.density;
 need(std::isfinite(q.transitionOutputMs),"nonfinite transition duration");
 f<<"{\"status\":"<<int(r.status)<<",\"limit_reached\":"<<(r.limitReached?"true":"false")
  <<",\"plan\":{\"outcome\":"<<int(p.outcome)<<",\"requested_frame\":"<<p.requestedFrame<<",\"applied_frame\":"<<p.appliedFrame<<",\"ramp_end_frame\":"<<p.rampEndFrame
  <<",\"applied_output_sample\":"<<p.appliedOutputSample<<",\"completion_output_sample\":"<<p.completionOutputSample<<",\"protected_events_skipped\":"<<p.protectedEventsSkipped
  <<",\"protected_events_paused\":"<<(p.protectedEventsPaused?"true":"false")<<",\"first_mutable_frame\":"<<p.firstMutableFrame<<",\"first_safe_frame\":"<<p.firstSafeFrame
  <<",\"next_event_frame\":"<<p.nextEventFrame<<",\"protection_end_frame\":"<<p.protectionEndFrame<<",\"safe_frames_used\":"<<p.safeFramesUsed<<",\"held_frames\":"<<p.heldFrames<<'}'
  <<",\"request\":{\"generation\":"<<q.generation<<",\"target_micros\":"<<q.target.micros<<",\"requested_input_sample\":"<<q.requestedInputSample<<",\"published_output_sample\":"<<q.publishedOutputSample
  <<",\"transition_output_ms_bits_u64\":"<<std::bit_cast<std::uint64_t>(q.transitionOutputMs)<<'}'
  <<",\"boundary\":{\"legacy\":"<<b.legacy<<",\"precise\":"<<b.precise<<",\"processed_node\":";arrayJson(f,b.processedNode);f<<",\"consumed_ola\":";arrayJson(f,b.consumedOla);f<<",\"consumed_fir\":";arrayJson(f,b.consumedFir);
 f<<"},\"output_frames\":"<<c.outputFrames<<",\"density_input\":"<<c.densityInput<<",\"state_preserved\":"<<(c.statePreserved?"true":"false")<<",\"changes_density\":"<<(c.changesDensity?"true":"false")
  <<",\"density\":{\"safe\":"<<(d.safe?"true":"false")<<",\"input_sample\":"<<d.inputSample<<",\"maximum_hop\":";arrayJson(f,d.maximumHop);f<<",\"maximum_hop_step\":";arrayJson(f,d.maximumHopStep);
 f<<",\"minimum_weight_bits_u64\":";arrayJson(f,d.minimumWeight);f<<",\"minimum_local_speed_bits_u64\":";arrayJson(f,d.minimumLocalSpeed);f<<",\"maximum_local_speed_bits_u64\":";arrayJson(f,d.maximumLocalSpeed);
 f<<",\"reconstructed_history_mismatches\":";arrayJson(f,d.reconstructedHistoryMismatches);f<<",\"reconstructed_history_max_difference\":";arrayJson(f,d.reconstructedHistoryMaxDifference);
 f<<",\"actual_weight_bits_u64\":";arrayJson(f,d.actualWeight);f<<",\"predicted_actual_weight_bits_u64\":";arrayJson(f,d.predictedActualWeight);f<<",\"weight_prediction_absolute_error_bits_u64\":";arrayJson(f,d.weightPredictionAbsoluteError);
 f<<",\"candidates_tried\":"<<d.candidatesTried<<",\"candidate_decisions\":[";
 for(std::size_t i=0;i<d.candidateTimings.size();++i){const auto& v=d.candidateTimings[i];f<<(i?",":"")<<"{\"input_sample\":"<<v.inputSample<<",\"accepted\":"<<(v.accepted?"true":"false")<<",\"probed\":"<<(v.probed?"true":"false")<<'}';}
 f<<"]}}";
 // guard/candidateのwall/CPU/weightCheckSecondsは測定値で、決定fieldではない。
}
void statisticsJson(std::ostream& f,const p59::ProgressiveTransitionPlanner& planner){
#if TS_INCREMENTAL_PLANNER_METRICS
 const auto s=planner.statistics();
 f<<"{\"available\":true,\"updates\":"<<s.updates<<",\"fixed_event_visits\":"<<s.fixedEventVisits<<",\"fixed_appended_nodes\":"<<s.fixedAppendedNodes<<",\"dynamic_appended_nodes\":"<<s.dynamicAppendedNodes
  <<",\"materialized_nodes\":"<<s.materializedNodes<<",\"history_replays\":"<<s.historyReplays<<",\"diagnostic_replay_requests\":"<<s.diagnosticReplayRequests<<",\"diagnostic_comparisons\":"<<s.diagnosticComparisons
  <<",\"prefix_proof_pages\":"<<s.prefixProofPages<<",\"prefix_proof_nodes\":"<<s.prefixProofNodes<<",\"index_bytes_copied\":"<<s.indexBytesCopied<<",\"fixed_cache_entries\":"<<s.fixedCacheEntries
  <<",\"page_live_bytes\":"<<s.pageLiveBytes<<",\"page_peak_bytes\":"<<s.pagePeakBytes<<",\"page_copied_bytes\":"<<s.pageCopiedBytes
  <<",\"planning_scratch_estimated_peak_bytes\":"<<s.planningScratchEstimatedPeakBytes<<'}';
#else
 (void)planner;f<<"{\"available\":false,\"updates\":null,\"fixed_event_visits\":null,\"fixed_appended_nodes\":null,\"dynamic_appended_nodes\":null,\"materialized_nodes\":null,\"history_replays\":null,\"diagnostic_replay_requests\":null,\"diagnostic_comparisons\":null,\"prefix_proof_pages\":null,\"prefix_proof_nodes\":null,\"index_bytes_copied\":null,\"fixed_cache_entries\":null,\"page_live_bytes\":null,\"page_peak_bytes\":null,\"page_copied_bytes\":null,\"planning_scratch_estimated_peak_bytes\":null}";
#endif
}
struct Request{std::uint64_t id=0;std::uint32_t target=0;unsigned percent=0;std::size_t due=0,firstAttempt=0,pending=0,published=0;bool started=false;};
int run(int argc,char** argv){
 need(argc==7,"INPUT PRESET 0|4|8 30|300|600 NEW_OUTPUT SOURCE_SHA");const fs::path input=argv[1],out=argv[5];const std::string preset=argv[2],sourceSha=argv[6];
 const auto expectedHistory=std::stoull(argv[3]),seconds=std::stoull(argv[4]);need(preset=="candidate"||preset=="baseline","preset");
 need(expectedHistory==0||expectedHistory==4||expectedHistory==8,"history count");need(seconds==30||seconds==300||seconds==600,"prefix seconds");
 need(sourceSha.size()==64&&std::all_of(sourceSha.begin(),sourceSha.end(),[](unsigned char c){return std::isxdigit(c);}),"source SHA");
 need(!fs::exists(out)&&fs::create_directories(out),"fresh output required");ts::WavStreamReader reader(input);const auto rate=reader.sampleRate();const auto channels=reader.channels();const auto frames=std::size_t(seconds)*rate;
 need((rate==44100||rate==48000)&&(channels==1||channels==2)&&reader.frames()>=frames,"input rate/channels/length");
 const auto inputSha=fileSha(input);const auto binarySha=fileSha(fs::absolute(argv[0]));const bool candidate=preset=="candidate";
 p56::AnalysisLimits limits;limits.maxInputFrames=frames;
 p56::ProgressiveAnalysisSession analysis(rate,channels,inputGeneration,limits,std::vector<std::uint32_t>{initialSpeed});
#if TS_INCREMENTAL_PLANNER_METRICS
 p59::ProgressiveTransitionPlanner planner(rate,frames,inputGeneration,initialSpeed,candidate,false);
#else
 p59::ProgressiveTransitionPlanner planner(rate,frames,inputGeneration,initialSpeed,candidate);
#endif
 Cost updates,plans,confirms;std::size_t received=0,appendCalls=0,next=0,nonfinalApplied=0,historyUpdates=0,totalPending=0;std::size_t previousCompletion=0;
 std::vector<Request> requests;requests.reserve(expectedHistory);constexpr std::array<std::uint32_t,4> targets{500000,750000,1500000,2000000};constexpr std::array<unsigned,4> progress{10,30,50,70};
 for(std::size_t i=0;i<expectedHistory;++i){const auto pct=progress[expectedHistory==8?i/2:i];requests.push_back({i+1,targets[i%targets.size()],pct,(frames*pct+99)/100});}
 std::ofstream decisions(out/"decisions.jsonl"),attempts(out/"attempts.jsonl"),observations(out/"observations.jsonl");decisions<<std::setprecision(17);attempts<<std::setprecision(17);observations<<std::setprecision(17);
 std::string reason;bool success=false;
 const auto summary=[&]{
  std::ofstream f(out/"SUMMARY.json");f<<std::setprecision(17)<<"{\"schema\":\"performance-planning-bench-v1\",\"status\":"<<quote(success?"PASS":"FAIL")<<",\"run_complete\":"<<(success?"true":"false")
   <<",\"source\":"<<quote(sourceSha)<<",\"preset\":"<<quote(preset)<<",\"metrics_compiled\":"<<(TS_INCREMENTAL_PLANNER_METRICS?"true":"false")<<",\"diagnostic_replay\":false,\"input_sha256\":"<<quote(inputSha)<<",\"binary_sha256\":"<<quote(binarySha)
   <<",\"prefix_seconds\":"<<seconds<<",\"source_rate\":"<<rate<<",\"channels\":"<<channels<<",\"input_frames\":"<<frames<<",\"received_frames\":"<<received<<",\"chunk_frames\":"<<chunk<<",\"append_calls\":"<<appendCalls
   <<",\"expected_history\":"<<expectedHistory<<",\"applied_history\":"<<planner.historyCount()<<",\"nonfinal_applied\":"<<nonfinalApplied<<",\"updates_with_committed_history\":"<<historyUpdates<<",\"pending_attempts\":"<<totalPending
   <<",\"update\":";costJson(f,updates);f<<",\"plan\":";costJson(f,plans);f<<",\"confirm\":";costJson(f,confirms);
  f<<",\"planner_update_plan_thread_cpu_s\":"<<updates.cpu+plans.cpu<<",\"planner_update_plan_wall_s\":"<<updates.elapsed+plans.elapsed
   <<",\"planner_transaction_thread_cpu_s\":"<<updates.cpu+plans.cpu+confirms.cpu<<",\"planner_transaction_wall_s\":"<<updates.elapsed+plans.elapsed+confirms.elapsed<<",\"map_bytes_final\":"<<planner.mapBytes()<<",\"statistics\":";statisticsJson(f,planner);
  f<<",\"reason\":"<<quote(reason)<<",\"analysis_append_cpu_included\":false,\"hash_json_cpu_included\":false,\"constructor_destructor_cpu_included\":false,\"clock_overhead_subtracted\":false,\"frontier\":\"zero coordinate-only fixture\",\"PCM_approval\":false,\"realtime_approval\":false,\"subjective_approval\":false,\"application_F_approval\":false}\n";f.close();need(bool(f),"summary write");
 };
 try{
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"schema\":\"performance-planning-bench-v1\",\"source\":"<<quote(sourceSha)<<",\"preset\":"<<quote(preset)<<",\"initial_speed_micros\":"<<initialSpeed<<",\"expected_history\":"<<expectedHistory<<",\"requests\":[";
   for(std::size_t i=0;i<requests.size();++i){const auto& q=requests[i];f<<(i?",":"")<<"{\"id\":"<<q.id<<",\"target_micros\":"<<q.target<<",\"progress_percent\":"<<q.percent<<",\"due_input_frames\":"<<q.due<<'}';}
   f<<"],\"input_file\":"<<quote(fs::absolute(input).string())<<",\"input_file_sha256\":"<<quote(inputSha)<<",\"input_file_frames\":"<<reader.frames()<<",\"prefix_frames\":"<<frames<<",\"prefix_seconds\":"<<seconds<<",\"chunk_frames\":"<<chunk
    <<",\"frontier\":\"all fields zero; coordinate only; no actual DSP history\",\"published_policy\":\"previous completion + 8192; first completion=0\",\"requested_speeds_in_analysis\":[1000000],\"diagnostic_replay\":false,\"PCM_approval\":false,\"realtime_approval\":false,\"subjective_approval\":false}\n";need(bool(f),"expected write");}
  // 一つの実入力producer。解析append/copyとsnapshot取得はplanner計測の外。
  std::array<std::vector<float>,2> buffer;std::array<const float*,2> pointers{};
  for(std::size_t c=0;c<channels;++c){buffer[c].resize(chunk);pointers[c]=buffer[c].data();}
  const ts::prototype::Phase36StreamingSpeedEngine::Frontier frontier{};
  const auto handleSnapshot=[&](const std::shared_ptr<const p56::AnalysisSnapshot>& snapshot){
   need(snapshot&&!snapshot->hasError&&!snapshot->isCancelled&&snapshot->receivedInputFrames==received,"analysis snapshot error");
   if(planner.historyCount())++historyUpdates;
   measure(updates,[&]{planner.update(snapshot);});
   while(next<requests.size()&&received>=requests[next].due){
    auto& q=requests[next];if(!q.started){q.started=true;q.firstAttempt=received;q.published=previousCompletion+8192;}
    p59::PlanningResult result;measure(plans,[&]{result=planner.plan({q.target},q.id,q.published,q.published,frontier);});
    attempts<<"{\"id\":"<<q.id<<",\"received\":"<<received<<",\"certified_nodes\":"<<snapshot->mapThroughNode<<",\"final\":"<<(snapshot->isFinal?"true":"false")<<",\"status\":"<<int(result.status)<<",\"published\":"<<q.published<<"}\n";
    if(result.status==p59::PlanningStatus::PendingAnalysis){++q.pending;++totalPending;need(!snapshot->isFinal,"Pending at final analysis");break;}
    // 全Decidedの決定fieldを出力。採用されなかった場合も隠さずFAILとする。
    decisions<<"{\"id\":"<<q.id<<",\"trigger_percent\":"<<q.percent<<",\"first_attempt_received\":"<<q.firstAttempt<<",\"decided_received\":"<<received<<",\"pending_attempts\":"<<q.pending<<",\"published\":"<<q.published<<",\"final_snapshot\":"<<(snapshot->isFinal?"true":"false")<<",\"decision\":";decisionJson(decisions,result);decisions<<"}\n";decisions.flush();need(bool(decisions)&&bool(attempts),"decision write");
    need(result.change.plan.applied()&&!result.limitReached,"scheduled valid target was not Applied");
    measure(confirms,[&]{planner.confirmPlan(true);});
    need(result.change.plan.completionOutputSample>=0,"negative completion");previousCompletion=std::size_t(result.change.plan.completionOutputSample);
    if(!snapshot->isFinal)++nonfinalApplied;++next;
    const auto v=planner.view();need(bool(v),"applied map absent");observations<<"{\"after_request_id\":"<<q.id<<",\"received\":"<<received<<",\"history\":"<<planner.historyCount()<<",\"node_count\":"<<v->map.starts().size()<<",\"all_nodes_i64le_sha256\":"<<quote(nodesSha(v->map))<<",\"statistics\":";statisticsJson(observations,planner);observations<<"}\n";
   }
  };
  while(received<frames){
   const auto amount=std::min(chunk,frames-received);
   for(std::size_t c=0;c<channels;++c)for(std::size_t i=0;i<amount;++i){const auto value=reader.sample(c,received+i);need(std::isfinite(value),"nonfinite input sample");buffer[c][i]=value;}
   analysis.appendInput(inputGeneration,received,pointers.data(),amount);received+=amount;++appendCalls;
   handleSnapshot(analysis.getSnapshot());
  }
  analysis.finishInput(inputGeneration);handleSnapshot(analysis.getSnapshot());
  need(next==expectedHistory&&planner.historyCount()==expectedHistory,"expected history not applied");
  if(expectedHistory)need(nonfinalApplied>0&&historyUpdates>0,"history did not exercise incremental analysis extensions");
  const auto view=planner.view();need(view&&view->final&&view->receivedInput==frames&&view->inputGeneration==inputGeneration,"final map identity");
  const auto& nodes=view->map.starts();need(nodes.size()==view->certifiedNodes&&nodes.size()>=2,"final map extent");
  for(std::size_t i=1;i<nodes.size();++i)need(nodes[i]>=nodes[i-1],"nonmonotonic final map");
  {std::ofstream f(out/"final_map.jsonl");f<<"{\"node_encoding\":\"signed int64 little-endian, nodes only in order\",\"all_nodes_sha256\":"<<quote(nodesSha(view->map))<<",\"all_events_sha256\":"<<quote(eventsSha(view->map))
   <<",\"source_hop\":"<<view->map.sourceHop()<<",\"node_count\":"<<nodes.size()<<",\"certified_nodes\":"<<view->certifiedNodes<<",\"first_node\":"<<nodes[0]<<",\"last_node\":"<<nodes.back()<<",\"input_generation\":"<<view->inputGeneration<<",\"version\":"<<view->version<<",\"base_version\":"<<view->baseVersion<<",\"first_changed_node\":"<<view->firstChangedNode
   <<",\"received_input\":"<<view->receivedInput<<",\"output_frames\":"<<view->outputFrames<<",\"final\":true,\"has_transitions\":"<<(view->hasTransitions?"true":"false")<<",\"density_modes\":[";for(std::size_t i=0;i<view->modes.size();++i)f<<(i?",":"")<<"["<<view->modes[i].first<<','<<(view->modes[i].second?"true":"false")<<']';f<<"]}\n";need(bool(f),"final map write");}
#if TS_INCREMENTAL_PLANNER_METRICS
  {const auto s=planner.statistics();need(s.updates==updates.calls&&s.historyReplays==0&&s.diagnosticReplayRequests==0&&s.diagnosticComparisons==0&&s.fixedCacheEntries<=5,"incremental normal path statistics");}
#endif
  decisions.close();attempts.close();observations.close();need(bool(decisions)&&bool(attempts)&&bool(observations),"JSONL close");
  need(fileSha(input)==inputSha&&fileSha(fs::absolute(argv[0]))==binarySha,"input/binary changed during process");
  success=true;summary();
  {std::ofstream f(out/"ARTIFACTS.json");f<<"{\"files\":[";bool first=true;for(const auto* name:{"EXPECTED.json","SUMMARY.json","decisions.jsonl","attempts.jsonl","observations.jsonl","final_map.jsonl"}){const auto path=out/name;f<<(first?"":",")<<"{\"path\":"<<quote(name)<<",\"bytes\":"<<fs::file_size(path)<<",\"sha256\":"<<quote(fileSha(path))<<'}';first=false;}f<<"]}\n";need(bool(f),"artifacts write");}
  return 0;
 }catch(const std::exception& error){reason=error.what();success=false;try{summary();}catch(...){}std::cerr<<reason<<'\n';return 1;}
}
}
int main(int argc,char** argv){try{return run(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 2;}}
