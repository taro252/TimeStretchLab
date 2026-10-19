#define PHASE61_SANDBOX_APP 1
#include "Phase61NativeTests.cpp"
#include "Phase61CallbackMallocProbe.h"
#include "Phase62PcmAudit.h"
#include <CoreAudio/CoreAudio.h>
// Run on one dedicated normal control thread, exactly as an application bridge.
int runLoopNative(int argc,char** argv){
    require(argc>=3,"input output [seconds=.5] [speed=2] [cycles=10] [candidate|baseline] [controls|whole]");
    const std::filesystem::path output=argv[2];require(std::filesystem::create_directories(output),"existing evidence directory");
    ts::WavStreamReader info(argv[1]);const auto rate=info.sampleRate();const auto range=argc>3?std::stod(argv[3]):.5;
    const auto speed=argc>4?std::stod(argv[4]):2.;const auto cycles=argc>5?std::stoull(argv[5]):10;
    const std::string mode=argc>7?argv[7]:"normal";const auto a=(mode=="whole"||mode=="compare")?0ULL:mode=="end"?std::uint64_t(info.frames()-std::llround(range*rate)):17ULL;
    const auto b=(mode=="whole"||mode=="end")?info.frames():std::min<std::uint64_t>(info.frames(),a+std::uint64_t(std::llround(range*rate)));
    ProgressiveOptions options;options.allowExperimentalLoops=true;options.allowUnvalidatedFastLocalSeek=true;options.initialSpeed=speed;
    options.preset=argc>6&&std::string(argv[6])=="baseline"?Preset::Baseline:Preset::Candidate;options.callbackRecordLimit=16384;
    LoopPcmAudit audit(info.channels());options.observerContext=&audit;options.observeEpochPcm=LoopPcmAudit::source;options.observeOutputPcm=LoopPcmAudit::output;
    phase61_heap_reset();options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    const auto began=std::chrono::steady_clock::now();ProgressiveMacPlaybackEngine e;e.prepare(argv[1],options);wait(e,State::Ready);
    const auto c=e.getStateSnapshot();const progressive::LoopContext context{c.inputGeneration,c.session,c.renderEpoch};
    require(!e.requestLoopRange(0,1,context).accepted,"one frame execution accepted");
    require(!e.requestLoopRange(0,rate/10,context).accepted,"100ms execution accepted");
    require(!e.requestLoopRange(a,b,{c.inputGeneration+1,c.session,c.renderEpoch}).accepted,"stale input accepted");
    progressive::LoopOptions lo;if(mode=="whole")lo.startPolicy=progressive::LoopStartPolicy::KeepPosition;
    const auto receipt=e.requestLoopRange(a,b,context,lo);require(receipt.accepted,"loop admission");
    const auto timeout=std::chrono::steady_clock::now()+std::chrono::seconds(std::uint64_t((double(b-a)/rate/speed+1)*(cycles+4))+30);
    auto poll=[&]{const auto l=e.getLoopSnapshot();if(l.state==progressive::LoopState::Failed)throw std::runtime_error(l.reason);require(std::chrono::steady_clock::now()<timeout,"loop timeout");return l;};
    if(mode!="whole")while(!poll().initialPositionComplete)std::this_thread::sleep_for(std::chrono::milliseconds(1));
    require(e.play(),"play");firstPcm(e);const auto rssStart=e.getPlaybackDiagnostics().rssBytes;
    std::ofstream rssLog(output/"rss_samples.jsonl");std::uint64_t lastRssCycle=UINT64_MAX;
    bool controlsDone=false;
    while(poll().cycles<cycles){
        const auto cycle=poll().cycles;if(cycle%100==0&&cycle!=lastRssCycle){const auto memory=e.getPlaybackDiagnostics();rssLog<<"{\"cycle\":"<<cycle<<",\"rss\":"<<memory.rssBytes<<",\"cpu_s\":"<<memory.processCpuS<<"}\n";rssLog.flush();lastRssCycle=cycle;}
        if(mode=="controls"&&!controlsDone&&poll().cycles>=2){
            require(e.pause(),"pause");const auto paused=e.getLoopSnapshot().cycles;std::this_thread::sleep_for(std::chrono::milliseconds(100));require(e.getLoopSnapshot().cycles==paused,"paused cycle advanced");
            auto current=e.getStateSnapshot();auto r=e.setSpeed(.75,current.session,current.inputGeneration,current.renderEpoch);require(r.result==ts::prototype::Phase39RequestResult::Accepted,"loop speed");
            require(e.resume(),"resume");current=e.getStateSnapshot();auto seek=e.requestSeekToInputFrame(b,current.inputGeneration,current.renderEpoch);require(seek.accepted,"out of range seek");auto done=waitSeek(e,seek.id);require(done.requestedInputFrame==a,"outside seek not corrected A");controlsDone=true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    require(e.pause(),"final pause");const auto loop=e.getLoopSnapshot();const auto savedHistory=e.loopHistory();const auto savedEpochs=e.closedEpochs().size();const auto measurementWall=std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count();const auto d=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();
    require(loop.cycles>=cycles&&!loop.safetyStopFrames,"successful cycles");require(!audit.errors&&!audit.nonfinite,"raw mix/order audit");
    require(!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites,"FIFO missing");require(e.seekHistory().size()<=1,"automatic loop leaked seek ledger");
    require(d.pipeline.sourceHashPasses==1&&d.pipeline.sourceSnapshotCreations==1&&d.pipeline.residentLockCalls==1,"input lease repeated");
    if(mode=="trace"){
        const auto records=e.callbackRecords();std::ofstream trace(output/"callbacks.csv");
        trace<<"sequence,clock_epoch,start_ns,io_end_ns,end_ns,host_ns,sample_time,flags,requested,raw_session,raw_output,raw_wanted,raw_received,fifo_before\n";
        for(const auto& row:records)trace<<row.sequence<<','<<row.epoch<<','<<row.startNs<<','<<row.ioEndNs<<','<<row.endNs<<','<<row.hostNs<<','<<row.sampleTime<<','<<row.timestampFlags<<','<<row.requested<<','<<row.raw.session<<','<<row.raw.outputBefore<<','<<row.raw.wanted<<','<<row.raw.received<<','<<row.raw.fifoBefore<<'\n';
    }
    auto clear=e.requestClearLoop(loop.id,context);require(clear.accepted,"clear with original context");
    require(e.resume(),"resume clear");
    while(e.getLoopSnapshot().clearPending){const auto l=e.getLoopSnapshot();require(l.state!=progressive::LoopState::Failed,"clear failed");require(std::chrono::steady_clock::now()<timeout,"clear timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    require(!e.getLoopSnapshot().enabled&&e.getLoopSnapshot().cycles==loop.cycles,"clear counted a cycle");
    e.stop();require(!e.getLoopSnapshot().enabled,"stop loop enabled");
    require(!audit.errors&&!audit.nonfinite,"clear mix audit");const auto original=e.getPlaybackDiagnostics();require(original.pipeline.finalDataAvailable,"loop stop final audit");
    for(const auto& closed:e.closedEpochs()){const auto& m=closed.pipeline.scheduling;require(closed.pipeline.finalDataAvailable&&!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"loop retirement audit");}
    require(e.play(),"restart");wait(e,State::Playing);require(!e.getLoopSnapshot().enabled,"restart revived loop");e.stop();
    const auto workgroup=[](const auto& p){const auto& m=p.scheduling;require(p.finalDataAvailable&&!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"retirement Workgroup");};
    workgroup(e.getPlaybackDiagnostics().pipeline);for(const auto& epoch:e.closedEpochs())workgroup(epoch.pipeline);
    std::ofstream f(output/"result.json");f<<"{\"functional_pass\":true,\"cycles\":"<<loop.cycles<<",\"rate\":"<<rate<<",\"channels\":"<<info.channels()<<",\"speed\":"<<speed<<",\"range_seconds\":"<<range<<",\"preset\":\""<<(options.preset==Preset::Candidate?"candidate":"baseline")<<"\",\"mode\":\""<<mode<<"\",\"raw_mix_errors\":"<<audit.errors<<",\"nonfinite\":"<<audit.nonfinite<<",\"zero_source_or_output_frames\":"<<audit.zeroFrames<<",\"safety_stop_frames\":"<<loop.safetyStopFrames<<",\"missing_frames\":"<<d.missingFrames<<",\"underrun_calls\":"<<d.underrunCalls<<",\"worker_deadlines\":"<<d.workerDeadlineMisses<<",\"worker_new\":"<<d.workerNewCalls<<",\"workgroup_errors\":"<<d.workgroupErrors<<",\"archived_epochs\":"<<d.archivedEpochCount<<",\"retained_epochs\":"<<savedEpochs<<",\"final_worker_deadlines\":"<<original.workerDeadlineMisses<<",\"final_worker_new\":"<<original.workerNewCalls<<",\"final_workgroup_errors\":"<<original.workgroupErrors<<",\"final_missing_frames\":"<<original.missingFrames<<",\"final_archived_epochs\":"<<original.archivedEpochCount<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"host_errors\":"<<(n.hostMissing+n.hostBackwards+n.hostCadenceErrors)<<",\"sample_errors\":"<<n.sampleErrors<<",\"hal_window_misses\":"<<n.halWindowMisses<<",\"callback_new\":"<<d.callbackCppNew.value_or(UINT64_MAX)<<",\"callback_heap_calls\":"<<phase61_heap_allocations()<<",\"callback_frees\":"<<phase61_heap_frees()<<",\"process_cpu_s\":"<<d.processCpuS<<",\"wall_s\":"<<measurementWall<<",\"rss_start\":"<<rssStart<<",\"rss_end\":"<<d.rssBytes<<",\"peak_rss\":"<<d.peakRssBytes<<",\"ready_ms\":"<<(loop.readyNs-loop.acceptedNs)/1e6<<",\"last_prepare_ms\":"<<(loop.lastReadyNs>=loop.lastPreparationNs?std::to_string((loop.lastReadyNs-loop.lastPreparationNs)/1e6):std::string("null"))<<",\"max_prepare_ms\":"<<loop.maxPreparationNs/1e6<<",\"preparations\":"<<loop.preparationCount<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<"}\n";
    std::ofstream history(output/"boundaries.jsonl");for(const auto& event:savedHistory)history<<"{\"cycle\":"<<event.cycle<<",\"old_epoch\":"<<event.oldEpoch<<",\"new_epoch\":"<<event.newEpoch<<",\"old_output_end\":"<<event.oldOutputEnd<<",\"new_output_start\":"<<event.newOutputStart<<",\"callback_frame\":"<<event.callbackFrame<<",\"overlap\":"<<event.overlapFrames<<",\"hal_boundary_estimate_ns\":"<<event.halBoundaryEstimateNs<<",\"render_ns\":"<<event.renderNs<<"}\n";
    if(loop.lastBoundary){const auto& v=*loop.lastBoundary;std::ofstream bfile(output/"last_boundary.json");bfile<<"{\"cycle\":"<<v.cycle<<",\"old_epoch\":"<<v.oldEpoch<<",\"new_epoch\":"<<v.newEpoch<<",\"input_a\":"<<v.inputA<<",\"input_b_exclusive\":"<<v.inputBExclusive<<",\"old_output_end\":"<<v.oldOutputEnd<<",\"new_output_start\":"<<v.newOutputStart<<",\"callback_frame\":"<<v.callbackFrame<<",\"overlap\":"<<v.overlapFrames<<",\"hal_boundary_estimate_ns\":"<<v.halBoundaryEstimateNs<<",\"render_ns\":"<<v.renderNs<<"}\n";}
    std::cout<<"PASS cycles="<<loop.cycles<<" worker_deadlines="<<d.workerDeadlineMisses<<" rss="<<d.rssBytes<<'\n';return 0;
}
int runLoopFaults(const std::filesystem::path& input,const std::filesystem::path& output){
    require(std::filesystem::create_directories(output),"fault output exists");std::ofstream log(output/"checks.jsonl");ts::WavStreamReader info(input);const auto rate=info.sampleRate();unsigned checks=0;
    auto context=[](ProgressiveMacPlaybackEngine& e){const auto c=e.getStateSnapshot();return progressive::LoopContext{c.inputGeneration,c.session,c.renderEpoch};};
    auto initial=[](ProgressiveMacPlaybackEngine& e){const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(!e.getLoopSnapshot().initialPositionComplete){require(e.getPlaybackState()!=State::Failed,"loop initial failure");require(std::chrono::steady_clock::now()<deadline,"loop initial timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}};
    auto passed=[&](const char* name){log<<"{\"check\":\""<<name<<"\",\"PASS\":true}\n";log.flush();++checks;};
    {
        ProgressiveMacPlaybackEngine e;e.prepare(input);wait(e,State::Ready);require(!e.loopAvailability().optIn&&!e.requestLoopRange(0,rate,context(e)).accepted,"default loop ON");require(!e.capabilities().seek&&!e.loopAvailability().publicLoopApproved,"public gate changed");e.stop();passed("opt_in_and_public_gates");
    }
    for(auto preset:{Preset::Candidate,Preset::Baseline}){
        ProgressiveOptions o;o.allowExperimentalLoops=true;o.preset=preset;o.initialSpeed=2.;
        {
            ProgressiveMacPlaybackEngine e;e.prepare(input,o);wait(e,State::Ready);const auto c=context(e);auto first=e.requestLoopRange(17,rate+17,c);require(first.accepted,"range");initial(e);
            require(e.getCurrentPlaybackPosition().inputFrame==17,"Ready exact A");require(e.getLoopSnapshot().cycles==0,"initial counted cycle");
            require(!e.requestLoopRange(rate,17,context(e)).accepted&&e.getLoopSnapshot().id==first.id,"rejection replaced active loop");
            auto second=e.requestLoopRange(31,rate+31,context(e));require(second.accepted,"replace range");require(!e.requestClearLoop(first.id,c).accepted,"old clear affected new loop");initial(e);
            require(e.getLoopSnapshot().id==second.id,"late completion reversed loop");require(!e.requestClearLoop(second.id,{c.inputGeneration,c.session+1000,c.renderEpoch}).accepted,"old session clear");
            require(e.requestClearLoop(second.id,context(e)).accepted,"clear");require(e.getPlaybackState()==State::Ready&&!e.getLoopSnapshot().enabled,"clear auto played");e.stop();passed("ready_a_replace_reject_clear");
        }
        for(unsigned fault:{1u,2u}){
            auto faultOptions=o;faultOptions.seekFailureForTest=fault;ProgressiveMacPlaybackEngine e;e.prepare(input,faultOptions);wait(e,State::Ready);require(e.requestLoopRange(0,rate,context(e)).accepted,"fault admission");wait(e,State::Failed);const auto l=e.getLoopSnapshot();require(l.state==progressive::LoopState::Failed&&!l.enabled&&!l.cycles,"fault success fabricated");e.stop();passed(fault==1?"before_workgroup_failure":"before_publication_failure");
        }
        {
            ProgressiveMacPlaybackEngine e;e.prepare(input,o);wait(e,State::Ready);auto r=e.requestLoopRange(0,rate,context(e));require(r.accepted,"route loop");initial(e);require(e.play(),"route play");firstPcm(e);e.simulateDeviceChangeForTest();wait(e,State::Stopped);require(!e.getLoopSnapshot().enabled,"route kept loop");require(e.play(),"route explicit replay");wait(e,State::Playing);require(!e.getLoopSnapshot().enabled,"route revived loop");e.stop();passed("route_safe_stop_and_explicit_replay");
        }
        {
            const auto copy=output/(preset==Preset::Candidate?"input_candidate.wav":"input_baseline.wav");std::filesystem::copy_file(input,copy);ProgressiveMacPlaybackEngine e;e.prepare(copy,o);wait(e,State::Ready);require(e.requestLoopRange(0,rate,context(e)).accepted,"loss admission");initial(e);e.play();firstPcm(e);require(e.pause(),"input loss pause");std::filesystem::rename(copy,copy.string()+".unavailable");wait(e,State::Failed);require(!e.getLoopSnapshot().enabled&&!e.getLoopSnapshot().cycles&&e.getLoopSnapshot().state==progressive::LoopState::Failed&&!e.getLoopSnapshot().reason.empty(),"loss failure contract");e.stop();passed("input_path_loss");
        }
    }
    std::cout<<"PASS fault/control checks="<<checks<<'\n';return 0;
}
int physicalLoop(const std::filesystem::path& input,const std::filesystem::path& output){
    require(std::filesystem::create_directories(output),"physical output exists");
    struct DeviceRate {
        AudioDeviceID id=0;double original=0;bool changed=false,restored=false;
        AudioObjectPropertyAddress property{kAudioDevicePropertyNominalSampleRate,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        double get(){double value=0;UInt32 size=sizeof(value);require(AudioObjectGetPropertyData(id,&property,0,nullptr,&size,&value)==noErr,"physical rate query");return value;}
        void set(double value){require(AudioObjectSetPropertyData(id,&property,0,nullptr,sizeof(value),&value)==noErr,"physical rate set");const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);while(std::abs(get()-value)>1){require(std::chrono::steady_clock::now()<until,"physical rate wait");std::this_thread::sleep_for(std::chrono::milliseconds(10));}}
        void restore(){if(changed){set(original);restored=true;changed=false;}}
        ~DeviceRate(){if(changed)try{restore();}catch(...) {std::cerr<<"装置レート復元失敗\n";}}
    } device;
    ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.allowExperimentalLoops=true;o.initialSpeed=.5;e.prepare(input,o);wait(e,State::Ready);const auto n=e.getNativeDiagnostics();device.id=n.deviceId;device.original=device.get();
    const auto s=e.getStateSnapshot();require(e.requestLoopRange(0,e.getPlaybackDiagnostics().sourceSampleRate,{s.inputGeneration,s.session,s.renderEpoch}).accepted,"physical loop admission");
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(!e.getLoopSnapshot().initialPositionComplete){require(std::chrono::steady_clock::now()<deadline,"physical loop Ready");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    require(e.play(),"physical play");firstPcm(e);Boolean writable=false;require(AudioObjectIsPropertySettable(device.id,&device.property,&writable)==noErr&&writable,"physical rate not writable");
    device.changed=true;const auto other=std::abs(device.original-48000)<1?44100.:48000.;device.set(other);wait(e,State::Stopped);const auto reason=e.getStateSnapshot().reason;const auto routes=e.getNativeDiagnostics().routeChanges;
    require(reason==StopReason::RouteChanged&&routes>0&&!e.getLoopSnapshot().enabled,"physical safe stop");e.stop();device.restore();
    std::ofstream f(output/"result.json");f<<"{\"PASS\":true,\"original_rate\":"<<device.original<<",\"changed_rate\":"<<other<<",\"restored\":"<<(device.restored?"true":"false")<<",\"route_changes\":"<<routes<<",\"physical_cable_replug\":false}\n";return 0;
}
int main(int argc,char** argv){int code=1;std::thread control([&]{try{code=argc==4&&std::string(argv[3])=="--physical-loop"?physicalLoop(argv[1],argv[2]):argc==4&&std::string(argv[3])=="--faults"?runLoopFaults(argv[1],argv[2]):runLoopNative(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return code;}
