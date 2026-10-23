#pragma once
#include <cstdint>
#include <string>
#include <optional>
#include "playback/ProgressiveFeatureContract.h"
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
struct LoopReceipt {std::uint64_t id=0;bool accepted=false;std::string reason;AvailabilityReason code=AvailabilityReason::Available;};
// Preparation is explicit, bounded and never changes playback position.
enum class LoopPreparationState {Pending,Preparing,Cancelling,Ready,Replaced,Cancelled,Failed};
inline bool terminal(LoopPreparationState s)noexcept{return s==LoopPreparationState::Ready||s==LoopPreparationState::Replaced||s==LoopPreparationState::Cancelled||s==LoopPreparationState::Failed;}
inline const char* name(LoopPreparationState s)noexcept{switch(s){
case LoopPreparationState::Pending:return "Pending";case LoopPreparationState::Preparing:return "Preparing";
case LoopPreparationState::Cancelling:return "Cancelling";case LoopPreparationState::Ready:return "Ready";
case LoopPreparationState::Replaced:return "Replaced";case LoopPreparationState::Cancelled:return "Cancelled";
case LoopPreparationState::Failed:return "Failed";}return "Unknown";}
struct LoopPreparationOperation {
    std::uint64_t id=0,inputGeneration=0,session=0,sourceRenderEpoch=0,version=0;
    std::uint64_t inputA=0,inputBExclusive=0,acceptedNs=0,startedNs=0,checkpointReadyNs=0,readyNs=0;
    std::uint64_t checkpointOutput=0,discardedFrames=0;
    std::uint32_t speedMicros=0;
    LoopPreparationState state=LoopPreparationState::Pending;
    AvailabilityReason code=AvailabilityReason::Available;
    double prefixCpuS=0,prefixWallS=0;
    bool workersJoined=false;
    std::string reason;
};
struct LoopPreparationSnapshot {std::optional<LoopPreparationOperation> latest;bool available=false;};
enum class LoopSpeedReceiptCode {Accepted,Duplicate,DuplicateInitial,InvalidContext,StaleContext,NoInput,NoLoop,ClearPending,LimitReached,Busy,Stopped};
struct LoopSpeedReceipt {std::uint64_t id=0;bool accepted=false,duplicate=false;std::string reason;LoopSpeedReceiptCode code=LoopSpeedReceiptCode::Stopped;};
enum class LoopSpeedState {Pending,Preparing,ReadyForResume,Committed,FixedBoundaryCommitted,Applied,Completed,Replaced,Cancelled,Failed};
inline const char* name(LoopSpeedState state)noexcept {
    switch(state){case LoopSpeedState::Pending:return "Pending";case LoopSpeedState::Preparing:return "Preparing";
    case LoopSpeedState::ReadyForResume:return "ReadyForResume";case LoopSpeedState::Committed:return "Committed";
    case LoopSpeedState::FixedBoundaryCommitted:return "FixedBoundaryCommitted";
    case LoopSpeedState::Applied:return "Applied";case LoopSpeedState::Completed:return "Completed";
    case LoopSpeedState::Replaced:return "Replaced";case LoopSpeedState::Cancelled:return "Cancelled";case LoopSpeedState::Failed:return "Failed";}return "Failed";
}
inline bool terminal(LoopSpeedState state)noexcept {return state==LoopSpeedState::Completed||state==LoopSpeedState::Replaced||state==LoopSpeedState::Cancelled||state==LoopSpeedState::Failed;}
enum class LoopSpeedDeferral {None,ProtectedFrontier,PreparationDeadline,BusyRetry,Unsupported,InternalLimit,PreparationFailed};
// External request identity. A Ready preparation and observed audio application
// are separate facts; a committed/started record is never rewritten Replaced.
struct LoopSpeedOperation {
    std::uint64_t id=0,loopID=0,inputGeneration=0,sourceSession=0,sourceRenderEpoch=0,acceptedCycle=0;
    std::uint32_t speedMicros=1000000;
    LoopSpeedState state=LoopSpeedState::Pending;
    LoopSpeedDeferral deferral=LoopSpeedDeferral::None;
    std::uint64_t preparationVersion=0,dynamicOperationID=0,session=0,renderEpoch=0,producerCycle=0,cycle=0,mapVersion=0,outputEnd=0;
    std::uint64_t dynamicSession=0,planningRenderEpoch=0; // internal operation owner, separate from a fixed fallback's adopted owner
    std::uint64_t acceptedNs=0,preparingNs=0,readyNs=0,commitObservedNs=0,firstChangedPublishedObservedNs=0,firstPcmObservedNs=0,completedNs=0,terminalNs=0;
    std::uint64_t firstChangedOutputFrame=0,completionOutputFrame=0,resumeInputFrame=0,discardedForPausedClearFrames=0;
    bool committed=false,outputStarted=false,fixedBoundary=false,adoptionPending=false,fixedBoundaryCommitted=false,noChange=false,clearContinuation=false;
    std::string reason;
};
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
    std::uint64_t pausedClearDiscardedFrames=0,pausedClearInputFrame=0; // replacement discard, never consumption/seek/cycle/underrun
    std::optional<LoopBoundaryEvent> lastBoundary;
    std::string reason;
};
struct LoopAvailability {
    bool implemented=true,optIn=false,allowed=false,publicLoopApproved=false;
    bool currentCycleSpeedChanges=false; // supported method; individual requests may defer to a protected B
    bool currentCycleSpeedImplemented=true;
    unsigned contractVersion=progressive::contractVersion;
    FeatureAvailability nativeLoops;
    std::uint32_t minimumInputMillis=100,maximumCallbackFrames=4096;
};
inline bool validLoopRange(std::uint64_t a,std::uint64_t b,std::uint64_t frames)noexcept{return a<b&&b<=frames;}
inline bool executableLoopRange(std::uint64_t a,std::uint64_t b,std::uint32_t rate)noexcept{return a<b&&b-a>=rate/10;}
}
