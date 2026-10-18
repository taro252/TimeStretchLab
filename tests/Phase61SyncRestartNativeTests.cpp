// Reuse the existing allocation probes, bounded PCM/mix audit and serial-queue
// helpers. This executable runs real SourceNode callbacks; barriers are normal
// worker hooks only. The helper thread only releases hooks, never calls APIs.
#define main phase61ExistingInteractiveMain
#include "Phase61InteractiveNativeTests.cpp"
#undef main
#include <condition_variable>
#include <mutex>
#include <set>

using Life=ts::prototype::phase58::LifecycleTestPoint;
struct SyncHooks {
    std::mutex mutex;std::condition_variable changed;
    std::optional<ProgressiveControlTestPoint> blockedControl;
    bool entered=false,released=false,timeout=false;
    std::uint64_t lifeSession=0;unsigned lifeStage=0,lifePermit=0,workerExits=0;bool joining=false;
    unsigned sequence=0,cleanupWait=0,cleanupDone=0,restartLaunch=0,acquires=0;
    static void control(void* ctx,ProgressiveControlTestPoint point)noexcept{
        auto& x=*static_cast<SyncHooks*>(ctx);std::unique_lock lock(x.mutex);const auto seq=++x.sequence;
        switch(point){
            case ProgressiveControlTestPoint::SeekCleanupWait:x.cleanupWait=seq;break;
            case ProgressiveControlTestPoint::SeekCleanupComplete:x.cleanupDone=seq;break;
            case ProgressiveControlTestPoint::RestartLaunch:x.restartLaunch=seq;break;
            case ProgressiveControlTestPoint::AcquiringResources:++x.acquires;break;
            default:break;
        }
        if(x.blockedControl==point&&!x.entered){x.entered=true;x.changed.notify_all();
            if(!x.changed.wait_for(lock,std::chrono::seconds(15),[&]{return x.released;}))x.timeout=true;
        }x.changed.notify_all();
    }
    static void lifecycle(void* ctx,Life point,std::uint64_t session)noexcept{
        auto& x=*static_cast<SyncHooks*>(ctx);std::unique_lock lock(x.mutex);
        if(!x.lifeSession||session!=x.lifeSession)return;unsigned needed=0;
        switch(point){
            case Life::BeforeJoin:x.lifeStage=1;needed=1;break;
            case Life::Joining:x.joining=true;break;
            case Life::WorkerExit:++x.workerExits;needed=2;break;
            case Life::JoinedBeforeFinalize:x.lifeStage=3;needed=3;break;
            case Life::BeforeFinalPublish:x.lifeStage=4;needed=4;break;
        }x.changed.notify_all();
        if(needed&&!x.changed.wait_for(lock,std::chrono::seconds(15),[&]{return x.lifePermit>=needed;}))x.timeout=true;
    }
    void await(const std::function<bool()>& predicate){std::unique_lock lock(mutex);
        require(changed.wait_for(lock,std::chrono::seconds(12),predicate),"normal-thread barrier deadline");}
    void release(){std::lock_guard lock(mutex);released=true;lifePermit=10;changed.notify_all();}
};
struct ReleaseHooks {SyncHooks& hooks;~ReleaseHooks(){hooks.release();}};
template<class Predicate>void poll(Predicate predicate,const char* why){const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(20);
    while(!predicate()){require(std::chrono::steady_clock::now()<until,why);std::this_thread::sleep_for(std::chrono::microseconds(100));}}
ProgressiveOptions optionsFor(SyncHooks& hooks,OutputAudit& audit,Preset preset){
    ProgressiveOptions o;o.preset=preset;o.initialSpeed=.5;o.allowUnvalidatedFastLocalSeek=true;
    o.controlTestHooks={&hooks,SyncHooks::control};o.pipelineLifecycleTestHooks={&hooks,SyncHooks::lifecycle,0};
    o.observerContext=&audit;o.observeEpochPcm=OutputAudit::source;o.observeOutputPcm=OutputAudit::output;
    o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    return o;
}
void lifetime(const ProgressiveMacPlaybackEngine& e){const auto check=[](const auto& d){const auto& m=d.scheduling;
    require(d.finalDataAvailable&&!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"unjoined / Workgroup retirement");};
    const auto d=e.getPlaybackDiagnostics();check(d.pipeline);for(const auto& item:e.closedEpochs())check(item.pipeline);
    require(!d.workerNewCalls&&!d.workgroupErrors&&d.callbackCppNew&&!*d.callbackCppNew,"worker/callback allocations or group errors");
    require(!phase61_heap_allocations()&&!phase61_heap_frees(),"callback heap allocation/free");
}
struct PhysicalRate {
    AudioDeviceID device=0;double original=0,target=0;bool changed=false;
    AudioObjectPropertyAddress property()const{return {kAudioDevicePropertyNominalSampleRate,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};}
    double rate()const{double value=0;UInt32 bytes=sizeof(value);auto p=property();require(AudioObjectGetPropertyData(device,&p,0,nullptr,&bytes,&value)==noErr,"physical rate query");return value;}
    void change(AudioDeviceID id){device=id;original=rate();target=std::abs(original-48000)<1?44100:48000;auto p=property();Boolean writable=false;
        require(AudioObjectIsPropertySettable(device,&p,&writable)==noErr&&writable,"physical rate not settable");
        require(AudioObjectSetPropertyData(device,&p,0,nullptr,sizeof(target),&target)==noErr,"physical rate change");changed=true;
        poll([&]{return std::abs(rate()-target)<1;},"physical rate did not change");}
    void restore(){if(!changed)return;auto p=property();require(AudioObjectSetPropertyData(device,&p,0,nullptr,sizeof(original),&original)==noErr,"physical rate restore");
        poll([&]{return std::abs(rate()-original)<1;},"physical rate restore query");changed=false;std::cerr<<"restored physical rate "<<original<<'\n';}
    ~PhysicalRate(){if(changed)try{restore();}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}}
};
void retireDiagnostics(const std::filesystem::path& input,std::ostream& rows,Preset preset,std::uint32_t rate,std::size_t ch,std::size_t frames){
    SyncHooks hooks;OutputAudit audit(ch,rate*24ULL);ProgressiveMacPlaybackEngine e;
    ReleaseHooks release{hooks};phase61_heap_reset();e.prepare(input,optionsFor(hooks,audit,preset));wait(e,State::Ready);e.play();firstPcm(e);
    const auto before=e.getStateSnapshot();{std::lock_guard lock(hooks.mutex);hooks.lifeSession=before.session;}
    auto request=e.requestInteractiveSeekToInputFrame(frames/2+17,before.inputGeneration,before.renderEpoch,before.session);require(request.accepted,"retire seek admission");
    unsigned samples=0;double maxDiagnosticMs=0;
    for(unsigned stage:{1u,2u,3u,4u}){
        hooks.await([&]{return stage==2?hooks.joining&&hooks.workerExits>0:hooks.lifeStage>=stage;});
        const auto start=std::chrono::steady_clock::now();
        for(unsigned i=0;i<128;++i){const auto began=std::chrono::steady_clock::now();const auto d=e.getPlaybackDiagnostics();
            maxDiagnosticMs=std::max(maxDiagnosticMs,std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-began).count());
            require(d.retiringPipeline&&d.retiringPipeline->session==before.session&&!d.retiringPipeline->finalDataAvailable,"retiring session / early final publication");
            require(d.pipeline.session!=before.session&&d.inputGeneration==before.inputGeneration&&d.renderEpoch>before.renderEpoch,"old/current identity mixed");
            require(d.archivedEpochCount==0&&e.closedEpochs().empty(),"archived before finalize");
            require(d.missingFrames==d.pipeline.missingFrames+d.retiringPipeline->missingFrames,"live total lost/doubled");
            require(d.workerDeadlineMisses==d.pipeline.scheduling.deadlineMisses+d.retiringPipeline->scheduling.deadlineMisses,"worker total lost/doubled");++samples;
        }require(std::chrono::steady_clock::now()-start<std::chrono::seconds(2),"diagnostics blocked on old join");
        {std::lock_guard lock(hooks.mutex);hooks.lifePermit=stage;hooks.changed.notify_all();}
    }
    poll([&]{return e.getPlaybackDiagnostics().archivedEpochCount==1;},"old archive missing");
    const auto d=e.getPlaybackDiagnostics();const auto history=e.closedEpochs();require(history.size()==1&&history[0].pipeline.finalDataAvailable,"final audit unavailable");
    require(history[0].pipeline.session==before.session&&d.missingFrames==d.pipeline.missingFrames+history[0].pipeline.missingFrames,"final totals lost/doubled");
    require(!d.retiringPipeline&&!hooks.timeout,"retiring lease or barrier leak");e.stop();lifetime(e);
    require(!audit.errors&&!audit.raw.errors,"PCM order/mix altered");
    rows<<"{\"case\":\"retiring_diagnostics\",\"candidate\":"<<(preset==Preset::Candidate?"true":"false")<<",\"snapshots\":"<<samples<<",\"max_diagnostic_ms\":"<<maxDiagnosticMs<<",\"final_available\":true,\"mixed_frames\":"<<audit.mixedFrames<<",\"worker_deadlines\":"<<e.getPlaybackDiagnostics().workerDeadlineMisses<<"}\n";rows.flush();
}
void restartRoute(const std::filesystem::path& input,std::ostream& rows,Preset preset,ProgressiveControlTestPoint point,const char* name,std::uint32_t rate,std::size_t ch,std::size_t frames,bool physical=false){
    PhysicalRate route;
    SyncHooks hooks;hooks.blockedControl=point;OutputAudit audit(ch,rate*24ULL);ProgressiveMacPlaybackEngine e;ReleaseHooks release{hooks};
    phase61_heap_reset();e.prepare(input,optionsFor(hooks,audit,preset));wait(e,State::Ready);e.play();firstPcm(e);
    require(e.setSpeed(.75).result==ts::prototype::Phase39RequestResult::Accepted,"latest speed");const auto old=e.getStateSnapshot();
    require(e.requestInteractiveSeekToInputFrame(frames/2+17,old.inputGeneration,old.renderEpoch,old.session).accepted,"restart seek");
    hooks.await([&]{return hooks.entered;});if(physical)route.change(e.getNativeDiagnostics().deviceId);else e.simulateDeviceChangeForTest();wait(e,State::Stopped);
    audit.nextClock=0; // SourceNode restarts its independent callback coordinate.
    require(e.getStateSnapshot().reason==StopReason::RouteChanged,"route reason");
    {std::lock_guard lock(hooks.mutex);require(hooks.acquires==1&&!hooks.cleanupDone&&!hooks.restartLaunch,"retirement already completed / auto restart");}
    bool waitObserved=false,noEarlyAcquisition=false;
    std::jthread helper([&]{
        std::unique_lock lock(hooks.mutex);
        waitObserved=hooks.changed.wait_for(lock,std::chrono::seconds(10),[&]{return hooks.cleanupWait>0;});
        noEarlyAcquisition=hooks.acquires==1&&!hooks.restartLaunch&&!hooks.cleanupDone;
        hooks.released=true;hooks.changed.notify_all();
    });
    require(e.play(),"explicit route restart acceptance");helper.join();
    require(waitObserved&&noEarlyAcquisition&&!hooks.timeout,"play bypassed pending seek cleanup");
    wait(e,State::Playing);firstPcm(e);const auto fresh=e.getStateSnapshot();
    if(physical)require(std::abs(e.getNativeDiagnostics().deviceRate-route.target)<1,"restart reused old device format");
    require(fresh.inputGeneration!=old.inputGeneration&&fresh.session!=old.session&&fresh.renderEpoch>old.renderEpoch,"restart identity reused");
    require(fresh.requestedSpeed==.75&&fresh.appliedTargetSpeed==.75,"latest speed lost");
    {std::lock_guard lock(hooks.mutex);require(hooks.cleanupDone>hooks.cleanupWait&&hooks.restartLaunch>hooks.cleanupDone&&hooks.acquires==2,"resource acquisition preceded cleanup");}
    require(e.getPlaybackDiagnostics().archivedEpochCount==0,"old result contaminated new input");
    for(const auto& op:e.seekHistory())require(progressive::terminal(op.state),"old seek revived");
    e.stop();lifetime(e);require(!audit.errors&&!audit.raw.errors,"restart PCM/mix order");
    // A later distinct owner must still acquire its own reservation successfully.
    {ProgressiveMacPlaybackEngine other;auto o=optionsFor(hooks,audit,preset);other.prepare(input,o);wait(other,State::Ready);other.stop();lifetime(other);}
    route.restore();rows<<"{\"case\":\""<<name<<"\",\"physical\":"<<(physical?"true":"false")<<",\"device_rate_before\":"<<route.original<<",\"device_rate_after\":"<<route.target<<",\"restored\":"<<(physical?"true":"null")<<",\"candidate\":"<<(preset==Preset::Candidate?"true":"false")<<",\"wait_observed\":true,\"cleanup_before_launch\":true,\"new_generation\":"<<fresh.inputGeneration<<",\"old_generation\":"<<old.inputGeneration<<",\"latest_speed\":0.75,\"worker_deadlines\":"<<e.getPlaybackDiagnostics().workerDeadlineMisses<<"}\n";rows.flush();
}
void archiveLimit(const std::filesystem::path& input,std::ostream& rows,Preset preset,std::uint32_t rate,std::size_t ch,std::size_t frames){
    SyncHooks hooks;hooks.blockedControl=ProgressiveControlTestPoint::SeekPreparationStarted;
    OutputAudit audit(ch,rate*24ULL);ProgressiveMacPlaybackEngine e;ReleaseHooks release{hooks};phase61_heap_reset();
    e.prepare(input,optionsFor(hooks,audit,preset));wait(e,State::Ready);const auto initial=e.getStateSnapshot();
    const auto cancelled=e.requestFastLocalSeekToInputFrame(frames/2);require(cancelled.accepted,"cancel preparation request");
    hooks.await([&]{return hooks.entered;});auto latest=e.requestFastLocalSeekToInputFrame(frames/3);require(latest.accepted,"replacement");hooks.release();waitSeek(e,latest.id);
    poll([&]{return e.getPlaybackDiagnostics().archivedEpochCount==2;},"cancelled preparation audit lost");
    require(e.getPlaybackDiagnostics().archivedPreparedEpochCount==1,"unpresented preparation missing");
    auto early=e.closedEpochs();require(early.size()==2&&early[0].preparedOnly&&early[0].pipeline.finalDataAvailable,"cancelled audit incomplete");
    for(unsigned i=0;i<20;++i){auto s=e.getStateSnapshot();auto r=e.requestInteractiveSeekToInputFrame(frames*(i%3+1)/5+17,s.inputGeneration,s.renderEpoch,s.session);require(r.accepted,"chain seek");waitSeek(e,r.id);
        poll([&]{return e.getPlaybackDiagnostics().archivedEpochCount==i+3;},"chain archive timeout");}
    const auto d=e.getPlaybackDiagnostics();const auto history=e.closedEpochs();std::set<std::uint64_t> sessions;
    for(const auto& h:history){require(h.pipeline.finalDataAvailable&&h.pipeline.inputGeneration==initial.inputGeneration,"archive generation");sessions.insert(h.pipeline.session);}
    require(history.size()==16&&sessions.size()==16&&d.archivedEpochCount==22&&d.archivedPreparedEpochCount==1,"bounded history / lifetime count");
    require(d.pipeline.sourceHashPasses==1&&d.pipeline.sourceSnapshotCreations==1&&d.pipeline.residentLockCalls==1,"input lease recreated");
    e.stop();lifetime(e);rows<<"{\"case\":\"archive_limit\",\"candidate\":"<<(preset==Preset::Candidate?"true":"false")<<",\"retired_total\":22,\"retained\":16,\"cancelled_preparations\":1}\n";rows.flush();
}
void ordinaryRestarts(const std::filesystem::path& input,const std::filesystem::path& output,std::ostream& rows,Preset preset,std::uint32_t rate,std::size_t ch,std::size_t frames){
    SyncHooks hooks;OutputAudit audit(ch,rate*24ULL);ProgressiveMacPlaybackEngine e;phase61_heap_reset();
    e.prepare(input,optionsFor(hooks,audit,preset));wait(e,State::Ready);e.play();firstPcm(e);const auto first=e.getStateSnapshot();
    require(e.setSpeed(.75).result==ts::prototype::Phase39RequestResult::Accepted,"stop latest speed");e.stop();audit.nextClock=0;require(e.play(),"Stop Play");wait(e,State::Playing);firstPcm(e);
    const auto second=e.getStateSnapshot();require(second.inputGeneration!=first.inputGeneration&&second.appliedTargetSpeed==.75,"Stop Play identity/speed");
    const auto r=e.requestFastLocalSeekToInputFrame(frames);require(r.accepted,"EOS seek");waitSeek(e,r.id);wait(e,State::Ended);
    const auto end=e.getStateSnapshot();audit.nextClock=0;require(e.play(),"EOS Play");wait(e,State::Playing);firstPcm(e);
    const auto third=e.getStateSnapshot();require(third.inputGeneration!=end.inputGeneration&&third.appliedTargetSpeed==.75,"EOS Play identity/speed");e.stop();lifetime(e);
    require(!audit.errors&&!audit.raw.errors,"Stop/EOS restart PCM order/mix");
    const auto missing=output/(preset==Preset::Candidate?"lost_candidate.wav":"lost_baseline.wav");std::filesystem::copy_file(input,missing);
    e.prepare(missing,optionsFor(hooks,audit,preset));wait(e,State::Ready);e.stop();std::filesystem::remove(missing);require(e.play(),"missing input acceptance");wait(e,State::Failed);
    require(!e.getPlaybackDiagnostics().error.empty(),"missing input failure reason lost");e.stop();
    rows<<"{\"case\":\"Stop_EOS_Play_and_missing_input\",\"candidate\":"<<(preset==Preset::Candidate?"true":"false")<<",\"passed\":true}\n";rows.flush();
}
int main(int argc,char** argv){if(argc!=3&&(argc!=4||std::string(argv[3])!="--physical"))return 1;const bool physical=argc==4;
    phase61_heap_reset();phase61_heap_begin();void* (*volatile allocate)(std::size_t)=std::malloc;void (*volatile freeProbe)(void*)=std::free;
    void* probe=allocate(37);freeProbe(probe);phase61_heap_end();
    if(!phase61_heap_allocations()||!phase61_heap_frees()){std::cerr<<"heap probe self-test failed\n";return 3;}
    int result=2;std::thread control([&]{try{
    const std::filesystem::path output=argv[2];require(std::filesystem::create_directories(output),"existing evidence directory");
    ts::WavStreamReader info(argv[1]);SmallDeviceBuffer device(true);std::ofstream rows(output/"rows.jsonl");
    for(auto preset:{Preset::Candidate,Preset::Baseline}){
        if(physical){
            for(auto [point,name]:{std::pair{ProgressiveControlTestPoint::SeekPreparationStarted,"physical_route_preparing_immediate_play"},std::pair{ProgressiveControlTestPoint::SwitchStartedOrDone,"physical_route_started_immediate_play"}})
                restartRoute(argv[1],rows,preset,point,name,info.sampleRate(),info.channels(),info.frames(),true);
            continue;
        }
        retireDiagnostics(argv[1],rows,preset,info.sampleRate(),info.channels(),info.frames());
        for(auto [point,name]:{std::pair{ProgressiveControlTestPoint::SeekPreparationStarted,"route_preparing_immediate_play"},std::pair{ProgressiveControlTestPoint::SwitchStartedOrDone,"route_started_immediate_play"},std::pair{ProgressiveControlTestPoint::RetiringOld,"route_retiring_immediate_play"}})
            restartRoute(argv[1],rows,preset,point,name,info.sampleRate(),info.channels(),info.frames());
        archiveLimit(argv[1],rows,preset,info.sampleRate(),info.channels(),info.frames());
        ordinaryRestarts(argv[1],output,rows,preset,info.sampleRate(),info.channels(),info.frames());
    }device.restore();std::cout<<"PASS "<<(physical?4:12)<<" native sync/restart groups: serial control API, gated retirement and explicit play\n";result=0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return result;}
