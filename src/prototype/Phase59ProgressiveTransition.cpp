#include "prototype/Phase59ProgressiveTransition.h"
#include <stdexcept>
#include <tuple>
#include <bit>
namespace ts::prototype::phase59 {
namespace {
TimeMap replayFixed(const phase56::AnalysisSnapshot& s,Phase39Speed speed){
    phase56::MapPrefixBuilder builder({speed.micros});std::vector<TransientEvent> events;
    events.reserve(s.closedEventCount);
    for(std::size_t i=0;i<s.closedEventCount;++i){const auto& e=s.events.at(i);builder.close(e,s.anchors.at(i));events.push_back(e);}
    if(s.isFinal)builder.finish(s.featureThrough);
    if(builder.nodes[0].size()!=s.mapThroughNode)throw std::logic_error("Certified map node count differs");
    return TimeMap(1024,std::move(builder.nodes[0]),std::move(events));
}
auto planFacts(const Phase39Plan& p){return std::tie(p.outcome,p.requestedFrame,p.appliedFrame,p.rampEndFrame,
    p.appliedOutputSample,p.completionOutputSample,p.protectedEventsSkipped,p.protectedEventsPaused,
    p.firstMutableFrame,p.firstSafeFrame,p.nextEventFrame,p.protectionEndFrame,p.safeFramesUsed,p.heldFrames);}
bool sameDecision(const PlannedChange& a,const PlannedChange& b){
    return planFacts(a.plan)==planFacts(b.plan)&&a.request.generation==b.request.generation&&a.request.target==b.request.target&&
        a.request.requestedInputSample==b.request.requestedInputSample&&a.request.publishedOutputSample==b.request.publishedOutputSample&&
        a.request.transitionOutputMs==b.request.transitionOutputMs&&a.boundary.legacy==b.boundary.legacy&&a.boundary.precise==b.boundary.precise&&
        a.boundary.processedNode==b.boundary.processedNode&&a.boundary.consumedOla==b.boundary.consumedOla&&a.boundary.consumedFir==b.boundary.consumedFir&&
        a.outputFrames==b.outputFrames&&a.densityInput==b.densityInput&&a.statePreserved==b.statePreserved&&a.changesDensity==b.changesDensity&&
        a.density.safe==b.density.safe&&a.density.inputSample==b.density.inputSample&&a.density.maximumHop==b.density.maximumHop&&
        a.density.maximumHopStep==b.density.maximumHopStep&&a.density.minimumWeight==b.density.minimumWeight&&
        a.density.minimumLocalSpeed==b.density.minimumLocalSpeed&&a.density.maximumLocalSpeed==b.density.maximumLocalSpeed&&
        a.density.reconstructedHistoryMismatches==b.density.reconstructedHistoryMismatches&&
        a.density.reconstructedHistoryMaxDifference==b.density.reconstructedHistoryMaxDifference&&a.density.actualWeight==b.density.actualWeight&&
        a.density.predictedActualWeight==b.density.predictedActualWeight&&a.density.weightPredictionAbsoluteError==b.density.weightPredictionAbsoluteError&&
        a.density.candidatesTried==b.density.candidatesTried;
}
template<class T,class Equal> void provePrefix(const phase56::ImmutableSeries<T>& before,
    const phase56::ImmutableSeries<T>& after,Equal equal,IncrementalPlanningStatistics& stats){
    if(after.size()<before.size())throw std::invalid_argument("Certified series regressed");
    constexpr auto width=phase56::ImmutableSeries<T>::pageWidth;
    for(std::size_t at=0;at<before.size();at+=width){
        const auto* a=before.borrowedPageData(at/width);const auto* b=after.borrowedPageData(at/width);++stats.prefixProofPages;
        if(a==b)continue;
        for(std::size_t j=0;j<std::min(width,before.size()-at);++j){++stats.prefixProofNodes;
            if(!equal(a[j],b[j]))throw std::invalid_argument("Certified prefix changed");}
    }
}
}
ProgressiveTransitionPlanner::ProgressiveTransitionPlanner(std::uint32_t rate,
    std::size_t frames,std::uint64_t generation,std::uint32_t initial,bool candidate,bool diagnosticReplay)
    :generation_(generation),rate_(rate),inputFrames_(frames),initial_{initial},tail_{initial},candidate_(candidate),diagnosticReplay_(diagnosticReplay),
     pageBudget_(std::make_shared<phase56::MemoryLedger>(4*1024*1024)){
    if(!rate||!frames||!generation||!formalSpeed(initial))throw std::invalid_argument("Invalid progressive transition session");
    pageBudget_->owner=pageBudget_;fixed_.reserve(5);accepted_.reserve(maximumChanges);plans_.reserve(maximumChanges);modes_.reserve(maximumChanges);
}
PersistentMap ProgressiveTransitionPlanner::fixed(Phase39Speed speed){
    auto found=std::find_if(fixed_.begin(),fixed_.end(),[&](const auto& f){return f.speed==speed.micros;});
    if(found==fixed_.end()){
        if(fixed_.size()==5)fixed_.erase(fixed_.begin());
        FixedState f;f.speed=speed.micros;
        bool provided=false;for(std::size_t i=0;i<snapshot_->speedCount;++i)provided|=snapshot_->speedMicros[i]==speed.micros;
        if(!provided)f.builder=std::make_unique<phase56::MapPrefixBuilder>(std::vector<std::uint32_t>{speed.micros});
        fixed_.push_back(std::move(f));found=std::prev(fixed_.end());
    }
    auto& f=*found;
    if(!f.builder)f.nodes=snapshot_->mapForSpeed(speed.micros);
    else{
        for(;f.events<snapshot_->closedEventCount;++f.events){f.builder->close(snapshot_->events.borrowedAt(f.events),snapshot_->anchors.borrowedAt(f.events));++statistics_.fixedEventVisits;}
        if(snapshot_->isFinal&&!f.final)f.builder->finish(snapshot_->featureThrough);
        if(f.builder->nodes[0].size()!=snapshot_->mapThroughNode)throw std::logic_error("Incremental fixed map node count differs");
        statistics_.fixedAppendedNodes+=snapshot_->mapThroughNode-f.nodes.size();
        f.nodes=f.nodes.extend(f.builder->nodes[0],snapshot_->mapThroughNode,pageBudget_);
    }
    f.final=snapshot_->isFinal;
    if(f.nodes.size()!=snapshot_->mapThroughNode)throw std::logic_error("Provided fixed map node count differs");
    return PersistentMap(f.nodes,snapshot_->events);
}
void ProgressiveTransitionPlanner::update(std::shared_ptr<const phase56::AnalysisSnapshot> s){
    if(rollbackView_)throw std::logic_error("Acknowledge dynamic plan before analysis update");
    if(!s||s->inputGeneration!=generation_||s->hasError||s->isCancelled||s->receivedInputFrames>inputFrames_||s->speedCount>s->speedMicros.size()||
        s->closedEventCount!=s->closedAnchorCount||s->events.size()!=s->closedEventCount||s->anchors.size()!=s->closedAnchorCount||
        (s->isFinal&&s->receivedInputFrames!=inputFrames_))throw std::invalid_argument("Invalid planning snapshot");
    if(snapshot_){
        if(snapshot_->isFinal||s->mapThroughNode<snapshot_->mapThroughNode||s->closedEventCount<snapshot_->closedEventCount||s->receivedInputFrames<snapshot_->receivedInputFrames)
            throw std::invalid_argument("Planning snapshot regressed/after final");
        provePrefix(snapshot_->events,s->events,[](const auto& a,const auto& b){return std::tie(a.onsetFrame,a.peakFrame,a.attackEndFrame,a.endFrame)==std::tie(b.onsetFrame,b.peakFrame,b.attackEndFrame,b.endFrame)&&std::bit_cast<std::uint32_t>(a.strength)==std::bit_cast<std::uint32_t>(b.strength);},statistics_);
        provePrefix(snapshot_->anchors,s->anchors,[](const auto& a,const auto& b){return a.frame==b.frame&&a.confident==b.confident&&std::bit_cast<std::uint64_t>(a.sampleOffset)==std::bit_cast<std::uint64_t>(b.sampleOffset)&&std::bit_cast<std::uint64_t>(a.absoluteInputSample)==std::bit_cast<std::uint64_t>(b.absoluteInputSample)&&std::bit_cast<std::uint64_t>(a.crestFactor)==std::bit_cast<std::uint64_t>(b.crestFactor);},statistics_);
        for(std::size_t i=0;i<snapshot_->speedCount;++i)for(std::size_t j=0;j<s->speedCount;++j)if(snapshot_->speedMicros[i]==s->speedMicros[j]&&
            std::any_of(fixed_.begin(),fixed_.end(),[&](const auto& f){return f.speed==snapshot_->speedMicros[i];}))
            provePrefix(snapshot_->maps[i],s->maps[j],std::equal_to<long long>{},statistics_);
    }
    const bool rebuild=!snapshot_||s->mapThroughNode!=snapshot_->mapThroughNode||s->closedEventCount!=snapshot_->closedEventCount||s->isFinal;
    snapshot_=std::move(s);++statistics_.updates;
    if(!rebuild||snapshot_->mapThroughNode<2)return;
    auto tail=fixed(tail_);const auto oldCount=view_?view_->certifiedNodes:0;
    if(!view_)publish(std::move(tail),0);
    else{
        const auto r=plans_.empty()?0:plans_.back().rampEndFrame;
        if(r>=oldCount)throw std::logic_error("Uncertified committed ramp end");
        const auto offset=view_->map.nodeAt(r)-tail.nodeAt(r);
        auto nodes=view_->map.nodeSeries().extendFrom(snapshot_->mapThroughNode,[&](auto i){return tail.nodeAt(i)+offset;},pageBudget_);
        statistics_.dynamicAppendedNodes+=snapshot_->mapThroughNode-oldCount;
        publish(PersistentMap(std::move(nodes),snapshot_->events),oldCount);
    }
    if(diagnosticReplay_)verifyCurrent();
}
void ProgressiveTransitionPlanner::publish(PersistentMap map,std::size_t firstChanged){
    if(failPublishForTest_){failPublishForTest_=false;throw std::bad_alloc();}
    auto view=std::make_shared<DynamicMap>();view->map=std::move(map);view->modes=modes_;
    view->inputGeneration=generation_;view->baseVersion=view_?view_->version:0;view->version=++version_;
    view->certifiedNodes=view->map.starts().size();view->receivedInput=snapshot_->receivedInputFrames;view->final=snapshot_->isFinal;
    view->hasTransitions=!accepted_.empty();view->firstChangedNode=firstChanged;
    if(view->final)view->outputFrames=accepted_.empty()?std::size_t(std::llround(inputFrames_*initial_.timeRatio())):
        std::size_t(std::llround(view->map.outputPositionForInputSample(double(inputFrames_))));
    statistics_.indexBytesCopied+=view->map.indexBytes();view_=std::move(view);
}
std::unique_ptr<Phase39TimeMap> ProgressiveTransitionPlanner::replayTimeline(){
    auto s=snapshot_;auto timeline=std::make_unique<Phase39TimeMap>(replayFixed(*s,initial_),rate_,initial_,candidate_?Phase39Planning::L2:Phase39Planning::C,
        [s](auto speed){return replayFixed(*s,speed);});
    for(std::size_t i=0;i<accepted_.size();++i){++statistics_.diagnosticReplayRequests;
        const auto p=timeline->submit(accepted_[i]);const auto& old=plans_[i];
        if(!p.applied()||p.appliedFrame!=old.appliedFrame||p.rampEndFrame!=old.rampEndFrame||p.appliedOutputSample!=old.appliedOutputSample||p.completionOutputSample!=old.completionOutputSample)
            throw std::logic_error("Committed speed history changed on analysis extension");
    }
    return timeline;
}
void ProgressiveTransitionPlanner::verifyCurrent(){
    auto old=replayTimeline();const auto& expected=old->current().starts();const auto actual=view_->map.starts();
    if(expected.size()!=actual.size())throw std::logic_error("Incremental/replay map extent differs");
    for(std::size_t i=0;i<expected.size();++i){++statistics_.diagnosticComparisons;if(expected[i]!=actual[i])throw std::logic_error("Incremental/replay map node differs");}
}
PlanningResult ProgressiveTransitionPlanner::plan(Phase39Speed target,std::uint64_t requestGeneration,
    std::size_t logicalPresented,std::size_t published,const Phase36StreamingSpeedEngine::Frontier& f){
    PlanningResult r;
    if(rollbackView_)throw std::logic_error("Acknowledge previous plan before replanning");
    if(!formalSpeed(target.micros)){r.status=PlanningStatus::Decided;r.change.plan.outcome=Phase39Outcome::Invalid;return r;}
    if(!view_)return r;
    if(accepted_.size()>=maximumChanges){r.status=PlanningStatus::Decided;r.limitReached=true;r.change.plan.outcome=Phase39Outcome::Invalid;return r;}
    if(!snapshot_->isFinal){const auto nodes=view_->map.starts();if(logicalPresented>=std::size_t(nodes.back()))return r;
        for(auto last:f.lastProcessedInput)if((last+1023)/1024>=nodes.size())return r;}
    // At most the current/target fixed maps and the evaluate proposal coexist.
    // Include their node/event copies, protection indexes and bounded history;
    // this is separate from immutable-page accounting, with no budget increase.
    const auto scratch=view_->certifiedNodes*(8*sizeof(long long)+4*sizeof(std::size_t))+
        snapshot_->closedEventCount*8*sizeof(TransientEvent)+
        (maximumChanges+1)*(4*sizeof(Phase39Plan)+2*sizeof(Phase39Request));
    statistics_.planningScratchEstimatedPeakBytes=std::max(statistics_.planningScratchEstimatedPeakBytes,scratch);
    statistics_.materializedNodes+=view_->certifiedNodes;
    Phase39TimeMap timeline(view_->map.materialize(),rate_,tail_,candidate_?Phase39Planning::L2:Phase39Planning::C,
        [this](auto speed){auto value=fixed(speed);statistics_.materializedNodes+=value.starts().size();return value.materialize();});
    if(!accepted_.empty())timeline.restoreCertifiedHistory(accepted_.back().generation,accepted_.back().publishedOutputSample,plans_.back().completionOutputSample,plans_);
    r.change=evaluate(timeline,f,modes_,tail_,target,requestGeneration,logicalPresented,published,inputFrames_,candidate_,snapshot_->isFinal);
    if(diagnosticReplay_){auto old=replayTimeline();const auto expected=evaluate(*old,f,modes_,tail_,target,requestGeneration,logicalPresented,published,inputFrames_,candidate_,snapshot_->isFinal);
        if(!sameDecision(r.change,expected))throw std::logic_error("Incremental/replay planning decision differs");}
    if(!r.change.plan.applied()&&!snapshot_->isFinal&&
        (r.change.plan.outcome==Phase39Outcome::NoSafeInterval||r.change.plan.outcome==Phase39Outcome::Truncated))return r;
    r.status=PlanningStatus::Decided;
    if(r.change.plan.applied()){
        rollbackView_=view_;rollbackTail_=tail_;rollbackModes_=modes_.size();
        accepted_.push_back(r.change.request);plans_.push_back(r.change.plan);
        if(r.change.changesDensity)modes_.emplace_back(r.change.densityInput,target.micros<500000);tail_=target;
        try{
            const auto& changed=timeline.current().starts();std::size_t first=r.change.plan.appliedFrame;
            while(first<view_->certifiedNodes&&changed[first]==view_->map.nodeAt(first))++first;
            auto nodes=view_->map.nodeSeries().prefix(first).extendFrom(changed.size(),[&](auto i){return changed[i];},pageBudget_);
            publish(PersistentMap(std::move(nodes),snapshot_->events),first);
            if(diagnosticReplay_)verifyCurrent();
        }catch(...){confirmPlan(false);throw;}
    }
    return r;
}
void ProgressiveTransitionPlanner::confirmPlan(bool applied){
    if(!rollbackView_)throw std::logic_error("No pending plan transaction");
    if(!applied){view_=std::move(rollbackView_);tail_=rollbackTail_;modes_.resize(rollbackModes_);accepted_.pop_back();plans_.pop_back();}
    rollbackView_.reset();
}
std::size_t ProgressiveTransitionPlanner::mapBytes()const noexcept{
    std::size_t bytes=pageBudget_->live.load()+(view_?view_->map.indexBytes()+view_->modes.capacity()*sizeof(std::pair<std::size_t,bool>):0)+
        (rollbackView_?rollbackView_->map.indexBytes()+rollbackView_->modes.capacity()*sizeof(std::pair<std::size_t,bool>):0);
    for(const auto& f:fixed_)if(f.builder)bytes+=f.builder->memoryBytes();return bytes+statistics_.planningScratchEstimatedPeakBytes;
}
IncrementalPlanningStatistics ProgressiveTransitionPlanner::statistics()const noexcept{
    auto s=statistics_;s.fixedCacheEntries=fixed_.size();s.pageLiveBytes=pageBudget_->live;s.pagePeakBytes=pageBudget_->peak;s.pageCopiedBytes=pageBudget_->copied;return s;
}
}
