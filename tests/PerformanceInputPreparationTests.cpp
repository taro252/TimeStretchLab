// C3: 入力準備の取消/絶対期限/資源回収。音声出力・callback・性能測定なし。
// MODE INPUT PRESET NEW_OUT SOURCE_SHA。
// pipeline: Standard workerのみ。engine_*は通常hookでconfigure前に止める。
// engine_ready_deadlineだけはPipelineのReady成功後に受付期限を跨ぐ。
#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase45PcmDigest.h"
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <libproc.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <unistd.h>

namespace {
namespace ip58=ts::prototype::phase58;
namespace ipp=ts::playback;
namespace fs=std::filesystem;
using InputClock=std::chrono::steady_clock;
using InputPoint=ip58::ControlTestPoint;
using InputPipeline=ip58::RealtimePipeline;
void inputNeed(bool value,const std::string& why){if(!value)throw std::runtime_error(why);}
std::string inputQuote(const std::string& value){
 std::string result="\"";for(unsigned char c:value){if(c=='\"'||c=='\\'){result+='\\';result+=char(c);}else if(c=='\n')result+="\\n";else if(c=='\r')result+="\\r";else if(c=='\t')result+="\\t";else if(c<32)result+='?';else result+=char(c);}return result+'\"';
}
std::string inputHash(const fs::path& path){
 std::ifstream stream(path,std::ios::binary);inputNeed(bool(stream),"hash input absent");ts::prototype::Phase45PcmDigest hash;std::array<char,65536> bytes{};
 while(stream.read(bytes.data(),bytes.size())||stream.gcount())hash.update(bytes.data(),std::size_t(stream.gcount()));inputNeed(stream.eof(),"hash read failed");return hash.finish();
}
const char* inputPointName(InputPoint point){switch(point){
 case InputPoint::InputCopyProgress:return "InputCopyProgress";case InputPoint::InputSamplesProgress:return "InputSamplesProgress";
 case InputPoint::InputResidentBefore:return "InputResidentBefore";case InputPoint::InputResidentAfter:return "InputResidentAfter";default:return "Other";}}
int inputPointIndex(InputPoint point){switch(point){case InputPoint::InputCopyProgress:return 0;case InputPoint::InputSamplesProgress:return 1;case InputPoint::InputResidentBefore:return 2;case InputPoint::InputResidentAfter:return 3;default:return -1;}}
struct InputResources {
 std::vector<std::pair<int,unsigned>> descriptors;
 std::uint64_t wiredRegions=0,wiredBytes=0,owners=0,ownerPeak=0;
};
InputResources inputResources(){
 InputResources value;std::array<proc_fdinfo,4096> fds{};
 const auto bytes=proc_pidinfo(getpid(),PROC_PIDLISTFDS,0,fds.data(),int(sizeof(fds)));
 inputNeed(bytes>0&&bytes<int(sizeof(fds))&&bytes%sizeof(proc_fdinfo)==0,"finite FD inventory unavailable");
 for(std::size_t i=0;i<std::size_t(bytes)/sizeof(proc_fdinfo);++i)value.descriptors.emplace_back(fds[i].proc_fd,fds[i].proc_fdtype);
 std::sort(value.descriptors.begin(),value.descriptors.end());
 mach_vm_address_t address=0;
 while(true){
  mach_vm_size_t size=0;vm_region_basic_info_data_64_t info{};mach_msg_type_number_t count=VM_REGION_BASIC_INFO_COUNT_64;mach_port_t object=MACH_PORT_NULL;
  const auto status=mach_vm_region(mach_task_self(),&address,&size,VM_REGION_BASIC_INFO_64,reinterpret_cast<vm_region_info_t>(&info),&count,&object);
  if(object!=MACH_PORT_NULL)mach_port_deallocate(mach_task_self(),object);
  if(status==KERN_INVALID_ADDRESS)break;inputNeed(status==KERN_SUCCESS&&size&&count==VM_REGION_BASIC_INFO_COUNT_64,"wired-region inventory unavailable");
  if(info.user_wired_count){++value.wiredRegions;value.wiredBytes+=size;}
  inputNeed(address+size>address,"region address overflow");address+=size;
 }
 const auto owners=InputPipeline::executionOwnerCounts();value.owners=owners.alive;value.ownerPeak=owners.peak;return value;
}
void inputReleased(const InputResources& baseline){
 const auto now=inputResources();inputNeed(now.descriptors==baseline.descriptors,"constructor leaked/replaced a file descriptor");
 inputNeed(now.wiredRegions==baseline.wiredRegions&&now.wiredBytes==baseline.wiredBytes,"constructor retained a wired mapping");
 inputNeed(!now.owners&&now.ownerPeak<=2,"constructor retained an execution owner/exceeded two");
}
struct InputEvent {InputPoint point;std::uint64_t session=0,offset=0;};
struct InputProbe {
 enum class Action {Observe,Cancel,Deadline};
 Action action=Action::Observe;InputPoint target=InputPoint::InputCopyProgress;std::uint64_t threshold=0;
 std::atomic<bool> cancelled{false};InputClock::time_point deadline{};
 std::vector<InputEvent> events;std::array<std::uint64_t,4> calls{},last{},maximumStep{};
 std::uint64_t session=0;bool triggered=false,error=false;InputResources during;
 InputProbe(){events.reserve(512);}
 static void event(void* context,InputPoint point,std::uint64_t session,std::uint64_t offset)noexcept{
  auto& p=*static_cast<InputProbe*>(context);const auto index=inputPointIndex(point);if(index<0)return;
  try{
   if(p.session&&p.session!=session)p.error=true;p.session=session;
   if(p.events.size()==p.events.capacity()){p.error=true;return;}p.events.push_back({point,session,offset});
   if(p.calls[index]&&offset<p.last[index])p.error=true;
   if(p.calls[index])p.maximumStep[index]=std::max(p.maximumStep[index],offset-p.last[index]);p.last[index]=offset;++p.calls[index];
   if(p.action!=Action::Observe&&!p.triggered&&point==p.target&&offset>=p.threshold){
    p.triggered=true;p.during=inputResources();
    if(p.action==Action::Cancel)p.cancelled=true;
    else while(InputClock::now()<p.deadline)std::this_thread::sleep_until(p.deadline);
   }
  }catch(...){p.error=true;p.cancelled=true;}
 }
};
void inputConfig(ip58::Configuration& config,bool candidate,InputProbe* probe=nullptr){
 config.speedMicros=1000000;config.candidate=candidate;config.residentInput=true;config.verifyPcm=false;config.seekCheckpoints=false;config.boundedEpochReservations=true;config.scheduling=ip58::WorkerScheduling::Standard;
 if(probe){config.controlTestHooks={probe,InputProbe::event,nullptr};config.inputPreparationCancel=&probe->cancelled;config.inputPreparationDeadline=probe->deadline;}
}
template<class Predicate>void inputWait(InputPipeline& pipeline,Predicate predicate,const char* why){
 const auto limit=InputClock::now()+std::chrono::seconds(12);while(!predicate()){inputNeed(!pipeline.failed(),pipeline.diagnostics().error);inputNeed(InputClock::now()<limit,why);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
}
void inputReady(InputPipeline& pipeline){pipeline.start();inputNeed(pipeline.waitUntilReady(std::chrono::seconds(12)),"normal pipeline not Ready: "+pipeline.diagnostics().error);inputWait(pipeline,[&]{return pipeline.finalAnalysisAvailable()&&pipeline.diagnostics().analysisDone;},"normal final analysis missing");}
void inputJoined(InputPipeline& pipeline){pipeline.stop();const auto d=pipeline.diagnostics();inputNeed(d.finalDataAvailable&&d.lifecycle==ip58::LifecycleState::Finalized&&!d.scheduling.active&&d.scheduling.joins==d.scheduling.leaves&&d.scheduling.leaves==d.scheduling.restores&&!d.missingFrames&&!d.missingCalls&&!d.rejectedWrites,"normal pipeline final join/supply contract");}
std::size_t inputDataOffset(const fs::path& path){
 std::ifstream stream(path,std::ios::binary);std::array<unsigned char,16> b{};stream.read(reinterpret_cast<char*>(b.data()),12);inputNeed(bool(stream)&&!std::memcmp(b.data(),"RIFF",4)&&!std::memcmp(b.data()+8,"WAVE",4),"RIFF fixture required");bool format=false;
 while(stream){stream.read(reinterpret_cast<char*>(b.data()),8);inputNeed(bool(stream),"WAV chunk absent");const auto size=std::uint32_t(b[4])|(std::uint32_t(b[5])<<8)|(std::uint32_t(b[6])<<16)|(std::uint32_t(b[7])<<24);const auto at=stream.tellg();
  if(!std::memcmp(b.data(),"fmt ",4)){inputNeed(size>=16,"fmt size");stream.read(reinterpret_cast<char*>(b.data()),16);inputNeed(bool(stream)&&b[0]==3&&!b[1]&&b[14]==32&&!b[15],"product IEEE Float32 fixture required");format=true;}
  else if(!std::memcmp(b.data(),"data",4)){inputNeed(format,"fmt must precede data");return std::size_t(at);}
  stream.seekg(at+std::streamoff(size)+std::streamoff(size&1));
 }throw std::runtime_error("fixture data missing");
}
void inputSaveProbe(std::ofstream& stream,const char* id,const InputProbe& probe,const InputResources& after,const std::string& reason){
 stream<<"{\"id\":"<<inputQuote(id)<<",\"session\":"<<probe.session<<",\"triggered\":"<<(probe.triggered?"true":"false")<<",\"exception\":"<<inputQuote(reason)
  <<",\"after_fd_count\":"<<after.descriptors.size()<<",\"after_wired_regions\":"<<after.wiredRegions<<",\"after_wired_bytes\":"<<after.wiredBytes<<",\"after_owners\":"<<after.owners<<",\"owner_peak\":"<<after.ownerPeak
  <<",\"during_owners\":"<<probe.during.owners<<",\"during_fd_count\":"<<probe.during.descriptors.size()<<",\"during_wired_regions\":"<<probe.during.wiredRegions<<",\"during_wired_bytes\":"<<probe.during.wiredBytes<<",\"events\":[";
 for(std::size_t i=0;i<probe.events.size();++i){const auto& e=probe.events[i];stream<<(i?",":"")<<"{\"point\":"<<inputQuote(inputPointName(e.point))<<",\"session\":"<<e.session<<",\"offset\":"<<e.offset<<'}';}stream<<"]}\n";stream.flush();inputNeed(bool(stream),"probe evidence write");
}
void inputFailure(const fs::path& input,bool candidate,InputProbe& probe,const InputResources& baseline,const char* expected,const char* id,std::ofstream& observations,bool triggered){
 ip58::Configuration config;inputConfig(config,candidate,&probe);std::string reason;
 try{InputPipeline unexpected(input,config);}catch(const std::runtime_error& error){reason=error.what();}
 inputNeed(!reason.empty()&&reason.find(expected)!=std::string::npos,"wrong/missing input-preparation exception: "+reason);
 inputNeed(!probe.error&&probe.session&&probe.triggered==triggered,"normal progress hook not exercised as specified");
 if(triggered){inputNeed(probe.during.owners==1&&probe.during.descriptors.size()==baseline.descriptors.size()+2,"preparation owner/FDs were not actually live at failure");inputNeed(!probe.events.empty()&&probe.events.back().point==probe.target&&probe.events.back().offset>=probe.threshold,"work continued beyond cancellation/deadline checkpoint");
  if(probe.target==InputPoint::InputResidentAfter||probe.target==InputPoint::InputSamplesProgress)inputNeed(probe.during.wiredBytes>baseline.wiredBytes,"post-mlock cancellation did not retain a real wired input mapping");
 }
 inputReleased(baseline);inputSaveProbe(observations,id,probe,inputResources(),reason);
}

struct InputEngineGate {
 std::atomic<bool> armed{false},entered{false},released{false},left{false},expired{false},allowJoinRelease{false},selectReady{false},heldReady{false};
 std::atomic<std::uint64_t> session{0},offset{0},enteredNs{0},joinReleases{0};InputResources during;
 void arm(bool ready=false){inputNeed(!entered.load()||left.load(),"engine gate rearm before leave");entered=false;released=false;left=false;expired=false;allowJoinRelease=false;selectReady=ready;heldReady=false;session=0;offset=0;enteredNs=0;armed=true;}
 static void hold(InputEngineGate& g)noexcept{
  try{g.during=inputResources();}catch(...){g.expired=true;}
  g.enteredNs=std::chrono::duration_cast<std::chrono::nanoseconds>(InputClock::now().time_since_epoch()).count();g.entered=true;
  const auto deadline=InputClock::now()+std::chrono::seconds(10);while(!g.released.load()&&InputClock::now()<deadline)std::this_thread::sleep_for(std::chrono::milliseconds(1));
  if(!g.released.load())g.expired=true;g.left=true;
 }
 static void pipelineEvent(void* context,InputPoint point,std::uint64_t session,std::uint64_t offset)noexcept{
  auto& g=*static_cast<InputEngineGate*>(context);if(point!=InputPoint::InputCopyProgress||offset||!g.armed.load())return;
  g.session=session;g.offset=offset;
  if(!g.selectReady.load()&&g.armed.exchange(false))hold(g);
 }
 static void engineEvent(void* context,ipp::ProgressiveControlTestPoint point)noexcept{
  auto& g=*static_cast<InputEngineGate*>(context);
  // Ready待機が成功した通常準備threadだけがここへ来る。Engine mutex外。
  if(point==ipp::ProgressiveControlTestPoint::ReadyBeforeConfigure&&g.selectReady.load()&&g.armed.exchange(false)){g.heldReady=true;hold(g);return;}
  if(point==ipp::ProgressiveControlTestPoint::InputPreparationJoinWait&&(g.entered.load()||g.allowJoinRelease.load())&&!g.left.load()){++g.joinReleases;g.released=true;}
 }
};
struct InputEngineAudit {
 std::uint64_t calls=0,serial=0,preparation=0;bool copied=false,error=false;
 static bool receive(void* context,const ipp::FinalOperationAudit& audit)noexcept{
  auto& a=*static_cast<InputEngineAudit*>(context);++a.calls;
  a.serial=audit.engineSerial;a.preparation=audit.preparation;
  a.error=a.calls!=1||!a.serial||!a.preparation||!audit.workersJoined||!audit.retirementComplete||!audit.seeks.empty()||!audit.stoppedSpeeds.empty()||!audit.loopSpeeds.empty()||!audit.loopPreparations.empty()||audit.epochAuditCalls||audit.epochAuditRejected;
  a.copied=!a.error;return a.copied;
 }
};
template<class Predicate>void inputEngineWait(ipp::ProgressiveMacPlaybackEngine& engine,Predicate predicate,const char* reason,bool permitFailure=false){
 const auto limit=InputClock::now()+std::chrono::seconds(12);while(!predicate()){if(!permitFailure)inputNeed(engine.getPlaybackState()!=ipp::progressive::State::Failed,engine.getPlaybackDiagnostics().error);inputNeed(InputClock::now()<limit,reason);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
}
void inputEngineSilent(ipp::ProgressiveMacPlaybackEngine& engine){
 const auto d=engine.getPlaybackDiagnostics();const auto n=engine.getNativeDiagnostics();
 inputNeed(!n.firstPcmMachNs&&!n.callbackCalls&&!d.generatedFrames&&!d.publishedFrames&&!d.consumedFrames&&!d.renderEpoch,"input preparation reached output/epoch/callback");
}
void inputSaveEngine(std::ofstream& stream,const char* phase,ipp::ProgressiveMacPlaybackEngine* engine,const InputEngineGate& gate){
 stream<<"{\"phase\":"<<inputQuote(phase)<<",\"constructor_session\":"<<gate.session.load()<<",\"constructor_offset\":"<<gate.offset.load()<<",\"gate_entered\":"<<gate.entered.load()<<",\"gate_left\":"<<gate.left.load()<<",\"held_ready_before_configure\":"<<gate.heldReady.load()<<",\"gate_entered_ns\":"<<gate.enteredNs.load()<<",\"join_releases\":"<<gate.joinReleases.load()
  <<",\"during_owners\":"<<gate.during.owners<<",\"during_fd_count\":"<<gate.during.descriptors.size();
 if(engine){const auto s=engine->getStateSnapshot();const auto d=engine->getPlaybackDiagnostics();stream<<",\"engine_serial\":"<<d.engineSerial<<",\"preparation\":"<<s.preparation<<",\"state\":"<<inputQuote(ipp::progressive::name(s.state))<<",\"reservation_bytes\":"<<d.reservationBytes<<",\"failure\":"<<inputQuote(d.error);}
 stream<<"}\n";stream.flush();inputNeed(bool(stream),"engine preparation evidence write");
}

const std::array<const char*,15> inputPipelineChecks{
 "C3I01_fixture_standard_no_audio","C3I02_pre_cancelled","C3I03_expired_at_entry",
 "C3I04_cancel_copy","C3I05_cancel_samples","C3I06_cancel_before_mlock","C3I07_cancel_after_mlock",
 "C3I08_deadline_copy","C3I09_deadline_samples","C3I10_deadline_before_mlock","C3I11_deadline_after_mlock",
 "C3I12_nonfinite_still_rejected","C3I13_success_chunk_contract","C3I14_two_owner_recovery","C3I15_final_resources"};
const std::array<const char*,8> inputEngineChecks{
 "C3E01_fixture_no_device","C3E02_constructor_held","C3E03_interruption",
 "C3E04_resources_released","C3E05_next_prepare_acquired","C3E06_next_cancel_joined","C3E07_final_owned_audit","C3E08_final_resources"};
const std::array<const char*,8> inputReadyDeadlineChecks{
 "C3R01_fixture_no_device","C3R02_ready_wait_succeeded_before_deadline","C3R03_ready_deadline_before_configure",
 "C3R04_joined_resources_released","C3R05_next_prepare_acquired","C3R06_next_cancel_joined","C3R07_final_owned_audit","C3R08_final_resources"};

int inputPreparationMain(int argc,char** argv){
 inputNeed(argc==6,"MODE INPUT PRESET NEW_OUT SOURCE_SHA");const std::string mode=argv[1],preset=argv[3];
 inputNeed(mode=="pipeline"||mode=="engine_stop"||mode=="engine_close"||mode=="engine_new_input"||mode=="engine_deadline"||mode=="engine_ready_deadline","unknown mode");inputNeed(preset=="baseline"||preset=="candidate","preset");
 const bool candidate=preset=="candidate",direct=mode=="pipeline",readyDeadline=mode=="engine_ready_deadline";const fs::path input=argv[2],out=argv[4];inputNeed(!fs::exists(out)&&fs::create_directories(out),"fresh output directory required");
 const auto expected=direct?inputPipelineChecks.size():inputEngineChecks.size();std::size_t done=0;
 const auto checkID=[&](std::size_t index){return direct?inputPipelineChecks[index]:readyDeadline?inputReadyDeadlineChecks[index]:inputEngineChecks[index];};
 std::ofstream checks(out/"checks.jsonl"),observations(out/"observations.jsonl");
 const auto pass=[&]{inputNeed(done<expected,"extra check");const auto id=checkID(done);++done;checks<<"{\"id\":"<<inputQuote(mode+"."+id)<<",\"pass\":true}\n";checks.flush();inputNeed(bool(checks),"check evidence write");};
 const auto finish=[&](bool ok,const std::string& reason){
  std::ofstream result(out/"SUMMARY.json");const auto owners=InputPipeline::executionOwnerCounts();result<<"{\"status\":"<<inputQuote(ok?"PASS":"FAIL")<<",\"run_complete\":"<<(ok?"true":"false")<<",\"mode\":"<<inputQuote(mode)<<",\"preset\":"<<inputQuote(preset)<<",\"source\":"<<inputQuote(argv[5])<<",\"expected\":"<<expected<<",\"executed\":"<<done<<",\"owner_alive\":"<<owners.alive<<",\"owner_peak\":"<<owners.peak<<",\"audio_output\":\"NOT_RUN\",\"performance\":\"NOT_ASSESSED\",\"callback_gate\":false,\"reason\":"<<inputQuote(reason)<<"}\n";result.close();inputNeed(bool(result),"summary write");
  std::ofstream artifacts(out/"ARTIFACTS.json");artifacts<<"{\"artifacts\":[";bool first=true;for(const auto* name:{"EXPECTED.json","MANIFEST.json","checks.jsonl","observations.jsonl","engine_final_audits.jsonl","nonfinite.wav","replacement_input.wav","SUMMARY.json"}){const auto path=out/name;if(!fs::exists(path))continue;artifacts<<(first?"":",")<<"{\"path\":"<<inputQuote(name)<<",\"bytes\":"<<fs::file_size(path)<<",\"sha256\":"<<inputQuote(inputHash(path))<<'}';first=false;}artifacts<<"]}\n";artifacts.close();inputNeed(bool(artifacts),"artifact manifest write");
 };
 try{
  inputNeed(ipp::progressive::contractVersion==4,"v4 constructor ABI required");const auto data=inputDataOffset(input);ts::WavStreamReader wav(input);
  inputNeed((wav.sampleRate()==44100||wav.sampleRate()==48000)&&(wav.channels()==1||wav.channels()==2)&&wav.frames()>=2ULL*wav.sampleRate()&&wav.frames()<=20ULL*wav.sampleRate(),"product Float32 2..20s fixture required");
  const auto inputBytes=fs::file_size(input);inputNeed(inputBytes>131072&&wav.frames()*wav.channels()>32768,"fixture must cross copy/sample chunk boundaries");const auto inputSha=inputHash(input);
  {std::ofstream file(out/"EXPECTED.json");file<<"{\"schema\":1,\"expected\":"<<expected<<",\"required_ids\":[";for(std::size_t i=0;i<expected;++i)file<<(i?",":"")<<inputQuote(mode+"."+checkID(i));file<<"],\"accepted_operation_ids\":[],\"callback_gate\":false}\n";file.close();inputNeed(bool(file),"expected IDs write");}
  {std::ofstream file(out/"MANIFEST.json");file<<"{\"schema\":1,\"source\":"<<inputQuote(argv[5])<<",\"binary_sha256\":"<<inputQuote(inputHash(fs::absolute(argv[0])))<<",\"input\":"<<inputQuote(fs::absolute(input).string())<<",\"input_sha256\":"<<inputQuote(inputSha)<<",\"input_bytes\":"<<inputBytes<<",\"sample_rate\":"<<wav.sampleRate()<<",\"channels\":"<<wav.channels()<<",\"frames\":"<<wav.frames()<<",\"preset\":"<<inputQuote(preset)<<",\"mode\":"<<inputQuote(mode)<<",\"contract_version\":4,\"copy_chunk_bytes\":131072,\"sample_chunk_values\":16384,\"deadline_budget_seconds\":1,\"gate_watchdog_seconds\":10,\"standard_pipeline_only\":"<<(direct?"true":"false")<<",\"engine_reaches_configure\":false,\"audio_output\":\"NOT_RUN\",\"performance\":\"NOT_ASSESSED\",\"callback_gate\":false}\n";file.close();inputNeed(bool(file),"manifest write");}
  if(direct){
   // 一度起動して通常FFT/ライブラリ初期化を済ませ、以後は厳密な同一FD集合と
   // user_wired_countのあるVM領域を比較する。RSS/allocator cacheは解放証明に使わない。
   {ip58::Configuration config;inputConfig(config,candidate);InputPipeline warm(input,config);inputReady(warm);inputJoined(warm);}
   const auto baseline=inputResources();inputNeed(!baseline.owners&&baseline.ownerPeak<=2,"initial owner leak");pass();
   {InputProbe p;p.cancelled=true;inputFailure(input,candidate,p,baseline,"取り消され",inputPipelineChecks[done],observations,false);pass();}
   {InputProbe p;p.deadline=InputClock::now()-std::chrono::milliseconds(1);inputFailure(input,candidate,p,baseline,"期限",inputPipelineChecks[done],observations,false);pass();}
   const std::array<InputPoint,4> targets{InputPoint::InputCopyProgress,InputPoint::InputSamplesProgress,InputPoint::InputResidentBefore,InputPoint::InputResidentAfter};
   for(const auto action:{InputProbe::Action::Cancel,InputProbe::Action::Deadline})for(const auto target:targets){
    InputProbe p;p.action=action;p.target=target;p.threshold=target==InputPoint::InputCopyProgress?131072:target==InputPoint::InputSamplesProgress?16384:0;
    if(action==InputProbe::Action::Deadline)p.deadline=InputClock::now()+std::chrono::seconds(1);
    inputFailure(input,candidate,p,baseline,action==InputProbe::Action::Cancel?"取り消され":"期限",inputPipelineChecks[done],observations,true);pass();
   }
   {const auto bad=out/"nonfinite.wav";inputNeed(fs::copy_file(input,bad),"nonfinite fixture copy");std::fstream file(bad,std::ios::in|std::ios::out|std::ios::binary);const std::array<unsigned char,4> nan{0,0,0xc0,0x7f};file.seekp(std::streamoff(data+32768*4));file.write(reinterpret_cast<const char*>(nan.data()),nan.size());file.close();inputNeed(bool(file),"nonfinite fixture patch");
    InputProbe p;inputFailure(bad,candidate,p,baseline,"Non-finite",inputPipelineChecks[done],observations,false);inputNeed(p.calls[1]&&p.last[1]>=32768,"nonfinite scan was not exercised");pass();}
   {InputProbe p;ip58::Configuration config;inputConfig(config,candidate,&p);
    {InputPipeline successful(input,config);const auto d=successful.diagnostics();inputNeed(!p.error&&p.session&&p.calls[0]>1&&p.calls[1]>1&&p.calls[2]==1&&p.calls[3]==1&&p.last[0]==inputBytes&&p.last[1]==wav.frames()*wav.channels()&&p.maximumStep[0]<=131072&&p.maximumStep[1]<=16384,"copy/sample progress was skipped, regressed or unbounded");
     inputNeed(d.sourceHashPasses==1&&d.sourceSnapshotCreations==1&&d.residentLockCalls==1&&d.sourceSnapshotBytes==inputBytes&&d.residentInputBytes==inputBytes&&d.inputSamplesPrevalidated&&d.inputSha256==inputSha&&!d.generated&&!d.published&&!d.consumed,"successful constructor changed identity/validation/output");inputReady(successful);inputJoined(successful);}
    inputReleased(baseline);inputSaveProbe(observations,inputPipelineChecks[done],p,inputResources(),"");pass();}
   {ip58::Configuration config;inputConfig(config,candidate);auto first=std::make_unique<InputPipeline>(input,config);inputReady(*first);const auto generation=first->inputGeneration(),session=first->sessionID();auto second=first->createSeek(wav.sampleRate(),1000000);inputReady(*second);
    inputNeed(InputPipeline::executionOwnerCounts().alive==2&&second->inputGeneration()==generation&&second->sessionID()!=session,"recovery did not acquire two same-lease owner shares");bool refused=false;try{auto third=first->createSeek(wav.sampleRate()*2ULL,1000000);}catch(const std::length_error&){refused=true;}inputNeed(refused&&InputPipeline::executionOwnerCounts().alive==2&&InputPipeline::executionOwnerCounts().peak<=2,"third recovery owner was not rejected atomically");
    inputJoined(*first);first.reset();inputNeed(InputPipeline::executionOwnerCounts().alive==1&&second->diagnostics().inputSha256==inputSha,"source retirement invalidated surviving input lease");inputJoined(*second);second.reset();inputReleased(baseline);pass();}
   inputReleased(baseline);inputNeed(InputPipeline::executionOwnerCounts().peak==2,"two-owner resource boundary not exercised");pass();
  }else{
   InputEngineGate gate;std::array<InputEngineAudit,2> audits;std::unique_ptr<ipp::ProgressiveMacPlaybackEngine> engine;
   struct EngineCleanup {InputEngineGate& gate;std::unique_ptr<ipp::ProgressiveMacPlaybackEngine>& engine;~EngineCleanup(){gate.allowJoinRelease=true;engine.reset();gate.released=true;}} cleanup{gate,engine};
   const auto baseline=inputResources();inputNeed(!baseline.owners,"engine initial owners");
   ipp::ProgressiveOptions options;options.preset=candidate?ipp::Preset::Candidate:ipp::Preset::Baseline;options.initialSpeed=1;options.featurePolicy=ipp::progressive::FeaturePolicyOptions{4,ipp::progressive::FeaturePolicy::Research,ipp::progressive::FeaturePolicy::Disabled,ipp::progressive::FeaturePolicy::Research};
   options.pipelineControlTestHooks={&gate,InputEngineGate::pipelineEvent,nullptr};options.controlTestHooks={&gate,InputEngineGate::engineEvent};options.finalOperationAuditContext=&audits[0];options.receiveFinalOperationAudit=InputEngineAudit::receive;options.prepareTimeout=mode=="engine_deadline"||readyDeadline?std::chrono::milliseconds(1000):std::chrono::milliseconds(10000);
   engine=std::make_unique<ipp::ProgressiveMacPlaybackEngine>();pass();gate.arm(readyDeadline);const auto firstCalled=InputClock::now();const auto firstAccepted=engine->prepare(input,options);gate.allowJoinRelease=true;inputNeed(firstAccepted,"first engine prepare rejected");
   inputEngineWait(*engine,[&]{return gate.entered.load();},readyDeadline?"ReadyBeforeConfigure hook absent":"first constructor gate absent");inputNeed(!gate.expired.load()&&gate.during.owners==1&&engine->getPlaybackState()==ipp::progressive::State::Preparing&&engine->getPlaybackDiagnostics().reservationBytes>0,"engine preparation/resource phase not held");
   if(readyDeadline){
    const auto entered=InputClock::time_point(std::chrono::nanoseconds(gate.enteredNs.load()));
    // acceptedDeadlineはprepare呼出中に作るため firstCalled+timeout 以降。
    // これより前のhook到達で、Ready待機そのものは期限内成功だったと確定する。
    inputNeed(gate.heldReady.load()&&gate.session.load()&&entered<firstCalled+options.prepareTimeout&&engine->getPlaybackDiagnostics().constructorS>=0,"Ready wait did not succeed before the accepted deadline");
    observations<<"{\"phase\":\"Ready_deadline_bound\",\"called_ns\":"<<std::chrono::duration_cast<std::chrono::nanoseconds>(firstCalled.time_since_epoch()).count()<<",\"conservative_deadline_ns\":"<<std::chrono::duration_cast<std::chrono::nanoseconds>((firstCalled+options.prepareTimeout).time_since_epoch()).count()<<",\"ready_hook_ns\":"<<gate.enteredNs.load()<<",\"hold_release_after_ns\":"<<std::chrono::duration_cast<std::chrono::nanoseconds>((entered+options.prepareTimeout+std::chrono::milliseconds(1)).time_since_epoch()).count()<<"}\n";
    observations.flush();inputNeed(bool(observations),"Ready deadline bound evidence write");
   }
   inputEngineSilent(*engine);const auto firstSession=gate.session.load(),firstSerial=engine->getPlaybackDiagnostics().engineSerial;inputSaveEngine(observations,readyDeadline?"Ready_wait_succeeded_before_configure":"first_held",engine.get(),gate);pass();
   if(mode=="engine_close"){engine.reset();inputNeed(audits[0].copied&&!audits[0].error&&gate.left.load()&&gate.joinReleases.load(),"constructor close did not release after cancellation/join");}
   else if(mode=="engine_deadline"||readyDeadline){
    const auto entered=InputClock::time_point(std::chrono::nanoseconds(gate.enteredNs.load()));std::this_thread::sleep_until(entered+options.prepareTimeout+std::chrono::milliseconds(1));gate.released=true;
    inputEngineWait(*engine,[&]{return engine->getPlaybackState()==ipp::progressive::State::Failed;},readyDeadline?"successful Ready wait bypassed accepted deadline":"accepted deadline ignored in constructor",true);
    const auto failure=engine->getPlaybackDiagnostics().error;
    inputNeed(failure.find(readyDeadline?"Readyが受付からの期限":"期限")!=std::string::npos&&gate.left.load(),"wrong engine deadline failure phase");inputEngineSilent(*engine);inputSaveEngine(observations,readyDeadline?"Ready_deadline_failed_before_configure":"constructor_deadline_failed",engine.get(),gate);engine->stop();
   }else{engine->stop();inputNeed(engine->getPlaybackState()==ipp::progressive::State::Stopped&&gate.left.load()&&gate.joinReleases.load(),"constructor stop did not cancel/join");inputEngineSilent(*engine);}
   inputSaveEngine(observations,"first_interrupted",engine.get(),gate);pass();inputReleased(baseline);pass();
   fs::path nextInput=input;if(mode=="engine_new_input"){nextInput=out/"replacement_input.wav";inputNeed(fs::copy_file(input,nextInput),"new input clone");}
   if(!engine){options.finalOperationAuditContext=&audits[1];engine=std::make_unique<ipp::ProgressiveMacPlaybackEngine>();inputNeed(engine->getPlaybackDiagnostics().engineSerial!=firstSerial,"closed engine serial reused");}
   options.prepareTimeout=std::chrono::milliseconds(10000);gate.arm();const auto nextAccepted=engine->prepare(nextInput,options);gate.allowJoinRelease=true;inputNeed(nextAccepted,"second prepare rejected after cleanup");
   inputEngineWait(*engine,[&]{return gate.entered.load();},"new preparation failed to reacquire released global reservation");inputNeed(!gate.expired.load()&&gate.session.load()!=firstSession&&gate.during.owners==1&&engine->getPlaybackDiagnostics().reservationBytes>0,"new prepare reused old constructor/lease or failed reservation");inputEngineSilent(*engine);inputSaveEngine(observations,"second_held",engine.get(),gate);pass();
   engine->stop();inputNeed(engine->getPlaybackState()==ipp::progressive::State::Stopped&&gate.left.load()&&gate.joinReleases.load()&&!gate.expired.load(),"second constructor stop/join failed");inputEngineSilent(*engine);inputReleased(baseline);inputSaveEngine(observations,"second_stopped",engine.get(),gate);pass();engine.reset();
   const auto auditCount=mode=="engine_close"?2U:1U;std::ofstream final(out/"engine_final_audits.jsonl");for(unsigned i=0;i<auditCount;++i){const auto& a=audits[i];inputNeed(a.calls==1&&a.copied&&!a.error&&a.preparation==(mode=="engine_close"?1U:2U),"final empty Accepted-set/join audit incomplete");final<<"{\"engine_serial\":"<<a.serial<<",\"preparation\":"<<a.preparation<<",\"calls\":"<<a.calls<<",\"owned_empty_operation_sets\":true,\"workers_joined\":true,\"retirement_complete\":true}\n";}final.close();inputNeed(bool(final),"engine final audit write");pass();inputReleased(baseline);inputNeed(!gate.expired.load(),"engine gate expired");pass();
  }
  inputNeed(done==expected,"incomplete fixed check set");checks.close();observations.close();finish(true,"");return 0;
 }catch(const std::exception& error){checks.close();observations.close();finish(false,error.what());std::cerr<<error.what()<<'\n';return 1;}
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=inputPreparationMain(argc,argv);}catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});control.join();return result;}

