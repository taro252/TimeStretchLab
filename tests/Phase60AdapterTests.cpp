#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include <iostream>
#include <thread>
using namespace ts::playback;using S=progressive::State;
void require(bool b,const char* s){if(!b)throw std::runtime_error(s);}
void wait(ProgressiveMacPlaybackEngine& e,S wanted){const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(e.getPlaybackState()!=wanted){if(e.getPlaybackState()==S::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);require(std::chrono::steady_clock::now()<end,"state timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}}
int main(int argc,char** argv){int exit=0;std::thread control([&]{try{
    require(argc==2,"input.wav required");ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.initialSpeed=2;
    require(!e.capabilities().seek&&!e.seekToInputSeconds(1),"seek must be unsupported");
    e.prepare(argv[1],o);e.stop();require(e.getPlaybackState()==S::Stopped,"stop preparing");
    e.prepare(argv[1],o);wait(e,S::Ready);const auto first=e.getStateSnapshot();require(first.session&&e.getPlaybackDiagnostics().pipeline.published>=12288,"false Ready");
    for(unsigned p=40;p<=200;++p)require(e.setSpeed(p/100.).result==ts::prototype::Phase39RequestResult::Accepted,"161 speeds");
    auto ops=e.operationHistory();require(ops.size()==161,"operation count");for(std::size_t i=0;i<160;++i)require(ops[i].state==ts::prototype::phase59::OperationState::Replaced,"Latest-Wins");
    e.stop();require(e.operationHistory().back().state==ts::prototype::phase59::OperationState::Cancelled,"stop pending");
    require(e.play(),"stop play acceptance");wait(e,S::Playing);require(e.getStateSnapshot().session!=first.session,"new session");
    require(e.setSpeed(.5,first.session,first.inputGeneration).result==ts::prototype::Phase39RequestResult::Stopped,"old session accepted");
    require(e.pause(),"pause");const auto at=e.getCurrentPlaybackPosition().outputFrame;std::this_thread::sleep_for(std::chrono::milliseconds(40));require(e.getCurrentPlaybackPosition().outputFrame==at,"paused consumption");require(e.resume(),"resume");e.stop();
    auto m=e.getPlaybackDiagnostics().pipeline.scheduling;require(!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"Workgroup lifetime");
    e.prepare(argv[1],o);wait(e,S::Ready);e.play();e.simulateDeviceChangeForTest();wait(e,S::Stopped);require(e.getStateSnapshot().reason==StopReason::RouteChanged,"route safe stop");
    e.prepare(argv[1],o);wait(e,S::Ready);ProgressiveMacPlaybackEngine other;other.prepare(argv[1],o);const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(5);while(other.getPlaybackState()!=S::Failed&&std::chrono::steady_clock::now()<limit)std::this_thread::sleep_for(std::chrono::milliseconds(2));require(other.getPlaybackState()==S::Failed,"resource ownership admission");other.stop();e.stop();
    auto tiny=o;tiny.memoryReservationBudget=1;e.prepare(argv[1],tiny);while(e.getPlaybackState()!=S::Failed)std::this_thread::sleep_for(std::chrono::milliseconds(2));require(!e.getPlaybackDiagnostics().error.empty(),"budget failure");
    e.prepare(argv[1],o);wait(e,S::Ready);e.play();wait(e,S::Ended);auto old=e.getStateSnapshot().session;require(e.play(),"EOS play");wait(e,S::Playing);require(e.getStateSnapshot().session!=old,"EOS generation");wait(e,S::Ended);
    m=e.getPlaybackDiagnostics().pipeline.scheduling;require(!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"EOS Workgroup lifetime");
    std::cout<<"PASS preparing stop, 161 admission, Latest-Wins, pause/resume, stop/play, route, budgets, failure recovery, EOS/restart\n";
}catch(const std::exception& err){std::cerr<<err.what()<<'\n';exit=1;}});control.join();return exit;}
