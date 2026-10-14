#include "playback/PlaybackEngine.h"
#include "platform/macos/MacPlaybackEngine.h"
#include "prototype/Phase47EvidenceFile.h"
#include "audio/WavStream.h"
#include "audio/WavWriter.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cmath>
#include <new>
#include <cstdlib>
#include <sys/resource.h>
using namespace ts;using namespace ts::playback;
namespace {
thread_local bool inCallback=false;std::atomic<std::uint64_t> allocations{0};
void enter()noexcept{inCallback=true;}void leave()noexcept{inCallback=false;}std::uint64_t count()noexcept{return allocations.load();}
std::uint64_t ns(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
struct Action {double seconds;std::string type;double value=0;};
void exportPlans(const std::filesystem::path& p,const std::vector<ts::prototype::Phase39PlanMetric>& plans){
    prototype::Phase47EvidenceFile f(p);auto& s=f.stream();s<<std::setprecision(17)<<"generation,requested_output,requested_input,from,target,fence,prepared,published,applied_frame,applied_output,completion_output,density_input,map_bytes,plan_ms,state_preserved\n";
    for(auto& r:plans)s<<r.generation<<','<<r.requestedOutput<<','<<r.requestedInput<<','<<r.from.value()<<','<<r.target.value()<<','<<r.planningFence<<','<<r.prepared<<','<<r.published<<','<<r.plan.appliedFrame<<','<<r.plan.appliedOutputSample<<','<<r.plan.completionOutputSample<<','<<r.firstDensityChangedInput<<','<<r.timeMapBytes<<','<<r.planMilliseconds<<','<<r.phase50StatePreserved<<'\n';f.commit();
}
void exportHistory(const std::filesystem::path& p,const std::vector<SpeedOperation>& ops){prototype::Phase47EvidenceFile f(p);auto& s=f.stream();s<<std::setprecision(17)<<"id,session,generation,observed_ns,sent_ns,completed_ns,target,status,apply_output,complete_output\n";for(auto& o:ops)s<<o.id<<','<<o.session<<','<<o.generation<<','<<o.observedNs<<','<<o.sentNs<<','<<o.completedNs<<','<<o.target<<','<<name(o.status)<<','<<o.applyOutput<<','<<o.completeOutput<<'\n';f.commit();}
void exportWorkers(const std::filesystem::path& p,const std::vector<prototype::Phase39BlockProfile>& rows){prototype::Phase47EvidenceFile f(p);auto& s=f.stream();s<<std::setprecision(17)<<"cycle,start_ns,published_ns,frames,fifo_after,wall_s,cpu_s,dsp_wall_s,dsp_cpu_s,fifo_wait_s,write_s,mutex_wait_s,mutex_hold_s,plan_wall_s,publication_interval_s\n";for(auto& r:rows)s<<r.cycleSequence<<','<<r.startMachNs<<','<<r.publishedMachNs<<','<<r.publicationFrames<<','<<r.fifoAfterWrite<<','<<r.fullCycleWallSeconds<<','<<r.fullCycleCpuSeconds<<','<<r.chunkWallSeconds<<','<<r.chunkCpuSeconds<<','<<r.fifoWaitSeconds<<','<<r.fifoWriteSeconds<<','<<r.mutexWaitSeconds<<','<<r.mutexHoldSeconds<<','<<r.planWallSeconds<<','<<r.publicationIntervalSeconds<<'\n';f.commit();}
void exportCallbacks(const std::filesystem::path& path,const std::vector<MacCallbackRecord>& callbacks){
    prototype::Phase47EvidenceFile cf(path);auto& cs=cf.stream();cs<<std::setprecision(17)<<"sequence,epoch,start_ns,end_ns,io_end_ns,host_ns,sample_time,flags,requested,wanted,received,output,generation,fifo_before,last_publication_ns\n";
    for(auto& r:callbacks)cs<<r.sequence<<','<<r.epoch<<','<<r.startNs<<','<<r.endNs<<','<<r.ioEndNs<<','<<r.hostNs<<','<<r.sampleTime<<','<<r.timestampFlags<<','<<r.requested<<','<<r.raw.wanted<<','<<r.raw.received<<','<<r.raw.outputBefore<<','<<r.raw.generation<<','<<r.raw.fifoBefore<<','<<r.raw.lastPublicationNs<<'\n';cf.commit();
}
void saveSummary(const std::filesystem::path& out,const std::string& preset,double finalSessionInitial,std::uint32_t sourceRate,std::size_t channels,
    const Diagnostics& d,const MacDiagnostics& native,PlaybackState finalState,const std::string& hash,bool offline,
    double prepareSeconds,double wall,bool priorAudioFail,bool priorMeasurementFail,std::size_t callbackRows,std::size_t workerRows,std::size_t planRows,std::size_t operationRows){
    rusage usage{};getrusage(RUSAGE_SELF,&usage);double cpu=usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6+usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6;
    bool audio=!priorAudioFail&&d.missingFrames==0&&d.rejectedWrites==0&&d.error.empty()&&d.concurrentRenders==0&&native.deadlineMisses==0&&native.formatErrors==0&&native.callbackCppAllocations==0;
    bool measurement=!priorMeasurementFail&&native.hostMissing==0&&native.hostBackwards==0&&native.hostCadenceErrors==0&&native.sampleErrors==0&&native.halWindowMisses==0&&native.callbackRecordsDropped==0&&native.error.empty();
    bool eos=finalState==PlaybackState::Ended&&d.reason==StopReason::EndOfStream&&d.consumedFrames==d.outputLength;
    bool route=d.reason==StopReason::RouteChanged&&finalState==PlaybackState::Stopped;
        prototype::Phase47EvidenceFile f(out/"summary.txt");auto& s=f.stream();s<<std::setprecision(17)<<"preset="<<preset<<"\ninitial="<<finalSessionInitial<<"\nsession="<<d.session<<"\noffline="<<offline<<"\nstate="<<name(finalState)<<"\nreason="<<name(d.reason)<<"\nAUDIO_QUALITY="<<(audio?"PASS":"FAIL")<<"\nMEASUREMENT_QUALITY="<<(measurement?"PASS":"FAIL")<<"\neos="<<eos<<"\nroute_stopped="<<route<<"\noutput_frames="<<d.outputLength<<"\nproduced_frames="<<d.producedFrames<<"\nsample_rate="<<sourceRate<<"\ncallback_calls="<<native.callbackCalls<<"\nconsumed_frames="<<d.consumedFrames<<"\npresented_frames="<<d.presentedFrames<<"\nmissing_frames="<<d.missingFrames<<"\nunderrun_calls="<<d.underrunCalls<<"\nmax_continuous_missing="<<d.maxContinuousMissingFrames<<"\nrejected_writes="<<d.rejectedWrites<<"\ncallback_allocations_measured="<<native.allocationMeasured<<"\ncallback_cpp_allocations="<<native.callbackCppAllocations<<"\ncallback_max_ns="<<native.maxCallbackNs<<"\ncallback_overruns="<<native.deadlineMisses<<"\nhost_missing="<<native.hostMissing<<"\nhost_backwards="<<native.hostBackwards<<"\nhost_cadence_errors="<<native.hostCadenceErrors<<"\nsample_errors="<<native.sampleErrors<<"\nhal_window_misses="<<native.halWindowMisses<<"\nrecords_dropped="<<native.callbackRecordsDropped<<"\ndevice="<<native.deviceId<<"\ndevice_rate="<<native.deviceRate<<"\ndevice_buffer="<<native.deviceBufferFrames<<"\ndevice_latency_ms="<<native.devicePresentationLatencyMs<<"\nbridge_steady_ns="<<native.bridgeSteadyNs<<"\nbridge_mach_ns="<<native.bridgeMachNs<<"\nbridge_uncertainty_ns="<<native.bridgeUncertaintyNs<<"\nsource_latency_ms="<<native.sourcePresentationLatencyMs<<"\nworker_max_wall_s="<<d.maxWorkerWallSeconds<<"\nworker_max_cpu_s="<<d.maxWorkerCpuSeconds<<"\nprepare_s="<<prepareSeconds<<"\nplayback_wall_s="<<wall<<"\ncpu_seconds="<<cpu<<"\nmax_rss="<<usage.ru_maxrss<<"\nraw_pcm_sha256="<<hash<<'\n';
        s<<"channels="<<channels<<"\ngenerated_frames="<<d.generatedFrames<<"\npublished_frames="<<d.producedFrames<<"\ndevice_raw_frames="<<d.consumedFrames
         <<"\nworker_error="<<d.error<<"\nnative_error="<<native.error<<"\nconcurrent_renders="<<d.concurrentRenders
         <<"\nhash_scope=fifo_published_raw_float32_interleaved_prefix\nhash_frames="<<d.producedFrames
         <<"\nfifo_frames=16384\nlead_frames="<<(preset=="candidate"?16384:12288)<<"\nblock_frames=2048\nqos=inherited\nPCM_CORRECTNESS=INDETERMINATE\nCSV_INTEGRITY=INDETERMINATE\nSESSION_VERDICT=INDETERMINATE\nstart_state=Playing\ncallback_rows="<<callbackRows<<"\nworker_rows="<<workerRows<<"\nplan_rows="<<planRows<<"\noperation_rows="<<operationRows
         <<"\nlast_pcm_target_end_ns="<<native.lastPcmTargetEndNs<<"\noutput_stopped_mach_ns="<<native.outputStoppedMachNs<<'\n';f.commit();
}

}
void* operator new(std::size_t n){if(inCallback)allocations.fetch_add(1);if(auto p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void*p)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){if(inCallback)allocations.fetch_add(1);void*p=nullptr;if(posix_memalign(&p,static_cast<std::size_t>(a),n?n:1))throw std::bad_alloc();return p;}
void* operator new[](std::size_t n,std::align_val_t a){return ::operator new(n,a);}void operator delete(void*p,std::align_val_t)noexcept{std::free(p);}void operator delete[](void*p,std::align_val_t)noexcept{std::free(p);}
int main(int argc,char**argv){
    if(argc<5){std::cerr<<"playback_demo input.wav output_dir candidate|baseline initial_speed [--offline] [--silent] [--actions file.csv] [--stall-ms n]\n";return 1;}
    try{
        const std::filesystem::path input=argv[1],out=argv[2];if(std::filesystem::exists(out/"summary.txt"))throw std::runtime_error("Refusing to overwrite run evidence");std::filesystem::create_directories(out);
        const std::string preset=argv[3];if(preset!="candidate"&&preset!="baseline")throw std::invalid_argument("Preset");
        auto config=preset=="candidate"?Configuration::candidate(std::stod(argv[4])):Configuration::baseline(std::stod(argv[4]));config.verifyRawPcm=true;config.detailedDiagnostics=true;
        std::uint32_t sourceRate=0;std::size_t sourceChannels=0,callbackRows=0;bool priorAudioFail=false,priorMeasurementFail=false;double finalSessionInitial=0;finalSessionInitial=config.initialSpeed;bool verifyDraining=false,drainVerified=false;bool offline=false,silent=false;std::vector<Action> actions;
        for(int i=5;i<argc;++i){std::string a=argv[i];if(a=="--verify-draining")verifyDraining=true;else if(a=="--offline")offline=true;else if(a=="--silent")silent=true;else if(a=="--stall-ms"&&i+1<argc){config.verificationHooks.controlledStallMs=std::stod(argv[++i]);config.verificationHooks.controlledOutput=48000*2;config.verificationHooks.controlledStock=config.leadFrames();}else if(a=="--actions"&&i+1<argc){std::ifstream f(argv[++i]);if(!f)throw std::runtime_error("Actions missing");std::string line;std::getline(f,line);while(std::getline(f,line)){std::replace(line.begin(),line.end(),',',' ');std::istringstream row(line);Action v;if(!(row>>v.seconds>>v.type))throw std::runtime_error("Actions invalid");row>>v.value;if(!std::isfinite(v.seconds)||v.seconds<0||(!actions.empty()&&v.seconds<actions.back().seconds))throw std::runtime_error("Action order");actions.push_back(v);}}else throw std::invalid_argument("Unknown argument");}
        Diagnostics d;MacDiagnostics native;PlaybackState finalState;std::string hash;std::vector<SpeedOperation> ops;std::vector<prototype::Phase39PlanMetric> plans;std::vector<prototype::Phase39BlockProfile> workers;
        auto prepareStart=ns();std::uint64_t playStart=0;double prepareSeconds=0,wall=0;
        if(offline){
            if(!actions.empty())throw std::invalid_argument("Offline schedule uses native commands; use fixed offline plus reference replay");
            PlaybackEngine e;if(!e.prepare(input,config)||!e.play())throw std::runtime_error(e.getPlaybackDiagnostics().error);sourceRate=e.sampleRate();sourceChannels=e.channels();prepareSeconds=(ns()-prepareStart)/1e9;playStart=ns();
            AudioBuffer audio;audio.sampleRate=e.sampleRate();audio.channels.resize(e.channels());std::vector<std::vector<float>> block(e.channels(),std::vector<float>(4096));std::vector<float*> ptr;for(auto& b:block)ptr.push_back(b.data());
            while(e.getPlaybackState()==PlaybackState::Playing){auto n=std::min<std::size_t>(4096,e.getPlaybackDiagnostics().fifoAvailable);if(!n){std::this_thread::sleep_for(std::chrono::microseconds(200));continue;}enter();auto r=e.renderAudio(ptr.data(),n,ns());leave();for(std::size_t c=0;c<ptr.size();++c)audio.channels[c].insert(audio.channels[c].end(),ptr[c],ptr[c]+r.received);}
            finalState=e.getPlaybackState();d=e.getPlaybackDiagnostics();hash=e.rawPcmSha();plans=e.plans();workers=e.workerProfiles();ops=e.operationHistory();WavWriter::write(out/"raw.wav",audio);wall=(ns()-playStart)/1e9;
            native.allocationMeasured=true;native.callbackCppAllocations=count();
        }else{
            MacPlaybackEngine e;MacOptions mo;mo.playbackGain=silent?0:.5f;mo.recordCallbacks=true;mo.allocationHooks={enter,leave,count};
            if(!e.prepare(input,config,mo))throw std::runtime_error("Prepare failed: "+e.getPlaybackDiagnostics().error+e.getNativeDiagnostics().error);sourceRate=e.sampleRate();sourceChannels=e.channels();prepareSeconds=(ns()-prepareStart)/1e9;if(!e.play())throw std::runtime_error("Play failed");playStart=ns();
            prototype::Phase47EvidenceFile af(out/"actions.csv");auto& as=af.stream();as<<std::setprecision(17)<<"planned_seconds,observed_ns,type,value,result,output,input,state\n";
            std::size_t index=0;bool routeExpected=false;unsigned restart=0;std::vector<std::pair<std::uint64_t,std::string>> sessionFolders;
            while(true){double elapsed=(ns()-playStart)/1e9;
                while(index<actions.size()&&elapsed>=actions[index].seconds){auto a=actions[index++];auto at=ns();bool ok=true;std::uint64_t id=0;if(a.type=="speed")id=e.setSpeed(a.value);else if(a.type=="pause")ok=e.pause();else if(a.type=="resume")ok=e.resume();else if(a.type=="stop"){
                    e.stop();auto closed=e.getPlaybackDiagnostics();auto nd=e.getNativeDiagnostics();
                    priorAudioFail|=closed.missingFrames||closed.rejectedWrites||!closed.error.empty()||closed.concurrentRenders||nd.deadlineMisses||nd.formatErrors||nd.callbackCppAllocations;
                    priorMeasurementFail|=nd.hostMissing||nd.hostBackwards||nd.hostCadenceErrors||nd.sampleErrors||nd.halWindowMisses||nd.callbackRecordsDropped||!nd.error.empty();
                    auto folder=out/("closed_session_"+std::to_string(closed.session));std::filesystem::create_directory(folder);
                    auto cp=e.plans();auto cw=e.workerProfiles();auto co=e.operationHistory();auto cb=e.callbackRecords();
                    exportPlans(folder/"plans.csv",cp);exportHistory(folder/"operations.csv",co);exportWorkers(folder/"workers.csv",cw);exportCallbacks(folder/"callbacks.csv",cb);
                    saveSummary(folder,preset,finalSessionInitial,sourceRate,sourceChannels,closed,nd,e.getPlaybackState(),e.rawPcmSha(),false,prepareSeconds,(ns()-playStart)/1e9,false,false,cb.size(),cw.size(),cp.size(),co.size());
                    sessionFolders.emplace_back(closed.session,folder.filename().string());
                }else if(a.type=="play"){finalSessionInitial=e.getRequestedSpeed();ok=e.play();++restart;}else if(a.type=="route"){e.simulateDeviceChangeForTest();routeExpected=true;}else throw std::invalid_argument("Unknown action");auto p=e.getCurrentPlaybackPosition();as<<a.seconds<<','<<at<<','<<a.type<<','<<a.value<<','<<(id?id:ok)<<','<<p.outputFrame<<','<<p.inputFrame<<','<<name(e.getPlaybackState())<<'\n';if(!ok)throw std::runtime_error("Lifecycle action rejected");}
                auto state=e.getPlaybackState();if(state==PlaybackState::Draining&&verifyDraining&&!drainVerified){
                    for(unsigned repeat=0;repeat<8;++repeat){
                        try{(void)e.callbackRecords();throw std::runtime_error("Callback export permitted during drain");}
                        catch(const std::logic_error&){}
                        if(e.getNativeDiagnostics().outputStoppedMachNs)throw std::runtime_error("Diagnostic export stopped audio early");
                    }
                    if(e.play())throw std::runtime_error("Restart permitted during output drain");bool refused=false;
                    try{e.prepare(input,config,mo);}catch(const std::logic_error&){refused=true;}
                    if(!refused)throw std::runtime_error("Prepare permitted during output drain");drainVerified=true;
                }if(state==PlaybackState::Ended||state==PlaybackState::Failed||(state==PlaybackState::Stopped&&routeExpected))break;
                if(elapsed>1800)throw std::runtime_error("Playback timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));
            }
            af.commit();finalState=e.getPlaybackState();d=e.getPlaybackDiagnostics();hash=e.rawPcmSha();plans=e.plans();workers=e.workerProfiles();ops=e.operationHistory();wall=(ns()-playStart)/1e9;
            if(verifyDraining&&finalState==PlaybackState::Ended){auto tail=e.getNativeDiagnostics();if(tail.outputStoppedMachNs<tail.lastPcmTargetEndNs+5000000)throw std::runtime_error("EOS ended before render-tail deadline");}
            std::vector<MacCallbackRecord> callbacks;
            const auto exportLimit=std::chrono::steady_clock::now()+std::chrono::seconds(1);
            for(;;){try{callbacks=e.callbackRecords();break;}catch(const std::logic_error&){
                if(std::chrono::steady_clock::now()>=exportLimit)throw;
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }}
            callbackRows=callbacks.size();native=e.getNativeDiagnostics();exportCallbacks(out/"callbacks.csv",callbacks);
            sessionFolders.emplace_back(d.session,".");
            prototype::Phase47EvidenceFile manifest(out/"sessions.csv");manifest.stream()<<"session,folder\n";
            for(auto& [id,folder]:sessionFolders)manifest.stream()<<id<<','<<folder<<'\n';manifest.commit();

            prototype::Phase47EvidenceFile sf(out/"lifecycle.txt");sf.stream()<<"drain_guard_verified="<<drainVerified<<"\nroute_expected="<<routeExpected<<"\nrestarts="<<restart<<"\nremaining_actions="<<actions.size()-index<<'\n';sf.commit();
        }
        exportPlans(out/"plans.csv",plans);exportHistory(out/"operations.csv",ops);exportWorkers(out/"workers.csv",workers);
        bool audio=!priorAudioFail&&d.missingFrames==0&&d.rejectedWrites==0&&d.error.empty()&&d.concurrentRenders==0&&native.deadlineMisses==0&&native.formatErrors==0&&native.callbackCppAllocations==0;
        bool measurement=!priorMeasurementFail&&native.hostMissing==0&&native.hostBackwards==0&&native.hostCadenceErrors==0&&native.sampleErrors==0&&native.halWindowMisses==0&&native.callbackRecordsDropped==0&&native.error.empty();
        bool eos=finalState==PlaybackState::Ended&&d.reason==StopReason::EndOfStream&&d.consumedFrames==d.outputLength;
        bool route=d.reason==StopReason::RouteChanged&&finalState==PlaybackState::Stopped;
        saveSummary(out,preset,finalSessionInitial,sourceRate,sourceChannels,d,native,finalState,hash,offline,prepareSeconds,wall,priorAudioFail,priorMeasurementFail,callbackRows,workers.size(),plans.size(),ops.size());

        std::cout<<"audio="<<(audio?"PASS":"FAIL")<<" measurement="<<(measurement?"PASS":"FAIL")<<" independent_pcm_verification=REQUIRED eos="<<eos<<" missing="<<d.missingFrames<<'\n';return audio&&measurement&&(eos||route)&&(!verifyDraining||drainVerified)?0:2;
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
