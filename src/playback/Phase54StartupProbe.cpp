// Same caller-level probe is linked to the frozen and updated libraries.
#include "playback/PlaybackEngine.h"
#include "platform/macos/MacPlaybackEngine.h"
#include "audio/WavStream.h"
#include <iostream>
#include <iomanip>
#include <sys/resource.h>
#include <ctime>
using namespace ts;using namespace ts::playback;
using Clock=std::chrono::steady_clock;
double cpu(){timespec t{};clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return t.tv_sec+t.tv_nsec*1e-9;}
double processCpu(){rusage r{};getrusage(RUSAGE_SELF,&r);return r.ru_utime.tv_sec+r.ru_utime.tv_usec*1e-6+r.ru_stime.tv_sec+r.ru_stime.tv_usec*1e-6;}
template<class F>void measure(const char* label,F f){auto b=Clock::now();auto c=cpu(),p=processCpu();if(!f())throw std::runtime_error(label);rusage r{};getrusage(RUSAGE_SELF,&r);std::cout<<label<<','<<std::chrono::duration<double>(Clock::now()-b).count()<<','<<cpu()-c<<','<<processCpu()-p<<','<<r.ru_maxrss<<','<<std::chrono::duration_cast<std::chrono::nanoseconds>(b.time_since_epoch()).count()<<','<<std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count()<<'\n';}
void drain(PlaybackEngine& e){std::array<std::array<float,4096>,2> b{};float* p[]={b[0].data(),b[1].data()};while(e.getPlaybackState()==PlaybackState::Playing){auto n=std::min<std::size_t>(4096,e.getPlaybackDiagnostics().fifoAvailable);if(n)e.renderAudio(p,n,1);else std::this_thread::sleep_for(std::chrono::microseconds(100));}if(e.getPlaybackState()!=PlaybackState::Ended||e.getPlaybackDiagnostics().missingFrames)throw std::runtime_error("drain: "+e.getPlaybackDiagnostics().error);}
#ifdef PHASE54_API
void printStages(const StartupDiagnostics& s,const char* scope="latest"){std::cout<<"scope="<<scope<<'\n';for(auto [label,t]:{std::pair{"internal_prepare",s.prepare},{"pipeline_constructor",s.pipeline},{"wav_metadata",s.metadata},{"identity_validation",s.identity},{"transient_analysis",s.analysis},{"time_map",s.timeMap},{"worker_initialization",s.workerInitialization},{"fifo_prefill",s.prefill}})std::cout<<label<<','<<t.wallSeconds<<','<<t.threadCpuSeconds<<",0,0,0,0\n";std::cout<<"analysis_hit="<<s.analysisHit<<"\nanalysis_runs="<<s.analysisRuns<<"\ncache_hits="<<s.cacheHits<<"\nanalysis_bytes="<<s.analysisBytes<<"\ncache_resident_bytes="<<s.cacheResidentBytes<<"\nbytes_hashed="<<s.bytesHashed<<'\n';}
#endif
#ifdef PHASE54_API
void nativeSnapshot(MacPlaybackEngine& e,const char* scope){auto n=e.getNativeDiagnostics();
 auto firstSteady=static_cast<long long>(n.firstPcmMachNs)+static_cast<long long>(n.bridgeSteadyNs)-static_cast<long long>(n.bridgeMachNs);
 std::cout<<"native_scope="<<scope<<"\nav_construction_wall_s="<<n.avConstruction.wallSeconds<<"\nav_construction_thread_cpu_s="<<n.avConstruction.threadCpuSeconds<<"\nav_start_wall_s="<<n.avStart.wallSeconds<<"\nav_start_thread_cpu_s="<<n.avStart.threadCpuSeconds
 <<"\nplay_to_first_pcm_callback_s="<<double(firstSteady-static_cast<long long>(n.playCalledSteadyNs))*1e-9<<"\nfirst_pcm_measured="<<(n.firstPcmMachNs!=0)<<'\n';}
#else
void nativeSnapshot(MacPlaybackEngine&,const char*){}
#endif
template<class Engine>void snapshot(Engine& e,const char* scope){
#ifdef PHASE54_API
 printStages(e.getStartupDiagnostics(),scope);
#endif
}
int main(int argc,char**argv){try{if(argc<3)throw std::invalid_argument("input.wav other.wav [native|prepare-only]");std::cout<<std::setprecision(17)<<"stage,wall_s,caller_cpu_s,process_cpu_s,rss_bytes,start_steady_ns,end_steady_ns\n";bool native=argc>3&&std::string(argv[3])=="native";auto c=Configuration::candidate(argc>4?std::stod(argv[4]):.5);
 if(native){MacPlaybackEngine e;MacOptions o;o.recordCallbacks=true;measure("cold_prepare",[&]{return e.prepare(argv[1],c,o);});snapshot(e,"cold_prepare");measure("ready_play",[&]{return e.play();});snapshot(e,"ready_play");std::this_thread::sleep_for(std::chrono::seconds(1));nativeSnapshot(e,"ready_play");e.stop();measure("stop_play",[&]{return e.play();});snapshot(e,"stop_play");std::this_thread::sleep_for(std::chrono::seconds(1));nativeSnapshot(e,"stop_play");e.stop();auto records=e.callbackRecords();auto n=e.getNativeDiagnostics();
#ifdef PHASE54_API
 printStages(e.getStartupDiagnostics());std::cout<<"av_construction,"<<n.avConstruction.wallSeconds<<','<<n.avConstruction.threadCpuSeconds<<",0,0,0,0\nav_start,"<<n.avStart.wallSeconds<<','<<n.avStart.threadCpuSeconds<<",0,0,0,0\nfirst_pcm_mach_ns="<<n.firstPcmMachNs<<"\nplay_called_steady_ns="<<n.playCalledSteadyNs<<'\n';
#endif
 std::cout<<"bridge_steady_ns="<<n.bridgeSteadyNs<<"\nbridge_mach_ns="<<n.bridgeMachNs<<'\n';std::cout<<"native_first_pcm_ns=";for(auto&r:records)if(r.raw.received){std::cout<<r.startNs;break;}std::cout<<"\nunderruns="<<e.getPlaybackDiagnostics().missingFrames<<"\ncallback_overruns="<<n.deadlineMisses<<"\ndevice="<<n.deviceId<<"\ndevice_rate="<<n.deviceRate<<'\n';return 0;}
 PlaybackEngine e;measure("cold_prepare",[&]{return e.prepare(argv[1],c);});snapshot(e,"cold_prepare");if(argc>3&&std::string(argv[3])=="prepare-only"){
#ifdef PHASE54_API
 printStages(e.getStartupDiagnostics());
#endif
 return 0;}measure("ready_play",[&]{return e.play();});snapshot(e,"ready_play");measure("already_playing",[&]{return e.play();});e.stop();measure("stop_play",[&]{return e.play();});snapshot(e,"stop_play");if(argc>3&&std::string(argv[3])=="startup-only"){e.stop();return 0;}drain(e);measure("eos_play",[&]{return e.play();});snapshot(e,"eos_play");e.stop();measure("same_file_new_speed",[&]{return e.prepare(argv[1],Configuration::candidate(1.5));});measure("other_file",[&]{return e.prepare(argv[2],c);});measure("return_file",[&]{return e.prepare(argv[1],c);});
#ifdef PHASE54_API
 printStages(e.getStartupDiagnostics());
#endif
 return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
