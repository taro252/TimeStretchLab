// Reuse the verification-only bounded capture and allocation instrumentation.
// Existing Phase61 Exact scenarios and their evidence remain unchanged.
#define PHASE61_SANDBOX_APP 1
#define runPhase61Native runPhase61ExactVerificationHost
#include "Phase61NativeTests.cpp"
#undef runPhase61Native

int runPhase61Native(const std::filesystem::path& input,const std::filesystem::path& output){
    require(std::filesystem::create_directories(output),"Evidence directory exists");
    std::ofstream rows(output/"sessions.jsonl");std::size_t total=0,failed=0;
    for(auto preset:{Preset::Candidate,Preset::Baseline})for(const std::string kind:{"gate","ready","playing","paused","pause_prepare","burst","chain","speed_prepare","speed_after","replace_ready","stop","stop_ready","route","input","eof"}){
        const auto name=std::string(preset==Preset::Candidate?"candidate_":"baseline_")+kind;
        const auto folder=output/name;std::filesystem::create_directory(folder);
        auto source=input;if(kind=="input"){source=folder/"source.wav";std::filesystem::copy_file(input,source);}
        ts::WavStreamReader info(source);const auto n=info.frames();const auto rate=info.sampleRate();require(n<=rate*20ULL,"Bounded native fixture");
        Capture capture(info.channels(),std::size_t(std::ceil(n*2.5))+2048);
        ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.preset=preset;o.initialSpeed=.5;o.callbackRecordLimit=8192;
        require(!o.allowUnvalidatedFastLocalSeek,"Research mode enabled by default");o.allowUnvalidatedFastLocalSeek=kind!="gate";
        o.observerContext=&capture;o.observeEpochPcm=Capture::observe;
        o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;},[]()noexcept{callbackCounting=false;},[]()noexcept{return callbackNew;}};
        bool functional=true;std::string error;std::uint64_t id=0;bool speedCompleted=false;
        try{
            require(!e.capabilities().seek,"Public seek gate opened");require(e.prepare(source,o),"prepare");wait(e,State::Ready);
            const auto initial=e.getStateSnapshot();
            if(kind=="gate"){
                const auto gated=e.requestFastLocalSeekToInputFrame(n/2);require(!gated.accepted&&gated.reason.find("未承認")!=std::string::npos,"Unapproved Fast API enabled");
            }else{
            for(double bad:{-1.,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN(),double(n)/rate+1e-8})require(!e.requestFastLocalSeekToInputSeconds(bad).accepted,"invalid seconds");
            require(!e.requestFastLocalSeekToInputFrame(0,0,0,1).accepted,"invalid preroll");
            require(!e.requestFastLocalSeekToInputFrame(n+1).accepted,"invalid frame");
            require(!e.requestFastLocalSeekToInputFrame(0,initial.inputGeneration+1).accepted,"stale generation");
            if(kind!="ready"&&kind!="eof"){require(e.play(),"play");firstPcm(e);}
            if(kind=="paused")require(e.pause(),"pause");
            const auto target=kind=="eof"?n:n/2+17;
            auto receipt=e.requestFastLocalSeekToInputFrame(target,initial.inputGeneration,initial.renderEpoch);require(receipt.accepted,"fast admission");id=receipt.id;
            if(kind=="pause_prepare")require(e.pause(),"pause during preparation");
            if(kind=="burst")for(unsigned i=0;i<64;++i){receipt=e.requestFastLocalSeekToInputFrame(target+i%17,initial.inputGeneration,initial.renderEpoch);require(receipt.accepted,"Latest-Wins");id=receipt.id;}
            if(kind=="speed_prepare"||kind=="replace_ready"||kind=="stop_ready"){
                const auto wanted=kind=="speed_prepare"?Seek::Preparing:Seek::Ready;
                const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(10);bool found=false;
                while(!found){for(const auto& op:e.seekHistory())if(op.id==id){found=op.state==wanted;if(found&&wanted==Seek::Ready)require(op.outputStartFrame>0,"Ready output coordinate not published");}require(std::chrono::steady_clock::now()<limit,"seek stage not observed");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
                if(kind=="speed_prepare")require(e.setSpeed(.75).result==ts::prototype::Phase39RequestResult::Accepted,"speed replan");
                else if(kind=="replace_ready"){const auto old=id;receipt=e.requestFastLocalSeekToInputFrame(n*3/4+29);require(receipt.accepted,"replace Ready");id=receipt.id;
                    for(const auto& op:e.seekHistory())if(op.id==old)require(op.state==Seek::Replaced,"Ready not replaced");}
            }
            if(kind=="stop"||kind=="stop_ready"){e.stop();require(e.getPlaybackState()==State::Stopped,"stop");}
            else if(kind=="route"){e.simulateDeviceChangeForTest();wait(e,State::Stopped);}
            else if(kind=="input"){std::filesystem::remove(source);wait(e,State::Failed);}
            else{
                auto completed=waitSeek(e,id);
                require(completed.mode==progressive::SeekMode::FastLocal&&completed.prerollMillis==500,"seek mode");
                require(completed.inputGeneration==initial.inputGeneration&&e.getStateSnapshot().inputGeneration==initial.inputGeneration&&completed.renderEpoch!=initial.renderEpoch&&completed.session!=initial.session,"generation/epoch isolation");
                if(kind=="speed_prepare")require(completed.replans>0,"speed preparation did not replan");
                if(kind=="chain"){
                    const auto again=e.requestFastLocalSeekToInputFrame(n*3/4+29,initial.inputGeneration,completed.renderEpoch);require(again.accepted,"chain");id=again.id;completed=waitSeek(e,id);
                }
                require(e.setSpeed(.75,initial.session,initial.inputGeneration,initial.renderEpoch).result==ts::prototype::Phase39RequestResult::Stopped,"stale speed epoch");
                const auto d=e.getPlaybackDiagnostics().pipeline;
                require(d.fastLocalSeek&&!d.checkpointUsed&&d.sourceHashPasses==1&&d.sourceSnapshotCreations==1&&d.residentLockCalls==1,"input reuse/local identity");
                if(kind=="ready"||kind=="paused"||kind=="pause_prepare"||kind=="eof"){
                    const bool paused=kind=="paused"||kind=="pause_prepare";const auto state=paused?State::Paused:State::Ready;require(e.getPlaybackState()==state,"autoplay");
                    require(e.getCurrentPlaybackPosition().inputFrame==completed.requestedInputFrame,"input coordinate");
                    const auto at=e.getCurrentPlaybackPosition().outputFrame;std::this_thread::sleep_for(std::chrono::milliseconds(25));require(e.getCurrentPlaybackPosition().outputFrame==at,"paused consumption");
                    require(paused?e.resume():e.play(),"play/resume");
                }
                if(kind=="speed_after"){
                    const auto current=e.getStateSnapshot();const auto speed=e.setSpeed(.4,current.session,current.inputGeneration,current.renderEpoch);require(speed.result==ts::prototype::Phase39RequestResult::Accepted,"post-seek density speed");
                    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(10);
                    while(!speedCompleted){for(const auto& op:e.operationHistory())if(op.id==speed.id)speedCompleted=op.state==ts::prototype::phase59::OperationState::Completed;
                        require(e.getPlaybackState()!=State::Failed,"dynamic failure");require(std::chrono::steady_clock::now()<until,"speed completion");std::this_thread::sleep_for(std::chrono::milliseconds(2));}
                }
                wait(e,State::Ended);
            }
            }
            e.stop();require(!capture.errors,"callback output identity/order");
        }catch(const std::exception& ex){functional=false;error=ex.what();e.stop();}
        const auto d=e.getPlaybackDiagnostics();const auto native=e.getNativeDiagnostics();auto epochs=e.closedEpochs();
        std::uint64_t deadlines=d.pipeline.scheduling.deadlineMisses,news=d.pipeline.realtimeNewCalls;bool lifetime=true;
        const auto check=[&](const auto& p){const auto& m=p.scheduling;lifetime&=!m.active&&m.joins==m.leaves&&m.leaves==m.restores&&!m.policyErrors&&!m.joinErrors&&!m.restoreErrors&&!m.intervalErrors&&!m.queryErrors&&!m.waitErrors&&!m.wakeErrors;};check(d.pipeline);
        for(const auto& epoch:epochs){deadlines+=epoch.pipeline.scheduling.deadlineMisses;news+=epoch.pipeline.realtimeNewCalls;check(epoch.pipeline);}
        double seam=0;std::size_t silentTail=0;const Slot* previous=nullptr;
        std::ofstream captures(folder/"captures.json");captures<<'[';bool comma=false;
        for(const auto& slot:capture.slots)if(slot.epoch){
            if(previous&&kind!="paused"&&kind!="pause_prepare"){
                for(std::size_t c=0;c<info.channels();++c)seam=std::max(seam,double(std::abs(previous->pcm[(previous->frames-1)*info.channels()+c]-slot.pcm[c])));
                std::size_t tail=0;for(auto at=previous->frames;at>0;--at){bool zero=true;for(std::size_t c=0;c<info.channels();++c)zero&=std::abs(previous->pcm[(at-1)*info.channels()+c])<1e-8;if(!zero)break;++tail;}silentTail=std::max(silentTail,tail);
            }
            const auto path=folder/("epoch_"+std::to_string(slot.epoch)+".f32");std::ofstream pcm(path,std::ios::binary);pcm.write(reinterpret_cast<const char*>(slot.pcm.data()),slot.frames*info.channels()*sizeof(float));
            if(comma)captures<<',';comma=true;captures<<"{\"epoch\":"<<slot.epoch<<",\"session\":"<<slot.session<<",\"generation\":"<<slot.generation<<",\"start\":"<<slot.start<<",\"frames\":"<<slot.frames<<",\"path\":"<<ts::prototype::phase58::jsonString(path.string())<<'}';previous=&slot;
        }captures<<"]\n";
        const bool measured=!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!native.deadlineMisses&&!native.formatErrors&&!native.hostMissing&&!native.hostBackwards&&!native.hostCadenceErrors&&!native.sampleErrors&&!native.halWindowMisses&&!deadlines&&!news&&lifetime&&d.callbackCppNew&&!*d.callbackCppNew&&!capture.errors;
        const bool seamPass=seam<1e-7&&silentTail<=rate*3/100;const bool pass=functional&&measured&&seamPass;++total;failed+=!pass;
        std::ofstream seeks(folder/"seeks.json");seeks<<'[';comma=false;for(const auto& op:e.seekHistory()){
            if(comma)seeks<<',';comma=true;seeks<<"{\"id\":"<<op.id<<",\"state\":\""<<progressive::name(op.state)<<"\",\"input\":"<<op.requestedInputFrame<<",\"output\":"<<op.outputStartFrame<<",\"epoch\":"<<op.renderEpoch<<",\"session\":"<<op.session<<",\"speed\":"<<op.speedMicros<<",\"replans\":"<<op.replans<<",\"accepted_ns\":"<<op.acceptedNs<<",\"ready_ns\":"<<op.readyNs<<",\"switched_ns\":"<<op.switchedNs<<",\"first_pcm_ns\":"<<op.firstCallbackNs<<",\"reason\":"<<ts::prototype::phase58::jsonString(op.reason)<<'}';}seeks<<"]\n";
        rows<<"{\"name\":\""<<name<<"\",\"PASS\":"<<(pass?"true":"false")<<",\"functional\":"<<(functional?"true":"false")<<",\"realtime\":"<<(measured?"true":"false")<<",\"seam_pass\":"<<(seamPass?"true":"false")<<",\"seam_step\":"<<seam<<",\"silent_tail_frames\":"<<silentTail<<",\"speed_completed\":"<<(speedCompleted?"true":"false")<<",\"missing\":"<<d.missingFrames<<",\"callback_deadlines\":"<<native.deadlineMisses<<",\"worker_deadlines\":"<<deadlines<<",\"callback_new\":"<<(d.callbackCppNew?std::to_string(*d.callbackCppNew):"null")<<",\"worker_new\":"<<news<<",\"lifetime\":"<<(lifetime?"true":"false")<<",\"peak_rss\":"<<d.peakRssBytes
            <<",\"device_id\":"<<native.deviceId<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames<<",\"source_rate\":"<<rate<<",\"source_channels\":"<<info.channels()<<",\"host_errors\":"<<native.hostMissing+native.hostBackwards+native.hostCadenceErrors<<",\"sample_errors\":"<<native.sampleErrors<<",\"hal_misses\":"<<native.halWindowMisses<<",\"error\":"<<ts::prototype::phase58::jsonString(error)<<"}\n";rows.flush();
        std::cout<<name<<" pass="<<pass<<" functional="<<functional<<" realtime="<<measured<<" seam="<<seam<<" tail="<<silentTail<<" error="<<error<<std::endl;
    }
    std::ofstream summary(output/"summary.json");summary<<"{\"cases\":"<<total<<",\"failed\":"<<failed<<",\"subjective_listening\":\"UNMEASURED\"}\n";return failed?2:0;
}
int runFastPerformance(const std::filesystem::path& input,const std::filesystem::path& output,bool awaitAnalysis=true){
    require(std::filesystem::create_directories(output),"Evidence exists");ts::WavStreamReader info(input);const auto rate=info.sampleRate();const auto n=info.frames();require(n==rate*300ULL,"300s input required");
    std::vector<std::size_t> positions{0,rate*30ULL,rate*150ULL,rate*270ULL,rate*285ULL};std::uint64_t rng=61061;
    for(unsigned i=0;i<5;++i){rng=(rng*6364136223846793005ULL+1);positions.push_back(rate+rng%(n-rate*2ULL));}
    if(!awaitAnalysis)positions={rate*270ULL};
    std::ofstream rows(output/"rows.jsonl");std::size_t count=0;bool all=true;
    for(auto speed:{400000u,500000u,750000u,1000000u,1500000u,2000000u})for(auto preset:{Preset::Candidate,Preset::Baseline})for(unsigned repeat=0;repeat<3;++repeat){
        ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.initialSpeed=speed/1000000.;o.preset=preset;o.callbackRecordLimit=8192;
        o.allowUnvalidatedFastLocalSeek=true;
        o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;},[]()noexcept{callbackCounting=false;},[]()noexcept{return callbackNew;}};
        require(e.prepare(input,o),"performance prepare");wait(e,State::Ready);
        const auto analysisDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);
        while(awaitAnalysis&&!e.getPlaybackDiagnostics().pipeline.analysisDone){require(std::chrono::steady_clock::now()<analysisDeadline,"analysis timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}
        const auto initialPreparation=e.getPlaybackDiagnostics();
        require(e.play(),"performance play");firstPcm(e);
        for(auto frame:positions){
            const auto before=e.getStateSnapshot();const auto receipt=e.requestFastLocalSeekToInputFrame(frame,before.inputGeneration,before.renderEpoch);require(receipt.accepted,"performance seek");
            auto op=waitSeek(e,receipt.id);
            const auto firstDeadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
            while(!op.firstCallbackNs){for(const auto& item:e.seekHistory())if(item.id==receipt.id)op=item;require(std::chrono::steady_clock::now()<firstDeadline,"first PCM timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
            const auto d=e.getPlaybackDiagnostics();const auto native=e.getNativeDiagnostics();
            bool quality=!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!native.deadlineMisses&&!native.formatErrors&&!native.hostMissing&&!native.hostBackwards&&!native.hostCadenceErrors&&!native.sampleErrors&&!native.halWindowMisses&&d.callbackCppNew&&!*d.callbackCppNew;
            const auto workerGood=[](const auto& p){const auto& m=p.scheduling;return !p.realtimeNewCalls&&!m.deadlineMisses&&!m.policyErrors&&!m.joinErrors&&!m.restoreErrors&&!m.intervalErrors&&!m.queryErrors&&!m.waitErrors&&!m.wakeErrors;};
            quality&=workerGood(d.pipeline);for(const auto& old:e.closedEpochs())quality&=workerGood(old.pipeline);
            std::uint64_t workerDeadlines=0,workerNews=0,workerErrors=0;
            const auto countWorker=[&](const auto& p){const auto& m=p.scheduling;workerDeadlines+=m.deadlineMisses;workerNews+=p.realtimeNewCalls;workerErrors+=m.policyErrors+m.joinErrors+m.restoreErrors+m.intervalErrors+m.queryErrors+m.waitErrors+m.wakeErrors;};
            countWorker(d.pipeline);for(const auto& old:e.closedEpochs())countWorker(old.pipeline);
            require(d.pipeline.fastLocalSeek&&!d.pipeline.checkpointUsed&&d.pipeline.sourceHashPasses==1&&d.pipeline.sourceSnapshotCreations==1&&d.pipeline.residentLockCalls==1,"first-visit input reuse");
            all&=quality;++count;
            rows<<"{\"speed\":"<<speed<<",\"candidate\":"<<(preset==Preset::Candidate?"true":"false")<<",\"repeat\":"<<repeat<<",\"input\":"<<frame<<",\"output\":"<<op.outputStartFrame<<",\"rate\":"<<rate<<",\"channels\":"<<info.channels()<<",\"ready_ms\":"<<(op.readyNs-op.acceptedNs)/1e6<<",\"switch_ms\":"<<(op.switchedNs-op.acceptedNs)/1e6<<",\"first_pcm_ms\":"<<(op.firstCallbackNs-op.acceptedNs)/1e6
                <<",\"pipeline_ready_s\":"<<d.pipeline.readyS<<",\"local_initialize_s\":"<<d.pipeline.localInitializeS<<",\"analysis_s\":"<<d.pipeline.analysisCpuS<<",\"dsp_s\":"<<d.pipeline.dspCpuS<<",\"discarded\":"<<d.pipeline.discardedFrames<<",\"local_begin\":"<<d.pipeline.localBeginOutput<<",\"seed_input\":"<<d.pipeline.localSeedInput<<",\"quality\":"<<(quality?"true":"false")<<",\"peak_rss\":"<<d.peakRssBytes<<",\"device_id\":"<<native.deviceId<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer\":"<<native.deviceBufferFrames
                <<",\"initial_ready_s\":"<<initialPreparation.acceptedToReadyS<<",\"initial_analysis_done_s\":"<<initialPreparation.pipeline.analysisDoneS<<",\"initial_analysis_complete\":"<<(initialPreparation.pipeline.analysisDone?"true":"false")<<",\"seek_analysis_start_s\":"<<d.pipeline.analysisStartS<<",\"seek_analysis_done_s\":"<<d.pipeline.analysisDoneS<<",\"source_hash_passes\":"<<d.pipeline.sourceHashPasses<<",\"source_snapshots\":"<<d.pipeline.sourceSnapshotCreations<<",\"resident_locks\":"<<d.pipeline.residentLockCalls
                <<",\"presentation_estimate_ms\":"<<(op.estimatedPresentationNs?double(op.estimatedPresentationNs-op.acceptedNs)/1e6:-1.)<<",\"missing\":"<<d.missingFrames<<",\"underrun_calls\":"<<d.underrunCalls<<",\"rejected_writes\":"<<d.rejectedWrites<<",\"callback_deadlines\":"<<native.deadlineMisses<<",\"format_errors\":"<<native.formatErrors<<",\"host_missing\":"<<native.hostMissing<<",\"host_backwards\":"<<native.hostBackwards<<",\"host_cadence_errors\":"<<native.hostCadenceErrors<<",\"sample_errors\":"<<native.sampleErrors<<",\"hal_misses\":"<<native.halWindowMisses<<",\"callback_new\":"<<(d.callbackCppNew?std::to_string(*d.callbackCppNew):"null")<<",\"worker_deadlines\":"<<workerDeadlines<<",\"worker_new\":"<<workerNews<<",\"worker_errors\":"<<workerErrors<<"}\n";rows.flush();
        }
        e.stop();const auto d=e.getPlaybackDiagnostics();const auto& m=d.pipeline.scheduling;
        require(!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"final Workgroup lifetime");
        for(const auto& old:e.closedEpochs()){const auto& g=old.pipeline.scheduling;require(!g.active&&g.joins==g.leaves&&g.leaves==g.restores,"retired Workgroup lifetime");}
        std::cout<<speed<<' '<<(preset==Preset::Candidate?"candidate":"baseline")<<' '<<repeat<<" complete quality="<<all<<std::endl;
    }
    std::ofstream summary(output/"summary.json");summary<<"{\"cases\":"<<count<<",\"realtime_pass\":"<<(all?"true":"false")<<",\"first_visit_per_input_session\":true,\"await_analysis\":"<<(awaitAnalysis?"true":"false")<<"}\n";return all?0:2;
}
#ifndef PHASE61_FAST_SANDBOX
int main(int argc,char** argv){if(argc!=3&&argc!=4)return 1;int result=1;std::thread control([&]{try{result=argc==4?runFastPerformance(argv[1],argv[2],std::string(argv[3])!="--early-performance"):runPhase61Native(argv[1],argv[2]);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return result;}
#endif
