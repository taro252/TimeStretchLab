#pragma once
#include <cstdint>
#include <memory>
namespace ts::prototype::phase58 {
struct RealtimeWorkerMetrics {
    bool enabled=false,active=false,policyMeasured=false;
    std::uint64_t promotions=0,joins=0,leaves=0,restores=0,intervalStarts=0,intervalFinishes=0;
    std::uint64_t policyErrors=0,joinErrors=0,restoreErrors=0,intervalErrors=0,queryErrors=0;
    std::uint64_t waitCalls=0,waitErrors=0,wakeErrors=0,deadlineMisses=0;
    int observedPolicy=-1,observedPriority=-1,restoredPolicy=-1,lastError=0,errorStage=0;
    double periodS=0,computationS=0,maxIntervalS=0;
    std::uint64_t createdTicks=0,policyAppliedTicks=0,joinedTicks=0,leftTicks=0,restoredTicks=0;
};
struct RealtimeIntervalTiming {
    std::uint64_t startTicks=0,endTicks=0,deadlineTicks=0;
};
// Created/released by the normal owner. Only the DSP worker promotes, joins,
// starts/finishes intervals and demotes. Other normal threads may signal it.
class RealtimeWorkerSupport {
    struct Impl;std::unique_ptr<Impl> impl_;
public:
    RealtimeWorkerSupport(bool enabled,std::uint32_t rate);
    ~RealtimeWorkerSupport();
    bool promote(bool failJoinForTest=false)noexcept;
    bool demote()noexcept;
    bool active()const noexcept;
    bool beginInterval()noexcept;
    bool finishInterval()noexcept;
    void signal()noexcept;
    void waitForSignal()noexcept;
    RealtimeWorkerMetrics metrics()const noexcept;
    RealtimeIntervalTiming lastInterval()const noexcept; // DSP owner thread only.
};
}
