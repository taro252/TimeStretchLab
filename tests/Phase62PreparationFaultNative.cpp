#define PHASE62_PLAYING_LEDGER_NO_MAIN
#include "Phase62PlayingLedgerNative.cpp"
namespace {
using FaultPoint=ph58::ControlTestPoint;
struct Fault {
    std::atomic<bool> armed{false};std::atomic<unsigned> hits{0};std::atomic<std::uint64_t> failedSession{0};
    WorkerGate deadline,retiring;
    static void normal(void* p,ProgressiveControlTestPoint at)noexcept{auto& f=*static_cast<Fault*>(p);WorkerGate::event(&f.deadline,at);WorkerGate::event(&f.retiring,at);}
    FaultPoint point;std::atomic<std::uint64_t> oldSession{0};
    static bool fail(void* p,FaultPoint at,std::uint64_t session,std::uint64_t)noexcept{
        auto& f=*static_cast<Fault*>(p);if(at!=f.point||session==f.oldSession||!f.armed.exchange(false))return false;
        ++f.hits;f.failedSession=session;return true;
    }
};
}
int runPreparationFault(int argc,char**argv){std::filesystem::path out;
try{
    require(argc==6,"mode input preset output sourceSHA");const std::string mode=argv[1];out=argv[4];require(!std::filesystem::exists(out)&&std::filesystem::create_directories(out),"fresh output");
    require(mode=="checkpoint"||mode=="reservation"||mode=="workgroup"||mode=="deadline"||mode=="paused_deadline","mode");
    const std::vector<std::string> ids{"stable_old_loop","actual_failure_branch","external_final_cause","old_PCM_or_paused_C_preserved","failed_preparation_retired","subsequent_request_recovers","normal_supply_and_owner_cap"};
    std::ofstream expected(out/"EXPECTED.json");expected<<"{\"mode\":"<<ph58::jsonString(mode)<<",\"expected\":7,\"required_ids\":[";for(std::size_t i=0;i<ids.size();++i)expected<<(i?",":"")<<ph58::jsonString(ids[i]);expected<<"],\"source_sha256\":"<<ph58::jsonString(argv[5])<<",\"functional_fault_injection\":true}\n";expected.close();
    Fault fault;fault.point=mode=="checkpoint"?FaultPoint::CheckpointPermit:mode=="reservation"?FaultPoint::EpochReservation:FaultPoint::WorkgroupJoin;
    LedgerFixture f(argv[2],std::string(argv[3])=="candidate"?Preset::Candidate:Preset::Baseline,out,ids,4096,{&fault,nullptr,Fault::fail},std::chrono::milliseconds(2000),{&fault,Fault::normal});
    struct ReleaseFaultGates{Fault& f;~ReleaseFaultGates(){f.deadline.released=true;f.retiring.released=true;}} releaseGates{fault};
    const auto old=f.engine->getStateSnapshot().session;fault.oldSession=old;auto frames=f.capture().frames.load();const auto loopBefore=f.engine->getLoopSnapshot();require(loopBefore.enabled&&loopBefore.initialPositionComplete,"stable reusable loop");f.pass("stable_old_loop");
    std::optional<std::uint64_t> C;
    if(mode=="paused_deadline"){require(f.engine->pause(),"pause");f.until([&]{C=f.engine->getCurrentPlaybackPosition().inputFrame;return C.has_value();},"paused position");frames=f.capture().frames.load();}
    if(mode=="deadline"||mode=="paused_deadline")fault.deadline.arm(ProgressiveControlTestPoint::NextPreparationDeadline);else fault.armed=true;
    if(mode!="reservation")fault.retiring.arm(ProgressiveControlTestPoint::RetiringPreparation);
    const auto request=f.request("faulted_75",.75);
    if(mode=="deadline"||mode=="paused_deadline"){f.until([&]{return fault.deadline.entered.load();},"deadline hook");std::this_thread::sleep_for(std::chrono::milliseconds(2100));fault.deadline.released=true;}
    f.until([&]{return progressive::terminal(f.row(request.id).state);},"external failure");const auto failed=f.row(request.id);require(failed.state==LS::Failed,"failed external state");
    if(mode=="deadline"||mode=="paused_deadline")require(failed.reason.find("期限")!=std::string::npos,"actual timeout reason");else require(fault.hits==1,"actual permit/reservation/join call site not reached");f.pass("actual_failure_branch");
    require(failed.deferral==progressive::LoopSpeedDeferral::PreparationFailed,"general failure retained stale deferral");f.pass("external_final_cause");
    if(mode!="reservation"){
        f.until([&]{return fault.retiring.entered.load();},"actual failed preparation retirement");
        if(C){require(!f.engine->play()&&!f.engine->getStateSnapshot().resumePending,"Play accepted while failed epoch is retiring");require(f.engine->getCurrentPlaybackPosition().inputFrame==C,"retiring failure moved C");}
        fault.retiring.released=true;
    }else {
        // Reservation precedes construction of the next execution owner. There
        // is no failed owner to retire and no RetiringPreparation event.
        require(!fault.retiring.entered&&ph58::RealtimePipeline::executionOwnerCounts().alive==1,"reservation rejection constructed or retained a next owner");
    }
    f.until([&]{return !f.engine->getPlaybackDiagnostics().retiringPipeline&&ph58::RealtimePipeline::executionOwnerCounts().alive==1;},"failed epoch retirement");
    require(f.engine->getLoopSnapshot().enabled&&f.engine->getLoopSnapshot().id==loopBefore.id,"old Loop lost");
    if(C){require(f.engine->getPlaybackState()==State::Paused&&!f.engine->getStateSnapshot().resumePending,"paused failure/resume intent");require(f.engine->getCurrentPlaybackPosition().inputFrame==C&&f.capture().frames==frames,"paused C/audio advanced");require(!f.engine->play(),"failed preparation play incorrectly accepted");}
    else {const auto afterFailure=f.capture().frames.load();f.until([&]{return f.capture().frames>afterFailure+f.rate/2;},"old PCM supply");require(f.engine->getStateSnapshot().session==old,"old owner changed on rejected preparation");}
    f.pass("old_PCM_or_paused_C_preserved");
    bool joinFailure=false;for(const auto& epoch:f.engine->closedEpochs())if(epoch.pipeline.session==fault.failedSession&&mode=="workgroup"){
        const auto&m=epoch.pipeline.scheduling;require(m.enabled&&m.joinErrors==1&&m.promotions==m.restores&&m.joins==m.leaves&&!m.active,"real Workgroup join failure cleanup");joinFailure=true;
    }
    if(mode=="workgroup")require(joinFailure,"failed Workgroup epoch missing");require(f.engine->getPlaybackDiagnostics().pipeline.loopReuse.checkpointPeak<=2,"checkpoint bound");f.pass("failed_preparation_retired");
    const auto recovery=f.request("recover_125",1.25);
    if(C){f.until([&]{return f.row(recovery.id).state==LS::ReadyForResume;},"recovery paused ready");require(f.engine->play(),"recovery play");}
    f.completed(recovery.id);require(operationJson(f.row(request.id))==operationJson(failed),"failed ID resurrected");f.pass("subsequent_request_recovers");
    f.exactIds(true);f.saveLedger("terminal_ledger.jsonl");require(!fault.deadline.expired&&!fault.retiring.expired,"fault gate expired");
    f.qualityAndOwnership();f.pass("normal_supply_and_owner_cap");
    std::ofstream summary(out/"SUMMARY.json");summary<<"{\"status\":\"PASS\",\"expected\":7,\"executed\":7,\"passed\":7,\"complete\":true}\n";std::cout<<"PHASE62_PREPARATION_FAULT_COMPLETE expected=7 executed=7 passed=7\n";return 0;
}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';if(!out.empty()){std::ofstream summary(out/"SUMMARY.json");summary<<"{\"status\":\"FAIL\",\"reason\":"<<ph58::jsonString(e.what())<<",\"complete\":false}\n";}return 1;}}

int main(int argc,char**argv){int code=1;std::thread owner([&]{code=runPreparationFault(argc,argv);});owner.join();return code;}
