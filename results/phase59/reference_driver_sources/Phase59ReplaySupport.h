#pragma once
#include "prototype/Phase59PlanningContract.h"
#include "prototype/Phase45PcmDigest.h"
#include "prototype/Phase39PlaybackPipeline.h"
#include "audio/WavStream.h"
#include <bit>
#include <fstream>
#include <sstream>
#include <iomanip>

namespace ts::prototype::phase59 {
struct LogicalOperation {
    std::size_t id=0,at=0,dispatched=0;
    std::uint32_t target=0;
    std::string status="Scheduled";
    std::uint64_t generation=0;
    PlannedChange change;
};
inline std::vector<LogicalOperation> readOperations(const std::filesystem::path& path) {
    std::ifstream file(path);if(!file)throw std::runtime_error("Cannot open logical requests");
    std::string line;std::getline(file,line);std::vector<LogicalOperation> result;
    while(std::getline(file,line)){
        if(line.empty())continue;
        const auto comma=line.find(',');if(comma==std::string::npos)throw std::invalid_argument("Invalid request row");
        LogicalOperation r;r.id=result.size()+1;r.at=std::stoull(line.substr(0,comma));r.target=std::stoul(line.substr(comma+1));
        if(!result.empty()&&r.at<result.back().at)throw std::invalid_argument("Logical request order regressed");
        if(result.size()>=4096)throw std::length_error("Bounded request history exceeded");result.push_back(r);
    }
    return result;
}
inline StretchConfig experimental(const WavStreamReader& reader,std::uint32_t initial) {
    if(!formalSpeed(initial))throw std::invalid_argument("Formal speed required");
    StretchConfig c;c.sampleRate=reader.sampleRate();c.channels=reader.channels();c.timeRatio=1.0/(double(initial)/1000000.0);
    c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;c.enablePhaseLocking=true;
    c.enableTransientHandling=true;c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;return c;
}
inline std::string mapSha(const TimeMap& map){Phase45PcmDigest digest;digest.update(map.starts().data(),map.starts().size()*sizeof(long long));return digest.finish();}
inline void writeOperations(const std::filesystem::path& path,const std::vector<LogicalOperation>& operations) {
    std::ofstream out(path);if(!out)throw std::runtime_error("Cannot write logical results");
    out<<"id,at_output,target_micros,status,generation,dispatched_output,outcome,requested_input,fence,requested_frame,applied_frame,ramp_end_frame,applied_output,completion_output,first_mutable,first_safe,next_event,protection_end,safe_frames,held_frames,skipped,paused,density_input,state_preserved,output_frames";
    for(int r=0;r<3;++r)out<<",density_hop_"<<r<<",density_step_"<<r<<",density_weight_bits_"<<r;
    out<<'\n';
    for(const auto& op:operations){const auto& c=op.change;const auto& p=c.plan;
        out<<op.id<<','<<op.at<<','<<op.target<<','<<op.status<<','<<op.generation<<','<<op.dispatched<<','<<int(p.outcome)<<','<<c.request.requestedInputSample<<','<<c.request.publishedOutputSample<<','<<p.requestedFrame<<','<<p.appliedFrame<<','<<p.rampEndFrame<<','<<p.appliedOutputSample<<','<<p.completionOutputSample<<','<<p.firstMutableFrame<<','<<p.firstSafeFrame<<','<<p.nextEventFrame<<','<<p.protectionEndFrame<<','<<p.safeFramesUsed<<','<<p.heldFrames<<','<<p.protectedEventsSkipped<<','<<p.protectedEventsPaused<<','<<c.densityInput<<','<<c.statePreserved<<','<<c.outputFrames;
        for(int r=0;r<3;++r)out<<','<<c.density.maximumHop[r]<<','<<c.density.maximumHopStep[r]<<','<<std::bit_cast<std::uint64_t>(c.density.minimumWeight[r]);out<<'\n';
    }
}
// Deterministic control adapter: generated/presented/published are advanced by
// exactly one 2048-frame block. Actual native replay records them separately.
struct LogicalControl {
    static constexpr auto none=std::size_t(-1);
    std::vector<LogicalOperation> operations;
    std::size_t next=0,pending=none,active=none;
    std::uint64_t generation=0;Phase39Speed tail;
    explicit LogicalControl(std::vector<LogicalOperation> r,Phase39Speed s):operations(std::move(r)),tail(s){}
    template<class Planner> void poll(std::size_t presented,const Phase36StreamingSpeedEngine::Frontier& f,
        const std::vector<std::pair<std::size_t,bool>>& modes,Planner&& plan) {
        if(active!=none){auto& op=operations[active];
            if(presented>=std::size_t(op.change.plan.completionOutputSample)&&
                (modes.empty()||std::all_of(f.nextInput.begin(),f.nextInput.end(),[&](auto p){return p>modes.back().first;}))){op.status="Completed";active=none;}
        }
        while(next<operations.size()&&operations[next].at<=presented){
            auto& op=operations[next];
            if(!formalSpeed(op.target)){op.status="RejectedInvalid";++next;continue;}
            if(pending!=none)operations[pending].status="Replaced";
            op.status="Pending";pending=next++;
        }
        const bool densityReady=modes.empty()||std::all_of(f.nextInput.begin(),f.nextInput.end(),[&](auto p){return p>modes.back().first;});
        if(active!=none||pending==none||!densityReady)return;
        auto& op=operations[pending];
        if(op.target==tail.micros){op.status="Duplicate";pending=none;return;}
        op.dispatched=presented;op.generation=++generation;op.status="Submitted";
        op.change=plan(op,f,tail);pending=none;
        if(op.change.plan.applied()){op.status="Applied";tail={op.target};active=op.id-1;}
        else op.status="Rejected";
    }
    void finish(){for(auto& op:operations)if(op.status=="Scheduled"||op.status=="Pending"||op.status=="Submitted"||op.status=="Applied")op.status="Cancelled";}
};
}
