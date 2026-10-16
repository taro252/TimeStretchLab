#include "prototype/Phase59ProgressiveTransition.h"
#include "prototype/Phase59ReplaySupport.h"
#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase56PinnedWav.h"
#include <iostream>
using namespace ts;using namespace ts::prototype;using namespace ts::prototype::phase59;
void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
template<class F>void rejects(F&& fn){bool rejected=false;try{fn();}catch(const std::exception&){rejected=true;}require(rejected,"Invalid state accepted");}
int main(int argc,char** argv){try{
    if(argc!=2)throw std::invalid_argument("input.wav");WavStreamReader reader(argv[1]);
    std::size_t prefixSnapshots=0,nonfinalApplied=0;
    for(bool candidate:{false,true}){
        auto c=experimental(reader,500000);c.timeRatio=2;const auto full=Phase13StreamingEngine(c).analyzeTransientEvents(argv[1]);
        Phase39TimeMap reference(full,reader.sampleRate(),{500000},candidate?Phase39Planning::L2:Phase39Planning::C);
        phase56::ProgressiveAnalysisSession analysis(reader.sampleRate(),reader.channels(),7,{},std::vector<std::uint32_t>{500000});
        phase56::PinnedWavSource source(argv[1],7);ProgressiveTransitionPlanner planner(reader.sampleRate(),reader.frames(),7,500000,candidate);
        Phase36StreamingSpeedEngine::Frontier f;bool changed=false;std::size_t received=0;
        require(planner.plan({1500000},1,0,0,f).status==PlanningStatus::PendingAnalysis,"Missing future analysis treated as empty events");
        while(received<reader.frames()){
            received+=source.appendNext(analysis,5003);auto snapshot=analysis.getSnapshot();planner.update(snapshot);
            if(auto v=planner.view()){
                const auto& expected=reference.current().starts();require(v->map.starts().size()<=expected.size(),"Prefix too long");
                require(std::equal(v->map.starts().begin(),v->map.starts().end(),expected.begin()),"Dynamic prefix mismatch");++prefixSnapshots;
                if(!changed){
                    const auto r=planner.plan({1500000},1,0,0,f);
                    if(r.status==PlanningStatus::Decided&&r.change.plan.applied()){
                        auto old=evaluate(reference,f,{}, {500000},{1500000},1,0,0,reader.frames(),candidate);
                        require(old.plan.applied()&&old.plan.appliedFrame==r.change.plan.appliedFrame&&old.plan.rampEndFrame==r.change.plan.rampEndFrame&&old.plan.completionOutputSample==r.change.plan.completionOutputSample,"Partial/full plan mismatch");
                        require(std::equal(planner.view()->map.starts().begin(),planner.view()->map.starts().end(),reference.current().starts().begin()),"Applied prefix mismatch");planner.confirmPlan(true);changed=true;++nonfinalApplied;
                    }
                }
            }
        }
        source.finish(analysis);planner.update(analysis.getSnapshot());require(changed,"No nonfinal transition exercised");
        require(planner.view()->map.starts()==reference.current().starts(),"Completed dynamic map differs");
        rejects([&]{planner.update(analysis.getSnapshot());});
        require(planner.plan({405000},2,0,0,f).change.plan.outcome==Phase39Outcome::Invalid,"1 percent validation failed");
        // Establish the initial complete map in a separate unmodified history.
        ProgressiveTransitionPlanner clean(reader.sampleRate(),reader.frames(),7,500000,candidate);clean.update(analysis.getSnapshot());auto initial=clean.view();
        phase57::ProgressiveSynthesisEngine engine(argv[1],500000,7);engine.enableDynamicTransitions();engine.supplySnapshot(analysis.getSnapshot());
        require(engine.trySupplyBorrowedDynamicMap(initial.get()),"Initial map failed");
        std::size_t output=0;const phase57::ProgressiveSynthesisEngine::Sink sink=[&](auto,auto at,const float*const*,auto n){require(at==output,"PCM gap");output+=n;};
        require(engine.advance(sink)==phase57::SynthesisState::Produced,"DSP did not advance");
        auto wrong=*initial;wrong.inputGeneration=8;wrong.version=2;wrong.baseVersion=1;require(!engine.trySupplyBorrowedDynamicMap(&wrong),"Old generation accepted");
        wrong=*initial;wrong.version=2;wrong.baseVersion=1;wrong.firstChangedNode=1;require(!engine.trySupplyBorrowedDynamicMap(&wrong),"Past node accepted");
        wrong=*initial;wrong.version=2;wrong.baseVersion=0;require(!engine.trySupplyBorrowedDynamicMap(&wrong),"Stale frontier version accepted");
        const auto frontier=engine.dspFrontier();
        clean.injectPublishFailureForTest();rejects([&]{clean.plan({1500000},1,0,output,frontier);});
        require(clean.historyCount()==0&&clean.tail().micros==500000&&clean.view()->version==initial->version,"Failed publication changed committed history");
        auto proposed=clean.plan({1500000},1,0,output,frontier);require(proposed.change.plan.applied(),"Rollback fixture did not apply");
        const auto abandonedVersion=clean.view()->version;clean.confirmPlan(false);
        require(clean.historyCount()==0&&clean.view()->version==initial->version&&clean.tail().micros==500000,"Stale proposal changed committed history");
        proposed=clean.plan({1500000},1,0,output,frontier);require(proposed.change.plan.applied()&&clean.view()->version>abandonedVersion&&clean.view()->baseVersion==initial->version,"Map ABA after rollback");
        require(engine.trySupplyBorrowedDynamicMap(clean.view().get()),"Replanned transaction failed");clean.confirmPlan(true);
        engine.cancel();require(engine.advance(sink)==phase57::SynthesisState::Cancelled,"Cancel became EOS");require(!engine.trySupplyBorrowedDynamicMap(initial.get()),"Map applied after cancel");
        auto malformed=std::make_shared<phase56::AnalysisSnapshot>(*analysis.getSnapshot());malformed->inputGeneration=8;
        ProgressiveTransitionPlanner invalid(reader.sampleRate(),reader.frames(),7,500000,candidate);rejects([&]{invalid.update(malformed);});
    }
    require(nonfinalApplied==2&&prefixSnapshots>2,"Incremental coverage missing");
    std::cout<<"PASS certified_prefix_snapshots="<<prefixSnapshots<<" nonfinal_applied="<<nonfinalApplied<<" generation/frontier/cancel rejection\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
