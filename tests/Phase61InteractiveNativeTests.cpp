// Reuse bounded C++ allocation counters and native wait helpers, not old scores.
#define PHASE61_SANDBOX_APP 1
#include "Phase61NativeTests.cpp"
#include "Phase61CallbackMallocProbe.h"
#include <CoreAudio/CoreAudio.h>

struct Counters {
    std::uint64_t missing=0,callback=0,host=0,sample=0,hal=0,worker=0,news=0,heap=0,frees=0;
    static Counters read(ProgressiveMacPlaybackEngine& e){
        const auto d=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();Counters x;
        x.missing=d.missingFrames;x.callback=n.deadlineMisses;x.host=n.hostMissing+n.hostBackwards+n.hostCadenceErrors;x.sample=n.sampleErrors;x.hal=n.halWindowMisses;x.news=d.callbackCppNew.value_or(0);

#ifdef PHASE61_INTERACTIVE_CONTRACT
        x.worker=d.workerDeadlineMisses;
#else
        x.worker=d.pipeline.scheduling.deadlineMisses;for(const auto& p:e.closedEpochs())x.worker+=p.pipeline.scheduling.deadlineMisses;
#endif
        x.heap=phase61_heap_allocations();x.frees=phase61_heap_frees();return x;
    }
};
void counters(std::ostream& f,const char* prefix,const Counters& a,const Counters& b){
    f<<",\""<<prefix<<"missing\":"<<a.missing-b.missing<<",\""<<prefix<<"callback_deadlines\":"<<a.callback-b.callback<<",\""<<prefix<<"host_errors\":"<<a.host-b.host<<",\""<<prefix<<"sample_errors\":"<<a.sample-b.sample<<",\""<<prefix<<"hal_errors\":"<<a.hal-b.hal<<",\""<<prefix<<"worker_deadlines\":"<<a.worker-b.worker<<",\""<<prefix<<"callback_new\":"<<a.news-b.news<<",\""<<prefix<<"heap_calls\":"<<a.heap-b.heap<<",\""<<prefix<<"heap_frees\":"<<a.frees-b.frees;
}
int performance(const std::filesystem::path& input,const std::filesystem::path& output,bool early){
    require(std::filesystem::create_directories(output),"existing evidence directory");
    ts::WavStreamReader info(input);const auto rate=info.sampleRate();require(info.frames()==300ULL*rate,"300s required");
    std::ofstream f(output/"rows.jsonl");std::size_t count=0;
    for(auto speed:{400000u,500000u,1000000u,2000000u})for(auto preset:{Preset::Candidate,Preset::Baseline})for(unsigned repeat=0;repeat<3;++repeat){
        ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.allowUnvalidatedFastLocalSeek=true;o.initialSpeed=speed/1e6;o.preset=preset;o.callbackRecordLimit=8192;
        o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
        phase61_heap_reset();e.prepare(input,o);wait(e,State::Ready);
        while(!early&&!e.getPlaybackDiagnostics().pipeline.analysisDone)std::this_thread::sleep_for(std::chrono::milliseconds(2));
        const auto initial=e.getPlaybackDiagnostics();require(e.play(),"play");firstPcm(e);
        const std::vector<std::uint64_t> positions=early?std::vector<std::uint64_t>{270ULL*rate}:std::vector<std::uint64_t>{30ULL*rate,150ULL*rate,270ULL*rate,285ULL*rate,83ULL*rate+12345};
        for(auto frame:positions){
            const auto before=Counters::read(e);const auto state=e.getStateSnapshot();
            auto receipt=e.requestFastLocalSeekToInputFrame(frame,state.inputGeneration,state.renderEpoch);require(receipt.accepted,"admission");auto op=waitSeek(e,receipt.id);
            const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(10);
            while(!op.firstCallbackNs){for(const auto& item:e.seekHistory())if(item.id==receipt.id)op=item;require(std::chrono::steady_clock::now()<limit,"new PCM timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
            bool retired=false;while(!retired){for(const auto& old:e.closedEpochs())retired|=old.renderEpoch==op.sourceRenderEpoch;
                require(std::chrono::steady_clock::now()<limit,"old retirement timeout");if(!retired)std::this_thread::sleep_for(std::chrono::microseconds(100));}
            for(const auto& item:e.seekHistory())if(item.id==receipt.id)op=item;
            const auto after=Counters::read(e);const auto d=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();
            require(d.pipeline.sourceHashPasses==1&&d.pipeline.sourceSnapshotCreations==1&&d.pipeline.residentLockCalls==1,"lease reuse");
            f<<"{\"speed\":"<<speed<<",\"candidate\":"<<(preset==Preset::Candidate?"true":"false")<<",\"repeat\":"<<repeat<<",\"input\":"<<frame<<",\"rate\":"<<rate<<",\"channels\":"<<info.channels()<<",\"output\":"<<op.outputStartFrame<<",\"epoch\":"<<op.renderEpoch<<",\"accepted_ns\":"<<op.acceptedNs<<",\"preparing_ns\":"<<op.preparingNs<<",\"fifo_ready_ns\":"<<op.readyNs<<",\"switch_ns\":"<<op.switchedNs<<",\"first_pcm_ns\":"<<op.firstCallbackNs<<",\"hal_estimate_ns\":"<<op.estimatedPresentationNs
             <<",\"ready_ms\":"<<double(op.readyNs-op.acceptedNs)/1e6<<",\"first_pcm_ms\":"<<double(op.firstCallbackNs-op.acceptedNs)/1e6<<",\"analysis_complete_at_play\":"<<(initial.pipeline.analysisDone?"true":"false")<<",\"peak_rss\":"<<d.peakRssBytes<<",\"device\":"<<n.deviceId<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames;
#ifdef PHASE61_INTERACTIVE_CONTRACT
            f<<",\"analysis_ready_ns\":"<<op.analysisReadyNs<<",\"switch_ready_ns\":"<<op.switchReadyNs<<",\"transition_begin_ns\":"<<op.transitionBeginNs<<",\"transition_end_ns\":"<<op.transitionEndNs<<",\"old_fifo_at_switch\":"<<op.oldFifoAtSwitchFrames<<",\"discarded_for_seek\":"<<op.discardedForSeekFrames<<",\"transition_frames\":"<<op.transitionFrames;
#endif
            counters(f,"delta_",after,before);counters(f,"lifetime_",after,{});f<<"}\n";f.flush();++count;
        }
        e.stop();const auto check=[](const auto& p){const auto& m=p.scheduling;require(!m.active&&m.joins==m.leaves&&m.leaves==m.restores&&!m.policyErrors&&!m.restoreErrors&&!m.joinErrors,"Workgroup lifetime");};check(e.getPlaybackDiagnostics().pipeline);for(const auto& p:e.closedEpochs())check(p.pipeline);
        std::cout<<speed<<" "<<int(preset)<<" repeat="<<repeat<<" cases="<<count<<std::endl;
    }return 0;
}
#ifdef PHASE61_INTERACTIVE_CONTRACT
struct OutputAudit {
    Capture raw;std::size_t channels;
    std::atomic<std::size_t> errors{0},mixedFrames{0},outputFrames{0};
    std::atomic<bool> switchObserved{false};
    std::uint64_t nextClock=0;
    // Phase62 metadata makes 4096 records exceed the default control-thread
    // stack. Allocate once before playback; the callback only assigns slots.
    std::vector<ProgressiveOutputSpan> spans;std::size_t count=0;
    OutputAudit(std::size_t ch,std::size_t frames):raw(ch,frames),channels(ch),spans(4096){}
    static void source(void* ctx,const float*const* p,std::size_t n,std::size_t at,std::uint64_t gen,std::uint64_t epoch,std::uint64_t session)noexcept{
        Capture::observe(&static_cast<OutputAudit*>(ctx)->raw,p,n,at,gen,epoch,session);
    }
    static void output(void* ctx,const float*const* p,const ProgressiveOutputSpan& span)noexcept{
        auto& a=*static_cast<OutputAudit*>(ctx);const Slot* fresh=nullptr;const Slot* old=nullptr;
        for(const auto& slot:a.raw.slots){if(slot.epoch==span.newEpoch)fresh=&slot;if(span.oldEpoch&&slot.epoch==span.oldEpoch)old=&slot;}
        if(span.callbackFrame!=a.nextClock)++a.errors;a.nextClock=span.callbackFrame+span.frames;
        if(a.count<a.spans.size())a.spans[a.count++]=span;else ++a.errors;
        auto value=[&](const Slot* s,std::size_t offset,std::size_t c)noexcept{
            if(!s||offset<s->start||offset>=s->start+s->frames){++a.errors;return 0.f;}return s->pcm[(offset-s->start)*a.channels+c];
        };
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<a.channels;++c){
            float expected=i<span.newReceivedFrames?value(fresh,span.newOutputOffset+i,c):0.f;
            if(i<span.mixedFrames){const float oldPcm=i<span.oldReceivedFrames?value(old,span.oldOutputOffset+i,c):0.f;
                const float gain=float(span.transitionOffset+i+1)/float(span.transitionLength);expected=oldPcm*(1.f-gain)+expected*gain;}
            if(p[c][i]!=expected||!std::isfinite(p[c][i]))++a.errors;
        }
        a.mixedFrames+=span.mixedFrames;a.outputFrames+=span.frames;if(span.mixedFrames)a.switchObserved=true;
    }
};
void operations(std::ostream& f,const std::vector<progressive::SeekOperation>& ops){
    f<<'[';bool comma=false;for(const auto& o:ops){if(comma)f<<',';comma=true;
        f<<"{\"id\":"<<o.id<<",\"state\":\""<<progressive::name(o.state)<<"\",\"stage\":\""<<progressive::name(o.stage)<<"\",\"reason\":"<<ts::prototype::phase58::jsonString(o.reason)<<",\"input\":"<<o.requestedInputFrame<<",\"output\":"<<o.outputStartFrame<<",\"epoch\":"<<o.renderEpoch<<",\"session\":"<<o.session<<",\"accepted_ns\":"<<o.acceptedNs<<",\"preparing_ns\":"<<o.preparingNs<<",\"analysis_ready_ns\":"<<o.analysisReadyNs<<",\"fifo_ready_ns\":"<<o.readyNs<<",\"switch_ready_ns\":"<<o.switchReadyNs<<",\"transition_begin_ns\":"<<o.transitionBeginNs<<",\"transition_end_ns\":"<<o.transitionEndNs<<",\"first_pcm_ns\":"<<o.firstCallbackNs<<",\"hal_estimate_ns\":"<<o.estimatedPresentationNs<<",\"old_fifo_at_switch\":"<<o.oldFifoAtSwitchFrames<<",\"discarded_for_seek\":"<<o.discardedForSeekFrames<<",\"transition_frames\":"<<o.transitionFrames<<",\"replans\":"<<o.replans<<",\"speed\":"<<o.speedMicros<<",\"generation\":"<<o.inputGeneration<<",\"source_epoch\":"<<o.sourceRenderEpoch<<",\"waited_analysis\":"<<(o.waitedForAnalysis?"true":"false")<<'}';}f<<"]\n";
}
struct SmallDeviceBuffer {
    AudioDeviceID device=0;UInt32 original=0;bool changed=false;
    explicit SmallDeviceBuffer(bool enabled){if(!enabled)return;UInt32 n=sizeof(device);AudioObjectPropertyAddress p{kAudioHardwarePropertyDefaultOutputDevice,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        require(AudioObjectGetPropertyData(kAudioObjectSystemObject,&p,0,nullptr,&n,&device)==noErr,"default device");p={kAudioDevicePropertyBufferFrameSize,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};n=sizeof(original);
        require(AudioObjectGetPropertyData(device,&p,0,nullptr,&n,&original)==noErr,"buffer query");UInt32 value=64;require(AudioObjectSetPropertyData(device,&p,0,nullptr,sizeof(value),&value)==noErr,"64 frame buffer unsupported");changed=true;
        UInt32 got=0;n=sizeof(got);require(AudioObjectGetPropertyData(device,&p,0,nullptr,&n,&got)==noErr&&got==64,"buffer did not become 64");
    }
    void restore(){if(!changed)return;AudioObjectPropertyAddress p{kAudioDevicePropertyBufferFrameSize,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        const auto result=AudioObjectSetPropertyData(device,&p,0,nullptr,sizeof(original),&original);UInt32 got=0,n=sizeof(got);
        require(result==noErr&&AudioObjectGetPropertyData(device,&p,0,nullptr,&n,&got)==noErr&&got==original,"device buffer restore failed");changed=false;std::cerr<<"restored device buffer "<<got<<" status="<<result<<'\n';
    }
    ~SmallDeviceBuffer(){if(changed)try{restore();}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}}
};
int controls(const std::filesystem::path& input,const std::filesystem::path& output,bool small=false){
    SmallDeviceBuffer buffer(small);
    require(std::filesystem::create_directories(output),"existing evidence");ts::WavStreamReader info(input);const auto rate=info.sampleRate();const auto frames=info.frames();require(frames<=rate*20,"short fixture required");
    std::ofstream rows(output/"sessions.jsonl");unsigned failures=0;
    for(auto preset:{Preset::Candidate,Preset::Baseline})for(const std::string kind:{"gate","ready","playing","paused","pause_prepare","burst","chain","speed_prepare","speed_after","replace_ready","speed_same_ready","stop_prepare","stop_ready","route_prepare","route_ready","promotion_failure","publication_failure","input","eof_playing","eof_paused","destroy_ready","pause_started","stop_started","burst_started","speed_started","route_started","destroy_started"}){
        auto folder=output/(std::string(preset==Preset::Candidate?"candidate_":"baseline_")+kind);std::filesystem::create_directory(folder);
        auto source=input;if(kind=="input"){source=folder/"source.wav";std::filesystem::copy_file(input,source);}
        OutputAudit audit(info.channels(),rate*24ULL);bool functional=true;std::string error;
        std::unique_ptr<ProgressiveMacPlaybackEngine> engine=std::make_unique<ProgressiveMacPlaybackEngine>();auto& e=*engine;
        ProgressiveOptions o;o.preset=preset;o.initialSpeed=.5;o.callbackRecordLimit=8192;o.allowUnvalidatedFastLocalSeek=kind!="gate";
        o.observerContext=&audit;o.observeEpochPcm=OutputAudit::source;o.observeOutputPcm=OutputAudit::output;
        o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
        if(kind=="promotion_failure")o.seekFailureForTest=1;if(kind=="publication_failure")o.seekFailureForTest=2;
        phase61_heap_reset();
        ProgressiveDiagnostics d;ProgressiveNativeDiagnostics native;std::vector<ProgressiveClosedEpoch> closed;std::vector<progressive::SeekOperation> history;
        try{
            e.prepare(source,o);wait(e,State::Ready);const auto initial=e.getStateSnapshot();
            require(!e.capabilities().seek&&e.seekAvailability().interactiveImplemented&&!e.seekAvailability().publicSeekApproved,"approval conflated");
            if(kind=="gate"){require(!e.requestFastLocalSeekToInputFrame(0).accepted&&!e.seekAvailability().interactiveAllowed,"missing opt in accepted");e.stop();}
            else{
                require(e.seekAvailability().interactiveAllowed,"explicit opt in rejected");
                require(!e.requestInteractiveSeekToInputFrame(0,initial.inputGeneration,initial.renderEpoch,initial.session+1).accepted,"stale session accepted");
                require(!e.requestInteractiveSeekToInputFrame(0,0,0,0).accepted,"unbound request accepted");
                require(!e.requestFastLocalSeekToInputFrame(0,0,0,999).accepted,"invalid preroll accepted");
                for(double bad:{-1.,double(INFINITY),double(NAN),double(frames)/rate+1e-8})require(!e.requestFastLocalSeekToInputSeconds(bad).accepted,"invalid seconds accepted");
                if(kind!="ready"&&kind!="eof_paused"){require(e.play(),"play");firstPcm(e);}
                if(kind=="paused")require(e.pause(),"pause");
                const auto target=kind=="eof_playing"||kind=="eof_paused"?frames:frames*3/5+17;
                auto r=e.requestInteractiveSeekToInputFrame(target,initial.inputGeneration,initial.renderEpoch,initial.session);require(r.accepted,"seek rejected");
                if(kind=="burst")for(unsigned i=0;i<64;++i){r=e.requestFastLocalSeekToInputFrame(target+i%17);require(r.accepted,"burst");}
                if(kind=="pause_prepare")require(e.pause(),"prepare pause");
                if(kind=="speed_prepare")require(e.setSpeed(.4).result==ts::prototype::Phase39RequestResult::Accepted,"prepare speed");
                const auto ready=[&]{const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(10);for(;;){auto s=e.getSeekSnapshot();if(s.latest.state==Seek::Ready||progressive::terminal(s.latest.state))return;require(std::chrono::steady_clock::now()<until,"Ready timeout");std::this_thread::sleep_for(std::chrono::microseconds(100));}};
                if(kind=="replace_ready"||kind=="speed_same_ready"||kind=="stop_ready"||kind=="route_ready"||kind=="destroy_ready")ready();
                if(kind=="speed_same_ready")require(e.setSpeed(.5).result==ts::prototype::Phase39RequestResult::Accepted,"same speed at SwitchReady");
                const bool startedCase=kind.ends_with("_started");
                if(startedCase){const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(10);while(!audit.switchObserved.load()){require(std::chrono::steady_clock::now()<until,"transition begin timeout");std::this_thread::sleep_for(std::chrono::microseconds(50));}}
                if(kind=="pause_started")require(e.pause(),"pause during transition");
                if(kind=="burst_started")for(unsigned i=0;i<64;++i){r=e.requestFastLocalSeekToInputFrame(target+i%17);require(r.accepted,"started burst");}
                if(kind=="speed_started"){const auto s=e.getStateSnapshot();require(e.setSpeed(.75,s.session,s.inputGeneration,s.renderEpoch).result==ts::prototype::Phase39RequestResult::Accepted,"started speed");}
                if(kind=="stop_prepare"||kind=="stop_ready"||kind=="stop_started")e.stop();
                else if(kind=="route_prepare"||kind=="route_ready"||kind=="route_started"){e.simulateDeviceChangeForTest();wait(e,State::Stopped);require(e.getStateSnapshot().reason==StopReason::RouteChanged,"route stop");}
                else if(kind=="promotion_failure"||kind=="publication_failure"){
                    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(10);
                    while(!progressive::terminal(e.getSeekSnapshot().latest.state)){require(std::chrono::steady_clock::now()<until,"failure timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
                    require(e.getSeekSnapshot().latest.state==Seek::Failed&&e.getPlaybackState()==State::Playing&&e.getStateSnapshot().renderEpoch==initial.renderEpoch&&!audit.mixedFrames,"failed promotion changed old playback");e.stop();
                }
                else if(kind=="input"){std::filesystem::remove(source);wait(e,State::Failed);}
                else if(kind=="destroy_ready"||kind=="destroy_started"){history=e.seekHistory();engine.reset();
                    const auto outputBefore=audit.outputFrames.load();ProgressiveMacPlaybackEngine replacement;replacement.prepare(source,o);wait(replacement,State::Ready);replacement.stop();require(audit.outputFrames.load()==outputBefore,"output revived after destruction");}
                else{
                    if(kind=="replace_ready"){r=e.requestFastLocalSeekToInputFrame(frames*3/4+31);require(r.accepted,"replace");}
                    auto complete=waitSeek(e,r.id);require(complete.state==Seek::Completed,"completion");
                    if(kind=="speed_prepare")require(complete.speedMicros==400000,"speed was lost");
                    if(kind=="chain")for(unsigned i=0;i<3;++i){const auto s=e.getStateSnapshot();auto again=e.requestInteractiveSeekToInputFrame(frames*(i+1)/5,s.inputGeneration,s.renderEpoch,s.session);require(again.accepted,"chain");complete=waitSeek(e,again.id);}
                    require(!e.requestInteractiveSeekToInputFrame(0,initial.inputGeneration,initial.renderEpoch,initial.session).accepted,"stale epoch accepted");
                    if(kind=="ready"||kind=="paused"||kind=="pause_prepare"||kind=="eof_paused"){
                        const auto state=kind=="ready"||kind=="eof_paused"?State::Ready:State::Paused;require(e.getPlaybackState()==state,"paused autoplay");
                        const auto before=e.getCurrentPlaybackPosition();require(before.inputFrame==complete.requestedInputFrame,"input frame error");std::this_thread::sleep_for(std::chrono::milliseconds(20));require(e.getCurrentPlaybackPosition().outputFrame==before.outputFrame,"paused consumed");
                        require(state==State::Ready?e.play():e.resume(),"resume");
                    }
                    if(kind=="speed_after"){
                        const auto s=e.getStateSnapshot();const auto speed=e.setSpeed(.75,s.session,s.inputGeneration,s.renderEpoch);require(speed.result==ts::prototype::Phase39RequestResult::Accepted,"speed after seek");
                        const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(10);bool done=false;while(!done){for(const auto& x:e.operationHistory())if(x.id==speed.id)done=x.state==ts::prototype::phase59::OperationState::Completed;require(std::chrono::steady_clock::now()<end,"speed completion");std::this_thread::sleep_for(std::chrono::milliseconds(2));}
                    }
                    if(kind=="playing"||kind=="eof_playing"||kind=="ready"||kind=="paused"||kind=="eof_paused")wait(e,State::Ended);
                    else std::this_thread::sleep_for(std::chrono::milliseconds(35));
                    e.stop();
                }
            }
            if(engine){e.stop();history=e.seekHistory();d=e.getPlaybackDiagnostics();native=e.getNativeDiagnostics();closed=e.closedEpochs();}
            for(const auto& x:history)if(!kind.starts_with("destroy_"))require(progressive::terminal(x.state),"nonterminal after stop");
            require(!phase61_heap_allocations()&&!phase61_heap_frees(),"callback C heap allocation/release");
            require(!audit.errors&&!audit.raw.errors,"raw order / mixed output equation / clock / finite PCM");
        }catch(const std::exception& ex){functional=false;error=ex.what();if(engine){e.stop();history=e.seekHistory();d=e.getPlaybackDiagnostics();native=e.getNativeDiagnostics();closed=e.closedEpochs();}}
        std::uint64_t deadlines=d.pipeline.scheduling.deadlineMisses;bool lifetime=true;
        auto check=[&](const auto& p){const auto& m=p.scheduling;lifetime&=!m.active&&m.joins==m.leaves&&m.leaves==m.restores&&!m.joinErrors&&!m.restoreErrors&&!m.policyErrors;};check(d.pipeline);for(const auto& x:closed){check(x.pipeline);deadlines+=x.pipeline.scheduling.deadlineMisses;}
        if(!lifetime){functional=false;error+=" Workgroup lifetime";}
        std::ofstream seekFile(folder/"seeks.json");operations(seekFile,history);
        std::ofstream captures(folder/"captures.json");captures<<'[';bool comma=false;
        for(const auto& s:audit.raw.slots)if(s.epoch){const auto path=folder/("raw_epoch_"+std::to_string(s.epoch)+".f32");std::ofstream f(path,std::ios::binary);f.write(reinterpret_cast<const char*>(s.pcm.data()),s.frames*audit.channels*sizeof(float));
            if(comma)captures<<',';comma=true;captures<<"{\"epoch\":"<<s.epoch<<",\"session\":"<<s.session<<",\"generation\":"<<s.generation<<",\"start\":"<<s.start<<",\"frames\":"<<s.frames<<",\"path\":"<<ts::prototype::phase58::jsonString(path.string())<<'}';}captures<<"]\n";
        std::ofstream spans(folder/"output_spans.csv");spans<<"callback_frame,frames,new_epoch,old_epoch,new_offset,old_offset,new_received,old_received,mixed_frames,transition_offset,transition_length\n";
        for(std::size_t i=0;i<audit.count;++i){const auto& s=audit.spans[i];spans<<s.callbackFrame<<','<<s.frames<<','<<s.newEpoch<<','<<s.oldEpoch<<','<<s.newOutputOffset<<','<<s.oldOutputOffset<<','<<s.newReceivedFrames<<','<<s.oldReceivedFrames<<','<<s.mixedFrames<<','<<s.transitionOffset<<','<<s.transitionLength<<'\n';}
        const auto measured=[&](std::uint64_t value){return engine?std::to_string(value):std::string("null");};
        rows<<"{\"kind\":\""<<kind<<"\",\"candidate\":"<<(preset==Preset::Candidate?"true":"false")<<",\"functional\":"<<(functional?"true":"false")<<",\"error\":"<<ts::prototype::phase58::jsonString(error)<<",\"raw_errors\":"<<audit.raw.errors<<",\"output_errors\":"<<audit.errors<<",\"mixed_frames\":"<<audit.mixedFrames<<",\"missing\":"<<measured(d.missingFrames)<<",\"callback_new\":"<<(d.callbackCppNew?std::to_string(*d.callbackCppNew):"null")<<",\"heap_calls\":"<<phase61_heap_allocations()<<",\"heap_frees\":"<<phase61_heap_frees()<<",\"callback_deadlines\":"<<measured(native.deadlineMisses)<<",\"device_buffer\":"<<measured(native.deviceBufferFrames)<<",\"worker_deadlines\":"<<measured(deadlines)<<",\"host_errors\":"<<measured(native.hostMissing+native.hostBackwards+native.hostCadenceErrors)<<",\"sample_errors\":"<<measured(native.sampleErrors)<<",\"hal_errors\":"<<measured(native.halWindowMisses)<<",\"lifetime\":"<<(engine?(lifetime?"true":"false"):"null")<<",\"destroyed_without_final_diagnostics\":"<<(kind.starts_with("destroy_")?"true":"false")<<"}\n";rows.flush();
        std::cout<<kind<<" "<<int(preset)<<" functional="<<functional<<" mix="<<audit.mixedFrames<<" error="<<error<<std::endl;failures+=!functional;
    }buffer.restore();return failures?2:0;
}
#endif
int main(int argc,char** argv){if(argc<3||argc>4)return 1;
    phase61_heap_reset();phase61_heap_begin();void* (*volatile allocate)(std::size_t)=std::malloc;void (*volatile release)(void*)=std::free;void* probe=allocate(37);release(probe);phase61_heap_end();
    if(!phase61_heap_allocations()||!phase61_heap_frees()){std::cerr<<"malloc/free interposition self-test failed\n";return 3;}phase61_heap_reset();int result=2;std::thread queue([&]{try{
#ifdef PHASE61_INTERACTIVE_CONTRACT
if(argc==4&&(std::string(argv[3])=="--controls"||std::string(argv[3])=="--controls64"))result=controls(argv[1],argv[2],std::string(argv[3])=="--controls64");else
#endif
result=performance(argv[1],argv[2],argc==4&&std::string(argv[3])=="--early");}catch(const std::exception& ex){std::cerr<<ex.what()<<'\n';}});queue.join();return result;}
