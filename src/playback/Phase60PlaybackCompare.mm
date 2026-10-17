#import <Foundation/Foundation.h>
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "audio/WavStream.h"
#include "prototype/Phase59Diagnostics.h"
#include "prototype/Phase45PcmDigest.h"
#include <fstream>
#include <sstream>
#include <iostream>
#include <sys/resource.h>
#include <mach/mach_time.h>
#include <unistd.h>

using namespace ts;using namespace ts::playback;
namespace {
NSString* text(const std::string& s){return [[NSString alloc]initWithBytes:s.data() length:s.size() encoding:NSUTF8StringEncoding];}
double now(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
double cpu(){rusage r{};getrusage(RUSAGE_SELF,&r);return r.ru_utime.tv_sec+r.ru_utime.tv_usec*1e-6+r.ru_stime.tv_sec+r.ru_stime.tv_usec*1e-6;}
std::uint64_t machNs(){mach_timebase_info_data_t t{};mach_timebase_info(&t);return static_cast<std::uint64_t>(static_cast<long double>(mach_absolute_time())*t.numer/t.denom);}
std::string shaFile(const std::filesystem::path& p){std::ifstream in(p,std::ios::binary);if(!in)throw std::runtime_error("Cannot hash input");prototype::Phase45PcmDigest hash;std::array<char,131072>b;while(in){in.read(b.data(),b.size());hash.update(b.data(),in.gcount());}return hash.finish();}
void save(const std::filesystem::path& path,id object){NSError* error=nil;NSData* data=[NSJSONSerialization dataWithJSONObject:object options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:&error];if(!data)throw std::runtime_error(error.localizedDescription.UTF8String);std::ofstream file(path,std::ios::binary);if(!file.write(static_cast<const char*>(data.bytes),data.length))throw std::runtime_error("Cannot write JSON");}
struct Action {double at=0;std::string kind;double value=0;};
struct Capture {std::vector<float> samples;std::size_t channels=0,frames=0;bool overflow=false;
    static void receive(void* ctx,const float*const* p,std::size_t n,std::size_t offset)noexcept{auto& c=*static_cast<Capture*>(ctx);if((offset+n)*c.channels>c.samples.size()){c.overflow=true;return;}for(std::size_t i=0;i<n;++i)for(std::size_t ch=0;ch<c.channels;++ch)c.samples[(offset+i)*c.channels+ch]=p[ch][i];c.frames=offset+n;}
};
NSMutableDictionary* nativeValue(const MacDiagnostics& d){return [@{
    @"device_id":@(d.deviceId),@"device_rate":@(d.deviceRate),@"device_buffer_frames":@(d.deviceBufferFrames),@"device_channels":@(d.deviceChannels),
    @"callback_calls":@(d.callbackCalls),@"callback_deadline_misses":@(d.deadlineMisses),@"callback_max_ns":@(d.maxCallbackNs),@"format_errors":@(d.formatErrors),
    @"host_missing":@(d.hostMissing),@"host_backwards":@(d.hostBackwards),@"host_cadence_errors":@(d.hostCadenceErrors),@"sample_errors":@(d.sampleErrors),@"hal_window_misses":@(d.halWindowMisses),
    @"route_changes":@(d.routeChanges),@"first_pcm_mach_ns":@(d.firstPcmMachNs),@"last_pcm_target_ns":@(d.lastPcmTargetEndNs),@"output_stopped_ns":@(d.outputStoppedMachNs),
    @"source_latency_ms":@(d.sourcePresentationLatencyMs),@"device_latency_ms":@(d.devicePresentationLatencyMs),@"callback_records_dropped":@(d.callbackRecordsDropped),
    @"cpp_new_measured":@NO,@"cpp_new_calls":[NSNull null],@"os_faults":[NSNull null],@"error":text(d.error)} mutableCopy];}
void callbacks(const std::filesystem::path& path,const std::vector<MacCallbackRecord>& rows){std::ofstream out(path);out<<"sequence,epoch,start_ns,end_ns,host_ticks,host_ns,sample,flags,rate_scalar,requested,wanted,received,consumed_before,fifo_before\n"<<std::setprecision(17);for(auto& r:rows)out<<r.sequence<<','<<r.epoch<<','<<r.startNs<<','<<r.endNs<<','<<r.hostTicks<<','<<r.hostNs<<','<<r.sampleTime<<','<<r.timestampFlags<<','<<r.rateScalar<<','<<r.requested<<','<<r.raw.wanted<<','<<r.raw.received<<','<<r.raw.outputBefore<<','<<r.raw.fifoBefore<<'\n';}
int run(int argc,char** argv){
    if(argc<2)throw std::invalid_argument("phase60_playback_compare input.wav --engine=legacy|legacy-current|progressive --preset=candidate|baseline --speed=1.00 --out=directory [--actions=at_s,action,value.csv] [--capture=raw.f32] [--verify-pcm] [--restarts=1]");
    const std::filesystem::path input=argv[1];std::filesystem::path out,actionsPath,capturePath;std::string kind="legacy",preset="candidate";double speed=1;unsigned restarts=0;bool verify=false;
    for(int i=2;i<argc;++i){const std::string f=argv[i];if(f.starts_with("--engine="))kind=f.substr(9);else if(f.starts_with("--preset="))preset=f.substr(9);else if(f.starts_with("--speed="))speed=std::stod(f.substr(8));else if(f.starts_with("--out="))out=f.substr(6);else if(f.starts_with("--actions="))actionsPath=f.substr(10);else if(f.starts_with("--capture="))capturePath=f.substr(10);else if(f=="--verify-pcm")verify=true;else if(f.starts_with("--restarts="))restarts=std::stoul(f.substr(11));else throw std::invalid_argument("Unknown flag: "+f);}
    progressive::speedMicros(speed);if((kind!="legacy"&&kind!="legacy-current"&&kind!="progressive")||(preset!="candidate"&&preset!="baseline")||out.empty()||restarts>16)throw std::invalid_argument("Invalid comparison configuration");
    if(!capturePath.empty()&&(kind!="progressive"||restarts))throw std::invalid_argument("Raw capture requires progressive and zero restarts");
    if(std::filesystem::exists(out))throw std::invalid_argument("Output exists; preserve previous evidence");std::filesystem::create_directories(out);
    std::vector<Action> actions;if(!actionsPath.empty()){std::ifstream in(actionsPath);if(!in)throw std::runtime_error("Cannot read actions");std::string line;std::getline(in,line);while(std::getline(in,line)){if(line.empty())continue;std::stringstream s(line);std::string at,action,value;std::getline(s,at,',');std::getline(s,action,',');std::getline(s,value,',');Action a{std::stod(at),action,value.empty()?0:std::stod(value)};if(!std::isfinite(a.at)||a.at<0||(!actions.empty()&&a.at<actions.back().at)||actions.size()>=4096)throw std::invalid_argument("Invalid action time/order/budget");if(action!="speed"&&action!="pause"&&action!="resume"&&action!="stop_play"&&action!="stop"&&action!="route")throw std::invalid_argument("Unknown action");actions.push_back(a);}}
    WavStreamReader reader(input);const auto inputSha=shaFile(input);Capture capture;capture.channels=reader.channels();
    if(!capturePath.empty()){const auto frames=std::size_t(std::ceil(reader.frames()*2.5))+8192;const auto bytes=frames*reader.channels()*sizeof(float);if(bytes>512ULL*1024*1024)throw std::length_error("Host capture budget 512MiB exceeded");capture.samples.resize(frames*reader.channels());}
    std::unique_ptr<MacPlaybackEngine> legacy;std::unique_ptr<ProgressiveMacPlaybackEngine> progressiveEngine;
    if(kind=="legacy"||kind=="legacy-current")legacy=std::make_unique<MacPlaybackEngine>();else progressiveEngine=std::make_unique<ProgressiveMacPlaybackEngine>();
    NSMutableArray* sessions=[NSMutableArray array];NSMutableArray* events=[NSMutableArray array];std::size_t actionIndex=0;bool fail=false,done=false;unsigned restart=0,segment=0;double begin=0,startCpu=0,readyAt=0,playAt=0,playReturn=0,sessionBase=0,peakSampledRss=0;std::uint64_t beginMach=0;
    auto beginSession=[&](bool initial){begin=now();beginMach=machNs();startCpu=cpu();readyAt=-1;playAt=begin;
        if(legacy){if(initial){auto c=preset=="candidate"?Configuration::candidate(speed):Configuration::baseline(speed);c.verifyRawPcm=verify;MacOptions m;m.recordCallbacks=true;m.seekFadeFrames=0;if(!legacy->prepare(input,c,m))throw std::runtime_error(legacy->getPlaybackDiagnostics().error);}readyAt=now()-begin;playAt=now();if(!legacy->play())throw std::runtime_error(legacy->getNativeDiagnostics().error);}
        else{if(initial){ProgressiveOptions o;o.initialSpeed=speed;o.preset=preset=="candidate"?Preset::Candidate:Preset::Baseline;o.callbackRecordLimit=262144;if(!capture.samples.empty()){o.observerContext=&capture;o.observeRawPcm=Capture::receive;}if(!progressiveEngine->prepare(input,o))throw std::runtime_error("Prepare rejected");}if(!progressiveEngine->play())throw std::runtime_error("Play rejected");}
        playReturn=now()-playAt;sessionBase=now();peakSampledRss=0;
    };
    auto finishSession=[&](const std::string& trigger){
        ++segment;const auto folder=out/("session_"+std::to_string(segment));std::filesystem::create_directory(folder);NSMutableDictionary* row=[NSMutableDictionary dictionary];
        row[@"trigger"]=text(trigger);row[@"wall_s"]=@(now()-begin);row[@"process_cpu_s"]=@(cpu()-startCpu);row[@"source_rate"]=@(reader.sampleRate());row[@"channels"]=@(reader.channels());row[@"input_frames"]=@(reader.frames());row[@"input_sha256"]=text(inputSha);row[@"pcm_correct"]=[NSNull null];row[@"os_faults"]=[NSNull null];
        MacDiagnostics n;std::uint64_t missing=0,underruns=0,rejected=0;
        if(legacy){const auto d=legacy->getPlaybackDiagnostics();n=legacy->getNativeDiagnostics();row[@"state"]=text(name(legacy->getPlaybackState()));row[@"session"]=@(d.session);row[@"generated_frames"]=@(d.generatedFrames);row[@"published_frames"]=@(d.producedFrames);row[@"consumed_frames"]=@(d.consumedFrames);row[@"presented_frames"]=@(d.presentedFrames);missing=d.missingFrames;underruns=d.underrunCalls;rejected=d.rejectedWrites;row[@"published_pcm_sha256"]=verify?text(legacy->rawPcmSha()):(id)[NSNull null];row[@"error"]=text(d.error);row[@"resident_input_bytes"]=[NSNull null];row[@"temporary_source_bytes"]=[NSNull null];row[@"worker_deadline_misses"]=[NSNull null];row[@"worker_cpu_s"]=[NSNull null];row[@"prepare_return_s"]=@(readyAt);row[@"play_return_s"]=@(now()-playAt);callbacks(folder/"callbacks.csv",legacy->callbackRecords());}
        else{const auto d=progressiveEngine->getPlaybackDiagnostics();n=progressiveEngine->getNativeDiagnostics();row[@"state"]=text(progressive::name(progressiveEngine->getPlaybackState()));row[@"session"]=@(d.session);row[@"input_generation"]=@(d.inputGeneration);row[@"generated_frames"]=@(d.generatedFrames);row[@"published_frames"]=@(d.publishedFrames);row[@"consumed_frames"]=@(d.consumedFrames);row[@"presented_frames"]=@(d.presentedFrames);missing=d.missingFrames;underruns=d.underrunCalls;rejected=d.rejectedWrites;row[@"time_stretch_lab_base_sha"]=text(d.timeStretchLabSha);row[@"resident_input_bytes"]=@(d.residentInputBytes);row[@"temporary_source_bytes"]=@(d.temporarySourceBytes);row[@"memory_reservation_bytes"]=@(d.reservationBytes);row[@"worker_deadline_misses"]=@(d.pipeline.scheduling.deadlineMisses);row[@"worker_cpu_s"]=d.dspWorkerCpuS?@(*d.dspWorkerCpuS):(id)[NSNull null];row[@"ready_s"]=@(d.acceptedToReadyS);row[@"constructor_s"]=@(d.constructorS);row[@"input_complete_at_prefill_ready"]=@(d.pipeline.inputAtReady==d.pipeline.inputFrames);row[@"pipeline_analysis_done_s"]=@(d.pipeline.analysisDoneS);row[@"pipeline_prefill_ready_s"]=@(d.pipeline.readyS);row[@"input_at_ready"]=@(d.pipeline.inputAtReady);row[@"non_eos_published"]=@(d.pipeline.nonEosPublished);row[@"error"]=text(d.error);
            const auto& m=d.pipeline.scheduling;row[@"workgroup"] = @{@"promotions":@(m.promotions),@"joins":@(m.joins),@"leaves":@(m.leaves),@"restores":@(m.restores),@"active":@(m.active),@"policy_errors":@(m.policyErrors),@"join_errors":@(m.joinErrors),@"restore_errors":@(m.restoreErrors),@"interval_errors":@(m.intervalErrors),@"query_errors":@(m.queryErrors),@"wait_errors":@(m.waitErrors),@"wake_errors":@(m.wakeErrors)};
            prototype::phase59::exportOperations(folder,progressiveEngine->operationHistory(),static_cast<std::uint32_t>(std::llround(speed*1e6)));callbacks(folder/"callbacks.csv",progressiveEngine->callbackRecords());
            try{auto map=progressiveEngine->finalTimeMap();std::ofstream nodes(folder/"dynamic_map.nodes.bin",std::ios::binary);nodes.write(reinterpret_cast<const char*>(map.starts().data()),map.starts().size()*sizeof(long long));}catch(const std::logic_error&){}
            row[@"sampled_peak_rss_bytes"]=@(peakSampledRss);
        }
        row[@"native"]=nativeValue(n);if(progressiveEngine){const auto pd=progressiveEngine->getNativeDiagnostics();row[@"native"][@"invalid_sample_time_calls"]=@(pd.invalidSampleTimeCalls);row[@"native"][@"invalid_rate_scalar_calls"]=@(pd.invalidRateScalarCalls);}
        row[@"missing_frames"]=@(missing);row[@"underrun_calls"]=@(underruns);row[@"rejected_writes"]=@(rejected);row[@"fifo_supply_pass"]=@(!missing&&!underruns&&!rejected);
        row[@"play_return_s"]=@(playReturn);
        const bool ended=[row[@"state"] isEqual:@"Ended"];row[@"eos"]=@(ended);row[@"first_pcm_from_request_s"]=n.firstPcmMachNs?@(double(n.firstPcmMachNs-beginMach)*1e-9):(id)[NSNull null];
        rusage usage{};getrusage(RUSAGE_SELF,&usage);row[@"peak_rss_bytes"]=@(usage.ru_maxrss);
        row[@"overall_audio_quality"]=missing||underruns||rejected?(id)@NO:(id)[NSNull null];if(progressiveEngine){const auto q=progressiveEngine->getPlaybackDiagnostics().overallAudioQuality;row[@"overall_audio_quality"]=q?@(*q):(id)[NSNull null];}
        bool valid=!missing&&!underruns&&!rejected&&!n.deadlineMisses&&!n.formatErrors&&[row[@"error"] length]==0;if(trigger=="eos")valid&=ended;fail|=!valid;row[@"supply_and_callback_pass"]=@(valid);[sessions addObject:row];save(folder/"summary.json",row);save(out/"sessions.json",sessions);
    };
    beginSession(true);const auto globalStart=now();
    while(!done){
        const auto state=legacy?std::string(name(legacy->getPlaybackState())):std::string(progressive::name(progressiveEngine->getPlaybackState()));
        if(progressiveEngine){peakSampledRss=std::max(peakSampledRss,double(progressiveEngine->getPlaybackDiagnostics().rssBytes));}
        bool restarted=false;
        while(actionIndex<actions.size()&&now()-globalStart>=actions[actionIndex].at){auto a=actions[actionIndex++];bool ok=true;std::uint64_t request=0;
            if(a.kind=="speed"){if(legacy)request=legacy->setSpeed(a.value);else request=progressiveEngine->setSpeed(a.value).id;ok=request!=0;}
            else if(a.kind=="pause")ok=legacy?legacy->pause():progressiveEngine->pause();
            else if(a.kind=="resume")ok=legacy?legacy->resume():progressiveEngine->resume();
            else if(a.kind=="route"){if(legacy)legacy->simulateDeviceChangeForTest();else progressiveEngine->simulateDeviceChangeForTest();}
            else if(a.kind=="stop"||a.kind=="stop_play"){if(legacy)legacy->stop();else progressiveEngine->stop();finishSession(a.kind);if(a.kind=="stop")done=true;else{beginSession(false);restarted=true;}}
            [events addObject:@{@"at_s":@(now()-globalStart),@"action":text(a.kind),@"value":@(a.value),@"ok":@(ok),@"request_id":@(request)}];fail|=!ok;
        }
        if(done)break;if(restarted)continue;
        if(state=="Ended"){finishSession("eos");if(restart++<restarts)beginSession(false);else done=true;}
        else if(state=="Failed"||state=="Stopped"){std::this_thread::sleep_for(std::chrono::milliseconds(10));finishSession(state);fail|=state=="Failed";done=true;}
        if(now()-sessionBase>reader.frames()/double(reader.sampleRate())*2.5+150){if(legacy)legacy->stop();else progressiveEngine->stop();finishSession("timeout");fail=true;done=true;}
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    if(!capturePath.empty()){std::ofstream raw(capturePath,std::ios::binary);raw.write(reinterpret_cast<const char*>(capture.samples.data()),capture.frames*capture.channels*sizeof(float));if(!raw||capture.overflow)fail=true;}
    save(out/"summary.json",@{@"measurement_completed":@YES,@"supply_and_callback_pass":@(!fail),@"engine":text(kind),@"preset":text(preset),@"initial_speed":@(speed),@"input_path":text(std::filesystem::absolute(input).string()),@"input_sha256":text(inputSha),@"sessions":sessions,@"events":events,@"capture_frames":@(capture.frames),@"capture_overflow":@(capture.overflow),@"physical_audio_continuity_verified":@NO,@"gate_2_passed":@NO});
    std::cout<<kind<<" sessions="<<sessions.count<<" supply_and_callback_pass="<<!fail<<'\n';return fail?2:0;
}
}
int main(int argc,char** argv){
    bool legacy=true;for(int i=2;i<argc;++i)if(std::string(argv[i]).starts_with("--engine="))legacy=std::string(argv[i])=="--engine=legacy";
    if(argc>=2&&legacy){execv(PHASE60_APPROVED_LEGACY_HOST,argv);std::cerr<<"承認Phase54ホストを起動できません。python3 scripts/phase60_build_legacy.py を先に実行してください\n";return 1;}
    int result=1;std::thread control([&]{@autoreleasepool {try{result=run(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';result=1;}}});control.join();return result;}
