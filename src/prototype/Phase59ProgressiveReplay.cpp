#include "prototype/Phase59ReplaySupport.h"
#include "prototype/Phase59Diagnostics.h"
#include "prototype/Phase56PinnedWav.h"
#include <iostream>
using namespace ts;using namespace ts::prototype;using namespace ts::prototype::phase59;
int main(int argc,char** argv){try{
    if(argc!=8)throw std::invalid_argument("input.wav initial_micros preset requests.csv actual.f32 output_directory chunk");
    const std::filesystem::path directory=argv[6];if(std::filesystem::exists(directory))throw std::runtime_error("Fresh replay directory required");std::filesystem::create_directories(directory);
    WavStreamReader reader(argv[1]);const auto initial=std::uint32_t(std::stoul(argv[2]));const bool candidate=std::string(argv[3])=="candidate";
    if(!candidate&&std::string(argv[3])!="baseline")throw std::invalid_argument("Preset");
    const std::string chunkOption=argv[7];const auto chunk=chunkOption=="irregular"?5003:std::stoull(chunkOption);if(!chunk||chunk>131072)throw std::invalid_argument("Chunk limit");
    constexpr std::array<std::size_t,9> irregular{1,3071,17,8193,1023,131071,7,5003,65535};std::size_t chunkIndex=0,received=0,published=0,nonfinalPcm=0,nonfinalPlans=0;
    phase56::ProgressiveAnalysisSession analysis(reader.sampleRate(),reader.channels(),1,{},std::vector<std::uint32_t>{initial});phase56::PinnedWavSource source(argv[1],1);
    ProgressiveTransitionPlanner planner(reader.sampleRate(),reader.frames(),1,initial,candidate);std::shared_ptr<const DynamicMap> view;
    phase57::ProgressiveSynthesisEngine engine(argv[1],initial,1);engine.enableDynamicTransitions();bool final=false;
    const auto schedule=readOperations(argv[4]);std::vector<SpeedOperation> records(schedule.size());
    for(std::size_t i=0;i<records.size();++i){records[i].id=i+1;records[i].session=records[i].inputGeneration=1;records[i].target=schedule[i].target;records[i].logicalPresented=schedule[i].at;}
    constexpr auto none=std::size_t(-1);std::size_t arrived=0,pending=none,active=none,waitingNodes=none;bool waitingFinal=false;std::uint64_t generation=0;Phase39Speed tail{initial};playback::StageClock origin;
    const auto control=[&](bool terminal=false){
        if(!published)return; // Legacy update hook first runs after a PCM block.
        const auto f=engine.dspFrontier();const bool densityReady=!view||view->modes.empty()||std::all_of(f.nextInput.begin(),f.nextInput.end(),[&](auto p){return p>view->modes.back().first;});
        if(active!=none&&records[active].state==OperationState::Applied&&published>=std::size_t(records[active].change.plan.completionOutputSample)&&densityReady){records[active].state=OperationState::Completed;records[active].completedS=origin.elapsed().wallSeconds;active=none;}
        if(terminal)return;
        while(arrived<schedule.size()&&schedule[arrived].at<=published){auto& op=records[arrived];op.acceptedS=origin.elapsed().wallSeconds;
            if(!formalSpeed(op.target)){op.state=OperationState::Rejected;op.acceptance=Phase39RequestResult::Invalid;op.change.plan.outcome=Phase39Outcome::Invalid;++arrived;continue;}
            if(pending!=none)records[pending].state=OperationState::Replaced;pending=arrived++;
        }
        if(active==none&&pending!=none&&densityReady&&view){auto& op=records[pending];
            if(op.target==tail.micros){op.state=OperationState::Duplicate;op.acceptance=Phase39RequestResult::Duplicate;pending=none;return;}
            active=pending;pending=none;op.generation=++generation;op.state=OperationState::Submitted;op.workerState=Phase39RequestState::Requested;op.plannerSeenS=op.workerSeenS=origin.elapsed().wallSeconds;waitingNodes=none;
        }
        if(active==none||records[active].workerState!=Phase39RequestState::Requested||!view)return;
        if(waitingNodes==analysis.getSnapshot()->mapThroughNode&&waitingFinal==final)return;
        auto& op=records[active];op.frontier=f;op.publishedAtPlan=published;op.planStartedS=origin.elapsed().wallSeconds;playback::StageClock cost;
        auto r=planner.plan({op.target},op.generation,op.logicalPresented,published,f);const auto t=cost.elapsed();op.planCpuS+=t.threadCpuSeconds;op.planWallS+=t.wallSeconds;op.planFinishedS=origin.elapsed().wallSeconds;++op.attempts;
        op.planningDecided=r.status==PlanningStatus::Decided;op.analysisNodesAtPlan=analysis.getSnapshot()->mapThroughNode;op.receivedInputAtPlan=received;op.finalAnalysisAtPlan=final;
        if(r.status==PlanningStatus::PendingAnalysis){++op.analysisDeferrals;waitingNodes=analysis.getSnapshot()->mapThroughNode;waitingFinal=final;return;}
        op.change=r.change;
        if(r.change.plan.applied()){
            auto next=planner.view();if(!engine.trySupplyBorrowedDynamicMap(next.get())){planner.confirmPlan(false);throw std::runtime_error("Synchronous dynamic plan rejected");}
            view=std::move(next);planner.confirmPlan(true);tail={op.target};op.state=OperationState::Applied;op.workerState=Phase39RequestState::Applied;op.appliedS=origin.elapsed().wallSeconds;op.consumedAtApply=published;if(!final)++nonfinalPlans;
        }else{op.state=OperationState::Rejected;op.workerState=Phase39RequestState::Rejected;if(r.limitReached)op.acceptance=Phase39RequestResult::LimitReached;active=none;}
    };
    Phase45PcmDigest digest;std::array<float,4096> interleaved{};std::ofstream raw(argv[5],std::ios::binary);if(!raw)throw std::runtime_error("PCM output missing");
    const phase57::ProgressiveSynthesisEngine::Sink sink=[&](auto g,auto at,const float*const* p,std::size_t n){if(g!=1||at!=published)throw std::runtime_error("PCM identity/gap");for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<reader.channels();++c)interleaved[i*reader.channels()+c]=p[c][i];raw.write(reinterpret_cast<const char*>(interleaved.data()),n*reader.channels()*sizeof(float));digest.update(interleaved.data(),n*reader.channels()*sizeof(float));published+=n;if(!final)nonfinalPcm+=n;};
    for(;;){const auto state=engine.advance(sink);
        if(state==phase57::SynthesisState::Finished){control(true);break;}
        if(state==phase57::SynthesisState::NeedsMoreAnalysis||state==phase57::SynthesisState::NeedsMoreInput){
            if(final)throw std::runtime_error("Unexpected final analysis wait");
            if(received<reader.frames())received+=source.appendNext(analysis,chunkOption=="irregular"?irregular[chunkIndex++%irregular.size()]:chunk);
            else {source.finish(analysis);final=true;}
            auto snapshot=analysis.getSnapshot();engine.supplySnapshot(snapshot);planner.update(snapshot);auto next=planner.view();
            if(next&&(!view||next->version!=view->version)){if(!engine.trySupplyBorrowedDynamicMap(next.get()))throw std::runtime_error("Progressive extension rejected");view=std::move(next);}control();continue;
        }
        if(state!=phase57::SynthesisState::Produced)throw std::runtime_error("Unexpected terminal state");control();
    }
    for(auto& op:records)if(op.state==OperationState::Pending||op.state==OperationState::Submitted||op.state==OperationState::Applied){op.state=OperationState::Cancelled;op.workerState=Phase39RequestState::Cancelled;}
    exportOperations(directory,records,initial);
    std::ofstream nodes(directory/"dynamic_map.nodes.bin",std::ios::binary);nodes.write(reinterpret_cast<const char*>(view->map.starts().data()),view->map.starts().size()*sizeof(long long));
    std::size_t deferrals=0;for(const auto& op:records)deferrals+=op.analysisDeferrals;
    std::ofstream summary(directory/"summary.json");summary<<"{\"frames\":"<<published<<",\"channels\":"<<reader.channels()<<",\"pcm_sha256\":\""<<digest.finish()<<"\",\"nonfinal_pcm_frames\":"<<nonfinalPcm<<",\"nonfinal_plans\":"<<nonfinalPlans<<",\"analysis_deferrals\":"<<deferrals<<",\"same_dsp_instance\":true,\"plans\":"<<planner.historyCount()<<"}\n";
    std::cout<<"progressive replay frames="<<published<<" deferrals="<<deferrals<<" nonfinal_plans="<<nonfinalPlans<<'\n';
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
