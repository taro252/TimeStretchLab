#pragma once
#include "prototype/Phase58RealtimePipeline.h"
#include <fstream>
#include <iomanip>
#include <bit>
namespace ts::prototype::phase59 {
inline void exportOperations(const std::filesystem::path& directory,const std::vector<SpeedOperation>& records,std::uint32_t initial) {
    std::ofstream out(directory/"speeds.csv"),plans(directory/"plans.csv"),frontiers(directory/"plan_frontiers.csv");
    out<<std::setprecision(17)<<"id,session,input_generation,generation,target_micros,state,worker_state,acceptance,logical_presented,requested_input,published_at_plan,consumed_at_apply,accepted_s,worker_seen_s,plan_started_s,plan_finished_s,applied_s,completed_s,plan_cpu_s,plan_wall_s,attempts,stale_replans,analysis_deferrals,outcome,applied_output,completion_output,density_input,planner_seen_s,planning_decided,analysis_nodes_at_plan,received_input_at_plan,final_analysis_at_plan\n";
    // Column order is the frozen Phase51 reference's existing plan replay ABI.
    plans<<std::setprecision(17)<<"generation,requested_output,requested_input,from_speed,target_speed,fence,applied_output,completion_output,applied_frame,ramp_end_frame,outcome,density_frame,precise_fence,state_preserved\n";
    frontiers<<std::setprecision(17)<<"id,prepared,published";
    for(int r=0;r<3;++r)frontiers<<",next_"<<r<<",last_"<<r<<",ola_"<<r;
    frontiers<<",fir_0,fir_1,precise_fence,legacy_fence";
    for(int r=0;r<3;++r){frontiers<<",history_count_"<<r<<",weight_sample_"<<r<<",weight_bits_"<<r;for(int i=0;i<24;++i)frontiers<<",history_input_"<<r<<'_'<<i<<",history_output_"<<r<<'_'<<i;}
    frontiers<<'\n';
    auto from=initial;
    for(const auto& op:records){const auto& c=op.change;const auto& p=c.plan;
        out<<op.id<<','<<op.session<<','<<op.inputGeneration<<','<<op.generation<<','<<op.target<<','<<name(op.state)<<','<<int(op.workerState)<<','<<int(op.acceptance)<<','<<op.logicalPresented<<','<<c.request.requestedInputSample<<','<<op.publishedAtPlan<<','<<op.consumedAtApply<<','<<op.acceptedS<<','<<op.workerSeenS<<','<<op.planStartedS<<','<<op.planFinishedS<<','<<op.appliedS<<','<<op.completedS<<','<<op.planCpuS<<','<<op.planWallS<<','<<op.attempts<<','<<op.staleReplans<<','<<op.analysisDeferrals<<','<<(op.planningDecided?int(p.outcome):-1)<<','<<p.appliedOutputSample<<','<<p.completionOutputSample<<','<<c.densityInput<<','<<op.plannerSeenS<<','<<op.planningDecided<<','<<op.analysisNodesAtPlan<<','<<op.receivedInputAtPlan<<','<<op.finalAnalysisAtPlan<<'\n';
        if(op.appliedS<0)continue;
        plans<<op.generation<<','<<op.logicalPresented<<','<<c.request.requestedInputSample<<','<<double(from)/1000000.0<<','<<double(op.target)/1000000.0<<','<<c.request.publishedOutputSample<<','<<p.appliedOutputSample<<','<<p.completionOutputSample<<','<<p.appliedFrame<<','<<p.rampEndFrame<<','<<int(p.outcome)<<','<<c.densityInput/1024<<','<<c.boundary.precise<<','<<c.statePreserved<<'\n';from=op.target;
        const auto& f=op.frontier;frontiers<<op.id<<','<<f.preparedOutput<<','<<op.publishedAtPlan;
        for(int r=0;r<3;++r)frontiers<<','<<f.nextInput[r]<<','<<f.lastProcessedInput[r]<<','<<f.finalizedOla[r];
        frontiers<<','<<f.firstUnprocessedFirSource[0]<<','<<f.firstUnprocessedFirSource[1]<<','<<c.boundary.precise<<','<<c.boundary.legacy;
        for(int r=0;r<3;++r){frontiers<<','<<f.recentFrameCount[r]<<','<<f.actualWeightSample[r]<<','<<std::bit_cast<std::uint32_t>(f.actualWeight[r]);for(int i=0;i<24;++i)frontiers<<','<<f.recentFrameInput[r][i]<<','<<f.recentFrameOutput[r][i];}
        frontiers<<'\n';
    }
}
}
