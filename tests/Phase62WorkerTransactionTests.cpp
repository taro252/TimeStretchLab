// Real planner/DSP transaction tests. Standard workers, offline functional only.
#define main phase62_cache_focus_unused_main
#include "Phase62CacheFocusTests.cpp"
#undef main
#include <atomic>
namespace {
using FaultPoint=p58::ControlTestPoint;
struct Gate {
    std::atomic<int> point{-1};std::atomic<bool> entered{false},release{false},expired{false},left{false},finished{false},finishRelease{false};
    std::atomic<std::uint64_t> id{0},session{0};std::atomic<bool> rejectOnce{false},delayOnce{false},delaying{false};
    void arm(FaultPoint p){point=int(p);entered=false;release=false;left=false;}
    static void event(void* context,FaultPoint p,std::uint64_t session,std::uint64_t id)noexcept{
        auto& g=*static_cast<Gate*>(context);
        if(p==FaultPoint::CacheReconstructionStarted&&g.delayOnce.exchange(false)){g.delaying=true;std::this_thread::sleep_for(std::chrono::milliseconds(300));}
        if(p==FaultPoint::CacheDeadlineFinished){g.finished=true;const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(10);while(!g.finishRelease&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::microseconds(100));if(!g.finishRelease)g.expired=true;return;}
        if(int(p)!=g.point.load())return;g.id=id;g.session=session;g.entered=true;
        const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(10);
        while(!g.release.load()&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::microseconds(100));
        if(!g.release.load())g.expired=true;g.left=true;
    }
    static bool fail(void* context,FaultPoint p,std::uint64_t,std::uint64_t)noexcept{return p==FaultPoint::ApplyingBeforeSupply&&static_cast<Gate*>(context)->rejectOnce.exchange(false);}
};
}
int main(int argc,char**argv){Gate g;Owners owners;fs::path out;
try{
    need(argc==5,"input preset mode output");const std::string mode=argv[3];out=argv[4];need(!fs::exists(out)&&fs::create_directories(out),"fresh output");
    const bool cache=mode=="cache_old_new";need(cache||mode=="applying_cancel"||mode=="planner_cancel"||mode=="proposal_cancel","mode");
    const std::vector<std::string> ids{"real_window","cancel_old","accept_new","old_completion_isolated","history_rollback","owners_and_resources"};
    std::ofstream expected(out/"EXPECTED.json");expected<<"{\"expected\":6,\"required_ids\":[";for(std::size_t i=0;i<ids.size();++i)expected<<(i?",":"")<<quote(ids[i]);expected<<"],\"mode\":"<<quote(mode)<<",\"preset\":"<<quote(argv[2])<<",\"binary_sha256\":"<<quote(sha(argv[0]))<<",\"input_sha256\":"<<quote(sha(argv[1]))<<",\"realtime\":false}\n";expected.close();
    std::ofstream checks(out/"checks.jsonl");unsigned passed=0;auto check=[&](const std::string& id,bool ok){checks<<"{\"id\":"<<quote(id)<<",\"pass\":"<<(ok?"true":"false")<<"}\n";checks.flush();need(ok,id);++passed;};
    ts::WavStreamReader wav(argv[1]);p58::Configuration c;c.speedMicros=1000000;c.candidate=std::string(argv[2])=="candidate";c.verifyPcm=false;c.residentInput=true;c.scheduling=p58::WorkerScheduling::AudioWorkgroup;c.controlTestHooks={&g,Gate::event,Gate::fail};
    owners.source=std::make_unique<Pipeline>(argv[1],c);ready(*owners.source);wait(*owners.source,[&]{return owners.source->finalAnalysisAvailable();},"source analysis");
    owners.current=owners.source->createLoopSeek(0,cache?wav.sampleRate()/2:wav.sampleRate()*8,1000000);owners.current->enableLoopReuse(0);owners.source->stop();owners.source.reset();ready(*owners.current);auto& p=*owners.current;need(p.setRealtimeRendering(true),"worker promotion");
    need((p.diagnostics().loopReuse.cacheBytes>0)==cache,"actual cache class");
    std::array<std::array<float,1024>,2> pcm;float* pointers[]{pcm[0].data(),pcm[1].data()};
    if(cache){const auto L=p.loopOutputEndFrame()-p.loopOutputStartFrame();std::size_t taken=0;while(taken<2*L){auto n=std::min<std::size_t>(1024,2*L-taken);wait(p,[&]{return p.available()>=n;},"warm cache supply");need(p.pullAudio(pointers,n).received==n,"warm cache read");taken+=n;}}
    g.arm(cache?FaultPoint::CacheDeadlineDecided:mode=="applying_cancel"?FaultPoint::ApplyingRejected:mode=="planner_cancel"?FaultPoint::PlannerBeforePlan:FaultPoint::PlannerProposal);g.rejectOnce=mode=="applying_cancel";g.delayOnce=cache;
    const auto a=p.requestLoopTransition(750000,0);need(a.result==ts::prototype::Phase39RequestResult::Accepted,"accept old A");
    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(10);
    while(!g.entered.load()){need(!p.failed(),p.diagnostics().error);need(std::chrono::steady_clock::now()<until,"missed required real window");if(!g.delaying&&p.available()>=1024){auto r=p.pullAudio(pointers,1024);need(r.received==1024,"offline supply");}std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    const auto s=p.loopTransition();check("real_window",g.id==a.id&&g.session==p.diagnostics().session&&s.state==State::Requested);
    check("cancel_old",p.cancelLoopTransition());
    if(!cache){g.release=true;wait(p,[&]{return g.left.load();},"gate release");g.arm(FaultPoint::PlannerBeforePlan);}
    p59::RequestReceipt b;wait(p,[&]{b=p.requestLoopTransition(1250000,p.positionSample().value().output);return b.result!=ts::prototype::Phase39RequestResult::Busy;},"settlement");check("accept_new",b.result==ts::prototype::Phase39RequestResult::Accepted&&b.id!=a.id);
    if(cache){g.release=true;wait(p,[&]{return g.finished.load();},"deadline finish");}
    else wait(p,[&]{return g.entered.load();},"new planner window");
    const auto next=p.loopTransition();
    {std::ofstream audit(out/"old_new_transaction.json");audit<<"{\"old_id\":"<<a.id<<",\"new_id\":"<<b.id<<",\"deadline_decision_id\":"<<g.id.load()<<",\"new_observed_id\":"<<next.operationID<<",\"state\":"<<quote(stateName(next.state))<<",\"reason\":"<<int(next.reason)<<"}\n";}
    check("old_completion_isolated",next.operationID==b.id&&next.reason==p58::LoopTransitionReason::None&&next.state==State::Requested);
    need(p.cancelLoopTransition(),"cancel new");g.release=true;g.finishRelease=true;
    wait(p,[&]{auto ops=p.speedOperations();return ops.size()==2&&ops[0].state==p59::OperationState::Cancelled&&ops[1].state==p59::OperationState::Cancelled;},"both cancellation acknowledgement");
    const auto operations=p.speedOperations();
    if(!cache)need(operations[0].attempts>0&&operations[0].change.plan.applied(),"real proposed plan was not rolled back");
    if(mode=="applying_cancel")need(!g.rejectOnce.load(),"real engine revalidation injection was not consumed");
    check("history_rollback",p.diagnostics().transitionHistory==0);
    const auto d=p.diagnostics();std::ofstream audit(out/"audit.json");audit<<"{\"old_id\":"<<a.id<<",\"new_id\":"<<b.id<<",\"observed_new_state\":"<<quote(stateName(next.state))<<",\"observed_new_reason\":"<<int(next.reason)<<",\"session\":"<<d.session<<",\"history\":"<<d.transitionHistory<<"}\n";audit.close();
    owners.retire();const auto counts=Pipeline::executionOwnerCounts();check("owners_and_resources",counts.alive==0&&counts.peak<=2&&!g.expired&&d.missingFrames==0&&d.loopReuse.checkpointPeak<=2);
    std::ofstream summary(out/"SUMMARY.json");summary<<"{\"status\":\"PASS\",\"expected\":6,\"executed\":"<<passed<<",\"passed\":"<<passed<<",\"complete\":true}\n";std::cout<<"PHASE62_WORKER_TRANSACTION_COMPLETE expected=6 executed="<<passed<<" passed="<<passed<<'\n';return 0;
}catch(const std::exception&e){g.release=true;g.finishRelease=true;std::cerr<<"FAIL "<<e.what()<<'\n';if(!out.empty()){std::ofstream s(out/"SUMMARY.json");s<<"{\"status\":\"FAIL\",\"reason\":"<<quote(e.what())<<",\"complete\":false}\n";}owners.retire();return 1;}}
