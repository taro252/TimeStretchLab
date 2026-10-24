// C2独立端点試験。CLI: INPUT candidate|baseline NEW_OUTPUT SOURCE_SHA
// 30秒mono/stereo 44.1/48k、固定1.0倍。各Preset8check、2ch形式×2Preset=4program/32check。
// source未start→next作成→source.stop→next.startの順で共有producerを開始する。
// 旧ownerの最終producer4値と必要解析Readyを固定し、共有final解析の変化とは区別。
// ゲートは通常producerのInputAnalysisPublishedだけ。callback/音声出力/RAW品質承認なし。
#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase45PcmDigest.h"
#include "prototype/Phase58Diagnostics.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <bit>
#include <utility>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mach/mach.h>
#include <mach/thread_info.h>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {
namespace fs=std::filesystem;
namespace p58=ts::prototype::phase58;
using Clock=std::chrono::steady_clock;
using Pipeline=p58::RealtimePipeline;
void need(bool v,const char* message){if(!v)throw std::runtime_error(message);}
std::string quote(const std::string& value){std::ostringstream f;f<<'"';for(unsigned char c:value){if(c=='"'||c=='\\')f<<'\\'<<char(c);else if(c<32)f<<"\\u00"<<std::hex<<std::setw(2)<<std::setfill('0')<<unsigned(c)<<std::dec;else f<<char(c);}f<<'"';return f.str();}
std::string sha(const fs::path& path){std::ifstream f(path,std::ios::binary);need(bool(f),"SHA input");ts::prototype::Phase45PcmDigest h;std::array<char,65536> b{};while(f.read(b.data(),b.size())||f.gcount())h.update(b.data(),std::size_t(f.gcount()));need(f.eof(),"SHA read");return h.finish();}
bool threadAlive(std::uint64_t wanted){
 thread_act_array_t threads=nullptr;mach_msg_type_number_t count=0;need(task_threads(mach_task_self(),&threads,&count)==KERN_SUCCESS,"thread enumeration");bool alive=false,error=false;
 for(mach_msg_type_number_t i=0;i<count;++i){thread_identifier_info_data_t info{};mach_msg_type_number_t n=THREAD_IDENTIFIER_INFO_COUNT;
  const auto status=thread_info(threads[i],THREAD_IDENTIFIER_INFO,reinterpret_cast<thread_info_t>(&info),&n);
  if(status==KERN_SUCCESS)alive|=info.thread_id==wanted;else if(status!=MACH_SEND_INVALID_DEST&&status!=KERN_TERMINATED&&status!=KERN_INVALID_ARGUMENT)error=true;
  mach_port_deallocate(mach_task_self(),threads[i]);}
 vm_deallocate(mach_task_self(),reinterpret_cast<vm_address_t>(threads),count*sizeof(thread_t));need(!error,"thread identifier query");return alive;
}
struct AnalysisGate{
 std::mutex mutex;std::condition_variable changed;const std::size_t threshold;
 bool hit=false,released=false,timedOut=false;std::uint64_t generation=0,joiningSession=0,joiningAnalysis=0;std::size_t received=0,publishes=0,joinCalls=0;
 explicit AnalysisGate(std::size_t n):threshold(n){}
 static void control(void* context,p58::ControlTestPoint point,std::uint64_t generation,std::uint64_t received)noexcept{
  auto& g=*static_cast<AnalysisGate*>(context);std::unique_lock lock(g.mutex);
  if(point==p58::ControlTestPoint::InputAnalysisJoinWait){g.joiningAnalysis=generation;++g.joinCalls;g.changed.notify_all();return;}
  if(point!=p58::ControlTestPoint::InputAnalysisPublished)return;++g.publishes;
  if(g.hit||received<g.threshold)return;g.hit=true;g.generation=generation;g.received=received;g.changed.notify_all();
  if(!g.changed.wait_for(lock,std::chrono::seconds(30),[&]{return g.released;})){g.timedOut=true;g.released=true;g.changed.notify_all();}
 }
 static void lifecycle(void* context,p58::LifecycleTestPoint point,std::uint64_t session)noexcept{
  if(point!=p58::LifecycleTestPoint::Joining)return;auto& g=*static_cast<AnalysisGate*>(context);std::lock_guard lock(g.mutex);g.joiningSession=session;g.changed.notify_all();
 }
 void waitHit(){std::unique_lock lock(mutex);need(changed.wait_for(lock,std::chrono::seconds(20),[&]{return hit;}),"8s producer gate not reached");need(!timedOut&&!released,"producer gate released prematurely");}
 void waitJoining(std::uint64_t session){std::unique_lock lock(mutex);need(changed.wait_for(lock,std::chrono::seconds(10),[&]{return joiningSession==session;}),"normal owner Joining event missing");}
 void waitAnalysisJoin(std::uint64_t generation){std::unique_lock lock(mutex);need(changed.wait_for(lock,std::chrono::seconds(10),[&]{return joiningAnalysis==generation;}),"last analysis token cancellation missing");}
 void release()noexcept{std::lock_guard lock(mutex);released=true;changed.notify_all();}
 std::size_t at(){std::lock_guard lock(mutex);return received;}
 bool held(){std::lock_guard lock(mutex);return hit&&!released&&!timedOut;}
 bool timeout(){std::lock_guard lock(mutex);return timedOut;}
 std::pair<std::uint64_t,std::size_t> joinFacts(){std::lock_guard lock(mutex);return {joiningAnalysis,joinCalls};}
 ~AnalysisGate(){release();}
};
// このguardをPipelineとstopperの宣言より後に置く。例外時も必ず
// producer gate解除→stopper join→両owner stop/破棄の順になり、destructorを詰まらせない。
struct Cleanup{
 AnalysisGate& gate;std::unique_ptr<Pipeline>& source;std::unique_ptr<Pipeline>& next;std::thread& stopper;
 void run()noexcept{gate.release();if(stopper.joinable())stopper.join();try{if(next)next->stop();}catch(...){}try{if(source)source->stop();}catch(...){}next.reset();source.reset();}
 ~Cleanup(){run();}
};
template<class F>void waitFor(F&& f,std::chrono::seconds timeout,const char* why){const auto end=Clock::now()+timeout;while(!f()){need(Clock::now()<end,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
void ready(Pipeline& p){need(p.waitUntilReady(std::chrono::seconds(15)),p.failed()?p.diagnostics().error.c_str():"Ready timeout");}
void observation(std::ostream& f,const char* label,const Pipeline& p){const auto d=p.diagnostics();f<<"{\"label\":"<<quote(label)<<",\"final_analysis_available\":"<<(p.finalAnalysisAvailable()?"true":"false")<<",\"required_analysis_available\":"<<(p.requiredAnalysisAvailable()?"true":"false")<<",\"available\":"<<p.available();p58::writeDiagnostics(f,d);f<<"}\n";f.flush();need(bool(f),"observations write");}

constexpr std::array<const char*,8> checkIDs{
 "C2U01_unstarted_resident_fixture","C2U02_unstarted_seek_subscription",
 "C2U03_old_final_zero_producer","C2U04_first_producer_after_old_stop",
 "C2U05_early_Ready_old_facts_fixed","C2U06_shared_EOS_old_facts_fixed",
 "C2U07_last_token_joins_once","C2U08_all_resources_retired"};
void sameFinalProducer(const Pipeline& source,const p58::Diagnostics& frozen){
 const auto d=source.diagnostics();
 need(d.finalDataAvailable&&d.lifecycle==p58::LifecycleState::Finalized&&!d.failed,"retired source is no longer finalized");
 need(d.analysisProducerThread==frozen.analysisProducerThread&&d.analysisProducerStarts==frozen.analysisProducerStarts&&d.analysisProducerReceived==frozen.analysisProducerReceived&&std::bit_cast<std::uint64_t>(d.analysisProducerCpuS)==std::bit_cast<std::uint64_t>(frozen.analysisProducerCpuS),"retired source final producer facts changed");
 need(!d.requiredAnalysisReady&&!source.requiredAnalysisAvailable()&&!d.analysisDone,"retired source own analysis requirement became Ready");
 need(d.analysisThread==0&&d.dspThread==0&&d.consumed==0&&d.generated==0&&d.published==0&&!source.available(),"unstarted retired source created workers or PCM");
}
int run(int argc,char** argv){
 need(argc==5||argc==6,"INPUT PRESET NEW_OUTPUT SOURCE_SHA [--worker=workgroup]");const bool workgroup=argc==6&&std::string(argv[5])=="--worker=workgroup";need(argc==5||workgroup,"worker option");const fs::path input=argv[1],out=argv[3];const std::string preset=argv[2],sourceSha=argv[4];
 need(preset=="candidate"||preset=="baseline","preset");need(sourceSha.size()==64&&std::all_of(sourceSha.begin(),sourceSha.end(),[](unsigned char c){return std::isxdigit(c);}),"source SHA");
 need(!fs::exists(out)&&fs::create_directories(out),"fresh output required");ts::WavStreamReader wav(input);const auto rate=wav.sampleRate();const auto channels=wav.channels();
 need((rate==44100||rate==48000)&&(channels==1||channels==2)&&wav.frames()==rate*30ULL,"exactly 30s mono/stereo 44.1/48k input required");
 AnalysisGate gate(rate*8ULL);std::unique_ptr<Pipeline> source,next;std::thread stopper;Cleanup cleanup{gate,source,next,stopper};
 std::ofstream checks(out/"checks.jsonl"),observations(out/"observations.jsonl");need(bool(checks)&&bool(observations),"evidence open");
 const auto inputSha=sha(input),binarySha=sha(fs::absolute(argv[0]));std::size_t executed=0,outputStart=0;std::uint64_t producer=0,generation=0,consumerAnalysis=0,consumerDsp=0;bool complete=false;std::string reason;
 p58::Diagnostics oldFinal{},newFinal{};
 const auto pass=[&]{need(executed<checkIDs.size(),"extra check");checks<<"{\"id\":"<<quote(checkIDs[executed++])<<",\"status\":\"PASS\"}\n";checks.flush();need(bool(checks),"check write");};
 const auto summary=[&]{std::ofstream f(out/"SUMMARY.json");const auto owners=Pipeline::executionOwnerCounts();const auto joined=gate.joinFacts();f<<std::setprecision(17)<<"{\"status\":"<<quote(complete?"PASS":"FAIL")<<",\"run_complete\":"<<(complete?"true":"false")<<",\"expected\":"<<checkIDs.size()<<",\"executed\":"<<executed
  <<",\"worker\":"<<quote(workgroup?"workgroup":"standard")<<",\"mode\":\"unstarted_source_handoff\",\"preset\":"<<quote(preset)<<",\"source\":"<<quote(sourceSha)<<",\"input_sha256\":"<<quote(inputSha)<<",\"binary_sha256\":"<<quote(binarySha)<<",\"rate\":"<<rate<<",\"channels\":"<<channels<<",\"input_frames\":"<<wav.frames()<<",\"speed_micros\":1000000,\"target_input_frame\":"<<rate
  <<",\"input_generation\":"<<generation<<",\"producer_thread\":"<<producer<<",\"consumer_analysis_thread\":"<<consumerAnalysis<<",\"consumer_dsp_thread\":"<<consumerDsp<<",\"producer_gate_received\":"<<gate.at()<<",\"output_start_frame\":"<<outputStart
  <<",\"old_final_producer_thread\":"<<oldFinal.analysisProducerThread<<",\"old_final_producer_starts\":"<<oldFinal.analysisProducerStarts<<",\"old_final_producer_received\":"<<oldFinal.analysisProducerReceived<<",\"old_final_producer_cpu_s\":"<<oldFinal.analysisProducerCpuS<<",\"old_required_analysis_ready\":"<<(oldFinal.requiredAnalysisReady?"true":"false")
  <<",\"new_final_producer_thread\":"<<newFinal.analysisProducerThread<<",\"new_final_producer_starts\":"<<newFinal.analysisProducerStarts<<",\"new_final_producer_received\":"<<newFinal.analysisProducerReceived<<",\"new_final_producer_cpu_s\":"<<newFinal.analysisProducerCpuS<<",\"last_analysis_join_generation\":"<<joined.first<<",\"last_analysis_join_calls\":"<<joined.second
  <<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak<<",\"gate_timeout\":"<<(gate.timeout()?"true":"false")<<",\"reason\":"<<quote(reason)<<",\"callback_gate\":false,\"audio_output\":\"NOT_RUN\",\"independent_frozen_PCM\":\"NOT_RUN_LIFETIME_ONLY\",\"performance_approval\":false,\"realtime_approval\":false,\"quality_approval\":false,\"subjective_approval\":false}\n";need(bool(f),"summary write");};
 const auto artifacts=[&]{checks.flush();observations.flush();std::ofstream f(out/"ARTIFACTS.json");f<<"{\"files\":[";bool first=true;for(const auto* name:{"EXPECTED.json","SUMMARY.json","checks.jsonl","observations.jsonl"}){const auto path=out/name;if(!fs::exists(path))continue;f<<(first?"":",")<<"{\"path\":"<<quote(name)<<",\"bytes\":"<<fs::file_size(path)<<",\"sha256\":"<<quote(sha(path))<<'}';first=false;}f<<"]}\n";need(bool(f),"artifact write");};
 try{
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"schema\":1,\"expected\":"<<checkIDs.size()<<",\"required_ids\":[";for(std::size_t i=0;i<checkIDs.size();++i)f<<(i?",":"")<<quote(checkIDs[i]);f<<"],\"mode\":\"unstarted_source_handoff\",\"preset\":"<<quote(preset)<<",\"source\":"<<quote(sourceSha)<<",\"input\":"<<quote(fs::absolute(input).string())<<",\"input_sha256\":"<<quote(inputSha)<<",\"binary\":"<<quote(fs::absolute(argv[0]).string())<<",\"binary_sha256\":"<<quote(binarySha)
   <<",\"rate\":"<<rate<<",\"channels\":"<<channels<<",\"input_frames\":"<<wav.frames()<<",\"speed_micros\":1000000,\"target_input_frame\":"<<rate<<",\"analysis_gate_after_frames\":"<<rate*8ULL<<",\"analysis_chunk\":32768,\"normal_worker_only\":true,\"Standard\":"<<(workgroup?"false":"true")<<",\"resident_input\":true,\"seek_checkpoints\":false,\"expected_owner_peak_max\":2,\"old_final_producer_values\":[0,0,0,0],\"old_required_analysis_ready\":false,\"shared_final_analysis_may_change\":true,\"callback_gate\":false,\"audio_output\":\"NOT_RUN\",\"independent_frozen_PCM\":\"NOT_RUN_LIFETIME_ONLY\"}\n";need(bool(f),"expected write");}
  p58::Configuration config;config.speedMicros=1000000;config.candidate=preset=="candidate";config.residentInput=true;config.scheduling=workgroup?p58::WorkerScheduling::AudioWorkgroup:p58::WorkerScheduling::Standard;config.dynamicTransitions=workgroup;config.seekCheckpoints=false;config.verifyPcm=false;config.recordStageDigests=false;config.analysisChunk=32768;
  config.controlTestHooks={&gate,AnalysisGate::control,nullptr};config.lifecycleTestHooks={&gate,AnalysisGate::lifecycle,0};source=std::make_unique<Pipeline>(input,config);const auto first=source->diagnostics();generation=source->inputGeneration();
  need(first.lifecycle==p58::LifecycleState::Unstarted&&first.residentInputBytes>0&&generation&&first.analysisProducerThread==0&&first.analysisProducerStarts==0&&first.analysisProducerReceived==0&&std::isfinite(first.analysisProducerCpuS)&&first.analysisProducerCpuS==0&&!source->requiredAnalysisAvailable()&&!source->finalAnalysisAvailable()&&!source->available(),"unstarted resident source already has producer/PCM");observation(observations,"source_unstarted",*source);pass();
  next=source->createSeek(rate,1000000);const auto created=next->diagnostics();need(next->inputGeneration()==generation&&next->sessionID()!=source->sessionID()&&created.lifecycle==p58::LifecycleState::Unstarted&&created.reusedInput&&created.reusedAnalysis&&created.analysisProducerThread==0&&created.analysisProducerStarts==0&&!next->requiredAnalysisAvailable()&&!next->available(),"unstarted seek subscription identity/state");
  {const auto owners=Pipeline::executionOwnerCounts();need(owners.alive==2&&owners.peak<=2,"unstarted owner bound");}observation(observations,"replacement_unstarted",*next);pass();
  source->stop();oldFinal=source->diagnostics();need(oldFinal.finalDataAvailable&&oldFinal.lifecycle==p58::LifecycleState::Finalized&&oldFinal.cancelled&&!oldFinal.failed&&oldFinal.analysisProducerThread==0&&oldFinal.analysisProducerStarts==0&&oldFinal.analysisProducerReceived==0&&std::isfinite(oldFinal.analysisProducerCpuS)&&oldFinal.analysisProducerCpuS==0,"unstarted source final producer values were not zero");
  sameFinalProducer(*source,oldFinal);need(gate.joinFacts().second==0&&!source->finalAnalysisAvailable(),"old stop retired the held unstarted subscription");observation(observations,"source_final_before_producer_start",*source);pass();
  next->start();gate.waitHit();const auto gated=next->diagnostics();producer=gated.analysisProducerThread;need(gate.held()&&gated.analysisProducerStarts==1&&producer&&producer!=gated.analysisThread&&producer!=gated.dspThread&&threadAlive(producer)&&gated.inputGeneration==generation&&gated.analysisProducerReceived==gate.at()&&gate.at()>=rate*8ULL&&gate.at()<wav.frames()&&!next->finalAnalysisAvailable()&&!gated.analysisDone,"first producer did not start once under the retained subscription");
  sameFinalProducer(*source,oldFinal);observation(observations,"replacement_first_producer_gated",*next);observation(observations,"source_final_during_new_producer",*source);pass();
  ready(*next);const auto early=next->diagnostics();outputStart=next->outputStartFrame();consumerAnalysis=early.analysisThread;consumerDsp=early.dspThread;
  need(gate.held()&&next->requiredAnalysisAvailable()&&early.requiredAnalysisReady&&!next->finalAnalysisAvailable()&&!early.analysisDone&&early.consumed==outputStart&&early.published>outputStart&&next->available()>0&&!early.renderingRequested&&early.analysisProducerStarts==1&&early.analysisProducerThread==producer&&early.analysisProducerReceived==gate.at()&&consumerAnalysis&&consumerDsp&&consumerAnalysis!=producer&&consumerDsp!=producer,"replacement was not inert early Ready before final analysis");
  sameFinalProducer(*source,oldFinal);need(!source->finalAnalysisAvailable()&&gate.joinFacts().second==0,"old final/shared analysis observation changed before gate release");observation(observations,"replacement_prefix_Ready",*next);observation(observations,"source_final_at_prefix_Ready",*source);pass();
  gate.release();waitFor([&]{need(!next->failed(),"replacement failed after producer release");return next->finalAnalysisAvailable()&&next->diagnostics().analysisDone;},std::chrono::seconds(30),"retained producer did not reach EOS");const auto eos=next->diagnostics();
  need(eos.analysisProducerThread==producer&&eos.analysisProducerStarts==1&&eos.analysisProducerReceived==wav.frames()&&std::isfinite(eos.analysisProducerCpuS)&&eos.analysisProducerCpuS>=0&&eos.consumed==outputStart&&next->requiredAnalysisAvailable()&&source->finalAnalysisAvailable(),"shared producer final identity/progress or consumption differs");
  sameFinalProducer(*source,oldFinal);observation(observations,"replacement_shared_EOS",*next);observation(observations,"source_final_after_shared_EOS",*source);pass();
  next->stop();newFinal=next->diagnostics();need(newFinal.finalDataAvailable&&newFinal.lifecycle==p58::LifecycleState::Finalized&&!newFinal.failed&&newFinal.analysisDone&&newFinal.analysisProducerThread==producer&&newFinal.analysisProducerStarts==1&&newFinal.analysisProducerReceived==wav.frames()&&std::isfinite(newFinal.analysisProducerCpuS)&&newFinal.analysisProducerCpuS>=0&&newFinal.requiredAnalysisReady,"replacement final producer facts missing");
  waitFor([&]{return !threadAlive(producer)&&!threadAlive(consumerAnalysis)&&!threadAlive(consumerDsp);},std::chrono::seconds(2),"last token left producer/consumer workers alive");
  const auto joined=gate.joinFacts();need(joined.first==generation&&joined.second==1,"last analysis token did not perform exactly one join attempt");sameFinalProducer(*source,oldFinal);source->stop();next->stop();const auto repeated=next->diagnostics();
  need(repeated.analysisProducerThread==newFinal.analysisProducerThread&&repeated.analysisProducerStarts==newFinal.analysisProducerStarts&&repeated.analysisProducerReceived==newFinal.analysisProducerReceived&&std::bit_cast<std::uint64_t>(repeated.analysisProducerCpuS)==std::bit_cast<std::uint64_t>(newFinal.analysisProducerCpuS)&&gate.joinFacts().second==1,"repeated stop changed final producer facts or repeated join");
  observation(observations,"replacement_last_token_final",*next);observation(observations,"source_final_after_last_join",*source);pass();
  need(!oldFinal.missingFrames&&!oldFinal.rejectedWrites&&!newFinal.missingFrames&&!newFinal.rejectedWrites&&!oldFinal.failed&&!newFinal.failed&&!gate.timeout(),"final supply/failure audit");sameFinalProducer(*source,oldFinal);cleanup.run();const auto owners=Pipeline::executionOwnerCounts();
  need(!owners.alive&&owners.peak<=2&&producer&&!threadAlive(producer)&&!threadAlive(consumerAnalysis)&&!threadAlive(consumerDsp),"owner/producer lifetime leak");need(sha(input)==inputSha&&sha(fs::absolute(argv[0]))==binarySha,"input/binary mutation");pass();need(executed==checkIDs.size(),"fixed IDs incomplete");complete=true;summary();artifacts();return 0;
 }catch(const std::exception& error){reason=error.what();cleanup.run();try{summary();artifacts();}catch(...){}std::cerr<<reason<<'\n';return 1;}
}
}
int main(int argc,char** argv){try{return run(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 2;}}
