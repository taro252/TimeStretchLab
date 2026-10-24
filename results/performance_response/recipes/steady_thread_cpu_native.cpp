// 同一sourceを旧/新headers・archiveへ個別linkする、通常診断OFFのnative CPU比較。
#define TS_PHASE62_INITIAL_NO_MAIN 1
#include "Phase62InitialLoopNative.cpp"
#include <sys/resource.h>
#include <libproc.h>/* THREAD_CPU_HEADERS_BEGIN */
#include <mach/mach.h>
#include <mach/thread_info.h>
#include <pthread.h>
#include <cstring>
/* THREAD_CPU_HEADERS_END */
namespace {
/* THREAD_CPU_HELPERS_BEGIN */
// 全て通常control thread。元a/b CPU窓の外側で各1回だけ採取する。
struct ThreadCpuRow {
    std::uint64_t beginNs=0,endNs=0,id=0,handle=0;
    kern_return_t identifierStatus=KERN_FAILURE,basicStatus=KERN_FAILURE,extendedStatus=KERN_FAILURE;
    mach_msg_type_number_t identifierCount=0,basicCount=0,extendedCount=0;
    thread_basic_info_data_t basic{};
    thread_extended_info_data_t extended{};
};
struct ThreadCpuSnapshot {
    std::uint64_t beginNs=0,endNs=0,controlId=0;
    int controlIdStatus=-1;
    kern_return_t taskStatus=KERN_FAILURE;
    std::vector<ThreadCpuRow> rows;
    std::vector<kern_return_t> portRelease;
    kern_return_t listRelease=KERN_SUCCESS;
    bool complete=false;
};
// bad_alloc/例外でもMach送信権と配列を解放する。callbackには到達しない。
struct ThreadCpuPorts {
    thread_act_array_t list=nullptr;mach_msg_type_number_t count=0;
    ~ThreadCpuPorts(){if(list){for(unsigned i=0;i<count;++i)mach_port_deallocate(mach_task_self(),list[i]);vm_deallocate(mach_task_self(),reinterpret_cast<vm_address_t>(list),count*sizeof(thread_t));}}
};
ThreadCpuSnapshot threadCpuSnapshot(){
    ThreadCpuSnapshot s;s.beginNs=initialNs();s.controlIdStatus=pthread_threadid_np(nullptr,&s.controlId);
    ThreadCpuPorts ports;s.taskStatus=task_threads(mach_task_self(),&ports.list,&ports.count);
    if(s.taskStatus==KERN_SUCCESS){
        s.rows.reserve(ports.count);s.portRelease.reserve(ports.count);
        for(unsigned i=0;i<ports.count;++i){
            ThreadCpuRow r;r.beginNs=initialNs();thread_identifier_info_data_t id{};
            r.identifierCount=THREAD_IDENTIFIER_INFO_COUNT;
            r.identifierStatus=thread_info(ports.list[i],THREAD_IDENTIFIER_INFO,reinterpret_cast<thread_info_t>(&id),&r.identifierCount);
            if(r.identifierStatus==KERN_SUCCESS){r.id=id.thread_id;r.handle=id.thread_handle;}
            r.basicCount=THREAD_BASIC_INFO_COUNT;
            r.basicStatus=thread_info(ports.list[i],THREAD_BASIC_INFO,reinterpret_cast<thread_info_t>(&r.basic),&r.basicCount);
            r.extendedCount=THREAD_EXTENDED_INFO_COUNT;
            r.extendedStatus=thread_info(ports.list[i],THREAD_EXTENDED_INFO,reinterpret_cast<thread_info_t>(&r.extended),&r.extendedCount);
            r.endNs=initialNs();s.rows.push_back(r);
        }
        for(unsigned i=0;i<ports.count;++i)s.portRelease.push_back(mach_port_deallocate(mach_task_self(),ports.list[i]));
        s.listRelease=vm_deallocate(mach_task_self(),reinterpret_cast<vm_address_t>(ports.list),ports.count*sizeof(thread_t));
        ports.list=nullptr; // 解放statusは結果へ残す。失敗を成功扱いにしない。
    }
    s.endNs=initialNs();s.complete=s.taskStatus==KERN_SUCCESS&&s.controlIdStatus==0&&!s.rows.empty()&&s.listRelease==KERN_SUCCESS;
    for(const auto& r:s.rows)s.complete=s.complete&&r.identifierStatus==KERN_SUCCESS&&r.id&&r.identifierCount==THREAD_IDENTIFIER_INFO_COUNT&&r.basicStatus==KERN_SUCCESS&&r.basicCount==THREAD_BASIC_INFO_COUNT&&r.extendedStatus==KERN_SUCCESS&&r.extendedCount==THREAD_EXTENDED_INFO_COUNT;
    for(auto status:s.portRelease)s.complete=s.complete&&status==KERN_SUCCESS;
    return s;
}
void threadCpuJson(std::ostream& f,const ThreadCpuSnapshot& s){
    f<<"{\"begin_ns\":"<<s.beginNs<<",\"end_ns\":"<<s.endNs<<",\"control_thread_id\":"<<s.controlId<<",\"control_id_status\":"<<s.controlIdStatus<<",\"task_status\":"<<s.taskStatus<<",\"list_release_status\":"<<s.listRelease<<",\"complete\":"<<(s.complete?"true":"false")<<",\"port_release_status\":[";
    for(std::size_t i=0;i<s.portRelease.size();++i)f<<(i?",":"")<<s.portRelease[i];f<<"],\"threads\":[";
    for(std::size_t i=0;i<s.rows.size();++i){const auto& r=s.rows[i];if(i)f<<',';
        f<<"{\"query_begin_ns\":"<<r.beginNs<<",\"query_end_ns\":"<<r.endNs<<",\"identifier_status\":"<<r.identifierStatus<<",\"identifier_count\":"<<r.identifierCount<<",\"id\":"<<r.id<<",\"handle\":"<<r.handle<<",\"basic_status\":"<<r.basicStatus<<",\"basic_count\":"<<r.basicCount<<",\"extended_status\":"<<r.extendedStatus<<",\"extended_count\":"<<r.extendedCount<<",\"basic\":";
        if(r.basicStatus==KERN_SUCCESS){const auto& b=r.basic;f<<"{\"user_s\":"<<double(b.user_time.seconds)+double(b.user_time.microseconds)*1e-6<<",\"system_s\":"<<double(b.system_time.seconds)+double(b.system_time.microseconds)*1e-6<<",\"cpu_usage\":"<<b.cpu_usage<<",\"policy\":"<<b.policy<<",\"run_state\":"<<b.run_state<<",\"flags\":"<<b.flags<<",\"suspend_count\":"<<b.suspend_count<<",\"sleep_time\":"<<b.sleep_time<<'}';}else f<<"null";
        f<<",\"extended\":";if(r.extendedStatus==KERN_SUCCESS){const auto& e=r.extended;const std::string name(e.pth_name,strnlen(e.pth_name,sizeof(e.pth_name)));f<<"{\"name\":"<<ts::prototype::phase58::jsonString(name)<<",\"user_ns\":"<<e.pth_user_time<<",\"system_ns\":"<<e.pth_system_time<<",\"cpu_usage\":"<<e.pth_cpu_usage<<",\"policy\":"<<e.pth_policy<<",\"run_state\":"<<e.pth_run_state<<",\"flags\":"<<e.pth_flags<<",\"sleep_time\":"<<e.pth_sleep_time<<",\"current_priority\":"<<e.pth_curpri<<",\"priority\":"<<e.pth_priority<<",\"max_priority\":"<<e.pth_maxpriority<<'}';}else f<<"null";f<<'}';
    }f<<"]}";
}
void threadCpuCounters(std::ostream& f,const ProgressiveDiagnostics& d){
    const auto& p=d.pipeline;const auto& s=p.scheduling;
    f<<"{\"session\":"<<d.session<<",\"render_epoch\":"<<d.renderEpoch<<",\"pipeline_session\":"<<p.session<<",\"analysis_thread_id\":"<<p.analysisThread<<",\"dsp_thread_id\":"<<p.dspThread<<",\"wait_calls\":"<<s.waitCalls<<",\"interval_starts\":"<<s.intervalStarts<<",\"interval_finishes\":"<<s.intervalFinishes<<",\"generated\":"<<p.generated<<",\"published\":"<<p.published<<",\"consumed\":"<<p.consumed<<",\"generated_frames\":"<<d.generatedFrames<<",\"published_frames\":"<<d.publishedFrames<<",\"consumed_frames\":"<<d.consumedFrames<<",\"presented_frames\":"<<d.presentedFrames<<",\"fifo_high_water\":"<<p.fifoHighWater<<",\"analysis_worker_cpu_s\":"<<p.analysisWorkerCpuS<<",\"dsp_worker_cpu_s\":"<<p.dspWorkerCpuS<<",\"backpressure_wait_s\":"<<p.backpressureWaitS<<",\"scheduling_enabled\":"<<(s.enabled?"true":"false")<<",\"scheduling_active\":"<<(s.active?"true":"false");
#if TS_THREAD_CPU_SHARED_PRODUCER
    f<<",\"analysis_producer_thread_id\":"<<p.analysisProducerThread<<",\"analysis_producer_cpu_s\":"<<p.analysisProducerCpuS;
#else
    f<<",\"analysis_producer_thread_id\":null,\"analysis_producer_cpu_s\":null";
#endif
    f<<'}';
}
/* THREAD_CPU_HELPERS_END */struct SteadyCpu {double wall=0,cpu=0;std::uint64_t wakeups=0;};
SteadyCpu steadyCpu(){rusage u{};require(!getrusage(RUSAGE_SELF,&u),"rusage");rusage_info_v4 p{};require(!proc_pid_rusage(getpid(),RUSAGE_INFO_V4,reinterpret_cast<rusage_info_t*>(&p)),"proc usage");return {double(initialNs())*1e-9,u.ru_utime.tv_sec+u.ru_utime.tv_usec*1e-6+u.ru_stime.tv_sec+u.ru_stime.tv_usec*1e-6,p.ri_interrupt_wkups};}
int steadyMain(int argc,char** argv){
    require(argc==6,"input preset speed seconds NEW_OUTPUT");const auto out=std::filesystem::path(argv[5]);require(std::filesystem::create_directories(out),"fresh evidence required");
    const auto duration=std::stod(argv[4]);require(duration>=5&&duration<=60,"bounded measurement");
    ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.preset=std::string(argv[2])=="candidate"?Preset::Candidate:Preset::Baseline;o.initialSpeed=std::stod(argv[3]);o.allowExperimentalLoops=true;o.seekCheckpoints=false;
    phase61_heap_reset();o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    require(e.prepare(argv[1],o),"prepare");initialWait(e,[&]{return e.getPlaybackState()==State::Ready&&e.getPlaybackDiagnostics().pipeline.analysisDone;});
    require(e.play(),"play");initialWait(e,[&]{return e.getPlaybackDiagnostics().consumedFrames>=1024;});
    const auto d0=e.getPlaybackDiagnostics();/* THREAD_CPU_PRE_BEGIN */const auto threadBefore=threadCpuSnapshot();/* THREAD_CPU_PRE_END */const auto a=steadyCpu();const auto end=InitialClock::now()+std::chrono::duration<double>(duration);std::uint64_t polls=0;
    while(InitialClock::now()<end){const auto s=e.getStateSnapshot();require(s.state==State::Playing,"playback did not remain Playing");(void)e.getCurrentPlaybackPosition();++polls;std::this_thread::sleep_for(std::chrono::milliseconds(200));}
    const auto b=steadyCpu();/* THREAD_CPU_POST_BEGIN */const auto threadAfter=threadCpuSnapshot();/* THREAD_CPU_POST_END */const auto d=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();e.stop();const auto final=e.getPlaybackDiagnostics();
    const auto owners=ts::prototype::phase58::RealtimePipeline::executionOwnerCounts();
    const bool rt=!final.missingFrames&&!final.rejectedWrites&&!final.workerDeadlineMisses&&!final.workgroupErrors&&!n.deadlineMisses&&!n.hostMissing&&!n.hostBackwards&&!n.hostCadenceErrors&&!n.sampleErrors&&!n.halWindowMisses&&!phase61_heap_allocations()&&!phase61_heap_frees()&&final.callbackCppNew&&!*final.callbackCppNew&&!final.workerNewCalls&&!owners.alive&&owners.peak<=2;
    std::ofstream f(out/"SUMMARY.json");f<<std::setprecision(15)<<"{\"complete\":true,\"rt_pass\":"<<(rt?"true":"false")<<",\"cpu_percent\":"<<100*(b.cpu-a.cpu)/(b.wall-a.wall)<<",\"cpu_s\":"<<b.cpu-a.cpu<<",\"wall_s\":"<<b.wall-a.wall<<",\"interrupt_wakeups\":"<<b.wakeups-a.wakeups<<",\"polls\":"<<polls<<",\"source_rate\":"<<d.sourceSampleRate<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"input_sha256\":\""<<final.pipeline.inputSha256<<"\",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"missing\":"<<final.missingFrames<<",\"rejected\":"<<final.rejectedWrites<<",\"generated_delta\":"<<d.pipeline.generated-d0.pipeline.generated<<",\"owners_peak\":"<<owners.peak<<",\"quality\":null,\"physical_audio\":null}\n";
/* THREAD_CPU_WRITE_BEGIN */
    f.flush();require(bool(f),"SUMMARY write");
    std::ofstream tf(out/"THREAD_CPU.json");tf<<std::setprecision(17);
    tf<<"{\"schema\":\"steady-thread-cpu-v1\",\"classification\":\"DIAGNOSTIC\",\"complete\":"<<(threadBefore.complete&&threadAfter.complete?"true":"false")<<",\"callback_modified\":false,\"extra_window_getters\":0,\"profile_changed\":false,\"cpu_approval\":false,\"quality\":null,\"physical_audio\":null,\"process_window\":{\"start_wall_s\":"<<a.wall<<",\"end_wall_s\":"<<b.wall<<",\"start_cpu_s\":"<<a.cpu<<",\"end_cpu_s\":"<<b.cpu<<",\"cpu_s\":"<<b.cpu-a.cpu<<",\"wall_s\":"<<b.wall-a.wall<<",\"cpu_percent\":"<<100*(b.cpu-a.cpu)/(b.wall-a.wall)<<"},\"before\":";threadCpuJson(tf,threadBefore);tf<<",\"after\":";threadCpuJson(tf,threadAfter);
    tf<<",\"counters_before\":";threadCpuCounters(tf,d0);tf<<",\"counters_after\":";threadCpuCounters(tf,d);
    tf<<",\"rt_pass\":"<<(rt?"true":"false")<<",\"rt_values\":{\"missing\":"<<final.missingFrames<<",\"rejected\":"<<final.rejectedWrites<<",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"workgroup_errors\":"<<final.workgroupErrors<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"host_missing\":"<<n.hostMissing<<",\"host_backwards\":"<<n.hostBackwards<<",\"host_cadence_errors\":"<<n.hostCadenceErrors<<",\"sample_errors\":"<<n.sampleErrors<<",\"hal_window_misses\":"<<n.halWindowMisses<<",\"callback_malloc\":"<<phase61_heap_allocations()<<",\"callback_free\":"<<phase61_heap_frees()<<",\"callback_cpp_new\":";if(final.callbackCppNew)tf<<*final.callbackCppNew;else tf<<"null";
    tf<<",\"worker_new\":"<<final.workerNewCalls<<",\"owners_alive\":"<<owners.alive<<",\"owners_peak\":"<<owners.peak<<",\"fifo_supply_failed\":"<<(final.fifoSupplyFailed?"true":"false")<<"},\"notes\":\"task_threads snapshots are sequential/non-atomic and outside original process CPU a/b. Counter d0/d span also includes the two snapshots. New/gone threads have no invented zero CPU; CPU samples are not statistical causal evidence or adoption approval.\"}\n";
    tf.flush();require(bool(tf),"THREAD_CPU write");
    /* THREAD_CPU_WRITE_END */    return rt?0:2;
}
}
int main(int argc,char** argv){int result=1;std::thread control([&]{try{result=steadyMain(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return result;}
