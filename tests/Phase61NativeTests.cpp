#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase58Diagnostics.h"
#include "prototype/Phase58FixAllocationProbe.h"
#include "audio/WavStream.h"
#include <fstream>
#include <iostream>
#include <thread>
#include <cstdlib>

// Verification executable only. Counts C++ new, not malloc/Objective-C/VM.
namespace {thread_local bool callbackCounting=false;thread_local std::uint64_t callbackNew=0;
void note(){ts::prototype::phase58::noteDspAllocation();if(callbackCounting)++callbackNew;}}
void* operator new(std::size_t n){note();if(auto p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}
void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void* operator new(std::size_t n,std::align_val_t a){note();void* p=nullptr;if(posix_memalign(&p,std::size_t(a),n?n:1))throw std::bad_alloc();return p;}
void* operator new[](std::size_t n,std::align_val_t a){return ::operator new(n,a);}
void operator delete(void* p,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::align_val_t)noexcept{std::free(p);}
void operator delete(void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t,std::align_val_t)noexcept{std::free(p);}

using namespace ts::playback;using State=progressive::State;using Seek=progressive::SeekState;
namespace {
void require(bool v,const char* m){if(!v)throw std::runtime_error(m);}
struct Slot {std::uint64_t epoch=0,session=0,generation=0;std::size_t start=0,frames=0;std::vector<float> pcm;};
struct Capture {
    std::array<Slot,8> slots;std::size_t channels=0;std::atomic<std::size_t> errors{0};
    Capture(std::size_t ch,std::size_t maxFrames):channels(ch){for(auto& slot:slots)slot.pcm.resize(ch*maxFrames);}
    static void observe(void* context,const float*const* p,std::size_t n,std::size_t offset,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& x=*static_cast<Capture*>(context);Slot* selected=nullptr;
        for(auto& slot:x.slots)if(slot.epoch==epoch){selected=&slot;break;}
        if(!selected)for(auto& slot:x.slots)if(!slot.epoch){slot.epoch=epoch;slot.generation=generation;slot.session=session;slot.start=offset;selected=&slot;break;}
        if(!selected||selected->start+selected->frames!=offset||(selected->frames+n)*x.channels>selected->pcm.size()){++x.errors;return;}
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<x.channels;++c)selected->pcm[(selected->frames+i)*x.channels+c]=p[c][i];
        selected->frames+=n;
    }
};
void wait(ProgressiveMacPlaybackEngine& e,State target){const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(40);while(e.getPlaybackState()!=target){
    if(e.getPlaybackState()==State::Failed&&target!=State::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);
    require(std::chrono::steady_clock::now()<limit,"native state timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}}
progressive::SeekOperation waitSeek(ProgressiveMacPlaybackEngine& e,std::uint64_t id){const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(40);for(;;){
    for(const auto& op:e.seekHistory())if(op.id==id&&progressive::terminal(op.state)){if(op.state!=Seek::Completed)throw std::runtime_error("seek terminal: "+op.reason);return op;}
    if(e.getPlaybackState()==State::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);
    require(std::chrono::steady_clock::now()<limit,"native seek timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}}
void firstPcm(ProgressiveMacPlaybackEngine& e){const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(10);while(!e.getNativeDiagnostics().firstPcmMachNs){
    if(e.getPlaybackState()==State::Failed)throw std::runtime_error(e.getPlaybackDiagnostics().error);require(std::chrono::steady_clock::now()<limit,"first callback timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}}
}
int runPhase61Native(const std::filesystem::path& input,const std::filesystem::path& output){
    if(!std::filesystem::create_directories(output))throw std::runtime_error("Refusing an existing evidence directory");std::ofstream rows(output/"sessions.jsonl");
    std::size_t executions=0,functionalFailures=0,qualityFailures=0;
    for(auto preset:{Preset::Candidate,Preset::Baseline})for(const std::string kind:{"ready","playing","paused","burst","chain","speed","stop","route","input","eof"}){
        const auto name=std::string(preset==Preset::Candidate?"candidate_":"baseline_")+kind;
        auto folder=output/name;std::filesystem::create_directory(folder);std::string error;bool functional=true;
        auto source=input;if(kind=="input"){source=folder/"source.wav";std::filesystem::copy_file(input,source);}
        ts::WavStreamReader info(source);const auto n=info.frames();const auto rate=info.sampleRate();require(n<=rate*20,"Bounded native capture requires <=20s fixture");
        Capture capture(info.channels(),std::size_t(std::ceil(n*2.5))+2048);
        ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.preset=preset;o.initialSpeed=kind=="paused"?.4:.5;o.callbackRecordLimit=8192;
        o.observerContext=&capture;o.observeEpochPcm=Capture::observe;
        o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;},[]()noexcept{callbackCounting=false;},[]()noexcept{return callbackNew;}};
        std::uint64_t initialEpoch=0,requestId=0;
        try{
            e.prepare(source,o);wait(e,State::Ready);const auto initial=e.getStateSnapshot();initialEpoch=initial.renderEpoch;
            for(double bad:{-1.,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN(),double(n)/rate+1e-8})require(!e.requestSeekToInputSeconds(bad).accepted,"invalid seconds accepted");
            require(!e.requestSeekToInputFrame(n+1).accepted,"invalid frame accepted");
            require(!e.requestSeekToInputFrame(0,initial.inputGeneration+1).accepted,"stale input accepted");
            require(!e.requestSeekToInputFrame(0,0,initialEpoch+1).accepted,"stale render accepted");
            if(kind!="ready"&&kind!="eof"){require(e.play(),"play");firstPcm(e);}
            if(kind=="paused")require(e.pause(),"pause");
            const auto target=kind=="eof"?n:std::min(n,std::size_t(n*.65)+17);
            if(kind=="burst"){
                for(unsigned i=0;i<161;++i)require(e.setSpeed((40+i)/100.).result==ts::prototype::Phase39RequestResult::Accepted,"161 speed admission");
                require(e.setSpeed(.5).result==ts::prototype::Phase39RequestResult::Accepted,"restore requested speed");
                for(unsigned i=0;i<64;++i){auto r=e.requestSeekToInputFrame(target+i%17,initial.inputGeneration,initialEpoch);require(r.accepted,"burst seek");requestId=r.id;}
                require(!e.requestSeekToInputSeconds(std::numeric_limits<double>::quiet_NaN()).accepted,"invalid burst did not reject");
            }else{auto r=e.requestSeekToInputFrame(target,initial.inputGeneration,initialEpoch);require(r.accepted,"seek admission");requestId=r.id;}
            if(kind=="speed"){
                const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);bool preparing=false;
                while(!preparing){for(const auto& op:e.seekHistory())if(op.id==requestId)preparing=op.state==Seek::Preparing;
                    require(std::chrono::steady_clock::now()<until,"did not observe Preparing for speed replan");std::this_thread::sleep_for(std::chrono::milliseconds(2));}
                require(e.setSpeed(1.25).result==ts::prototype::Phase39RequestResult::Accepted,"speed during seek");
            }
            if(kind=="stop"){e.stop();require(e.getPlaybackState()==State::Stopped,"stop state");}
            else if(kind=="route"){e.simulateDeviceChangeForTest();wait(e,State::Stopped);require(e.getStateSnapshot().reason==StopReason::RouteChanged,"route reason");}
            else if(kind=="input"){std::filesystem::remove(source);wait(e,State::Failed);}
            else{
                auto completed=waitSeek(e,requestId);
                if(kind=="speed")require(completed.replans>0,"Preparing speed change did not replan the same ID");
                if(kind=="chain"){
                    std::this_thread::sleep_for(std::chrono::milliseconds(25));
                    const auto previous=completed;
                    const auto again=e.requestSeekToInputFrame(std::min(n,std::size_t(n*.85)+29),initial.inputGeneration,completed.renderEpoch);require(again.accepted,"second completed seek");requestId=again.id;completed=waitSeek(e,requestId);
                    require(e.getPlaybackDiagnostics().pipeline.checkpointUsed,"native checkpoint was not restored");
                    require(completed.renderEpoch!=previous.renderEpoch&&completed.session!=previous.session,"second seek epoch/session reused");
                    require(e.setSpeed(.75,previous.session,initial.inputGeneration,previous.renderEpoch).result==ts::prototype::Phase39RequestResult::Stopped,"previous seek speed epoch accepted");
                }
                const auto now=e.getStateSnapshot();
                require(now.inputGeneration==initial.inputGeneration&&now.session!=initial.session&&now.renderEpoch!=initialEpoch,"seek generation/session isolation");
                if(kind=="paused"||kind=="ready"||kind=="eof"){
                    require(e.getCurrentPlaybackPosition().outputFrame==completed.outputStartFrame,"Ready/Paused seek position mismatch");
                    require(e.getCurrentPlaybackPosition().inputFrame==completed.requestedInputFrame,"exact unconsumed input target lost");
                    require(e.getPlaybackDiagnostics().currentEpochPresentedFrame==completed.outputStartFrame,"old epoch logical position mixed");
                }
                require(e.setSpeed(.75,initial.session,initial.inputGeneration,initialEpoch).result==ts::prototype::Phase39RequestResult::Stopped,"old speed epoch accepted");
                if(kind=="paused"){
                    require(e.getPlaybackState()==State::Paused,"paused seek resumed");const auto at=e.getCurrentPlaybackPosition().outputFrame;
                    std::this_thread::sleep_for(std::chrono::milliseconds(40));require(e.getCurrentPlaybackPosition().outputFrame==at,"paused seek consumed");require(!completed.firstCallbackNs,"paused seek reported presentation");require(e.resume(),"resume");
                }else if(kind=="ready"||kind=="eof"){require(e.getPlaybackState()==State::Ready,"Ready seek autoplayed");require(e.play(),"play after Ready seek");}
                wait(e,State::Ended);
            }
            e.stop();for(const auto& op:e.seekHistory())require(progressive::terminal(op.state),"nonterminal seek after stop");
            require(!capture.errors,"callback epoch/order/capacity");
        }catch(const std::exception& ex){functional=false;error=ex.what();e.stop();}
        const auto d=e.getPlaybackDiagnostics();const auto native=e.getNativeDiagnostics();
        std::ofstream environment(folder/"environment.json");environment<<"{\"device_id\":"<<native.deviceId<<",\"device_rate\":"<<native.deviceRate<<",\"device_buffer_frames\":"<<native.deviceBufferFrames<<",\"source_rate\":"<<rate<<",\"callback_calls\":"<<native.callbackCalls<<",\"first_pcm_ns\":"<<native.firstPcmMachNs<<",\"callback_max_ns\":"<<native.maxCallbackNs<<",\"process_cpu_s\":"<<d.processCpuS<<",\"peak_rss_bytes\":"<<d.peakRssBytes<<",\"resident_bytes\":"<<d.residentInputBytes<<",\"reservation_bytes\":"<<d.reservationBytes<<"}\n";
        std::uint64_t workerDeadlines=d.pipeline.scheduling.deadlineMisses,workerNew=d.pipeline.realtimeNewCalls;bool lifetime=true;
        auto checkLifetime=[&](const auto& p){const auto& m=p.scheduling;lifetime&=!m.active&&m.joins==m.leaves&&m.leaves==m.restores&&!m.policyErrors&&!m.joinErrors&&!m.restoreErrors&&!m.intervalErrors&&!m.queryErrors&&!m.waitErrors&&!m.wakeErrors;};checkLifetime(d.pipeline);
        for(const auto& old:e.closedEpochs()){workerDeadlines+=old.pipeline.scheduling.deadlineMisses;workerNew+=old.pipeline.realtimeNewCalls;checkLifetime(old.pipeline);}
        const bool expectedInputFailure=kind=="input";
        const bool quality=!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!native.deadlineMisses&&!native.formatErrors&&!native.hostMissing&&!native.hostBackwards&&!native.hostCadenceErrors&&!native.sampleErrors&&!native.halWindowMisses&&!workerDeadlines&&!workerNew&&lifetime&&d.callbackCppNew&&!*d.callbackCppNew&&!capture.errors;
        executions++;functionalFailures+=!functional;qualityFailures+=!quality;
        const auto ops=e.seekHistory();
        std::ofstream seeks(folder/"seeks.json");seeks<<'[';bool comma=false;
        for(const auto& op:ops){if(comma)seeks<<',';comma=true;seeks<<"{\"id\":"<<op.id<<",\"state\":\""<<progressive::name(op.state)<<"\",\"input_generation\":"<<op.inputGeneration<<",\"source_epoch\":"<<op.sourceRenderEpoch<<",\"epoch\":"<<op.renderEpoch<<",\"session\":"<<op.session<<",\"input_frame\":"<<op.requestedInputFrame<<",\"output_start\":"<<op.outputStartFrame<<",\"speed_micros\":"<<op.speedMicros<<",\"accepted_ns\":"<<op.acceptedNs<<",\"preparing_ns\":"<<op.preparingNs<<",\"replans\":"<<op.replans<<",\"ready_ns\":"<<op.readyNs<<",\"switched_ns\":"<<op.switchedNs<<",\"first_callback_ns\":"<<op.firstCallbackNs<<",\"estimated_presentation_ns\":"<<op.estimatedPresentationNs<<",\"reason\":"<<ts::prototype::phase58::jsonString(op.reason)<<'}';}seeks<<"]\n";
        std::ofstream captures(folder/"captures.json");captures<<'[';comma=false;
        for(std::size_t i=0;i<capture.slots.size();++i){const auto& slot=capture.slots[i];if(!slot.epoch)continue;
            const auto path=folder/("epoch_"+std::to_string(slot.epoch)+".f32");std::ofstream f(path,std::ios::binary);f.write(reinterpret_cast<const char*>(slot.pcm.data()),slot.frames*info.channels()*sizeof(float));
            auto speed=std::uint32_t(std::llround(o.initialSpeed*1000000));for(const auto& op:ops)if(op.renderEpoch==slot.epoch)speed=op.speedMicros;
            if(comma)captures<<',';comma=true;captures<<"{\"path\":"<<ts::prototype::phase58::jsonString(path.string())<<",\"epoch\":"<<slot.epoch<<",\"session\":"<<slot.session<<",\"input_generation\":"<<slot.generation<<",\"start\":"<<slot.start<<",\"frames\":"<<slot.frames<<",\"channels\":"<<info.channels()<<",\"speed_micros\":"<<speed<<",\"complete_suffix\":"<<(slot.epoch!=initialEpoch&&slot.epoch==d.renderEpoch&&kind!="stop"&&kind!="route"&&kind!="input"?"true":"false")<<",\"fixed_oracle_applicable\":"<<(slot.epoch==initialEpoch&&(kind=="speed"||kind=="burst")?"false":"true")<<'}';
        }captures<<"]\n";
        std::ofstream callbacks(folder/"callbacks.csv");callbacks<<"sequence,clock_epoch,session,output_before,received,wanted,start_ns,end_ns,host_ns\n";for(const auto& r:e.callbackRecords())callbacks<<r.sequence<<','<<r.epoch<<','<<r.raw.session<<','<<r.raw.outputBefore<<','<<r.raw.received<<','<<r.raw.wanted<<','<<r.startNs<<','<<r.endNs<<','<<r.hostNs<<'\n';
        rows<<"{\"name\":\""<<name<<"\",\"functional\":"<<(functional?"true":"false")<<",\"quality\":"<<(quality?"true":"false")<<",\"expected_input_failure\":"<<(expectedInputFailure?"true":"false")<<",\"error\":"<<ts::prototype::phase58::jsonString(error)<<",\"missing\":"<<d.missingFrames<<",\"underruns\":"<<d.underrunCalls<<",\"callback_deadlines\":"<<native.deadlineMisses<<",\"callback_new\":"<<(d.callbackCppNew?std::to_string(*d.callbackCppNew):"null")<<",\"worker_deadlines\":"<<workerDeadlines<<",\"worker_new\":"<<workerNew<<",\"workgroup_lifetime\":"<<(lifetime?"true":"false")<<",\"host_cadence\":"<<native.hostCadenceErrors<<",\"sample_errors\":"<<native.sampleErrors<<",\"hal_misses\":"<<native.halWindowMisses<<",\"source_hash_passes\":"<<d.pipeline.sourceHashPasses<<",\"snapshots\":"<<d.pipeline.sourceSnapshotCreations<<",\"mlock_calls\":"<<d.pipeline.residentLockCalls<<",\"peak_rss_bytes\":"<<d.peakRssBytes<<",\"input_generation\":"<<d.inputGeneration<<"}\n";rows.flush();
        std::cout<<name<<" functional="<<functional<<" quality="<<quality<<" error="<<error<<'\n'<<std::flush;
    }
    std::ofstream summary(output/"summary.json");summary<<"{\"executions\":"<<executions<<",\"functional_failures\":"<<functionalFailures<<",\"quality_failures\":"<<qualityFailures<<",\"completed\":true}\n";
    return executions==20&&!functionalFailures&&!qualityFailures?0:2;
}
int runPhase61DeepNative(const std::filesystem::path& input,const std::filesystem::path& output){
    if(!std::filesystem::create_directories(output))throw std::runtime_error("Refusing an existing evidence directory");const auto folder=output/"candidate_deep";std::filesystem::create_directory(folder);
    ts::WavStreamReader info(input);const auto rate=info.sampleRate();require(info.frames()>=rate*300ULL,"Deep probe requires >=300s");
    // Test-host capture only: bounded 32s per epoch, independent of song length.
    Capture capture(info.channels(),rate*32ULL);ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.initialSpeed=.5;o.callbackRecordLimit=8192;
    o.observerContext=&capture;o.observeEpochPcm=Capture::observe;o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;},[]()noexcept{callbackCounting=false;},[]()noexcept{return callbackNew;}};
    bool functional=true;std::string error;std::vector<std::pair<std::uint64_t,double>> admissions;admissions.reserve(2);
    try{
        e.prepare(input,o);wait(e,State::Ready);require(e.play(),"deep play");firstPcm(e);
        for(unsigned seconds:{270u,285u}){
            const auto state=e.getStateSnapshot();const auto call=std::chrono::steady_clock::now();
            const auto receipt=e.requestSeekToInputFrame(rate*seconds,state.inputGeneration,state.renderEpoch);
            admissions.emplace_back(receipt.id,std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-call).count());require(receipt.accepted,"deep admission");
            const auto completed=waitSeek(e,receipt.id);require(completed.renderEpoch!=state.renderEpoch,"deep epoch reuse");
            require(e.getPlaybackDiagnostics().pipeline.checkpointUsed==(seconds==285),"deep checkpoint selection");
            const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(10);bool heard=false;
            while(!heard){for(const auto& op:e.seekHistory())if(op.id==receipt.id&&op.firstCallbackNs)heard=true;require(std::chrono::steady_clock::now()<until,"deep first callback timeout");std::this_thread::sleep_for(std::chrono::milliseconds(2));}
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }
        e.stop();require(!capture.errors,"deep capture capacity/order");
    }catch(const std::exception& ex){functional=false;error=ex.what();e.stop();}
    const auto d=e.getPlaybackDiagnostics();const auto native=e.getNativeDiagnostics();
    std::uint64_t deadlines=d.pipeline.scheduling.deadlineMisses,workerNew=d.pipeline.realtimeNewCalls;bool lifetime=true;
    auto check=[&](const auto& p){const auto& m=p.scheduling;lifetime&=!m.active&&m.joins==m.leaves&&m.leaves==m.restores&&!m.policyErrors&&!m.joinErrors&&!m.restoreErrors&&!m.intervalErrors&&!m.queryErrors&&!m.waitErrors&&!m.wakeErrors;};check(d.pipeline);
    for(const auto& old:e.closedEpochs()){check(old.pipeline);deadlines+=old.pipeline.scheduling.deadlineMisses;workerNew+=old.pipeline.realtimeNewCalls;}
    const bool quality=!d.missingFrames&&!d.underrunCalls&&!d.rejectedWrites&&!native.deadlineMisses&&!native.formatErrors&&!native.hostMissing&&!native.hostBackwards&&!native.hostCadenceErrors&&!native.sampleErrors&&!native.halWindowMisses&&!deadlines&&!workerNew&&lifetime&&d.callbackCppNew&&!*d.callbackCppNew&&!capture.errors;
    std::ofstream receiptLog(folder/"admissions.json");receiptLog<<'[';bool separate=false;for(const auto& item:admissions){if(separate)receiptLog<<',';separate=true;receiptLog<<"{\"seek_id\":"<<item.first<<",\"receipt_wall_ms\":"<<item.second<<'}';}receiptLog<<"]\n";receiptLog.close();
    const auto ops=e.seekHistory();std::ofstream seeks(folder/"seeks.json");seeks<<'[';bool comma=false;
    for(const auto& op:ops){if(comma)seeks<<',';comma=true;seeks<<"{\"id\":"<<op.id<<",\"state\":\""<<progressive::name(op.state)<<"\",\"input_generation\":"<<op.inputGeneration<<",\"source_epoch\":"<<op.sourceRenderEpoch<<",\"epoch\":"<<op.renderEpoch<<",\"session\":"<<op.session<<",\"input_frame\":"<<op.requestedInputFrame<<",\"output_start\":"<<op.outputStartFrame<<",\"speed_micros\":"<<op.speedMicros<<",\"accepted_ns\":"<<op.acceptedNs<<",\"preparing_ns\":"<<op.preparingNs<<",\"replans\":"<<op.replans<<",\"ready_ns\":"<<op.readyNs<<",\"switched_ns\":"<<op.switchedNs<<",\"first_callback_ns\":"<<op.firstCallbackNs<<",\"estimated_presentation_ns\":"<<op.estimatedPresentationNs<<",\"reason\":"<<ts::prototype::phase58::jsonString(op.reason)<<'}';}seeks<<"]\n";seeks.close();
    std::ofstream captures(folder/"captures.json");captures<<'[';comma=false;
    for(const auto& slot:capture.slots)if(slot.epoch){const auto path=folder/("epoch_"+std::to_string(slot.epoch)+".f32");std::ofstream raw(path,std::ios::binary);raw.write(reinterpret_cast<const char*>(slot.pcm.data()),slot.frames*info.channels()*4);
        if(comma)captures<<',';comma=true;captures<<"{\"path\":"<<ts::prototype::phase58::jsonString(path.string())<<",\"epoch\":"<<slot.epoch<<",\"session\":"<<slot.session<<",\"input_generation\":"<<slot.generation<<",\"start\":"<<slot.start<<",\"frames\":"<<slot.frames<<",\"channels\":"<<info.channels()<<",\"speed_micros\":500000,\"complete_suffix\":false,\"fixed_oracle_applicable\":true}";}captures<<"]\n";captures.close();
    std::ofstream callbacks(folder/"callbacks.csv");callbacks<<"sequence,clock_epoch,session,output_before,received,wanted,start_ns,end_ns,host_ns\n";for(const auto& r:e.callbackRecords())callbacks<<r.sequence<<','<<r.epoch<<','<<r.raw.session<<','<<r.raw.outputBefore<<','<<r.raw.received<<','<<r.raw.wanted<<','<<r.startNs<<','<<r.endNs<<','<<r.hostNs<<'\n';
    std::ofstream rows(output/"sessions.jsonl");rows<<"{\"name\":\"candidate_deep\",\"functional\":"<<(functional?"true":"false")<<",\"quality\":"<<(quality?"true":"false")<<",\"error\":"<<ts::prototype::phase58::jsonString(error)<<",\"missing\":"<<d.missingFrames<<",\"underruns\":"<<d.underrunCalls<<",\"callback_deadlines\":"<<native.deadlineMisses<<",\"callback_new\":"<<(d.callbackCppNew?std::to_string(*d.callbackCppNew):"null")<<",\"worker_deadlines\":"<<deadlines<<",\"worker_new\":"<<workerNew<<",\"workgroup_lifetime\":"<<(lifetime?"true":"false")<<",\"host_cadence\":"<<native.hostCadenceErrors<<",\"sample_errors\":"<<native.sampleErrors<<",\"hal_misses\":"<<native.halWindowMisses<<",\"source_hash_passes\":"<<d.pipeline.sourceHashPasses<<",\"snapshots\":"<<d.pipeline.sourceSnapshotCreations<<",\"mlock_calls\":"<<d.pipeline.residentLockCalls<<",\"peak_rss_bytes\":"<<d.peakRssBytes<<",\"reservation_bytes\":"<<d.reservationBytes<<",\"callback_max_ns\":"<<native.maxCallbackNs<<",\"input_generation\":"<<d.inputGeneration<<"}\n";rows.close();
    std::ofstream summary(output/"summary.json");summary<<"{\"executions\":1,\"seek_completions\":"<<ops.size()<<",\"functional_failures\":"<<!functional<<",\"quality_failures\":"<<!quality<<",\"completed\":true}\n";
    std::cout<<"deep native functional="<<functional<<" quality="<<quality<<" error="<<error<<'\n';return functional&&quality?0:2;
}

#ifndef PHASE61_SANDBOX_APP
int main(int argc,char** argv){if(argc!=3&&argc!=4)return 1;int code=1;std::thread control([&]{try{code=argc==4&&std::string(argv[3])=="--deep"?runPhase61DeepNative(argv[1],argv[2]):runPhase61Native(argv[1],argv[2]);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});control.join();return code;}
#endif
