#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "Phase62FixTrace.h"
#include <chrono>
#include <iostream>
#include <thread>
using namespace ts::playback;
using State=progressive::State;
static void check(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
static void ready(ProgressiveMacPlaybackEngine& engine){
    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(40);
    while(engine.getPlaybackState()!=State::Ready){
        check(engine.getPlaybackState()!=State::Failed,engine.getPlaybackDiagnostics().error.c_str());
        check(std::chrono::steady_clock::now()<until,"Ready timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
}
int main(int argc,char** argv){
    if(argc!=4)return 1;int code=1;
    std::thread control([&]{try{
        const auto repeats=std::stoul(argv[3]);check(repeats>0&&repeats<=100,"repeat range");
        const std::filesystem::path out=argv[2];check(std::filesystem::create_directories(out),"existing evidence directory");
        std::ofstream rows(out/"rows.jsonl");std::uint64_t hosts=0,samples=0,hal=0,callbackDeadlines=0,workerDeadlines=0;
        bool functional=true;unsigned completed=0;
        for(unsigned repeat=0;repeat<repeats;++repeat){
            const auto folder=out/std::to_string(repeat);std::filesystem::create_directory(folder);
            ProgressiveMacPlaybackEngine engine;ProgressiveOptions options;
            options.initialSpeed=.4;options.preset=Preset::Candidate;
            options.allowExperimentalLoops=true; // enables fixed trace storage; no loop request is sent
            options.callbackRecordLimit=2048;engine.prepare(argv[1],options);ready(engine);
            check(engine.play(),"play");std::this_thread::sleep_for(std::chrono::milliseconds(250));check(engine.pause(),"pause");
            const auto d=engine.getPlaybackDiagnostics();const auto n=engine.getNativeDiagnostics();const auto loop=engine.getLoopSnapshot();
            check(!loop.enabled&&!loop.cycles,"unexpected loop");
            writePhase62Trace(folder/"callbacks_all_spans.jsonl",engine.loopCallbackRecords());
            writePhase62Trace(folder/"clock_anomaly_window.jsonl",engine.loopClockAnomalyRecords());
            engine.stop();const auto final=engine.getPlaybackDiagnostics();const auto& m=final.pipeline.scheduling;
            check(final.pipeline.finalDataAvailable&&!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"retirement");
            const auto h=n.hostMissing+n.hostBackwards+n.hostCadenceErrors;
            hosts+=h;samples+=n.sampleErrors;hal+=n.halWindowMisses;callbackDeadlines+=n.deadlineMisses;workerDeadlines+=final.workerDeadlineMisses;
            const bool good=!final.missingFrames&&!final.underrunCalls&&!final.rejectedWrites&&!final.workgroupErrors;
            functional&=good;++completed;
            rows<<"{\"repeat\":"<<repeat<<",\"functional_pass\":"<<(good?"true":"false")<<",\"loop_enabled\":false,\"cycles\":0,\"source_rate\":"<<d.sourceSampleRate<<",\"device_id\":"<<n.deviceId<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer\":"<<n.deviceBufferFrames<<",\"host_errors\":"<<h<<",\"sample_errors\":"<<n.sampleErrors<<",\"hal_window_misses\":"<<n.halWindowMisses<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"worker_deadlines\":"<<final.workerDeadlineMisses<<",\"missing_frames\":"<<final.missingFrames<<",\"input_sha256\":\""<<final.pipeline.inputSha256<<"\"}\n";rows.flush();
        }
        const bool clocks=!hosts&&!samples&&!hal,realtime=!callbackDeadlines&&!workerDeadlines;
        const bool pass=functional&&clocks&&realtime&&completed==repeats;
        std::ofstream summary(out/"summary.json");summary<<"{\"PASS\":"<<(pass?"true":"false")<<",\"functional_pass\":"<<(functional?"true":"false")<<",\"clock_pass\":"<<(clocks?"true":"false")<<",\"realtime_pass\":"<<(realtime?"true":"false")<<",\"expected\":"<<repeats<<",\"completed\":"<<completed<<",\"host_errors\":"<<hosts<<",\"sample_errors\":"<<samples<<",\"hal_window_misses\":"<<hal<<",\"callback_deadlines\":"<<callbackDeadlines<<",\"worker_deadlines\":"<<workerDeadlines<<",\"loop_requested\":false,\"acoustic_loopback\":null}\n";
        code=pass?0:2;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';}});control.join();return code;
}
