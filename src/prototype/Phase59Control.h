#pragma once
#include "prototype/Phase59ProgressiveTransition.h"
#include "prototype/Phase39PlaybackPipeline.h"
#include <atomic>
#include <optional>
#include <type_traits>
#include <unistd.h>

namespace ts::prototype::phase59 {
// Same operation meanings as PlaybackEngine's SpeedStatus. The lower-level
// worker state/result remain the existing Phase39 enums without renaming.
enum class OperationState {Pending,Submitted,Applied,Completed,Replaced,Duplicate,Rejected,Cancelled};
inline const char* name(OperationState s)noexcept {
    switch(s){case OperationState::Pending:return "Pending";case OperationState::Submitted:return "Submitted";
        case OperationState::Applied:return "Applied";case OperationState::Completed:return "Completed";
        case OperationState::Replaced:return "Replaced";case OperationState::Duplicate:return "Duplicate";
        case OperationState::Rejected:return "Rejected";case OperationState::Cancelled:return "Cancelled";}return "Unknown";
}
struct SpeedOperation {
    std::uint64_t id=0,session=0,inputGeneration=0,generation=0;
    std::uint32_t target=0;
    OperationState state=OperationState::Pending;
    Phase39RequestState workerState=Phase39RequestState::Idle;
    Phase39RequestResult acceptance=Phase39RequestResult::Accepted;
    std::size_t logicalPresented=0,acceptedLogicalPresented=0,publishedAtPlan=0,consumedAtApply=0;
    std::size_t analysisNodesAtPlan=0,receivedInputAtPlan=0;
    bool planningDecided=false,finalAnalysisAtPlan=false;
    Phase36StreamingSpeedEngine::Frontier frontier;
    PlannedChange change;
    double acceptedS=-1,plannerSeenS=-1,workerSeenS=-1,planStartedS=-1,planFinishedS=-1,appliedS=-1,completedS=-1;
    double planCpuS=0,planWallS=0;
    std::size_t attempts=0,staleReplans=0,analysisDeferrals=0;
};
struct RequestReceipt {std::uint64_t id=0;Phase39RequestResult result=Phase39RequestResult::Invalid;};
struct PlanningFrontier {
    Phase36StreamingSpeedEngine::Frontier dsp;
    std::uint64_t mapVersion=0;
    std::size_t published=0,consumed=0;
    double atS=0;
    std::uint64_t cycle=0;
};
// One realtime publisher, one normal reader. Three fixed slots, full sequence
// tag, hazard before validation. Copies only POD data; no mutex/ownership/new.
template<class T> class ValueMailbox {
    static_assert(std::is_trivially_copyable_v<T>);
    alignas(64) std::array<T,3> values_{};
    alignas(64) std::atomic<std::uint64_t> published_{3};
    alignas(64) std::atomic<unsigned> hazard_{3};
    std::uint64_t version_=0;
public:
    ValueMailbox(){
        auto* memory=reinterpret_cast<volatile unsigned char*>(values_.data());
        const auto bytes=sizeof(values_),page=std::size_t(std::max<long>(1,sysconf(_SC_PAGESIZE)));
        for(std::size_t at=0;at<bytes;at+=page)memory[at]=memory[at];
        memory[bytes-1]=memory[bytes-1];
    }
    void publish(const T& value)noexcept {
        const auto published=unsigned(published_.load()&3),hazard=hazard_.load();
        for(unsigned slot=0;slot<3;++slot)if(slot!=published&&slot!=hazard){values_[slot]=value;published_.store((++version_<<2)|slot);return;}
    }
    std::optional<T> read()noexcept {
        for(unsigned attempt=0;attempt<4;++attempt){const auto tag=published_.load();if(tag==3)return {};
            hazard_.store(unsigned(tag&3));if(published_.load()!=tag){hazard_.store(3);continue;}
            auto value=values_[tag&3];hazard_.store(3);return value;}
        return {};
    }
};
}
