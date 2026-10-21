#include "prototype/Phase58FixRealtimeWorker.h"
#include <AudioToolbox/AudioWorkInterval.h>
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <mach/thread_policy.h>
#include <mach/sync_policy.h>
#include <os/object.h>
#include <pthread.h>
#include <atomic>
#include <algorithm>
#include <limits>
#include <stdexcept>
namespace ts::prototype::phase58 {
struct RealtimeWorkerSupport::Impl {
    const bool enabled;const double period,computation;
    mach_timebase_info_data_t timebase{};std::uint32_t periodTicks=0,computationTicks=0;
    os_workgroup_interval_t group=nullptr;semaphore_t semaphore=MACH_PORT_NULL;
    os_workgroup_join_token_s token{};thread_extended_policy_data_t normal{true};
    bool policySet=false,joined=false,interval=false;std::uint64_t intervalStart=0,deadline=0;
    RealtimeIntervalTiming lastInterval;
    std::atomic<bool> active{false},notified{false},policyMeasured{false};
    std::atomic<std::uint64_t> promotions{0},joins{0},leaves{0},restores{0},starts{0},finishes{0};
    std::atomic<std::uint64_t> policyErrors{0},joinErrors{0},restoreErrors{0},intervalErrors{0},queryErrors{0},waitCalls{0},waitErrors{0},wakeErrors{0},misses{0};
    std::atomic<int> observedPolicy{-1},observedPriority{-1},restoredPolicy{-1},lastError{0},errorStage{0};
    std::atomic<double> maxInterval{0};
    std::atomic<std::uint64_t> createdTicks{0},policyAppliedTicks{0},joinedTicks{0},leftTicks{0},restoredTicks{0};
    Impl(bool on,std::uint32_t rate):enabled(on),period(rate?2048./rate:0),computation(.9*period){
        if(!enabled)return;
        if(rate!=44100&&rate!=48000)throw std::invalid_argument("Realtime worker rate");
        if(mach_timebase_info(&timebase)!=KERN_SUCCESS)throw std::runtime_error("Mach clock unavailable");
        const auto ticks=[&](double s){const auto n=s*1e9*timebase.denom/timebase.numer;if(n<1||n>std::numeric_limits<std::uint32_t>::max())throw std::invalid_argument("Realtime interval range");return std::uint32_t(n);};
        periodTicks=ticks(period);computationTicks=ticks(computation);
        group=AudioWorkIntervalCreate("TimeStretchLab Phase58 Fix DSP",OS_CLOCK_MACH_ABSOLUTE_TIME,nullptr);
        if(!group)throw std::runtime_error("Cannot create audio workgroup interval");
        createdTicks=mach_absolute_time();
        if(semaphore_create(mach_task_self(),&semaphore,SYNC_POLICY_FIFO,0)!=KERN_SUCCESS){os_release(group);group=nullptr;throw std::runtime_error("Cannot create DSP semaphore");}
    }
    ~Impl(){if(semaphore!=MACH_PORT_NULL)semaphore_destroy(mach_task_self(),semaphore);if(group)os_release(group);}
    void error(int stage,int code)noexcept{errorStage=stage;lastError=code;}
    bool finish()noexcept{
        if(!interval)return true;
        const auto end=mach_absolute_time();const double seconds=double(end-intervalStart)*timebase.numer/timebase.denom*1e-9;
        lastInterval={intervalStart,end,deadline};
        maxInterval=std::max(maxInterval.load(),seconds);if(end>deadline)++misses;
        const auto result=os_workgroup_interval_finish(group,nullptr);interval=false;
        if(result){++intervalErrors;error(4,result);return false;}++finishes;return true;
    }
    bool demote()noexcept{
        bool success=finish();
        if(joined){os_workgroup_leave(group,&token);leftTicks=mach_absolute_time();joined=false;++leaves;}
        if(policySet){
            const auto thread=pthread_mach_thread_np(pthread_self());
            const auto result=thread_policy_set(thread,THREAD_EXTENDED_POLICY,reinterpret_cast<thread_policy_t>(&normal),THREAD_EXTENDED_POLICY_COUNT);
            if(result!=KERN_SUCCESS){++restoreErrors;error(5,result);success=false;}
            else{restoredTicks=mach_absolute_time();++restores;policySet=false;thread_extended_info_data_t info{};mach_msg_type_number_t count=THREAD_EXTENDED_INFO_COUNT;
                const auto queried=thread_info(thread,THREAD_EXTENDED_INFO,reinterpret_cast<thread_info_t>(&info),&count);
                if(queried==KERN_SUCCESS)restoredPolicy=info.pth_policy;else{++queryErrors;error(8,queried);success=false;}}
        }
        active=false;return success;
    }
};
RealtimeWorkerSupport::RealtimeWorkerSupport(bool enabled,std::uint32_t rate):impl_(std::make_unique<Impl>(enabled,rate)){}
RealtimeWorkerSupport::~RealtimeWorkerSupport()=default;
bool RealtimeWorkerSupport::promote(bool failJoinForTest)noexcept{
    auto& x=*impl_;if(!x.enabled||x.active.load())return true;
    const auto thread=pthread_mach_thread_np(pthread_self());mach_msg_type_number_t count=THREAD_EXTENDED_POLICY_COUNT;boolean_t defaults=false;
    auto result=thread_policy_get(thread,THREAD_EXTENDED_POLICY,reinterpret_cast<thread_policy_t>(&x.normal),&count,&defaults);
    if(result!=KERN_SUCCESS){++x.queryErrors;x.error(8,result);return false;}
    thread_time_constraint_policy_data_t policy{x.periodTicks,x.computationTicks,x.periodTicks,true};
    result=thread_policy_set(thread,THREAD_TIME_CONSTRAINT_POLICY,reinterpret_cast<thread_policy_t>(&policy),THREAD_TIME_CONSTRAINT_POLICY_COUNT);
    if(result!=KERN_SUCCESS){++x.policyErrors;x.error(1,result);return false;}
    x.policyAppliedTicks=mach_absolute_time();
    x.policySet=true;++x.promotions;
    const auto join=failJoinForTest?EINVAL:os_workgroup_join(x.group,&x.token);
    if(join){++x.joinErrors;x.error(2,join);x.demote();return false;}
    x.joinedTicks=mach_absolute_time();
    x.joined=true;++x.joins;
    thread_extended_info_data_t info{};count=THREAD_EXTENDED_INFO_COUNT;
    result=thread_info(thread,THREAD_EXTENDED_INFO,reinterpret_cast<thread_info_t>(&info),&count);
    if(result!=KERN_SUCCESS){++x.queryErrors;x.error(8,result);x.demote();return false;}
    x.observedPolicy=info.pth_policy;x.observedPriority=info.pth_curpri;
    if(info.pth_policy!=POLICY_RR||info.pth_curpri<64){++x.queryErrors;x.error(8,KERN_INVALID_POLICY);x.demote();return false;}
    x.policyMeasured=true;x.active=true;return true;
}
bool RealtimeWorkerSupport::demote()noexcept{return impl_->demote();}
bool RealtimeWorkerSupport::active()const noexcept{return impl_->active.load();}
bool RealtimeWorkerSupport::beginInterval()noexcept{
    auto& x=*impl_;if(!x.active.load())return true;
    x.intervalStart=mach_absolute_time();x.deadline=x.intervalStart+x.periodTicks;
    const auto result=os_workgroup_interval_start(x.group,x.intervalStart,x.deadline,nullptr);
    if(result){++x.intervalErrors;x.error(3,result);return false;}x.interval=true;++x.starts;return true;
}
bool RealtimeWorkerSupport::finishInterval()noexcept{return impl_->finish();}
RealtimeIntervalTiming RealtimeWorkerSupport::lastInterval()const noexcept{return impl_->lastInterval;}
void RealtimeWorkerSupport::signal()noexcept{
    auto& x=*impl_;if(!x.enabled||x.notified.exchange(true))return;
    const auto result=semaphore_signal(x.semaphore);if(result!=KERN_SUCCESS){x.notified=false;++x.wakeErrors;x.error(7,result);}
}
void RealtimeWorkerSupport::waitForSignal()noexcept{
    auto& x=*impl_;if(!x.enabled)return;++x.waitCalls;mach_timespec_t duration{0,2000000};
    const auto result=semaphore_timedwait(x.semaphore,duration);
    if(result==KERN_SUCCESS)x.notified=false;
    else if(result!=KERN_OPERATION_TIMED_OUT&&result!=KERN_ABORTED){++x.waitErrors;x.error(6,result);}
}
RealtimeWorkerMetrics RealtimeWorkerSupport::metrics()const noexcept{
    const auto& x=*impl_;RealtimeWorkerMetrics r;r.enabled=x.enabled;r.active=x.active;r.policyMeasured=x.policyMeasured;
    r.promotions=x.promotions;r.joins=x.joins;r.leaves=x.leaves;r.restores=x.restores;r.intervalStarts=x.starts;r.intervalFinishes=x.finishes;
    r.policyErrors=x.policyErrors;r.joinErrors=x.joinErrors;r.restoreErrors=x.restoreErrors;r.intervalErrors=x.intervalErrors;r.queryErrors=x.queryErrors;
    r.waitCalls=x.waitCalls;r.waitErrors=x.waitErrors;r.wakeErrors=x.wakeErrors;r.deadlineMisses=x.misses;
    r.observedPolicy=x.observedPolicy;r.observedPriority=x.observedPriority;r.restoredPolicy=x.restoredPolicy;r.lastError=x.lastError;r.errorStage=x.errorStage;
    r.createdTicks=x.createdTicks;r.policyAppliedTicks=x.policyAppliedTicks;r.joinedTicks=x.joinedTicks;r.leftTicks=x.leftTicks;r.restoredTicks=x.restoredTicks;
    r.periodS=x.period;r.computationS=x.computation;r.maxIntervalS=x.maxInterval;return r;
}
}
