#import <Foundation/Foundation.h>
#import <AudioToolbox/AudioToolbox.h>
#include "prototype/Phase58Diagnostics.h"
#include "prototype/Phase56PinnedWav.h"
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <mach/thread_policy.h>
#include <pthread.h>
#include <array>
#include <iostream>
#include <cmath>
using namespace ts::prototype;
namespace {
struct Observation {
    const char* name="";int setResult=-1,queryResult=-1,infoResult=-1,relative=0;
    qos_class_t qos=QOS_CLASS_UNSPECIFIED;thread_extended_info_data_t info{};
};
Observation observe(const char* name,int set=-1){
    Observation r;r.name=name;r.setResult=set;
    r.queryResult=pthread_get_qos_class_np(pthread_self(),&r.qos,&r.relative);
    mach_msg_type_number_t count=THREAD_EXTENDED_INFO_COUNT;
    r.infoResult=thread_info(pthread_mach_thread_np(pthread_self()),THREAD_EXTENDED_INFO,reinterpret_cast<thread_info_t>(&r.info),&count);
    return r;
}
struct Activity {
    id<NSObject> token=nil;
    explicit Activity(bool enabled){if(enabled)token=[NSProcessInfo.processInfo beginActivityWithOptions:NSActivityUserInitiatedAllowingIdleSystemSleep|NSActivityLatencyCritical reason:@"Phase58 Fixのスケジューリング診断"];}
    ~Activity(){if(token)[NSProcessInfo.processInfo endActivity:token];}
};
}
int main(int argc,char** argv){@autoreleasepool{try{
    if(argc!=3)throw std::invalid_argument("fixture.wav plain|activity|workgroup");
    const std::string mode=argv[2];if(mode!="plain"&&mode!="activity"&&mode!="workgroup")throw std::invalid_argument("mode");
    Activity activity(mode=="activity");ts::WavStreamReader metadata(argv[1]);
    os_workgroup_interval_t group=mode=="workgroup"?AudioWorkIntervalCreate("Phase58 Fix synthetic scheduling probe",OS_CLOCK_MACH_ABSOLUTE_TIME,nullptr):nil;
    if(mode=="workgroup"&&!group)throw std::runtime_error("Cannot create audio work interval");
    phase56::ProgressiveAnalysisSession analysis(metadata.sampleRate(),metadata.channels(),1,{},std::vector<std::uint32_t>{2000000});
    phase56::PinnedWavSource source(argv[1],1);std::size_t at=0;
    while(at<metadata.frames())at+=source.appendNext(analysis,32768);
    source.finish(analysis);auto snapshot=analysis.getSnapshot();
    std::array<Observation,9> observations{};std::exception_ptr error;
    int policySet=-1,join=-1,intervalStart=-1,intervalFinish=-1,restore=-1;
    std::thread worker([&]{try{
        observations[0]=observe("thread_entry");
        observations[1]=observe("after_qos_request",pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED,0));
        phase57::ProgressiveSynthesisEngine engine(argv[1],2000000,1);
        engine.setDeclaredFinalOutputFrames(std::size_t(std::llround(metadata.frames()*.5)));
        observations[2]=observe("after_engine_initialization");
        engine.supplySnapshot(snapshot);engine.advance([](auto,auto,const float*const*,std::size_t){});
        observations[3]=observe("after_first_dsp_block");
        const auto until=std::chrono::steady_clock::now()+std::chrono::milliseconds(100);
        volatile double x=.1;while(std::chrono::steady_clock::now()<until)x=std::sin(x+.001);
        observations[4]=observe("after_100ms_cpu_work");
        observations[5]=observe("after_qos_reapplication",pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED,0));
        if(group){
            mach_timebase_info_data_t base{};mach_timebase_info(&base);
            const auto ticks=[&](double seconds){return std::uint32_t(seconds*1e9*base.denom/base.numer);};
            thread_time_constraint_policy_data_t policy{ticks(2048./metadata.sampleRate()),ticks(.9*2048./metadata.sampleRate()),ticks(2048./metadata.sampleRate()),true};
            const auto thread=pthread_mach_thread_np(pthread_self());
            policySet=thread_policy_set(thread,THREAD_TIME_CONSTRAINT_POLICY,reinterpret_cast<thread_policy_t>(&policy),THREAD_TIME_CONSTRAINT_POLICY_COUNT);
            observations[6]=observe("after_time_constraint_request");
            os_workgroup_join_token_s token{};
            if(policySet==KERN_SUCCESS){
                join=os_workgroup_join(group,&token);observations[7]=observe("after_workgroup_join");
                if(join==0){
                    const auto begin=mach_absolute_time();intervalStart=os_workgroup_interval_start(group,begin,begin+ticks(2048./metadata.sampleRate()),nullptr);
                    if(intervalStart==0){const auto end=begin+ticks(.001);volatile double v=.1;while(mach_absolute_time()<end)v=std::sin(v+.001);intervalFinish=os_workgroup_interval_finish(group,nullptr);}
                    os_workgroup_leave(group,&token);
                }
                thread_extended_policy_data_t normal{true};restore=thread_policy_set(thread,THREAD_EXTENDED_POLICY,reinterpret_cast<thread_policy_t>(&normal),THREAD_EXTENDED_POLICY_COUNT);
                pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED,0);
            }
            observations[8]=observe("after_standard_policy_restored");
        }
    }catch(...){error=std::current_exception();}});worker.join();if(error)std::rethrow_exception(error);
    std::cout<<"{\"mode\":"<<phase58::jsonString(mode)<<",\"activity_obtained\":"<<(activity.token!=nil)<<",\"audio_output_test\":false,\"synthetic_realtime_only\":"<<(mode=="workgroup")<<",\"policy_set_result\":"<<policySet<<",\"workgroup_join_result\":"<<join<<",\"interval_start_result\":"<<intervalStart<<",\"interval_finish_result\":"<<intervalFinish<<",\"restore_result\":"<<restore<<",\"observations\":[";
    for(std::size_t i=0;i<(mode=="workgroup"?observations.size():6);++i){const auto& o=observations[i];if(i)std::cout<<',';
        std::cout<<"{\"stage\":"<<phase58::jsonString(o.name)<<",\"set_result\":"<<o.setResult<<",\"query_result\":"<<o.queryResult<<",\"info_result\":"<<o.infoResult<<",\"qos_class\":"<<unsigned(o.qos)<<",\"relative_priority\":"<<o.relative<<",\"policy\":"<<o.info.pth_policy<<",\"current_priority\":"<<o.info.pth_curpri<<",\"base_priority\":"<<o.info.pth_priority<<",\"max_priority\":"<<o.info.pth_maxpriority<<'}';
    }std::cout<<"]}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}}
