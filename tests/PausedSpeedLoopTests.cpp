#define main pausedIncludedMain
#include "PausedSpeedNativeTests.cpp"
#undef main
int main(int argc,char** argv){if(argc!=3)return 1;int result=1;std::thread owner([&]{try{
    WavStreamReader wav(argv[1]);ProgressiveOptions o;o.initialSpeed=2;o.allowExperimentalLoops=true;o.preset=std::string(argv[2])=="baseline"?Preset::Baseline:Preset::Candidate;
    ProgressiveMacPlaybackEngine e;e.prepare(argv[1],o);state(e,State::Ready);const auto s=e.getStateSnapshot();
    progressive::LoopOptions lo;lo.startPolicy=progressive::LoopStartPolicy::KeepPosition;
    auto r=e.requestLoopRange(0,wav.frames(),{s.inputGeneration,s.session,s.renderEpoch},lo);check(r.accepted,r.reason);
    wait([&]{auto loop=e.getLoopSnapshot();check(loop.state!=progressive::LoopState::Failed,loop.reason);return loop.state==progressive::LoopState::Armed;});
    check(e.play(),"Loop Ready play acceptance");state(e,State::Playing);wait([&]{return e.getLoopSnapshot().cycles>=1;});check(e.pause(),"loop pause");
    check(e.setSpeed(1.25).result==Phase39RequestResult::Accepted,"loop speed accepted");check(!e.getStateSnapshot().stoppedSpeed,"loop routed through stopped speed");check(e.resume(),"Loop pending boundary resume");state(e,State::Playing);
    wait([&]{auto l=e.getLoopSnapshot();check(l.state!=progressive::LoopState::Failed,l.reason);return l.appliedSpeed==1.25;});check(e.pause(),"clear loop pause");
    const auto current=e.getStateSnapshot();auto clear=e.requestClearLoop(r.id,{current.inputGeneration,current.session,current.renderEpoch});check(clear.accepted,clear.reason);check(e.resume(),"Loop clearing resume");state(e,State::Ended);
    check(!e.getPlaybackDiagnostics().missingFrames,"Loop supply regression");e.stop();std::cout<<"PASS native Loop KeepPosition Ready/start, boundary speed Paused/resume, clear Paused/resume; existing opt-in contract\n";result=0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});owner.join();return result;}
