// C2独立Pipeline試験draft。実装ファイル/CMake/testsは変更しない。
// CLI: MODE INPUT candidate|baseline TARGET_MICROS NEW_OUTPUT SOURCE_SHA
// MODE: same changed cancel_seek last_stop unstarted_last final_fast final_loop final_eos
// same/changedは400000/1000000/2000000、補助modeは1000000のみ。
// 1 input/Preset: 6 suffix cases + 6補助 =12program/96check。
// mono/stereo×両Presetなら48program/384check。各起動は独立process。
// Standard/AudioWorkgroup+resident。RT昇格は要求せず、実機/性能承認は別。
// 普通Exactは1秒input、producerを8秒以上の公開直後で止めて先行Ready。
// 旧ownerをstop/joinしても新ownerのtokenがproducerを保持することを検査。
// suffix.f32はinterleaved Float32、実入力rate/channels。独立frozen全RAWの
// [outputStartFrame, outputFrames)とroot driverで全bit比較する（本clientは代用しない）。
// ゲートは通常producerだけ。pullAudio/callbackにゲート/待機は一切置かない。
#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase45PcmDigest.h"
#include "prototype/Phase58Diagnostics.h"
#include "audio/WavStream.h"
#include <array>
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
 bool hit=false,released=false,timedOut=false;std::uint64_t generation=0,joiningSession=0,joiningAnalysis=0;std::size_t received=0,publishes=0;
 explicit AnalysisGate(std::size_t n):threshold(n){}
 static void control(void* context,p58::ControlTestPoint point,std::uint64_t generation,std::uint64_t received)noexcept{
  auto& g=*static_cast<AnalysisGate*>(context);std::unique_lock lock(g.mutex);
  if(point==p58::ControlTestPoint::InputAnalysisJoinWait){g.joiningAnalysis=generation;g.changed.notify_all();return;}
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
 "C2P01_configuration_resident_fixture","C2P02_one_producer_gated_nonfinal",
 "C2P03_old_Ready_no_consumption","C2P04_prefix_Ready_or_preserved_final_rule",
 "C2P05_owner_token_handoff_or_cancellation","C2P06_producer_progress_or_last_join",
 "C2P07_complete_suffix_RAW_or_terminal_join","C2P08_all_resources_retired"};

int run(int argc,char** argv){
 need(argc==7||argc==8,"MODE INPUT PRESET TARGET_MICROS NEW_OUTPUT SOURCE_SHA [--worker=workgroup]");const bool workgroup=argc==8&&std::string(argv[7])=="--worker=workgroup";need(argc==7||workgroup,"worker option");const std::string mode=argv[1],preset=argv[3],sourceSha=argv[6];const fs::path input=argv[2],out=argv[5];const auto target=std::stoul(argv[4]);
 const bool suffix=mode=="same"||mode=="changed",cancel=mode=="cancel_seek",last=mode=="last_stop",unstarted=mode=="unstarted_last";
 const bool finalFast=mode=="final_fast",finalLoop=mode=="final_loop",finalEos=mode=="final_eos",compat=finalFast||finalLoop||finalEos;
 need(suffix||cancel||last||unstarted||compat,"mode");need(preset=="candidate"||preset=="baseline","preset");need(target==400000||target==1000000||target==2000000,"fixed target speeds");need(suffix||target==1000000,"auxiliary representative target=1 only");
 need(sourceSha.size()==64&&std::all_of(sourceSha.begin(),sourceSha.end(),[](unsigned char c){return std::isxdigit(c);}),"source SHA");need(!fs::exists(out)&&fs::create_directories(out),"fresh output required");
 ts::WavStreamReader wav(input);const auto rate=wav.sampleRate();const auto channels=wav.channels();need((rate==44100||rate==48000)&&(channels==1||channels==2)&&wav.frames()>=rate*30ULL&&wav.frames()<=rate*600ULL,"30..600s mono/stereo 44.1/48k input");
 AnalysisGate gate(rate*8ULL);std::unique_ptr<Pipeline> source,next;std::thread stopper;
 // stopperが参照する結果変数もguardより先に置き、例外時のjoinまで生存させる。
 std::atomic<bool> stopDone{false};std::exception_ptr stopError;Cleanup cleanup{gate,source,next,stopper};
 std::ofstream checks(out/"checks.jsonl"),observations(out/"observations.jsonl");std::size_t executed=0,captured=0,earlyFrames=0,outputStart=0,outputFrames=0;std::uint64_t producer=0,generation=0;bool complete=false;std::string reason,rawSha;
 p58::Diagnostics oldFinal{},newFinal{};const auto inputSha=sha(input),binarySha=sha(fs::absolute(argv[0]));
 const auto pass=[&]{need(executed<checkIDs.size(),"extra check");checks<<"{\"id\":"<<quote(checkIDs[executed++])<<",\"status\":\"PASS\"}\n";checks.flush();need(bool(checks),"check write");};
 const auto summary=[&]{std::ofstream f(out/"SUMMARY.json");const auto owners=Pipeline::executionOwnerCounts();f<<std::setprecision(17)<<"{\"status\":"<<quote(complete?"PASS":"FAIL")<<",\"run_complete\":"<<(complete?"true":"false")<<",\"expected\":8,\"executed\":"<<executed
  <<",\"worker\":"<<quote(workgroup?"workgroup":"standard")<<",\"mode\":"<<quote(mode)<<",\"preset\":"<<quote(preset)<<",\"source\":"<<quote(sourceSha)<<",\"speed_micros\":"<<target<<",\"input_sha256\":"<<quote(inputSha)<<",\"binary_sha256\":"<<quote(binarySha)<<",\"rate\":"<<rate<<",\"channels\":"<<channels<<",\"input_frames\":"<<wav.frames()
  <<",\"producer_thread\":"<<producer<<",\"input_generation\":"<<generation<<",\"producer_gate_received\":"<<gate.at()<<",\"old_producer_starts\":"<<oldFinal.analysisProducerStarts<<",\"new_producer_starts\":"<<newFinal.analysisProducerStarts
  <<",\"producer_received_final\":"<<newFinal.analysisProducerReceived<<",\"producer_cpu_s_final\":"<<newFinal.analysisProducerCpuS<<",\"suffix_captured\":"<<(suffix?"true":"false")<<",\"suffix_frames\":"<<captured<<",\"prefix_PCM_before_final_frames\":"<<earlyFrames<<",\"output_start_frame\":"<<outputStart<<",\"output_frames\":"<<outputFrames<<",\"suffix_sha256\":"<<(rawSha.empty()?"null":quote(rawSha))
  <<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak<<",\"gate_timeout\":"<<(gate.timeout()?"true":"false")<<",\"reason\":"<<quote(reason)<<",\"callback_gate\":false,\"audio_output\":\"NOT_RUN\",\"independent_frozen_PCM\":\"ROOT_DRIVER_PENDING\",\"performance_approval\":false,\"realtime_approval\":false,\"quality_approval\":false,\"subjective_approval\":false}\n";need(bool(f),"summary write");};
 try{
  {std::ofstream f(out/"EXPECTED.json");f<<"{\"expected\":8,\"required_ids\":[";for(std::size_t i=0;i<checkIDs.size();++i)f<<(i?",":"")<<quote(checkIDs[i]);f<<"],\"mode\":"<<quote(mode)<<",\"target_input_frame\":"<<(finalEos?wav.frames():rate)<<",\"analysis_gate_after_frames\":"<<rate*8ULL<<",\"normal_worker_only\":true,\"Standard\":"<<(workgroup?"false":"true")<<",\"resident_input\":true,\"seek_checkpoints\":false,\"expected_owner_peak_max\":2,\"independent_frozen_PCM\":\"ROOT_DRIVER_PENDING\",\"audio_output\":\"NOT_RUN\"}\n";need(bool(f),"expected write");}
  p58::Configuration config;config.speedMicros=mode=="same"?target:target==1000000&&mode=="changed"?750000:1000000;config.candidate=preset=="candidate";config.residentInput=true;config.scheduling=workgroup?p58::WorkerScheduling::AudioWorkgroup:p58::WorkerScheduling::Standard;config.dynamicTransitions=workgroup;config.seekCheckpoints=false;config.verifyPcm=true;config.recordStageDigests=false;config.analysisChunk=32768;
  config.controlTestHooks={&gate,AnalysisGate::control,nullptr};config.lifecycleTestHooks={&gate,AnalysisGate::lifecycle,0};source=std::make_unique<Pipeline>(input,config);need(source->diagnostics().residentInputBytes>0,"resident bytes missing");pass();
  source->start();gate.waitHit();auto initial=source->diagnostics();producer=initial.analysisProducerThread;generation=initial.inputGeneration;
  need(gate.held()&&initial.analysisProducerStarts==1&&producer&&threadAlive(producer)&&generation&&initial.analysisProducerReceived==gate.at()&&!source->finalAnalysisAvailable()&&!initial.analysisDone,"producer nonfinal fixture");observation(observations,"old_at_8s_gate",*source);pass();
  ready(*source);const auto frozen=source->diagnostics();need(!frozen.consumed&&!frozen.renderingRequested&&source->available()>0&&!source->finalAnalysisAvailable(),"old Ready consumed or final");pass();
  // last_stopは旧単独ownerの最後のtokenを検証する。
  if(last){
   need(Pipeline::executionOwnerCounts().alive==1,"source-only owner count");pass();
   stopper=std::thread([&]{try{source->stop();}catch(...){stopError=std::current_exception();}stopDone=true;});gate.waitJoining(source->sessionID());
   gate.waitAnalysisJoin(generation);need(gate.held()&&threadAlive(producer)&&!stopDone.load()&&!source->diagnostics().finalDataAvailable,"last stop skipped producer join");pass();gate.release();stopper.join();if(stopError)std::rethrow_exception(stopError);
   waitFor([&]{return !threadAlive(producer);},std::chrono::seconds(2),"producer survives last source stop");oldFinal=source->diagnostics();newFinal=oldFinal;need(stopDone&&oldFinal.finalDataAvailable&&oldFinal.lifecycle==p58::LifecycleState::Finalized,"last source join incomplete");pass();
   need(!source->finalAnalysisAvailable()&&oldFinal.analysisProducerReceived==gate.at()&&oldFinal.cancelled&&!oldFinal.failed,"last stop did not cancel partial producer");observation(observations,"last_source_final",*source);pass();
  }else{
   if(finalFast)next=source->createFastLocalSeek(rate,target,rate/2);else if(finalLoop)next=source->createLoopSeek(rate,rate+rate/2,target);else next=source->createSeek(finalEos?wav.frames():rate,target);
   need(next->inputGeneration()==generation&&next->sessionID()!=source->sessionID(),"replacement identity");
   if(unstarted){need(next->diagnostics().lifecycle==p58::LifecycleState::Unstarted&&!next->available()&&!next->requiredAnalysisAvailable(),"unstarted token fixture");}
   else{
    next->start();if(compat){
     waitFor([&]{return next->diagnostics().analysisThread!=0;},std::chrono::seconds(5),"waiting consumer not started");
     need(!next->waitUntilReady(std::chrono::milliseconds(25))&&!next->requiredAnalysisAvailable()&&!next->finalAnalysisAvailable()&&!next->available(),"FastLocal/Loop/EOS bypassed final analysis");
    }else{
     ready(*next);const auto d=next->diagnostics();outputStart=next->outputStartFrame();
     need(gate.held()&&next->requiredAnalysisAvailable()&&d.requiredAnalysisReady&&!next->finalAnalysisAvailable()&&!d.analysisDone&&d.consumed==outputStart&&d.published>outputStart&&!d.renderingRequested&&d.reusedInput&&d.reusedAnalysis&&d.analysisProducerStarts==1&&d.analysisProducerThread==producer&&d.analysisProducerReceived==gate.at(),"ordinary Exact was not inert early Ready");
     need(source->diagnostics().consumed==frozen.consumed,"new preparation consumed old FIFO");
    }
   }
   observation(observations,"replacement_before_final",*next);pass();
   if(cancel){
    next->stop();newFinal=next->diagnostics();need(newFinal.finalDataAvailable&&newFinal.cancelled&&gate.held()&&threadAlive(producer)&&source->diagnostics().analysisProducerStarts==1&&!source->finalAnalysisAvailable(),"cancelled replacement cancelled shared producer");pass();
    gate.release();waitFor([&]{return source->finalAnalysisAvailable()&&!source->failed();},std::chrono::seconds(30),"old producer failed after replacement cancel");source->stop();oldFinal=source->diagnostics();
    waitFor([&]{return !threadAlive(producer);},std::chrono::seconds(2),"producer not joined after cancel case");need(oldFinal.analysisProducerStarts==1&&oldFinal.analysisProducerReceived==wav.frames()&&oldFinal.finalDataAvailable,"old survivor final analysis missing");pass();
    const auto d=next->diagnostics();need(d.analysisProducerReceived==newFinal.analysisProducerReceived&&d.analysisProducerCpuS==newFinal.analysisProducerCpuS&&d.finalDataAvailable,"cancelled owner final producer facts changed");observation(observations,"cancelled_next_final",*next);pass();
   }else{
    // tokenはconstructorから保持される。unstartedでも旧stopがproducerを止めない。
    source->stop();oldFinal=source->diagnostics();need(oldFinal.finalDataAvailable&&gate.held()&&threadAlive(producer)&&next->diagnostics().analysisProducerStarts==1&&next->diagnostics().analysisProducerThread==producer&&!next->finalAnalysisAvailable(),"old stop retired new owner's producer");pass();
    if(unstarted){
     stopper=std::thread([&]{try{next->stop();}catch(...){stopError=std::current_exception();}stopDone=true;});gate.waitJoining(next->sessionID());gate.waitAnalysisJoin(generation);need(gate.held()&&threadAlive(producer)&&!stopDone.load(),"unstarted last token skipped join");gate.release();stopper.join();if(stopError)std::rethrow_exception(stopError);
     waitFor([&]{return !threadAlive(producer);},std::chrono::seconds(2),"producer survives unstarted final token");newFinal=next->diagnostics();need(stopDone&&newFinal.finalDataAvailable&&newFinal.analysisProducerReceived==gate.at()&&!next->finalAnalysisAvailable(),"unstarted last token failed cancellation");pass();
     need(!next->available()&&!newFinal.failed&&newFinal.cancelled,"unstarted cancellation emitted PCM");observation(observations,"unstarted_next_final",*next);pass();
    }else{
     std::vector<float> earlyPcm;
     if(suffix){
      // Pipelineでの明示Resume相当は最初のpull。全解析前に一ブロック実際に
      // 消費し、そのPCMも同じ全suffix RAWへ保存する（callback/gateは使わない）。
      std::array<std::vector<float>,2> pcm;std::array<float*,2> ptr{};for(std::size_t c=0;c<channels;++c){pcm[c].resize(2048);ptr[c]=pcm[c].data();}
      const auto amount=std::min(std::size_t(2048),next->available());need(amount&&gate.held()&&!next->finalAnalysisAvailable(),"early RAW fixture");const auto r=next->pullAudio(ptr.data(),amount);
      need(r.received==amount&&r.wanted==amount&&r.outputBefore==outputStart,"early partial-analysis RAW gap");earlyPcm.resize(amount*channels);
      for(std::size_t i=0;i<amount;++i)for(std::size_t c=0;c<channels;++c){need(std::isfinite(pcm[c][i]),"nonfinite early PCM");earlyPcm[i*channels+c]=pcm[c][i];}earlyFrames=captured=amount;observation(observations,"explicit_first_pull_before_final",*next);
     }
     gate.release();waitFor([&]{need(!next->failed(),"replacement failed after old stop");return next->finalAnalysisAvailable();},std::chrono::seconds(30),"shared producer did not reach EOS after old stop");
     if(compat)ready(*next);const auto progressed=next->diagnostics();need(progressed.analysisProducerStarts==1&&progressed.analysisProducerThread==producer&&progressed.analysisProducerReceived==wav.frames(),"producer restarted or incomplete");pass();
     if(suffix){
      outputStart=next->outputStartFrame();outputFrames=std::size_t(std::llround(wav.frames()*(1.0/(double(target)/1000000.0))));need(outputStart==next->fixedOutputFrameForInput(rate)&&next->diagnostics().consumed==outputStart+captured,"certified prefix/final OA or early consumption differs");
      std::ofstream raw(out/"suffix.f32",std::ios::binary);ts::prototype::Phase45PcmDigest hash;std::array<std::vector<float>,2> pcm;std::array<float*,2> ptr{};for(std::size_t c=0;c<channels;++c){pcm[c].resize(2048);ptr[c]=pcm[c].data();}std::vector<float> interleaved(2048*channels);
      raw.write(reinterpret_cast<const char*>(earlyPcm.data()),earlyPcm.size()*sizeof(float));hash.update(earlyPcm.data(),earlyPcm.size()*sizeof(float));
      const auto until=Clock::now()+std::chrono::seconds(60+2*(wav.frames()/rate));
      while(!next->drained()){
       need(!next->failed()&&Clock::now()<until,"suffix EOS timeout/failure");const auto amount=std::min(std::size_t(2048),next->available());if(!amount){std::this_thread::sleep_for(std::chrono::milliseconds(1));continue;}
       const auto r=next->pullAudio(ptr.data(),amount);need(r.wanted==amount&&r.received==amount&&r.outputBefore==outputStart+captured,"suffix RAW gap/missing");
       for(std::size_t i=0;i<amount;++i)for(std::size_t c=0;c<channels;++c){need(std::isfinite(pcm[c][i]),"nonfinite suffix PCM");interleaved[i*channels+c]=pcm[c][i];}
       raw.write(reinterpret_cast<const char*>(interleaved.data()),amount*channels*sizeof(float));hash.update(interleaved.data(),amount*channels*sizeof(float));captured+=amount;
      }
      raw.close();need(bool(raw),"RAW write");rawSha=hash.finish();need(captured==outputFrames-outputStart&&next->finished()&&next->diagnostics().consumed==outputFrames,"full suffix frame length");next->stop();newFinal=next->diagnostics();
      need(newFinal.finalDataAvailable&&newFinal.dspDone&&newFinal.analysisDone&&!newFinal.failed&&newFinal.outputFrames==outputFrames&&newFinal.pcmSha256==rawSha&&sha(out/"suffix.f32")==rawSha,"EOS/final suffix hash mismatch");
      {std::ofstream f(out/"CAPTURE.json");f<<"{\"raw\":\"suffix.f32\",\"sha256\":"<<quote(rawSha)<<",\"format\":\"interleaved Float32 native little-endian\",\"rate\":"<<rate<<",\"channels\":"<<channels<<",\"speed_micros\":"<<target<<",\"preset\":"<<quote(preset)<<",\"input_sha256\":"<<quote(inputSha)<<",\"target_input_frame\":"<<rate<<",\"output_start_frame\":"<<outputStart<<",\"full_output_frames\":"<<outputFrames<<",\"suffix_frames\":"<<captured<<",\"frozen_comparison_recipe\":\"compare all bytes with independent fixed RAW [output_start_frame*channels*4, full_output_frames*channels*4)\",\"independent_comparison\":\"NOT_RUN\"}\n";need(bool(f),"capture metadata");}
     }else{if(finalEos)need(next->finished()&&!next->available()&&next->outputStartFrame()==next->fixedOutputFrameForInput(wav.frames()),"EOS final seek state");next->stop();newFinal=next->diagnostics();need(newFinal.finalDataAvailable&&!newFinal.failed,"final-only compatibility join");}
     waitFor([&]{return !threadAlive(producer);},std::chrono::seconds(2),"producer still alive after final next stop");const auto retained=source->diagnostics();need(retained.analysisProducerReceived==oldFinal.analysisProducerReceived&&retained.analysisProducerCpuS==oldFinal.analysisProducerCpuS&&retained.consumed==oldFinal.consumed&&retained.finalDataAvailable,"retired owner final facts changed");observation(observations,"next_complete_final",*next);pass();
    }
   }
  }
  need(!oldFinal.missingFrames&&!oldFinal.rejectedWrites&&!newFinal.missingFrames&&!newFinal.rejectedWrites&&!oldFinal.failed&&!newFinal.failed&&!gate.timeout(),"pipeline final supply/failure audit");cleanup.run();const auto owners=Pipeline::executionOwnerCounts();need(!owners.alive&&owners.peak<=2&&producer&&!threadAlive(producer),"owner/producer lifetime leak");need(sha(input)==inputSha&&sha(fs::absolute(argv[0]))==binarySha,"input/binary mutation");pass();need(executed==checkIDs.size(),"fixed IDs incomplete");complete=true;summary();
  checks.close();observations.close();{std::ofstream f(out/"ARTIFACTS.json");f<<"{\"files\":[";bool first=true;for(const auto* name:{"EXPECTED.json","SUMMARY.json","checks.jsonl","observations.jsonl","suffix.f32","CAPTURE.json"}){const auto path=out/name;if(!fs::exists(path))continue;f<<(first?"":",")<<"{\"path\":"<<quote(name)<<",\"bytes\":"<<fs::file_size(path)<<",\"sha256\":"<<quote(sha(path))<<'}';first=false;}f<<"]}\n";need(bool(f),"artifacts write");}return 0;
 }catch(const std::exception& error){reason=error.what();cleanup.run();try{summary();}catch(...){}std::cerr<<reason<<'\n';return 1;}
}
}
int main(int argc,char** argv){try{return run(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 2;}}
