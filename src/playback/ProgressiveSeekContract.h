#pragma once
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include "playback/ProgressiveFeatureContract.h"
#define PHASE61_INTERACTIVE_CONTRACT 1

namespace ts::playback::progressive {
enum class SeekMode {Exact,FastLocal};
enum class SeekState {Pending,Preparing,Ready,Completed,Replaced,Cancelled,Rejected,Failed};
enum class SeekStage {None,PreparingAnalysis,PreparingFifo,SwitchReady,Transitioning,Finished};
inline const char* name(SeekStage s)noexcept{
    switch(s){case SeekStage::None:return "None";case SeekStage::PreparingAnalysis:return "PreparingAnalysis";
    case SeekStage::PreparingFifo:return "PreparingFifo";case SeekStage::SwitchReady:return "SwitchReady";
    case SeekStage::Transitioning:return "Transitioning";case SeekStage::Finished:return "Finished";}return "Unknown";
}
struct SeekAvailability {
    bool exactImplemented=true,interactiveImplemented=true;
    bool interactiveOptIn=false,interactiveAllowed=false,publicSeekApproved=false;
    unsigned contractVersion=progressive::contractVersion;
    FeatureAvailability exact,interactive;
};
inline const char* name(SeekState s)noexcept{
    switch(s){case SeekState::Pending:return "Pending";case SeekState::Preparing:return "Preparing";
    case SeekState::Ready:return "Ready";case SeekState::Completed:return "Completed";
    case SeekState::Replaced:return "Replaced";case SeekState::Cancelled:return "Cancelled";
    case SeekState::Rejected:return "Rejected";case SeekState::Failed:return "Failed";}return "Unknown";
}
inline bool terminal(SeekState s)noexcept{return s!=SeekState::Pending&&s!=SeekState::Preparing&&s!=SeekState::Ready;}
// The supplied double duration is the inclusive seconds endpoint. Validate
// before rounding, so a just-out-of-range value cannot round back into the song.
inline std::uint64_t inputFrameForSeconds(double seconds,std::uint32_t rate,std::uint64_t frames){
    if(!rate||!std::isfinite(seconds)||seconds<0)throw std::invalid_argument("シーク秒数は有限の非負値です");
    const auto duration=double(frames)/rate;
    if(seconds>duration)throw std::out_of_range("シーク位置が曲長を超えています");
    if(seconds==duration)return frames;
    return static_cast<std::uint64_t>(std::floor(static_cast<long double>(seconds)*rate+.5L));
}
struct SeekReceipt {std::uint64_t id=0;bool accepted=false;std::string reason;AvailabilityReason code=AvailabilityReason::Available;};
struct SeekOperation {
    SeekMode mode=SeekMode::Exact;
    std::uint32_t prerollMillis=0;
    std::uint64_t id=0,inputGeneration=0,sourceRenderEpoch=0,renderEpoch=0,session=0;
    std::uint64_t requestedInputFrame=0,outputStartFrame=0;
    SeekState state=SeekState::Rejected;
    std::string reason;
    AvailabilityReason code=AvailabilityReason::Available;
    std::uint32_t speedMicros=0,replans=0;
    // All these timestamps use Mach monotonic nanoseconds. Presentation is an
    // API host-time estimate, never a measurement of acoustic output.
    std::uint64_t acceptedNs=0,preparingNs=0,readyNs=0,switchedNs=0;
    std::uint64_t firstCallbackNs=0,estimatedPresentationNs=0;
    SeekStage stage=SeekStage::None;
    std::uint64_t analysisReadyNs=0,switchReadyNs=0,transitionBeginNs=0,transitionEndNs=0;
    std::uint64_t oldFifoAtSwitchFrames=0,discardedForSeekFrames=0,transitionFrames=0;
    bool waitedForAnalysis=false;
};
struct SeekSnapshot {SeekOperation latest;std::uint64_t activeId=0,pendingId=0;};
}
