#pragma once
#include "prototype/Phase59PlanningContract.h"
#include "prototype/Phase56ProgressiveAnalysis.h"
#include "prototype/Phase59PersistentMap.h"

namespace ts::prototype::phase59 {
inline constexpr std::size_t maximumChanges=512;
struct DynamicMap {
    PersistentMap map;
    std::vector<std::pair<std::size_t,bool>> modes;
    std::uint64_t inputGeneration=0,version=0,baseVersion=0;
    std::size_t certifiedNodes=0,receivedInput=0,firstChangedNode=0;
    std::size_t outputFrames=0;
    bool final=false,hasTransitions=false;
};
enum class PlanningStatus {PendingAnalysis,Decided};
struct PlanningResult {
    PlanningStatus status=PlanningStatus::PendingAnalysis;
    PlannedChange change;
    bool limitReached=false;
};
struct IncrementalPlanningStatistics {
    std::uint64_t updates=0,fixedEventVisits=0,fixedAppendedNodes=0,dynamicAppendedNodes=0;
    std::uint64_t materializedNodes=0,historyReplays=0,diagnosticReplayRequests=0,diagnosticComparisons=0;
    std::uint64_t prefixProofPages=0,prefixProofNodes=0,indexBytesCopied=0;
    std::size_t fixedCacheEntries=0,pageLiveBytes=0,pagePeakBytes=0,pageCopiedBytes=0;
    // Conservative payload bound for the normal-thread Phase39 materialized
    // maps/proposal/protection/history work, not measured allocator/RSS bytes.
    std::size_t planningScratchEstimatedPeakBytes=0;
};
// One normal planning owner. Published coordinates share immutable prefix
// pages. Whole-vector Phase39 planning is explicit work for a new request;
// analysis extension never resubmits historical requests.
class ProgressiveTransitionPlanner {
    struct FixedState {
        std::uint32_t speed=0;std::size_t events=0;bool final=false;
        std::unique_ptr<phase56::MapPrefixBuilder> builder;
        phase56::ImmutableSeries<long long> nodes;
    };
    std::uint64_t generation_,version_=0;
    std::uint32_t rate_;std::size_t inputFrames_;Phase39Speed initial_,tail_;
    bool candidate_,diagnosticReplay_;
    std::shared_ptr<const phase56::AnalysisSnapshot> snapshot_;
    std::vector<FixedState> fixed_;
    std::shared_ptr<phase56::MemoryLedger> pageBudget_;
    std::vector<Phase39Request> accepted_;
    std::vector<Phase39Plan> plans_;
    std::vector<std::pair<std::size_t,bool>> modes_;
    std::shared_ptr<const DynamicMap> view_,rollbackView_;
    Phase39Speed rollbackTail_{};std::size_t rollbackModes_=0;
    bool failPublishForTest_=false;
    IncrementalPlanningStatistics statistics_;
    PersistentMap fixed(Phase39Speed);
    std::unique_ptr<Phase39TimeMap> replayTimeline();
    void verifyCurrent();
    void publish(PersistentMap,std::size_t firstChanged);
public:
    ProgressiveTransitionPlanner(std::uint32_t rate,std::size_t inputFrames,
        std::uint64_t inputGeneration,std::uint32_t initial,bool candidate,bool diagnosticReplay=false);
    void update(std::shared_ptr<const phase56::AnalysisSnapshot>);
    PlanningResult plan(Phase39Speed target,std::uint64_t requestGeneration,
        std::size_t logicalPresented,std::size_t published,
        const Phase36StreamingSpeedEngine::Frontier&);
    void confirmPlan(bool applied);
    void injectPublishFailureForTest(){failPublishForTest_=true;}
    std::shared_ptr<const DynamicMap> view()const{return view_;}
    Phase39Speed tail()const noexcept{return tail_;}
    std::size_t mapBytes()const noexcept;
    std::size_t historyCount()const noexcept{return accepted_.size();}
    IncrementalPlanningStatistics statistics()const noexcept;
};
}
