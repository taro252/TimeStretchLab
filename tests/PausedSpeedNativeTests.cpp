#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase39TimeMap.h"
#include "audio/WavStream.h"
#include <bit>
#include <cstring>
#include <fstream>
#include <iostream>
#include <thread>
#include <libproc.h>
#include <mach/mach.h>
using namespace ts;using namespace ts::playback;using namespace ts::prototype;
using State=progressive::State;
static void check(bool v,const std::string& why){if(!v)throw std::runtime_error(why);}
template<class F> static void wait(F f){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(60);while(!f()){check(std::chrono::steady_clock::now()<end,"wait timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
static void state(ProgressiveMacPlaybackEngine& e,State wanted){wait([&]{auto s=e.getStateSnapshot();check(s.state!=State::Failed,s.error);return s.state==wanted;});}
struct Capture {
    std::atomic<std::uint64_t> epoch{0},firstNs{0};std::atomic<std::size_t> count{0},errors{0};
    std::size_t start=0,channels;std::vector<float> pcm;std::uint64_t session=0,generation=0;
    explicit Capture(std::size_t ch):channels(ch),pcm(65536*ch){}
    void reset(){epoch=0;count=errors=firstNs=0;session=generation=0;}
    static void raw(void* ctx,const float*const* p,std::size_t n,std::size_t at,std::uint64_t gen,std::uint64_t ep,std::uint64_t session)noexcept{
        auto& x=*static_cast<Capture*>(ctx);if(ep!=x.epoch.load())return;const auto done=x.count.load(std::memory_order_relaxed);
        if(!done){x.start=at;x.generation=gen;x.session=session;x.firstNs=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
        if((done&&at!=x.start+done)||done+n>65536){++x.errors;return;}
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<x.channels;++c)x.pcm[(done+i)*x.channels+c]=p[c][i];x.count.store(done+n,std::memory_order_release);
    }
    static void output(void* ctx,const float*const*,const ProgressiveOutputSpan& span)noexcept{
        auto& x=*static_cast<Capture*>(ctx);if(span.newEpoch==x.epoch.load()&&(span.oldEpoch||span.mixedFrames||span.newMissingFrames||span.newReceivedFrames!=span.frames))++x.errors;
    }
};
struct Gate {
    std::atomic<bool> armed{false},entered{false},release{false};
    ProgressiveControlTestPoint point=ProgressiveControlTestPoint::SeekPreparationStarted;
    static void event(void* ctx,ProgressiveControlTestPoint point)noexcept{
        auto& g=*static_cast<Gate*>(ctx);if(point!=g.point||!g.armed.exchange(false))return;
        g.entered=true;const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(15);
        while(!g.release.load()&&std::chrono::steady_clock::now()<end)std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
};
static StoppedSpeedOperation ready(ProgressiveMacPlaybackEngine& e,std::uint64_t id,std::uint64_t oldEpoch=0,std::size_t oldConsumed=0){
    StoppedSpeedOperation op;wait([&]{auto s=e.getStateSnapshot();check(s.state!=State::Failed,s.error);check(s.stoppedSpeed&&s.stoppedSpeed->id==id,"operation correlation lost");op=*s.stoppedSpeed;
        check(op.state!=StoppedSpeedState::Failed,op.reason);check(op.state!=StoppedSpeedState::Cancelled&&op.state!=StoppedSpeedState::Replaced,"unexpected cancellation");
        if(oldEpoch){const auto d=e.getPlaybackDiagnostics();if(d.renderEpoch==oldEpoch)check(d.consumedFrames==oldConsumed,"old FIFO consumed during preparation");}
        return op.state==StoppedSpeedState::ReadyForResume;});return op;
}
static void seek(ProgressiveMacPlaybackEngine& e,std::size_t frame){auto r=e.requestSeekToInputFrame(frame);check(r.accepted,r.reason);wait([&]{auto s=e.getSeekSnapshot();check(s.latest.id==r.id,"seek lost");check(s.latest.state!=progressive::SeekState::Failed,s.latest.reason);return s.latest.state==progressive::SeekState::Completed;});}
static std::uint64_t request(ProgressiveMacPlaybackEngine& e,double speed){const auto t=std::chrono::steady_clock::now();auto r=e.setSpeed(speed);check(r.result==Phase39RequestResult::Accepted,"speed rejected");check(std::chrono::steady_clock::now()-t<std::chrono::milliseconds(100),"API blocked on preparation");return r.id;}
static void matrix(const std::filesystem::path& input,const std::filesystem::path& refs,Preset preset,bool all){
    WavStreamReader wav(input);Capture capture(wav.channels());ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.preset=preset;o.observerContext=&capture;o.observeEpochPcm=Capture::raw;o.observeOutputPcm=Capture::output;
    StretchConfig config;config.sampleRate=wav.sampleRate();config.channels=wav.channels();config.timeRatio=2;config.qualityMode=QualityMode::Experimental;
    config.enableMultiResolution=config.enablePhaseLocking=config.enableTransientHandling=config.enableAdaptiveTimeMapping=config.enablePreciseTransientAnchoring=config.enableStereoCoherence=true;
    const auto analysis=Phase13StreamingEngine(config).analyzeTransientEvents(input);
    e.prepare(input,o);state(e,State::Ready);
    std::vector<unsigned> speeds;if(all)for(unsigned s=400000;s<=2000000;s+=10000)speeds.push_back(s);else speeds={750000,1250000,400000,2000000,490000,500000,990000,1000000,1010000};
    // The first case is a real play -> pause at an actual consumed cursor.
    capture.epoch=e.getStateSnapshot().renderEpoch;check(e.play(),"initial play");wait([&]{return capture.count.load()>=wav.sampleRate()/3;});check(e.pause(),"initial pause");
    auto frozen=e.getCurrentPlaybackPosition();check(frozen.inputFrame&&frozen.sampledOutputFrame==frozen.outputFrame,"unpaired pause position");
    for(auto speed:speeds){
        if(speed!=speeds.front())seek(e,wav.frames()/2+17);
        const auto before=e.getPlaybackDiagnostics();const auto position=e.getCurrentPlaybackPosition();check(position.inputFrame.has_value(),"missing exact input");const auto seeks=e.seekHistory().size();
        capture.reset();auto id=request(e,speed/1e6);const auto op=ready(e,id,before.renderEpoch,before.consumedFrames);
        check(op.positionCaptured&&op.resumeInputFrame==*position.inputFrame,"input position moved");check(e.seekHistory().size()==seeks,"speed fabricated user seek");
        auto d=e.getPlaybackDiagnostics();check(d.consumedFrames==d.pipeline.outputStartFrame&&d.currentEpochPresentedFrame==d.pipeline.outputStartFrame,"new epoch consumed while stopped");
        check((e.getPlaybackState()==State::Paused)&&!capture.count,"preparation played audio");
        Phase39TimeMap timeline(analysis,wav.sampleRate(),Phase39Speed{speed},preset==Preset::Candidate?Phase39Planning::L2:Phase39Planning::C);
        const auto expected=std::min(std::size_t(std::llround(wav.frames()/(speed/1e6))),std::size_t(std::max(0LL,std::llround(timeline.current().outputPositionForInputSample(double(op.resumeInputFrame))))));
        check(op.outputStartFrame==expected,"independent TimeMap mismatch");
        check(d.pipeline.sourceHashPasses==1&&d.pipeline.sourceSnapshotCreations==1&&d.pipeline.residentLockCalls==1&&d.pipeline.reusedAnalysis,"input/analysis was recreated");
        capture.epoch=op.renderEpoch;auto called=std::chrono::steady_clock::now();check(e.resume(),"resume acceptance");wait([&]{return capture.count.load()>=2048;});check(e.pause(),"pause after PCM");
        check(!capture.errors&&capture.start==expected&&capture.session==op.session&&capture.generation==op.inputGeneration,"epoch/output span/RAW continuity");
        std::ifstream raw(refs/(std::to_string(speed)+"_"+(preset==Preset::Candidate?"candidate":"baseline")+".f32"),std::ios::binary);check(bool(raw),"reference missing");raw.seekg(expected*wav.channels()*sizeof(float));
        std::vector<float> reference(capture.count*wav.channels());check(bool(raw.read(reinterpret_cast<char*>(reference.data()),reference.size()*sizeof(float))),"reference truncated");
        check(std::memcmp(reference.data(),capture.pcm.data(),reference.size()*sizeof(float))==0,"independent legacy RAW PCM mismatch");
        d=e.getPlaybackDiagnostics();check(!d.missingFrames&&!d.rejectedWrites,"new supply failure");
        std::cout<<"{\"case\":\"pcm\",\"speed\":"<<speed<<",\"candidate\":"<<(preset==Preset::Candidate)<<",\"input\":"<<op.resumeInputFrame<<",\"output\":"<<expected<<",\"epoch\":"<<op.renderEpoch<<",\"frames\":"<<capture.count<<",\"ready_ms\":"<<double(op.readyNs-op.acceptedNs)/1e6<<",\"resume_first_pcm_ms\":"<<double(capture.firstNs.load()-std::chrono::duration_cast<std::chrono::nanoseconds>(called.time_since_epoch()).count())/1e6<<",\"rss\":"<<d.rssBytes<<",\"fd_bytes\":"<<proc_pidinfo(getpid(),PROC_PIDLISTFDS,0,nullptr,0)<<",\"PASS\":true}"<<std::endl;
    }
    e.stop();
}
static void shortReady(const std::filesystem::path& input,const std::filesystem::path& refs,Preset preset){
    WavStreamReader wav(input);Capture capture(wav.channels());ProgressiveMacPlaybackEngine e;ProgressiveOptions options;options.preset=preset;options.observerContext=&capture;options.observeEpochPcm=Capture::raw;
    e.prepare(input,options);state(e,State::Ready);check(e.getPlaybackDiagnostics().pipeline.dspDone,"short initial Ready precondition");
    for(double speed:{.75,1.25}){const auto d=e.getPlaybackDiagnostics();auto op=ready(e,request(e,speed),d.renderEpoch,d.consumedFrames);check(op.resumeInputFrame==0&&op.outputStartFrame==0&&!capture.count,"short Ready consumed");}
    const auto op=*e.getStateSnapshot().stoppedSpeed;capture.epoch=op.renderEpoch;check(e.play(),"short play");state(e,State::Ended);
    const auto frames=std::size_t(std::llround(wav.frames()/1.25));check(capture.count==frames&&!capture.errors&&capture.start==0,"short output length/identity");
    std::ifstream raw(refs/("1250000_"+std::string(preset==Preset::Candidate?"candidate":"baseline")+".f32"),std::ios::binary);
    std::vector<float> reference(frames*wav.channels());check(bool(raw.read(reinterpret_cast<char*>(reference.data()),reference.size()*4)),"short reference");check(!std::memcmp(reference.data(),capture.pcm.data(),reference.size()*4),"short independent RAW PCM mismatch");
    std::cout<<"{\"case\":\"short_initial_ready\",\"candidate\":"<<(preset==Preset::Candidate)<<",\"frames\":"<<frames<<",\"PASS\":true}"<<std::endl;
}
static void switchedPause(const std::filesystem::path& input,Preset preset){
    WavStreamReader wav(input);Gate gate;ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.preset=preset;o.allowUnvalidatedFastLocalSeek=true;o.controlTestHooks={&gate,Gate::event};
    e.prepare(input,o);state(e,State::Ready);check(e.play(),"switch play");std::this_thread::sleep_for(std::chrono::milliseconds(40));
    gate.point=ProgressiveControlTestPoint::SwitchStartedOrDone;gate.armed=true;
    const auto target=wav.frames()/2+17;check(e.requestFastLocalSeekToInputFrame(target).accepted,"interactive seek for pause race");wait([&]{return gate.entered.load();});
    check(e.pause(),"pause completed switch");const auto frozen=e.getCurrentPlaybackPosition();
    check(frozen.inputFrame&&*frozen.inputFrame>target&&frozen.sampledOutputFrame==frozen.outputFrame,"new epoch cursor not captured");
    const auto id=request(e,.75);check(e.resume(),"switch deferred resume");gate.release=true;const auto op=ready(e,id);
    check(op.resumeInputFrame==*frozen.inputFrame,"consumed new seek PCM rewound to requested target");state(e,State::Playing);e.stop();
    std::cout<<"{\"case\":\"switched_pause\",\"candidate\":"<<(preset==Preset::Candidate)<<",\"target\":"<<target<<",\"frozen\":"<<*frozen.inputFrame<<",\"PASS\":true}"<<std::endl;
}
static void controls(const std::filesystem::path& input,Preset preset){
    switchedPause(input,preset);
    WavStreamReader wav(input);
    for(const std::string kind:{"burst","reverse","cancel","seek","invalid","stop","route","close","input","failure","eof","tail","playing_pending","seek_speed","stable","double_cancel","limit"}){
        Gate gate;auto e=std::make_unique<ProgressiveMacPlaybackEngine>();ProgressiveOptions o;o.preset=preset;o.controlTestHooks={&gate,Gate::event};if(kind=="failure")o.seekFailureForTest=1;
        e->prepare(input,o);state(*e,State::Ready);
        if(kind=="eof"||kind=="tail")seek(*e,kind=="eof"?wav.frames():wav.frames()-13);
        if(kind=="playing_pending"){check(e->play(),"play");std::this_thread::sleep_for(std::chrono::milliseconds(40));request(*e,.65);check(e->pause(),"pause transition");}
        gate.armed=true;std::uint64_t id=0,seekID=0;
        if(kind=="seek_speed"){auto r=e->requestSeekToInputFrame(wav.frames()*2/3+19);check(r.accepted,"seek before speed");seekID=r.id;wait([&]{return gate.entered.load();});id=request(*e,.75);}
        else{id=request(*e,.75);wait([&]{return gate.entered.load();});}
        // Every public call below executes while the preparation worker is gated.
        check(kind=="playing_pending"?e->resume():e->play(),"deferred start acceptance");check(e->getStateSnapshot().resumePending&&e->getPlaybackState()!=State::Playing,"premature Playing");
        if(kind=="burst")for(auto speed:{.80,.65,1.20})id=request(*e,speed);
        if(kind=="reverse")id=request(*e,1.0);
        if(kind=="cancel"||kind=="stable"||kind=="double_cancel")check(e->pause(),"cancel resume");
        if(kind=="double_cancel"){id=request(*e,1.25);check(e->play()&&e->pause(),"second cancellation");}
        if(kind=="limit"){for(unsigned i=1;i<4096;++i)id=request(*e,(i%161+40)/100.);auto r=e->setSpeed(.80);check(r.result==Phase39RequestResult::LimitReached&&e->getStateSnapshot().stoppedSpeed->id==id,"limit replaced valid operation");}
        if(kind=="seek")check(e->requestSeekToInputFrame(wav.frames()*2/3+19).accepted,"seek during preparation");
        if(kind=="invalid"){bool invalid=false;try{e->setSpeed(.399);}catch(const std::invalid_argument&){invalid=true;}check(invalid,"invalid accepted");auto r=e->setSpeed(.80,UINT64_MAX);check(r.result==Phase39RequestResult::Stopped,"stale accepted");check(e->getStateSnapshot().stoppedSpeed->id==id,"invalid replaced valid");}
        if(kind=="route"){e->simulateDeviceChangeForTest();state(*e,State::Stopped);}
        gate.release=true;
        if(kind=="stop"||kind=="input"){e->stop();if(kind=="input"){e->prepare(input,o);state(*e,State::Ready);}}
        else if(kind=="close")e.reset();
        else if(kind=="failure"){wait([&]{return e->getStateSnapshot().stoppedSpeed->state==StoppedSpeedState::Failed;});check(e->getPlaybackState()==State::Ready&&!e->getStateSnapshot().resumePending&&!e->play(),"failure auto resumed");}
        else if(kind!="route"){
            auto op=ready(*e,id);if(kind=="seek"||kind=="seek_speed")check(op.resumeInputFrame==wav.frames()*2/3+19,"seek target overwritten");
            if(kind=="seek_speed")check(e->getSeekSnapshot().latest.id==seekID&&e->getSeekSnapshot().latest.state==progressive::SeekState::Completed,"real seek history lost");
            if(kind=="burst")check(op.speedMicros==1200000,"Latest-Wins failed");if(kind=="reverse")check(op.speedMicros==1000000,"A-B-A failed");
            if(kind=="cancel"||kind=="stable"||kind=="double_cancel"){
                wait([&]{return !e->getPlaybackDiagnostics().retiringPipeline;});
                const auto before=e->getPlaybackDiagnostics();const auto fds=proc_pidinfo(getpid(),PROC_PIDLISTFDS,0,nullptr,0);
                std::this_thread::sleep_for(std::chrono::milliseconds(kind=="stable"?300:20));
                const auto after=e->getPlaybackDiagnostics();check(e->getPlaybackState()==State::Ready&&!e->getStateSnapshot().resumePending,"cancel auto resumed");
                check(after.renderEpoch==before.renderEpoch&&after.archivedEpochCount==before.archivedEpochCount&&after.consumedFrames==before.consumedFrames,"ready reconstruction loop");
                check(proc_pidinfo(getpid(),PROC_PIDLISTFDS,0,nullptr,0)==fds,"ready FD growth");
                std::cout<<"{\"case\":\"idle_resources\",\"candidate\":"<<(preset==Preset::Candidate)<<",\"cpu_delta_s\":"<<after.processCpuS-before.processCpuS<<",\"rss_delta\":"<<std::int64_t(after.rssBytes)-std::int64_t(before.rssBytes)<<",\"fd_bytes\":"<<fds<<",\"PASS\":true}"<<std::endl;
            }
            else if(kind=="eof")wait([&]{return e->getPlaybackState()==State::Ended;});else state(*e,State::Playing);
        }
        if(e){if(kind=="stop"||kind=="route"||kind=="input"){std::this_thread::sleep_for(std::chrono::milliseconds(20));check(e->getPlaybackState()==(kind=="input"?State::Ready:State::Stopped),"stale completion resumed");}e->stop();check(e->getPlaybackDiagnostics().pipeline.finalDataAvailable,"active worker not joined");for(const auto& old:e->closedEpochs())check(old.pipeline.finalDataAvailable,"prepared/retired worker not joined");}
        std::cout<<"{\"case\":\""<<kind<<"\",\"candidate\":"<<(preset==Preset::Candidate)<<",\"PASS\":true}"<<std::endl;
    }
}
int main(int argc,char** argv){if(argc!=5){std::cerr<<"input reference-dir candidate|baseline matrix|representative|controls\n";return 1;}int result=1;std::thread owner([&]{try{const auto preset=std::string(argv[3])=="candidate"?Preset::Candidate:Preset::Baseline;if(std::string(argv[4])=="controls")controls(argv[1],preset);else if(std::string(argv[4])=="short")shortReady(argv[1],argv[2],preset);else matrix(argv[1],argv[2],preset,std::string(argv[4])=="matrix");result=0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});owner.join();return result;}
