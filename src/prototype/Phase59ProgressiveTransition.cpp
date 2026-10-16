#include "prototype/Phase59ProgressiveTransition.h"
#include <stdexcept>
namespace ts::prototype::phase59 {
ProgressiveTransitionPlanner::ProgressiveTransitionPlanner(std::uint32_t rate,
    std::size_t frames,std::uint64_t generation,std::uint32_t initial,bool candidate)
    :generation_(generation),rate_(rate),inputFrames_(frames),initial_{initial},tail_{initial},candidate_(candidate) {
    if(!rate||!frames||!generation||!formalSpeed(initial))throw std::invalid_argument("Invalid progressive transition session");
    accepted_.reserve(maximumChanges);plans_.reserve(maximumChanges);modes_.reserve(maximumChanges);
}
TimeMap ProgressiveTransitionPlanner::fixed(const phase56::AnalysisSnapshot& s,Phase39Speed speed)const {
    phase56::MapPrefixBuilder builder({speed.micros});std::vector<TransientEvent> events;
    events.reserve(s.closedEventCount);
    for(std::size_t i=0;i<s.closedEventCount;++i){const auto& e=s.events.at(i);builder.close(e,s.anchors.at(i));events.push_back(e);}
    if(s.isFinal)builder.finish(s.featureThrough);
    if(builder.nodes[0].size()!=s.mapThroughNode)throw std::logic_error("Certified map node count differs");
    return TimeMap(1024,std::move(builder.nodes[0]),std::move(events));
}
void ProgressiveTransitionPlanner::update(std::shared_ptr<const phase56::AnalysisSnapshot> s) {
    if(rollbackTimeline_)throw std::logic_error("Acknowledge dynamic plan before analysis update");
    if(!s||s->inputGeneration!=generation_||s->hasError||s->isCancelled||s->receivedInputFrames>inputFrames_||
        s->closedEventCount!=s->closedAnchorCount||s->events.size()!=s->closedEventCount||s->anchors.size()!=s->closedAnchorCount||
        (s->isFinal&&s->receivedInputFrames!=inputFrames_))throw std::invalid_argument("Invalid planning snapshot");
    if(snapshot_&&(snapshot_->isFinal||s->mapThroughNode<snapshot_->mapThroughNode||s->closedEventCount<snapshot_->closedEventCount||s->receivedInputFrames<snapshot_->receivedInputFrames))
        throw std::invalid_argument("Planning snapshot regressed/after final");
    const bool rebuild=!snapshot_||s->mapThroughNode!=snapshot_->mapThroughNode||s->closedEventCount!=snapshot_->closedEventCount||s->isFinal;
    snapshot_=std::move(s);
    if(!rebuild||snapshot_->mapThroughNode<2)return;
    const auto* certified=snapshot_.get();
    auto timeline=std::make_unique<Phase39TimeMap>(fixed(*certified,initial_),rate_,initial_,candidate_?Phase39Planning::L2:Phase39Planning::C,
        [this](auto speed){return fixed(*snapshot_,speed);});
    for(std::size_t i=0;i<accepted_.size();++i){
        const auto p=timeline->submit(accepted_[i]);const auto& old=plans_[i];
        if(!p.applied()||p.appliedFrame!=old.appliedFrame||p.rampEndFrame!=old.rampEndFrame||p.appliedOutputSample!=old.appliedOutputSample||p.completionOutputSample!=old.completionOutputSample)
            throw std::logic_error("Committed speed history changed on analysis extension");
    }
    if(view_){const auto& before=view_->map.starts();const auto& after=timeline->current().starts();
        if(after.size()<before.size()||!std::equal(before.begin(),before.end(),after.begin()))throw std::logic_error("Published dynamic prefix changed");}
    timeline_=std::move(timeline);publish();
}
void ProgressiveTransitionPlanner::publish() {
    if(failPublishForTest_){failPublishForTest_=false;throw std::bad_alloc();}
    auto view=std::make_shared<DynamicMap>();view->map=timeline_->current();view->modes=modes_;
    view->inputGeneration=generation_;view->baseVersion=view_?view_->version:0;view->version=++version_;
    view->certifiedNodes=view->map.starts().size();view->receivedInput=snapshot_->receivedInputFrames;view->final=snapshot_->isFinal;
    view->hasTransitions=!accepted_.empty();
    view->firstChangedNode=view_?view_->map.starts().size():0;
    if(view_){const auto& a=view_->map.starts();const auto& b=view->map.starts();
        for(std::size_t i=0;i<std::min(a.size(),b.size());++i)if(a[i]!=b[i]){view->firstChangedNode=i;break;}}
    if(view->final)view->outputFrames=accepted_.empty()?std::size_t(std::llround(inputFrames_*initial_.timeRatio())):
        std::size_t(std::llround(view->map.outputPositionForInputSample(double(inputFrames_))));
    view_=std::move(view);
}
PlanningResult ProgressiveTransitionPlanner::plan(Phase39Speed target,std::uint64_t requestGeneration,
    std::size_t logicalPresented,std::size_t published,const Phase36StreamingSpeedEngine::Frontier& f) {
    PlanningResult r;
    if(rollbackTimeline_)throw std::logic_error("Acknowledge previous plan before replanning");
    if(!formalSpeed(target.micros)){r.status=PlanningStatus::Decided;r.change.plan.outcome=Phase39Outcome::Invalid;return r;}
    if(!timeline_)return r;
    if(accepted_.size()>=maximumChanges){r.status=PlanningStatus::Decided;r.limitReached=true;r.change.plan.outcome=Phase39Outcome::Invalid;return r;}
    // The requested inverse map and both immutable interpolation nodes must
    // exist. Missing future information is Pending, never an empty-event tail.
    if(!snapshot_->isFinal){
        const auto& nodes=timeline_->current().starts();
        if(logicalPresented>=std::size_t(nodes.back()))return r;
        for(auto last:f.lastProcessedInput)if((last+1023)/1024>=nodes.size())return r;
    }
    auto candidate=*timeline_;
    r.change=evaluate(candidate,f,modes_,tail_,target,requestGeneration,logicalPresented,published,inputFrames_,candidate_,snapshot_->isFinal);
    if(!r.change.plan.applied()&&!snapshot_->isFinal&&
        (r.change.plan.outcome==Phase39Outcome::NoSafeInterval||r.change.plan.outcome==Phase39Outcome::Truncated))return r;
    r.status=PlanningStatus::Decided;
    if(r.change.plan.applied()){
        rollbackTimeline_=std::make_unique<Phase39TimeMap>(*timeline_);rollbackView_=view_;rollbackTail_=tail_;rollbackModes_=modes_.size();
        *timeline_=std::move(candidate);accepted_.push_back(r.change.request);plans_.push_back(r.change.plan);
        if(r.change.changesDensity)modes_.emplace_back(r.change.densityInput,target.micros<500000);
        tail_=target;
        try{publish();}catch(...){confirmPlan(false);throw;}
    }
    return r;
}
void ProgressiveTransitionPlanner::confirmPlan(bool applied) {
    if(!rollbackTimeline_)throw std::logic_error("No pending plan transaction");
    if(!applied){timeline_=std::move(rollbackTimeline_);view_=std::move(rollbackView_);tail_=rollbackTail_;modes_.resize(rollbackModes_);accepted_.pop_back();plans_.pop_back();}
    rollbackTimeline_.reset();rollbackView_.reset();
}
std::size_t ProgressiveTransitionPlanner::mapBytes()const noexcept {
    return (timeline_?timeline_->fixedMapBytes():0)+(view_?view_->map.starts().capacity()*sizeof(long long)+view_->modes.capacity()*sizeof(std::pair<std::size_t,bool>):0);
}
}
