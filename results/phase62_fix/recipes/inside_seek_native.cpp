#define PHASE61_SANDBOX_APP 1
#include "Phase61NativeTests.cpp"
#include "Phase61CallbackMallocProbe.h"
#include "Phase62PcmAudit.h"
#include "Phase62FixTrace.h"
#include <CoreAudio/CoreAudio.h>
static std::optional<unsigned> phase62ThreadCount(){
    thread_act_array_t threads=nullptr;mach_msg_type_number_t count=0;
    if(task_threads(mach_task_self(),&threads,&count)!=KERN_SUCCESS)return {};
    for(mach_msg_type_number_t i=0;i<count;++i)mach_port_deallocate(mach_task_self(),threads[i]);
    vm_deallocate(mach_task_self(),reinterpret_cast<vm_address_t>(threads),count*sizeof(thread_t));return count;
}
static std::vector<float> insideReference;
static std::atomic<std::uint64_t> insideIgnoredSession{UINT64_MAX},insideErrors{0},insideSamples{0};
static std::atomic<std::size_t> insideFirstMismatch{SIZE_MAX};
static std::size_t insideAOutput=0,insideIOutput=0,insideBOutput=0;
struct InsideFirst {std::atomic<std::uint64_t> session{0};std::size_t output=0;};
static std::array<InsideFirst,16> insideFirst;

static void insideSource(void* context,const float*const* p,std::size_t n,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
    LoopPcmAudit::source(context,p,n,at,generation,epoch,session);
    const auto ignored=insideIgnoredSession.load(std::memory_order_acquire);if(ignored==UINT64_MAX||session==ignored)return;
    auto& first=insideFirst[session%insideFirst.size()];if(first.session.load(std::memory_order_relaxed)!=session){first.output=at;first.session.store(session,std::memory_order_release);}
    const auto channels=static_cast<LoopPcmAudit*>(context)->channels;
    if((at+n)*channels>insideReference.size()){++insideErrors;return;}
    for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<channels;++c){
        const auto sample=(at+i)*channels+c;
        if(std::bit_cast<std::uint32_t>(p[c][i])!=std::bit_cast<std::uint32_t>(insideReference[sample])){++insideErrors;auto expected=SIZE_MAX;insideFirstMismatch.compare_exchange_strong(expected,sample);}
    }insideSamples.fetch_add(n*channels);
}
// Run on one dedicated normal control thread, exactly as an application bridge.
int runLoopNative(int argc,char** argv){
    require(argc>=3,"input output [seconds=.5] [speed=2] [cycles=10] [candidate|baseline] [controls|whole]");
    const std::filesystem::path output=argv[2];require(std::filesystem::create_directories(output),"existing evidence directory");
    ts::WavStreamReader info(argv[1]);const auto rate=info.sampleRate();const auto range=argc>3?std::stod(argv[3]):.5;
    const auto speed=argc>4?std::stod(argv[4]):2.;const auto cycles=argc>5?std::stoull(argv[5]):10;
    const std::string mode=argc>7?argv[7]:"normal";const auto a=argc>8?std::stoull(argv[8]):(mode=="whole"||mode=="compare")?0ULL:mode=="end"?std::uint64_t(info.frames()-std::llround(range*rate)):17ULL;
    const auto b=(mode=="whole"||mode=="end")?info.frames():std::min<std::uint64_t>(info.frames(),a+std::uint64_t(std::llround(range*rate)));
    ProgressiveOptions options;options.allowExperimentalLoops=true;options.allowUnvalidatedFastLocalSeek=true;options.initialSpeed=speed;
    options.preset=argc>6&&std::string(argv[6])=="baseline"?Preset::Baseline:Preset::Candidate;options.callbackRecordLimit=16384;
    require(argc>9,"independent RAW reference required");
    {std::ifstream file(argv[9],std::ios::binary|std::ios::ate);require(bool(file),"reference open");const auto bytes=std::size_t(file.tellg());require(bytes&&bytes%(sizeof(float)*info.channels())==0,"reference dimensions");insideReference.resize(bytes/sizeof(float));file.seekg(0);file.read(reinterpret_cast<char*>(insideReference.data()),std::streamsize(bytes));require(bool(file),"reference read");for(float v:insideReference)require(std::isfinite(v),"reference nonfinite");}
    {const auto rawPath=std::filesystem::path(argv[9]);std::ifstream file(rawPath.parent_path()/(rawPath.stem().string()+"_reference.log"));std::ostringstream text;text<<file.rdbuf();const auto meta=text.str();auto marker=meta.find("\"positions\"");require(marker!=std::string::npos,"reference position metadata missing");marker=meta.find('[',marker);require(marker!=std::string::npos,"reference position array missing");std::istringstream positions(meta.substr(marker+1));char separator=0;positions>>insideAOutput>>separator;require(separator==',',"reference position separator");positions>>insideIOutput>>separator;require(separator==',',"reference position separator");positions>>insideBOutput;require(bool(positions)&&insideAOutput<insideIOutput&&insideIOutput<insideBOutput&&insideBOutput<=insideReference.size()/info.channels(),"reference positions invalid");}
    LoopPcmAudit audit(info.channels());options.observerContext=&audit;options.observeEpochPcm=insideSource;options.observeOutputPcm=LoopPcmAudit::output;
    phase61_heap_reset();options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    const auto began=std::chrono::steady_clock::now();ProgressiveMacPlaybackEngine e;e.prepare(argv[1],options);wait(e,State::Ready);
    const auto c=e.getStateSnapshot();const progressive::LoopContext context{c.inputGeneration,c.session,c.renderEpoch};
    require(!e.requestLoopRange(0,1,context).accepted,"one frame execution accepted");
    require(!e.requestLoopRange(0,rate*99/1000,context).accepted,"99ms execution accepted");
    require(!e.requestLoopRange(a,b,{c.inputGeneration+1,c.session,c.renderEpoch}).accepted,"stale input accepted");
    progressive::LoopOptions lo;if(mode=="whole")lo.startPolicy=progressive::LoopStartPolicy::KeepPosition;
    const auto receipt=e.requestLoopRange(a,b,context,lo);require(receipt.accepted,"loop admission");
    // Cold preparation at A=270s has a separate 120s preparation budget.
    // This harness watchdog includes it; it is not a speed-response limit.
    const auto timeout=std::chrono::steady_clock::now()+std::chrono::seconds(std::uint64_t((double(b-a)/rate/speed+1)*(cycles+4))+150);
    auto poll=[&]{const auto l=e.getLoopSnapshot();if(l.state==progressive::LoopState::Failed)throw std::runtime_error(l.reason);require(std::chrono::steady_clock::now()<timeout,"loop timeout");return l;};
    if(mode!="whole")while(!poll().initialPositionComplete)std::this_thread::sleep_for(std::chrono::milliseconds(1));
    require(e.play(),"play");firstPcm(e);const auto rssStart=e.getPlaybackDiagnostics().rssBytes;
    std::ofstream rssLog(output/"rss_samples.jsonl");std::uint64_t lastRssCycle=UINT64_MAX;
    bool controlsDone=false;
    while(poll().cycles<cycles){
        const auto cycle=poll().cycles;if(cycle%100==0&&cycle!=lastRssCycle){const auto memory=e.getPlaybackDiagnostics();rssLog<<"{\"cycle\":"<<cycle<<",\"rss\":"<<memory.rssBytes<<",\"cpu_s\":"<<memory.processCpuS<<",\"wall_s\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count()<<",\"threads\":";const auto threadCount=phase62ThreadCount();if(threadCount)rssLog<<*threadCount;else rssLog<<"null";rssLog<<"}\n";rssLog.flush();lastRssCycle=cycle;}
        if(mode=="controls"&&!controlsDone&&poll().cycles>=2){
            require(e.pause(),"pause");const auto paused=e.getLoopSnapshot().cycles;std::this_thread::sleep_for(std::chrono::milliseconds(100));require(e.getLoopSnapshot().cycles==paused,"paused cycle advanced");
            const auto expectedAOutput=insideAOutput;
            auto current=e.getStateSnapshot();insideIgnoredSession.store(current.session,std::memory_order_release);auto r=e.setSpeed(.75,current.session,current.inputGeneration,current.renderEpoch);require(r.result==ts::prototype::Phase39RequestResult::Accepted,"loop speed");
            require(e.resume(),"resume");current=e.getStateSnapshot();const auto inside=a+(b-a)/2;auto seek=e.requestSeekToInputFrame(inside,current.inputGeneration,current.renderEpoch);require(seek.accepted,"out of range seek");auto done=waitSeek(e,seek.id);require(done.requestedInputFrame==inside,"inside seek coordinate changed");const auto position=e.getCurrentPlaybackPosition();require(done.outputStartFrame==insideIOutput,"inside seek map coordinate differs from independent oracle");
            const auto& first=insideFirst[done.session%insideFirst.size()];require(first.session.load(std::memory_order_acquire)==done.session&&first.output==insideIOutput,"first RAW did not start at requested independent output coordinate");
            require(position.inputFrame&&*position.inputFrame>=a&&*position.inputFrame<b&&position.sampledOutputFrame>=insideIOutput&&position.sampledOutputFrame<insideBOutput,"inside seek position sample outside requested output interval");
            while(poll().cycles<paused+2)std::this_thread::sleep_for(std::chrono::milliseconds(1));
            require(e.getLoopSnapshot().lastBoundary&&e.getLoopSnapshot().lastBoundary->newOutputStart==expectedAOutput,"inside seek did not return to original A");
            {std::ofstream value(output/"inside_seek.json");value<<"{\"PASS\":true,\"input_a\":"<<a<<",\"input_b_exclusive\":"<<b<<",\"requested_input\":"<<inside<<",\"observed_input\":"<<*position.inputFrame<<",\"return_output_a\":"<<expectedAOutput<<"}\n";}controlsDone=true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    require(e.pause(),"final pause");const auto loop=e.getLoopSnapshot();const auto savedHistory=e.loopHistory();const auto savedEpochs=e.closedEpochs().size();const auto measurementWall=std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count();const auto d=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();
    writePhase62Trace(output/"callbacks_all_spans.jsonl",e.loopCallbackRecords());writePhase62Trace(output/"clock_anomaly_window.jsonl",e.loopClockAnomalyRecords());
    rssLog<<"{\"cycle\":"<<loop.cycles<<",\"rss\":"<<d.rssBytes<<",\"cpu_s\":"<<d.processCpuS<<",\"wall_s\":"<<measurementWall<<",\"threads\":";const auto finalThreads=phase62ThreadCount();if(finalThreads)rssLog<<*finalThreads;else rssLog<<"null";rssLog<<"}\n";rssLog.flush();
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
    const auto afterClear=e.getLoopSnapshot();
    const auto clearState=e.getPlaybackState();
    const bool clearContinued=clearState==State::Playing||(b==info.frames()&&(clearState==State::Draining||clearState==State::Ended));
    require(!afterClear.enabled&&!afterClear.clearPending&&afterClear.state!=progressive::LoopState::Failed&&clearContinued,"clear did not continue or reach normal EOS");
    require(afterClear.cycles>=loop.cycles&&!afterClear.failurePaddingFrames&&!afterClear.outputAffectedFrames,"clear supply/count failed");
    require(afterClear.lastBoundary&&afterClear.cycles==afterClear.lastBoundary->cycle,"clear connection counted as repetition");
    require(e.getPlaybackDiagnostics().error.empty(),"clear retained playback failure");
    const auto clearNative=e.getNativeDiagnostics();const auto clearDiagnostics=e.getPlaybackDiagnostics();
    e.stop();require(!e.getLoopSnapshot().enabled,"stop loop enabled");
    writePhase62Trace(output/"after_clear_callbacks_all_spans.jsonl",e.loopCallbackRecords());
    {std::ofstream clearResult(output/"clear_result.json");clearResult<<"{\"PASS\":true,\"self_repeats_while_preparing\":"<<(afterClear.cycles-loop.cycles)<<",\"failure_padding_frames\":"<<afterClear.failurePaddingFrames<<",\"output_affected_frames\":"<<afterClear.outputAffectedFrames<<",\"missing_frames\":"<<clearDiagnostics.missingFrames<<",\"callback_deadlines\":"<<clearNative.deadlineMisses<<",\"host_errors\":"<<(clearNative.hostMissing+clearNative.hostBackwards+clearNative.hostCadenceErrors)<<",\"sample_errors\":"<<clearNative.sampleErrors<<",\"hal_window_misses\":"<<clearNative.halWindowMisses<<",\"connection_counted_as_cycle\":false}\n";}
    require(!audit.errors&&!audit.nonfinite,"clear mix audit");const auto original=e.getPlaybackDiagnostics();require(original.pipeline.finalDataAvailable,"loop stop final audit");
    for(const auto& closed:e.closedEpochs()){const auto& m=closed.pipeline.scheduling;require(closed.pipeline.finalDataAvailable&&!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"loop retirement audit");}
    for(const auto& closed:e.closedEpochs())if(closed.pipeline.session==d.pipeline.session){const auto& m=closed.pipeline.loopReuse;std::ofstream f(output/"loop_final_reuse.json");f<<std::setprecision(12)<<"{\"session\":"<<closed.pipeline.session<<",\"final_data_available\":"<<closed.pipeline.finalDataAvailable<<",\"input_sha256\":"<<ts::prototype::phase58::jsonString(closed.pipeline.inputSha256)<<",\"input_a\":"<<a<<",\"input_b_exclusive\":"<<b<<",\"applied_speed\":"<<loop.appliedSpeed<<",\"map_builds\":"<<m.mapBuilds<<",\"workers_created\":"<<m.workerCreations<<",\"fft_plans\":"<<m.fftPlanCreations<<",\"warm_fft_plans\":"<<m.warmFftPlanCreations<<",\"seed_clones\":"<<m.seedClones<<",\"cache_bytes\":"<<m.cacheBytes<<",\"reuse_count\":"<<m.cyclesPrepared<<",\"seed_restores\":"<<m.seedRestores<<",\"cold_discarded_frames\":"<<m.coldDiscardedFrames<<",\"warm_discarded_frames\":"<<m.warmDiscardedFrames<<",\"map_s\":"<<m.mapS<<",\"map_cpu_s\":"<<m.mapCpuS<<",\"analysis_wait_s\":"<<m.analysisWaitS<<",\"dsp_construct_s\":"<<m.dspConstructS<<",\"cold_prefix_s\":"<<m.coldPrefixS<<",\"cold_prefix_cpu_s\":"<<m.coldPrefixCpuS<<",\"cold_dsp_cpu_s\":"<<m.coldCpuS<<",\"warm_work_cpu_s\":"<<m.warmCpuS<<",\"restore_s\":"<<m.restoreS<<",\"join_s\":"<<m.joinS<<",\"dsp_worker_cpu_s\":"<<closed.pipeline.dspWorkerCpuS<<"}\n";}

    require(std::filesystem::is_regular_file(output/"loop_final_reuse.json")&&std::filesystem::file_size(output/"loop_final_reuse.json")>0,"missing final loop statistics");
    require(e.play(),"restart");wait(e,State::Playing);require(!e.getLoopSnapshot().enabled,"restart revived loop");e.stop();
    const auto workgroup=[](const auto& p){const auto& m=p.scheduling;require(p.finalDataAvailable&&!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"retirement Workgroup");};
    workgroup(e.getPlaybackDiagnostics().pipeline);for(const auto& epoch:e.closedEpochs())workgroup(epoch.pipeline);
    {std::ofstream value(output/"inside_reference.json");value<<"{\"PASS\":"<<(!insideErrors&&insideSamples?"true":"false")<<",\"samples_checked\":"<<insideSamples.load()<<",\"bit_errors\":"<<insideErrors.load()<<",\"first_mismatch_sample\":"<<insideFirstMismatch.load()<<",\"speed_micros\":750000}\n";}
    require(!insideErrors&&insideSamples,"inside independent RAW mismatch");
    std::ofstream f(output/"result.json");f<<std::setprecision(12)<<"{\"functional_pass\":true,\"cycles\":"<<loop.cycles<<",\"rate\":"<<rate<<",\"channels\":"<<info.channels()<<",\"speed\":"<<speed<<",\"range_seconds\":"<<range<<",\"input_a\":"<<a<<",\"input_b_exclusive\":"<<b<<",\"period_frames\":"<<loop.periodFrames<<",\"reuse_count\":"<<loop.reuseCount<<",\"map_builds\":"<<loop.mapBuilds<<",\"workers_created\":"<<loop.workerCreations<<",\"cache_bytes\":"<<loop.cacheBytes<<",\"seed_restores\":"<<loop.seedRestores<<",\"cold_discarded_frames\":"<<loop.coldDiscardedFrames<<",\"warm_discarded_frames\":"<<loop.warmDiscardedFrames<<",\"fft_plans\":"<<d.pipeline.loopReuse.fftPlanCreations<<",\"warm_fft_plans\":"<<d.pipeline.loopReuse.warmFftPlanCreations<<",\"seed_clones\":"<<d.pipeline.loopReuse.seedClones<<",\"map_s\":"<<d.pipeline.loopReuse.mapS<<",\"map_cpu_s\":"<<d.pipeline.loopReuse.mapCpuS<<",\"analysis_wait_s\":"<<d.pipeline.loopReuse.analysisWaitS<<",\"dsp_construct_s\":"<<d.pipeline.loopReuse.dspConstructS<<",\"cold_prefix_s\":"<<d.pipeline.loopReuse.coldPrefixS<<",\"cold_prefix_cpu_s\":"<<d.pipeline.loopReuse.coldPrefixCpuS<<",\"cold_dsp_cpu_s\":"<<d.pipeline.loopReuse.coldCpuS<<",\"warm_work_cpu_s\":"<<d.pipeline.loopReuse.warmCpuS<<",\"restore_s\":"<<d.pipeline.loopReuse.restoreS<<",\"output_affected_frames\":"<<loop.outputAffectedFrames<<",\"failure_padding_frames\":"<<loop.failurePaddingFrames<<",\"preset\":\""<<(options.preset==Preset::Candidate?"candidate":"baseline")<<"\",\"mode\":\""<<mode<<"\",\"raw_mix_errors\":"<<audit.errors<<",\"nonfinite\":"<<audit.nonfinite<<",\"zero_source_or_output_frames\":"<<audit.zeroFrames<<",\"safety_stop_frames\":"<<loop.safetyStopFrames<<",\"missing_frames\":"<<d.missingFrames<<",\"underrun_calls\":"<<d.underrunCalls<<",\"worker_deadlines\":"<<d.workerDeadlineMisses<<",\"worker_new\":"<<d.workerNewCalls<<",\"workgroup_errors\":"<<d.workgroupErrors<<",\"archived_epochs\":"<<d.archivedEpochCount<<",\"retained_epochs\":"<<savedEpochs<<",\"final_worker_deadlines\":"<<original.workerDeadlineMisses<<",\"final_worker_new\":"<<original.workerNewCalls<<",\"final_workgroup_errors\":"<<original.workgroupErrors<<",\"final_missing_frames\":"<<original.missingFrames<<",\"final_archived_epochs\":"<<original.archivedEpochCount<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"host_errors\":"<<(n.hostMissing+n.hostBackwards+n.hostCadenceErrors)<<",\"sample_errors\":"<<n.sampleErrors<<",\"hal_window_misses\":"<<n.halWindowMisses<<",\"invalid_sample_time_calls\":"<<n.invalidSampleTimeCalls<<",\"invalid_rate_scalar_calls\":"<<n.invalidRateScalarCalls<<",\"callback_new\":"<<d.callbackCppNew.value_or(UINT64_MAX)<<",\"callback_heap_calls\":"<<phase61_heap_allocations()<<",\"callback_frees\":"<<phase61_heap_frees()<<",\"process_cpu_s\":"<<d.processCpuS<<",\"wall_s\":"<<measurementWall<<",\"rss_start\":"<<rssStart<<",\"rss_end\":"<<d.rssBytes<<",\"peak_rss\":"<<d.peakRssBytes<<",\"ready_ms\":"<<(loop.readyNs-loop.acceptedNs)/1e6<<",\"last_prepare_ms\":"<<(loop.lastReadyNs>=loop.lastPreparationNs?std::to_string((loop.lastReadyNs-loop.lastPreparationNs)/1e6):std::string("null"))<<",\"max_prepare_ms\":"<<loop.maxPreparationNs/1e6<<",\"preparations\":"<<loop.preparationCount<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<"}\n";
    std::ofstream history(output/"boundaries.jsonl");for(const auto& event:savedHistory)history<<"{\"cycle\":"<<event.cycle<<",\"old_epoch\":"<<event.oldEpoch<<",\"new_epoch\":"<<event.newEpoch<<",\"old_output_end\":"<<event.oldOutputEnd<<",\"new_output_start\":"<<event.newOutputStart<<",\"callback_frame\":"<<event.callbackFrame<<",\"boundary_processing\":"<<event.boundaryProcessingFrames<<",\"overlap\":"<<event.overlapFrames<<",\"hal_boundary_estimate_ns\":"<<event.halBoundaryEstimateNs<<",\"render_ns\":"<<event.renderNs<<"}\n";
    if(loop.lastBoundary){const auto& v=*loop.lastBoundary;std::ofstream bfile(output/"last_boundary.json");bfile<<"{\"cycle\":"<<v.cycle<<",\"old_epoch\":"<<v.oldEpoch<<",\"new_epoch\":"<<v.newEpoch<<",\"input_a\":"<<v.inputA<<",\"input_b_exclusive\":"<<v.inputBExclusive<<",\"old_output_end\":"<<v.oldOutputEnd<<",\"new_output_start\":"<<v.newOutputStart<<",\"callback_frame\":"<<v.callbackFrame<<",\"boundary_processing\":"<<v.boundaryProcessingFrames<<",\"overlap\":"<<v.overlapFrames<<",\"hal_boundary_estimate_ns\":"<<v.halBoundaryEstimateNs<<",\"render_ns\":"<<v.renderNs<<"}\n";}
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
            auto tiny=o;tiny.memoryReservationBudget=1;ProgressiveMacPlaybackEngine e;e.prepare(input,tiny);wait(e,State::Failed);
            require(e.getPlaybackDiagnostics().error.find("メモリ予約")!=std::string::npos,"budget failure reason");
            require(!e.getLoopSnapshot().enabled&&!e.play(),"budget failure resumed");e.stop();passed("reservation_budget_failure");
        }
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
    ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.allowExperimentalLoops=true;o.initialSpeed=.5;e.prepare(input,o);wait(e,State::Ready);const auto n=e.getNativeDiagnostics();
    device.id=n.deviceId;device.original=device.get();
    const auto s=e.getStateSnapshot();require(e.requestLoopRange(0,e.getPlaybackDiagnostics().sourceSampleRate,{s.inputGeneration,s.session,s.renderEpoch}).accepted,"physical loop admission");
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(!e.getLoopSnapshot().initialPositionComplete){require(std::chrono::steady_clock::now()<deadline,"physical loop Ready");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    require(e.play(),"physical play");firstPcm(e);Boolean writable=false;require(AudioObjectIsPropertySettable(device.id,&device.property,&writable)==noErr&&writable,"physical rate not writable");
    device.changed=true;const auto other=std::abs(device.original-48000)<1?44100.:48000.;device.set(other);wait(e,State::Stopped);const auto reason=e.getStateSnapshot().reason;const auto routes=e.getNativeDiagnostics().routeChanges;
    require(reason==StopReason::RouteChanged&&routes>0&&!e.getLoopSnapshot().enabled,"physical safe stop");
    writePhase62Trace(output/"callbacks_all_spans.jsonl",e.loopCallbackRecords());writePhase62Trace(output/"clock_anomaly_window.jsonl",e.loopClockAnomalyRecords());e.stop();device.restore();
    std::ofstream f(output/"result.json");f<<"{\"PASS\":true,\"original_rate\":"<<device.original<<",\"changed_rate\":"<<other<<",\"restored\":"<<(device.restored?"true":"false")<<",\"route_changes\":"<<routes<<",\"physical_cable_replug\":false}\n";return 0;
}
#ifndef PHASE62_SANDBOX_APP
int main(int argc,char** argv){int code=1;std::thread control([&]{try{code=argc==4&&std::string(argv[3])=="--physical-loop"?physicalLoop(argv[1],argv[2]):argc==4&&std::string(argv[3])=="--faults"?runLoopFaults(argv[1],argv[2]):runLoopNative(argc,argv);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return code;}

#endif
