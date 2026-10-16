#pragma once
#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase42DensityGuard.h"
#include "prototype/Phase50Boundary.h"
#include <optional>

namespace ts::prototype::phase59 {
inline bool formalSpeed(std::uint32_t s) noexcept {
    return s>=400000 && s<=2000000 && s%10000==0;
}
inline std::size_t inverseInput(const TimeMap& map,std::size_t output) {
    const auto& starts=map.starts();
    auto it=std::upper_bound(starts.begin(),starts.end(),static_cast<long long>(output));
    if(it==starts.begin())return 0;
    const auto index=std::min<std::size_t>(it-starts.begin()-1,starts.size()-2);
    const auto span=starts[index+1]-starts[index];
    const auto fraction=span>0?std::clamp((double(output)-starts[index])/double(span),0.0,1.0):0.0;
    return static_cast<std::size_t>(std::llround((index+fraction)*map.sourceHop()));
}
// Normal planning thread only. The arithmetic and rejection order are the
// Phase39PlaybackPipeline worker contract, including Candidate's precise L1.
struct PlannedChange {
    Phase39Plan plan;
    Phase39Request request;
    Phase42DensityDecision density;
    Phase50Boundary boundary;
    std::size_t outputFrames=0,densityInput=0;
    bool statePreserved=false,changesDensity=false;
};
inline PlannedChange evaluate(Phase39TimeMap& timeline,
    const Phase36StreamingSpeedEngine::Frontier& frontier,
    const std::vector<std::pair<std::size_t,bool>>& modes,
    Phase39Speed from,Phase39Speed target,std::uint64_t generation,
    std::size_t asked,std::size_t published,std::size_t inputFrames,bool candidate,bool complete=true) {
    PlannedChange r;
    r.boundary=phase50Boundary(frontier,timeline.current(),published);
    const auto fence=candidate?r.boundary.precise:r.boundary.legacy;
    r.request={generation,target,inverseInput(timeline.current(),asked),static_cast<long long>(fence),50.0};
    auto proposal=timeline;
    r.plan=proposal.submit(r.request);
    if(!r.plan.applied())return r;
    auto reject=[&](Phase39Outcome why){r.plan.outcome=why;return r;};
    if(!proposal.monotonic()||proposal.touchesProtected(r.plan))return reject(Phase39Outcome::NoSafeInterval);
    r.statePreserved=phase50PreservesState(frontier,timeline.current(),proposal.current());
    if(candidate&&!r.statePreserved)return reject(Phase39Outcome::NoSafeInterval);
    if(complete){
        r.outputFrames=static_cast<std::size_t>(std::llround(proposal.current().outputPositionForInputSample(double(inputFrames))));
        if(r.outputFrames<=std::max({frontier.preparedOutput,frontier.firstUnprocessedFirSource[0],frontier.firstUnprocessedFirSource[1]})+2048)
            return reject(Phase39Outcome::Truncated);
    }else if(std::size_t(proposal.current().starts().back())<=std::max({frontier.preparedOutput,
        frontier.firstUnprocessedFirSource[0],frontier.firstUnprocessedFirSource[1]})+2048){
        return reject(Phase39Outcome::Truncated);
    }
    r.changesDensity=(from.value()<.50)!=(target.value()<.50);
    if(r.changesDensity){
        if(!modes.empty()&&std::any_of(frontier.nextInput.begin(),frontier.nextInput.end(),[&](auto p){return p<=modes.back().first;}))
            return reject(Phase39Outcome::NoSafeInterval);
        const auto certifiedEnd=(proposal.current().starts().size()-1)*1024;
        const auto guardLimit=complete?inputFrames:std::min(inputFrames,certifiedEnd>32768?certifiedEnd-32768:0);
        r.density=chooseSafeDensitySwitch(proposal.current(),r.plan,frontier,modes,
            from.value()<.50,target.value()<.50,fence,guardLimit,false);
        if(!r.density.safe)return reject(Phase39Outcome::NoSafeInterval);
        r.densityInput=r.density.inputSample;
        if(r.densityInput<=*std::max_element(frontier.lastProcessedInput.begin(),frontier.lastProcessedInput.end()))
            return reject(Phase39Outcome::NoSafeInterval);
    }
    timeline=std::move(proposal);
    return r;
}
}
