#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include <iostream>
#include <sstream>
#include <thread>

// stdin is read on this dedicated serial control thread. The engine's own
// preparation/render workers continue while the user is entering a command.
int main(int argc,char** argv){
    if(argc<2||argc>4){std::cerr<<"使用法: phase61_interactive_play input.wav [speed=1.0] [candidate|baseline]\n";return 1;}
    int result=0;std::thread control([&]{try{
        using namespace ts::playback;
        ProgressiveOptions o;o.allowUnvalidatedFastLocalSeek=true;
        if(argc>2)o.initialSpeed=std::stod(argv[2]);
        if(argc>3){const std::string p=argv[3];if(p!="candidate"&&p!="baseline")throw std::invalid_argument("preset");o.preset=p=="baseline"?Preset::Baseline:Preset::Candidate;}
        ProgressiveMacPlaybackEngine e;e.prepare(argv[1],o);e.play();
        std::cout<<"実音声の開発用Interactiveホスト（出力音量50%）。\n"
                   "seek 秒 / exact 秒 / speed 倍率 / pause / resume / stop / play / status / quit\n"
                   "受付後はstatusで準備・完了・最初のPCMを確認してください。\n"<<std::flush;
        std::string line;
        while(std::cout<<"> "<<std::flush,std::getline(std::cin,line)){
            std::istringstream in(line);std::string cmd;double v=0;in>>cmd;
            try{
                if(cmd=="quit"||cmd=="q")break;
                if(cmd=="seek"||cmd=="exact"){
                    if(!(in>>v))throw std::invalid_argument("秒数が必要です");
                    const auto s=e.getStateSnapshot();const auto r=cmd=="seek"?
#ifdef PHASE61_INTERACTIVE_CONTRACT
                        e.requestInteractiveSeekToInputSeconds(v,s.inputGeneration,s.renderEpoch,s.session):
#else
                        e.requestFastLocalSeekToInputSeconds(v,s.inputGeneration,s.renderEpoch):
#endif
                        e.requestSeekToInputSeconds(v,s.inputGeneration,s.renderEpoch);
                    std::cout<<"受付 id="<<r.id<<" accepted="<<r.accepted<<" "<<r.reason<<'\n';
                }else if(cmd=="speed"){
                    if(!(in>>v))throw std::invalid_argument("倍率が必要です");const auto s=e.getStateSnapshot();const auto r=e.setSpeed(v,s.session,s.inputGeneration,s.renderEpoch);
                    std::cout<<"速度受付 id="<<r.id<<" result="<<int(r.result)<<'\n';
                }else if(cmd=="pause")std::cout<<"pause="<<e.pause()<<'\n';
                else if(cmd=="resume")std::cout<<"resume="<<e.resume()<<'\n';
                else if(cmd=="play")std::cout<<"play="<<e.play()<<'\n';
                else if(cmd=="stop")e.stop();
                else if(cmd=="status"){
                    const auto s=e.getStateSnapshot();const auto p=e.getCurrentPlaybackPosition();const auto q=e.getSeekSnapshot();const auto d=e.getPlaybackDiagnostics();
                    std::cout<<"state="<<progressive::name(s.state)<<" gen="<<s.inputGeneration<<" session="<<s.session<<" epoch="<<s.renderEpoch<<" output="<<p.outputFrame<<" input="<<(p.inputFrame?std::to_string(*p.inputFrame):"未取得")<<" analysis="<<d.pipeline.analysisDone<<" error="<<s.error<<'\n';
                    const auto& x=q.latest;
                    std::cout<<"seek="<<x.id<<" "<<progressive::name(x.state)<<" reason="<<x.reason<<" Ready(ms)="<<(x.readyNs?double(x.readyNs-x.acceptedNs)/1e6:-1)<<" 新PCM(ms)="<<(x.firstCallbackNs?double(x.firstCallbackNs-x.acceptedNs)/1e6:-1)<<'\n';
#ifdef PHASE61_INTERACTIVE_CONTRACT
                    const auto permission=e.seekAvailability();std::cout<<"段階="<<progressive::name(x.stage)<<" 開発opt-in="<<permission.interactiveOptIn<<" 現在の許可="<<permission.interactiveAllowed<<" 一般公開承認="<<permission.publicSeekApproved<<" 旧FIFO破棄="<<x.discardedForSeekFrames<<'\n';
#endif
                }else if(!cmd.empty())std::cout<<"不明なコマンドです\n";
            }catch(const std::exception& ex){std::cout<<"操作エラー: "<<ex.what()<<'\n';}
        }
        e.stop();
    }catch(const std::exception& ex){std::cerr<<ex.what()<<'\n';result=2;}});control.join();return result;
}
