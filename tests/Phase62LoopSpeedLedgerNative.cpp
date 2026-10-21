#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <thread>
#include <stdexcept>
namespace {
using namespace ts::playback;
using State=progressive::State;
using LS=progressive::LoopSpeedState;
struct Gate {
    std::atomic<bool> armed{false},entered{false},release{false};
    static void event(void* p,ProgressiveControlTestPoint point)noexcept{
        auto& g=*static_cast<Gate*>(p);
        if(point!=ProgressiveControlTestPoint::SeekPreparationStarted||!g.armed.exchange(false))return;
        g.entered=true;const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(60);
        while(!g.release.load()&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
};
void require(bool b,const char* why){if(!b)throw std::runtime_error(why);}
template<class F>void until(ProgressiveMacPlaybackEngine& e,F f){
    const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(30);
    while(!f()){require(e.getPlaybackState()!=State::Failed,e.getPlaybackDiagnostics().error.c_str());require(std::chrono::steady_clock::now()<end,"timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}
}
progressive::LoopContext context(ProgressiveMacPlaybackEngine& e){auto s=e.getStateSnapshot();return {s.inputGeneration,s.session,s.renderEpoch};}
void run(const std::filesystem::path& input,Preset preset,const std::filesystem::path& folder,std::size_t limit,bool stoppedLimit){
    require(std::filesystem::create_directories(folder),"output exists");
    std::ofstream rows(folder/"checks.jsonl");unsigned passed=0;
    const auto pass=[&](const char* id){rows<<"{\"id\":\""<<id<<"\",\"status\":\"PASS\"}\n";rows.flush();++passed;};
    Gate gate;ProgressiveMacPlaybackEngine e;struct Release {Gate& g;~Release(){g.release=true;}} release{gate};
    ProgressiveOptions o;o.preset=preset;o.allowExperimentalLoops=true;o.loopSpeedOperationLimitForTest=stoppedLimit?4096:limit;o.stoppedSpeedOperationLimitForTest=stoppedLimit?limit:4096;o.controlTestHooks={&gate,Gate::event};
    require(e.prepare(input,o),"prepare");until(e,[&]{return e.getPlaybackState()==State::Ready;});
    const auto rate=e.getPlaybackDiagnostics().sourceSampleRate;
    require(e.requestLoopRange(0,rate*8,context(e)).accepted,"loop");until(e,[&]{return e.getLoopSnapshot().initialPositionComplete;});
    auto duplicate=e.requestLoopSpeed(1.,context(e));require(duplicate.accepted&&duplicate.duplicate&&!duplicate.id&&duplicate.code==progressive::LoopSpeedReceiptCode::DuplicateInitial&&e.loopSpeedHistory().empty(),"initial duplicate");pass("initial_duplicate_no_slot");
    auto first=e.requestLoopSpeed(.75,context(e));require(first.accepted&&!first.duplicate,"first request");
    until(e,[&]{auto s=e.getStateSnapshot();return s.stoppedSpeed&&s.stoppedSpeed->id==first.id&&s.stoppedSpeed->state==StoppedSpeedState::ReadyForResume;});
    require(e.loopSpeedOperation(first.id)->state==LS::ReadyForResume,"external Ready before play");pass("ready_before_resume");
    require(e.play(),"play");std::this_thread::sleep_for(std::chrono::milliseconds(80));require(e.pause(),"pause");
    auto before=e.stoppedSpeedHistory().front();require(before.outputStarted,"start fact missing");
    auto second=e.requestLoopSpeed(1.25,context(e));require(second.accepted,"second request");
    auto after=e.stoppedSpeedHistory().front();require(after.state==before.state&&after.outputStarted&&after.readyNs==before.readyNs&&after.session==before.session,"started preparation rewritten");
    require(e.loopSpeedOperation(first.id)->state==LS::Completed,"started external result");pass("started_history_immutable");
    until(e,[&]{return e.getStateSnapshot().stoppedSpeed->state==StoppedSpeedState::ReadyForResume;});
    gate.armed=true;auto third=e.requestLoopSpeed(.4,context(e));require(third.accepted,"third request");until(e,[&]{return gate.entered.load();});
    std::uint64_t previous=third.id;
    while(e.loopSpeedHistory().size()<limit){const auto speed=e.getStateSnapshot().stoppedSpeed->speedMicros==750000?1.25:.75;auto r=e.requestLoopSpeed(speed,context(e));require(r.accepted&&!r.duplicate,"early cap");require(e.loopSpeedOperation(previous)->state==LS::Replaced,"old receipt missing terminal");previous=r.id;}
    pass("all_replaced_receipts_retained");
    require(e.resume()&&e.getStateSnapshot().resumePending,"resume intent");
    const auto old=e.getStateSnapshot();const auto c=e.getCurrentPlaybackPosition();const auto loop=e.getLoopSnapshot();
    auto refused=e.requestLoopSpeed(2.,context(e));require(!refused.accepted&&!refused.reason.empty()&&refused.code==progressive::LoopSpeedReceiptCode::LimitReached,"limit reason");
    require(refused.reason.find(stoppedLimit?"停止中":"外部Loop")!=std::string::npos,"wrong limit reason");
    auto held=e.getStateSnapshot();require(held.resumePending&&held.stoppedSpeed->id==old.stoppedSpeed->id&&held.requestedSpeed==old.requestedSpeed&&e.getCurrentPlaybackPosition().inputFrame==c.inputFrame&&e.getLoopSnapshot().cycles==loop.cycles,"rejection changed intent/C");
    auto same=e.requestLoopSpeed(old.requestedSpeed,context(e));require(same.accepted&&same.duplicate&&same.id==old.stoppedSpeed->id&&e.loopSpeedHistory().size()==limit,"duplicate consumes full ledger");
    require(e.pause()&&!e.getStateSnapshot().resumePending,"cancel intent");pass("limit_before_side_effects_duplicate_and_repause");
    gate.release=true;until(e,[&]{return e.getStateSnapshot().stoppedSpeed->state==StoppedSpeedState::ReadyForResume;});
    auto stale=context(e);++stale.inputGeneration;auto invalid=e.requestLoopSpeed(.4,stale);require(!invalid.accepted&&!invalid.reason.empty()&&invalid.code==progressive::LoopSpeedReceiptCode::StaleContext,"stale reason");pass("stale_context_reason");
    e.stop();const auto history=e.loopSpeedHistory();require(history.size()==limit,"history discarded by Stop");for(const auto& op:history)require(progressive::terminal(op.state),"accepted ID left pending");require(e.loopSpeedOperation(first.id)->state==LS::Completed,"completed past changed by Stop");pass("stop_terminalizes_without_rewriting_past");
    require(ts::prototype::phase58::RealtimePipeline::executionOwnerCounts().alive==0&&ts::prototype::phase58::RealtimePipeline::executionOwnerCounts().peak<=2,"owner after stop/peak");pass("owners_retired");
    std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"schema\":1,\"run_complete\":true,\"status\":\""<<(passed==8?"PASS":"FAIL")<<"\",\"expected\":8,\"executed\":"<<passed<<",\"admission_limit\":"<<limit<<",\"independent_PCM\":\"NOT_RUN\"}\n";
    require(passed==8,"case count");std::cout<<"ledger native PASS "<<limit<<std::endl;
}
}
int main(int argc,char** argv){if(argc<4||argc>6)return 2;int result=1;std::thread worker([&]{try{run(argv[1],std::string(argv[2])=="candidate"?ts::playback::Preset::Candidate:ts::playback::Preset::Baseline,argv[3],argc>=5?std::stoull(argv[4]):6,argc==6&&std::string(argv[5])=="stopped");result=0;}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;}});worker.join();return result;}
