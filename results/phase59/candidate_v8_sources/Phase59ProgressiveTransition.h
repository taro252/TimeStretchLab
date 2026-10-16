#pragma once
#include "prototype/Phase59PlanningContract.h"
#include "prototype/Phase56ProgressiveAnalysis.h"

namespace ts::prototype::phase59 {
inline constexpr std::size_t maximumChanges=512;
struct DynamicMap {
    TimeMap map;
    std::vector<std::pair<std::size_t,bool>> modes;
    std::uint64_t inputGeneration=0,version=0,baseVersion=0;
    std::size_t certifiedNodes=0,receivedInput=0,firstChangedNode=0;
    std::size_t outputFrames=0;
    bool final=false;
};
enum class PlanningStatus {PendingAnalysis,Decided};
struct PlanningResult {
    PlanningStatus status=PlanningStatus::PendingAnalysis;
    PlannedChange change;
    bool limitReached=false;
};
// Single non-realtime owner. Fixed coordinates are computed directly from
// closed events/anchors with Phase56's exact builder, then passed as a prefix
// to the existing Phase39 algorithm. No provisional full analysis is made.
class ProgressiveTransitionPlanner {
    std::uint64_t generation_,version_=0;
    std::uint32_t rate_;std::size_t inputFrames_;Phase39Speed initial_,tail_;
    bool candidate_;
    std::shared_ptr<const phase56::AnalysisSnapshot> snapshot_;
    std::unique_ptr<Phase39TimeMap> timeline_;
    std::vector<Phase39Request> accepted_;
    std::vector<Phase39Plan> plans_;
    std::vector<std::pair<std::size_t,bool>> modes_;
    std::shared_ptr<const DynamicMap> view_;
    std::unique_ptr<Phase39TimeMap> rollbackTimeline_;
    std::shared_ptr<const DynamicMap> rollbackView_;
    Phase39Speed rollbackTail_{};
    std::size_t rollbackModes_=0;
    TimeMap fixed(const phase56::AnalysisSnapshot&,Phase39Speed)const;
    void publish();
public:
    ProgressiveTransitionPlanner(std::uint32_t rate,std::size_t inputFrames,
        std::uint64_t inputGeneration,std::uint32_t initial,bool candidate);
    void update(std::shared_ptr<const phase56::AnalysisSnapshot>);
    PlanningResult plan(Phase39Speed target,std::uint64_t requestGeneration,
        std::size_t logicalPresented,std::size_t published,
        const Phase36StreamingSpeedEngine::Frontier&);
    // Normal owner acknowledges the realtime reader's bounded application.
    // A stale frontier rolls back the proposal, including its speed history.
    void confirmPlan(bool applied);
    std::shared_ptr<const DynamicMap> view()const{return view_;}
    Phase39Speed tail()const noexcept{return tail_;}
    std::size_t mapBytes()const noexcept;
    std::size_t historyCount()const noexcept{return accepted_.size();}
};
}
