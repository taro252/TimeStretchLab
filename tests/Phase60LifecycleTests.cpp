#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include <iostream>
#include <thread>
using namespace ts::playback;using State=progressive::State;
void require(bool v,const char* s){if(!v)throw std::runtime_error(s);}
void wait(ProgressiveMacPlaybackEngine& e,State wanted){auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(20);while(e.getPlaybackState()!=wanted){if(e.getPlaybackState()==State::Failed&&wanted!=State::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);require(std::chrono::steady_clock::now()<deadline,"lifecycle timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}}
void settled(ProgressiveMacPlaybackEngine& e){for(const auto& o:e.operationHistory()){using O=ts::prototype::phase59::OperationState;require(o.state!=O::Pending&&o.state!=O::Submitted&&o.state!=O::Applied,"nonterminal operation after stop");}const auto m=e.getPlaybackDiagnostics().pipeline.scheduling;require(!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"worker lifetime leak");}
int main(int argc,char** argv){int code=0;std::thread control([&]{try{
    require(argc==2,"input.wav");const std::filesystem::path input=argv[1],different=input.parent_path()/"drums.wav";ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.initialSpeed=1;
    for(int i=0;i<3;++i){e.prepare(input,o);e.play();e.stop();require(e.getPlaybackState()==State::Stopped,"cancelled prepare revived");require(e.getNativeDiagnostics().firstPcmMachNs==0,"auto-play after cancel");}
    e.prepare(input,o);wait(e,State::Ready);const auto original=e.getPlaybackDiagnostics().pipeline.inputSha256;e.play();wait(e,State::Playing);
    const auto receipt=e.setSpeed(.4);require(receipt.id>0,"playing request rejected");std::this_thread::sleep_for(std::chrono::milliseconds(5));
    const auto p=e.getCurrentPlaybackPosition();if(p.sampledOutputFrame)require(*p.sampledOutputFrame<=p.outputFrame,"position sample newer than current consumption");e.stop();settled(e);
    e.prepare(input,o);wait(e,State::Ready);e.play();wait(e,State::Playing);require(e.pause(),"pause");require(e.setSpeed(.49).id>0,"paused pending request");e.stop();settled(e);
    const auto old=e.getStateSnapshot().session;e.prepare(different,o);wait(e,State::Ready);require(e.getStateSnapshot().session!=old,"input switch session reused");require(e.getPlaybackDiagnostics().pipeline.inputSha256!=original,"input switch reused old input");e.stop();settled(e);
    const auto temporary=std::filesystem::temp_directory_path()/("phase60_mutation_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count())+".wav");std::filesystem::copy_file(input,temporary);
    e.prepare(temporary,o);wait(e,State::Ready);std::filesystem::remove(temporary);wait(e,State::Failed);require(!e.getPlaybackDiagnostics().error.empty(),"source loss lacks reason");
    e.prepare(input,o);wait(e,State::Ready);e.stop();settled(e);
    std::cout<<"PASS prepare/auto-play cancel x3, playing-request stop, paused-request stop, input switch, selected source loss/recovery, paired position\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';code=1;}});control.join();return code;}
