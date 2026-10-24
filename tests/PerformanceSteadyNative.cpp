// 同一sourceを旧/新headers・archiveへ個別linkする、通常診断OFFのnative CPU比較。
#define TS_PHASE62_INITIAL_NO_MAIN 1
#include "Phase62InitialLoopNative.cpp"
#include <sys/resource.h>
#include <libproc.h>
namespace {
struct SteadyCpu {double wall=0,cpu=0;std::uint64_t wakeups=0;};
SteadyCpu steadyCpu(){rusage u{};require(!getrusage(RUSAGE_SELF,&u),"rusage");rusage_info_v4 p{};require(!proc_pid_rusage(getpid(),RUSAGE_INFO_V4,reinterpret_cast<rusage_info_t*>(&p)),"proc usage");return {double(initialNs())*1e-9,u.ru_utime.tv_sec+u.ru_utime.tv_usec*1e-6+u.ru_stime.tv_sec+u.ru_stime.tv_usec*1e-6,p.ri_interrupt_wkups};}
int steadyMain(int argc,char** argv){
    require(argc==6,"input preset speed seconds NEW_OUTPUT");const auto out=std::filesystem::path(argv[5]);require(std::filesystem::create_directories(out),"fresh evidence required");
    const auto duration=std::stod(argv[4]);require(duration>=5&&duration<=60,"bounded measurement");
    ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.preset=std::string(argv[2])=="candidate"?Preset::Candidate:Preset::Baseline;o.initialSpeed=std::stod(argv[3]);o.allowExperimentalLoops=true;o.seekCheckpoints=false;
    phase61_heap_reset();o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    require(e.prepare(argv[1],o),"prepare");initialWait(e,[&]{return e.getPlaybackState()==State::Ready&&e.getPlaybackDiagnostics().pipeline.analysisDone;});
    require(e.play(),"play");initialWait(e,[&]{return e.getPlaybackDiagnostics().consumedFrames>=1024;});
    const auto d0=e.getPlaybackDiagnostics();const auto a=steadyCpu();const auto end=InitialClock::now()+std::chrono::duration<double>(duration);std::uint64_t polls=0;
    while(InitialClock::now()<end){const auto s=e.getStateSnapshot();require(s.state==State::Playing,"playback did not remain Playing");(void)e.getCurrentPlaybackPosition();++polls;std::this_thread::sleep_for(std::chrono::milliseconds(200));}
    const auto b=steadyCpu();const auto d=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();e.stop();const auto final=e.getPlaybackDiagnostics();
    const auto owners=ts::prototype::phase58::RealtimePipeline::executionOwnerCounts();
    const bool rt=!final.missingFrames&&!final.rejectedWrites&&!final.workerDeadlineMisses&&!final.workgroupErrors&&!n.deadlineMisses&&!n.hostMissing&&!n.hostBackwards&&!n.hostCadenceErrors&&!n.sampleErrors&&!n.halWindowMisses&&!phase61_heap_allocations()&&!phase61_heap_frees()&&final.callbackCppNew&&!*final.callbackCppNew&&!final.workerNewCalls&&!owners.alive&&owners.peak<=2;
    std::ofstream f(out/"SUMMARY.json");f<<std::setprecision(15)<<"{\"complete\":true,\"rt_pass\":"<<(rt?"true":"false")<<",\"cpu_percent\":"<<100*(b.cpu-a.cpu)/(b.wall-a.wall)<<",\"cpu_s\":"<<b.cpu-a.cpu<<",\"wall_s\":"<<b.wall-a.wall<<",\"interrupt_wakeups\":"<<b.wakeups-a.wakeups<<",\"polls\":"<<polls<<",\"source_rate\":"<<d.sourceSampleRate<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"input_sha256\":\""<<final.pipeline.inputSha256<<"\",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"missing\":"<<final.missingFrames<<",\"rejected\":"<<final.rejectedWrites<<",\"generated_delta\":"<<d.pipeline.generated-d0.pipeline.generated<<",\"owners_peak\":"<<owners.peak<<",\"quality\":null,\"physical_audio\":null}\n";
    return rt?0:2;
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=steadyMain(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return result;}
