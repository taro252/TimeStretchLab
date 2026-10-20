#pragma once
#include <cstdint>
#include <string>
#include <optional>
namespace ts::playback::progressive {
enum class LoopState {Disabled,Pending,Preparing,Armed,Active,Cancelled,Rejected,Failed};
inline const char* name(LoopState s)noexcept{
    switch(s){case LoopState::Disabled:return "Disabled";case LoopState::Pending:return "Pending";
    case LoopState::Preparing:return "Preparing";case LoopState::Armed:return "Armed";case LoopState::Active:return "Active";
    case LoopState::Cancelled:return "Cancelled";case LoopState::Rejected:return "Rejected";case LoopState::Failed:return "Failed";}return "Unknown";
}
enum class LoopStartPolicy {ReturnToA,KeepPosition};
struct LoopContext {std::uint64_t inputGeneration=0,session=0,renderEpoch=0;};
struct LoopOptions {LoopStartPolicy startPolicy=LoopStartPolicy::ReturnToA;};
struct LoopReceipt {std::uint64_t id=0;bool accepted=false;std::string reason;};
struct LoopSpeedReceipt {std::uint64_t id=0;bool accepted=false,duplicate=false;std::string reason;};
struct LoopBoundaryEvent {
    std::uint64_t loopID=0,cycle=0,settingCycle=0,oldEpoch=0,newEpoch=0;
    std::uint64_t inputA=0,inputBExclusive=0,oldOutputEnd=0,newOutputStart=0;
    std::uint64_t callbackFrame=0,renderNs=0,halBoundaryEstimateNs=0; // frame of logical B, after overlap
    std::uint32_t overlapFrames=0;
    std::uint32_t boundaryProcessingFrames=0; // Fix: each side; overlapFrames=0, period stays L
};
struct LoopSnapshot {
    std::uint64_t id=0,inputGeneration=0,session=0,sourceRenderEpoch=0,currentRenderEpoch=0;
    std::uint64_t startFrame=0,endFrameExclusive=0,cycles=0;
    LoopState state=LoopState::Disabled;
    bool enabled=false,initialPositionComplete=false,clearPending=false;
    double requestedSpeed=1,appliedSpeed=1;
    std::uint64_t speedRequestID=0,acceptedNs=0,readyNs=0,preparationCount=0;
    std::uint64_t dynamicOperationID=0,dynamicCycle=0,mapVersion=0,dynamicOutputEnd=0;
    std::uint64_t dynamicSpeedRequestID=0,speedFailureRequestID=0;
    bool speedPreparationFailed=false;
    std::string speedDeferReason;
    std::uint64_t lastPreparationNs=0,lastReadyNs=0,maxPreparationNs=0;
    std::uint64_t safetyStopFrames=0; // explicit failure output, never successful silence
    std::uint64_t oldMissingFrames=0,newMissingFrames=0,outputAffectedFrames=0,failurePaddingFrames=0;
    bool reusable=false;
    std::uint64_t periodFrames=0,cacheBytes=0,reuseCount=0,seedRestores=0,mapBuilds=0,workerCreations=0;
    std::uint64_t coldDiscardedFrames=0,warmDiscardedFrames=0;
    std::optional<LoopBoundaryEvent> lastBoundary;
    std::string reason;
};
struct LoopAvailability {
    bool implemented=true,optIn=false,allowed=false,publicLoopApproved=false;
    bool currentCycleSpeedChanges=false; // partial implementation; full integration gates remain open
    std::uint32_t minimumInputMillis=100,maximumCallbackFrames=4096;
};
inline bool validLoopRange(std::uint64_t a,std::uint64_t b,std::uint64_t frames)noexcept{return a<b&&b<=frames;}
inline bool executableLoopRange(std::uint64_t a,std::uint64_t b,std::uint32_t rate)noexcept{return a<b&&b-a>=rate/10;}
}
