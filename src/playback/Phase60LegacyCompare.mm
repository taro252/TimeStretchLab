// Built in a separate CMake graph against the approved Phase54 headers/libraries.
// Never link two versions of the DSP into the same process.
#import <Foundation/Foundation.h>
#include "platform/macos/MacPlaybackEngine.h"
#include "audio/WavStream.h"
#include "prototype/Phase45PcmDigest.h"
#include <mach/mach_time.h>
#include <sys/resource.h>
#include <fstream>
#include <sstream>
#include <iostream>
using namespace ts;using namespace ts::playback;
namespace {
NSString* txt(const std::string& s){return [[NSString alloc]initWithBytes:s.data() length:s.size() encoding:NSUTF8StringEncoding];}
double now(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
double cpu(){rusage r{};getrusage(RUSAGE_SELF,&r);return r.ru_utime.tv_sec+r.ru_utime.tv_usec*1e-6+r.ru_stime.tv_sec+r.ru_stime.tv_usec*1e-6;}
std::uint64_t ns(){mach_timebase_info_data_t t{};mach_timebase_info(&t);return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*t.numer/t.denom);}
void save(const std::filesystem::path& path,id obj){NSError* e=nil;NSData* d=[NSJSONSerialization dataWithJSONObject:obj options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:&e];if(!d)throw std::runtime_error("JSON export failed");std::ofstream out(path,std::ios::binary);if(!out.write(static_cast<const char*>(d.bytes),d.length))throw std::runtime_error("JSON write failed");}
struct Action{double at;std::string kind;double value;};
int run(int argc,char** argv){
    if(argc<2)throw std::invalid_argument("input.wav required");std::filesystem::path input=argv[1],out,actionFile;std::string preset="candidate";double speed=1;unsigned restarts=0;bool verify=false;
    for(int i=2;i<argc;++i){const std::string f=argv[i];if(f.starts_with("--out="))out=f.substr(6);else if(f.starts_with("--preset="))preset=f.substr(9);else if(f.starts_with("--speed="))speed=std::stod(f.substr(8));else if(f.starts_with("--actions="))actionFile=f.substr(10);else if(f.starts_with("--restarts="))restarts=std::stoul(f.substr(11));else if(f=="--verify-pcm")verify=true;else if(f!="--engine=legacy")throw std::invalid_argument("Unsupported legacy option: "+f);}
    if(out.empty()||std::filesystem::exists(out)||restarts>16||(preset!="candidate"&&preset!="baseline")||!std::isfinite(speed)||speed<.4||speed>2||std::abs(speed*100-std::llround(speed*100))>1e-8)throw std::invalid_argument("Invalid legacy configuration / output exists");
    std::filesystem::create_directories(out);WavStreamReader reader(input);prototype::Phase45PcmDigest hash;std::ifstream file(input,std::ios::binary);std::array<char,131072> buffer;while(file){file.read(buffer.data(),buffer.size());hash.update(buffer.data(),file.gcount());}auto inputSha=hash.finish();
    std::vector<Action> actions;if(!actionFile.empty()){std::ifstream in(actionFile);if(!in)throw std::runtime_error("Actions unavailable");std::string line;std::getline(in,line);while(std::getline(in,line)){if(line.empty())continue;std::stringstream s(line);std::string at,kind,value;std::getline(s,at,',');std::getline(s,kind,',');std::getline(s,value,',');Action a{std::stod(at),kind,value.empty()?0:std::stod(value)};if(!std::isfinite(a.at)||a.at<0||(!actions.empty()&&a.at<actions.back().at)||actions.size()>=4096)throw std::invalid_argument("Invalid actions");if(kind!="pause"&&kind!="resume"&&kind!="speed"&&kind!="stop"&&kind!="stop_play"&&kind!="route")throw std::invalid_argument("Unknown action");actions.push_back(a);}}
    MacPlaybackEngine engine;NSMutableArray* sessions=[NSMutableArray array];NSMutableArray* events=[NSMutableArray array];double begin=0,beginCpu=0,prepareS=0,playS=0;std::uint64_t beginNs=0;unsigned sessionIndex=0,restart=0;std::size_t nextAction=0;bool failed=false,done=false;
    auto start=[&](bool first){begin=now();beginNs=ns();beginCpu=cpu();prepareS=0;
        if(first){auto c=preset=="candidate"?Configuration::candidate(speed):Configuration::baseline(speed);c.verifyRawPcm=verify;MacOptions o;o.recordCallbacks=true; // same preset/FIFO/gain, no seek in this experiment
            if(!engine.prepare(input,c,o))throw std::runtime_error(engine.getPlaybackDiagnostics().error);prepareS=now()-begin;}
        const auto t=now();if(!engine.play())throw std::runtime_error(engine.getNativeDiagnostics().error);playS=now()-t;
    };
    auto finish=[&](const std::string& trigger){const auto folder=out/("session_"+std::to_string(++sessionIndex));std::filesystem::create_directory(folder);auto d=engine.getPlaybackDiagnostics();auto n=engine.getNativeDiagnostics();auto startup=engine.getStartupDiagnostics();rusage u{};getrusage(RUSAGE_SELF,&u);const bool supply=!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites;bool pass=supply&&!n.deadlineMisses&&!n.formatErrors&&d.error.empty()&&n.error.empty();if(trigger=="eos")pass&=engine.getPlaybackState()==PlaybackState::Ended;failed|=!pass;
        NSDictionary* row=@{@"trigger":txt(trigger),@"state":txt(name(engine.getPlaybackState())),@"session":@(d.session),@"input_sha256":txt(inputSha),@"source_rate":@(reader.sampleRate()),@"channels":@(reader.channels()),@"input_frames":@(reader.frames()),@"wall_s":@(now()-begin),@"process_cpu_s":@(cpu()-beginCpu),@"peak_rss_bytes":@(u.ru_maxrss),@"prepare_return_s":@(prepareS),@"play_return_s":@(playS),@"first_pcm_from_request_s":n.firstPcmMachNs?@(double(n.firstPcmMachNs-beginNs)*1e-9):(id)[NSNull null],@"analysis_cache_hit":@(startup.analysisHit),@"analysis_bytes":@(startup.analysisBytes),@"generated_frames":@(d.generatedFrames),@"published_frames":@(d.producedFrames),@"consumed_frames":@(d.consumedFrames),@"presented_frames":@(d.presentedFrames),@"missing_frames":@(d.missingFrames),@"underrun_calls":@(d.underrunCalls),@"rejected_writes":@(d.rejectedWrites),@"fifo_supply_pass":@(supply),@"supply_and_callback_pass":@(pass),@"eos":@(engine.getPlaybackState()==PlaybackState::Ended),@"error":txt(d.error),@"resident_input_bytes":[NSNull null],@"temporary_source_bytes":[NSNull null],@"worker_cpu_s":[NSNull null],@"worker_deadline_misses":[NSNull null],@"pcm_correct":[NSNull null],@"published_pcm_sha256":verify?txt(engine.rawPcmSha()):(id)[NSNull null],@"overall_audio_quality":supply?(id)[NSNull null]:(id)@NO,
            @"native":@{@"device_id":@(n.deviceId),@"device_rate":@(n.deviceRate),@"device_buffer_frames":@(n.deviceBufferFrames),@"callback_calls":@(n.callbackCalls),@"callback_deadline_misses":@(n.deadlineMisses),@"host_missing":@(n.hostMissing),@"host_backwards":@(n.hostBackwards),@"host_cadence_errors":@(n.hostCadenceErrors),@"sample_errors":@(n.sampleErrors),@"hal_window_misses":@(n.halWindowMisses),@"format_errors":@(n.formatErrors),@"route_changes":@(n.routeChanges),@"callback_records_dropped":@(n.callbackRecordsDropped),@"first_pcm_mach_ns":@(n.firstPcmMachNs),@"last_pcm_target_ns":@(n.lastPcmTargetEndNs),@"output_stopped_ns":@(n.outputStoppedMachNs),@"cpp_new_measured":@NO,@"cpp_new_calls":[NSNull null],@"os_faults":[NSNull null],@"error":txt(n.error)}};
        std::ofstream cb(folder/"callbacks.csv");cb<<std::setprecision(17)<<"sequence,epoch,start_ns,end_ns,host_ns,sample,flags,requested,wanted,received,consumed_before,fifo_before\n";for(const auto& r:engine.callbackRecords())cb<<r.sequence<<','<<r.epoch<<','<<r.startNs<<','<<r.endNs<<','<<r.hostNs<<','<<r.sampleTime<<','<<r.timestampFlags<<','<<r.requested<<','<<r.raw.wanted<<','<<r.raw.received<<','<<r.raw.outputBefore<<','<<r.raw.fifoBefore<<'\n';
        std::ofstream ops(folder/"operations.csv");ops<<"id,session,generation,target,status,apply_output,complete_output\n";for(const auto& o:engine.operationHistory())ops<<o.id<<','<<o.session<<','<<o.generation<<','<<o.target<<','<<int(o.status)<<','<<o.applyOutput<<','<<o.completeOutput<<'\n';
        [sessions addObject:row];save(folder/"summary.json",row);save(out/"sessions.json",sessions);
    };
    start(true);const auto global=now();while(!done){auto state=engine.getPlaybackState();bool restarted=false;
        while(nextAction<actions.size()&&now()-global>=actions[nextAction].at){auto a=actions[nextAction++];bool ok=true;std::uint64_t request=0;
            if(a.kind=="speed")request=engine.setSpeed(a.value);else if(a.kind=="pause")ok=engine.pause();else if(a.kind=="resume")ok=engine.resume();else if(a.kind=="route")engine.simulateDeviceChangeForTest();else{engine.stop();finish(a.kind);if(a.kind=="stop")done=true;else{start(false);restarted=true;}}
            [events addObject:@{@"at_s":@(now()-global),@"action":txt(a.kind),@"value":@(a.value),@"ok":@(ok),@"request_id":@(request)}];failed|=!ok;
        }
        if(done)break;if(restarted)continue;
        if(state==PlaybackState::Ended){finish("eos");if(restart++<restarts)start(false);else done=true;}
        else if(state==PlaybackState::Failed||state==PlaybackState::Stopped){std::this_thread::sleep_for(std::chrono::milliseconds(10));finish(name(state));failed|=state==PlaybackState::Failed;done=true;}
        if(now()-begin>reader.frames()/double(reader.sampleRate())*2.5+150){engine.stop();finish("timeout");failed=true;done=true;}
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    save(out/"summary.json",@{@"measurement_completed":@YES,@"supply_and_callback_pass":@(!failed),@"engine":@"legacy",@"legacy_sha":@"039592e59cc1a525b495e38d3cedeb6c050792b1",@"preset":txt(preset),@"initial_speed":@(speed),@"input_sha256":txt(inputSha),@"sessions":sessions,@"events":events,@"physical_audio_continuity_verified":@NO,@"gate_2_passed":@NO});std::cout<<"approved Phase54 sessions="<<sessions.count<<" supply_and_callback_pass="<<!failed<<'\n';return failed?2:0;
}
}
int main(int argc,char** argv){int code=1;std::thread control([&]{@autoreleasepool{try{code=run(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}}});control.join();return code;}
