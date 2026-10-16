#include "platform/macos/MacPlaybackEngine.h"
#include "prototype/Phase58Diagnostics.h"
#include <fstream>
#include <iostream>
#include <sys/resource.h>
using namespace ts::playback;
namespace ph=ts::prototype::phase58;
static std::uint64_t steadyNs(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
int main(int argc,char** argv){try{
    if(argc!=5)throw std::invalid_argument("input candidate|baseline speed_micros fresh_output");
    const std::filesystem::path out=argv[4];if(std::filesystem::exists(out))throw std::runtime_error("Fresh output required");std::filesystem::create_directories(out);
    const std::string preset=argv[2];if(preset!="candidate"&&preset!="baseline")throw std::invalid_argument("preset");
    const auto micros=std::stoul(argv[3]);if(micros<400000||micros>2000000||micros%10000)throw std::invalid_argument("speed");
    auto config=preset=="candidate"?Configuration::candidate(double(micros)/1000000):Configuration::baseline(double(micros)/1000000);config.verifyRawPcm=true;config.detailedDiagnostics=true;
    MacPlaybackEngine engine;MacOptions options;options.recordCallbacks=true;options.playbackGain=.5f;
    for(unsigned run=0;run<2;++run){
        const auto processCpu=[](){rusage u{};getrusage(RUSAGE_SELF,&u);return u.ru_utime.tv_sec+u.ru_utime.tv_usec*1e-6+u.ru_stime.tv_sec+u.ru_stime.tv_usec*1e-6;};const auto cpuStart=processCpu();const auto start=steadyNs();double prepared=-1;
        if(!run){if(!engine.prepare(argv[1],config,options))throw std::runtime_error("Legacy prepare failed");prepared=double(steadyNs()-start)*1e-9;}
        const auto play=steadyNs();if(!engine.play())throw std::runtime_error("Legacy play failed");const auto playReturned=steadyNs();
        std::this_thread::sleep_for(std::chrono::seconds(1));engine.stop();
        const auto n=engine.getNativeDiagnostics();const auto c=engine.getPlaybackDiagnostics();const auto s=engine.getStartupDiagnostics();const auto records=engine.callbackRecords();
        double workerCpu=0;for(const auto& p:engine.workerProfiles())workerCpu+=p.fullCycleCpuSeconds;
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        const auto firstSteady=static_cast<std::int64_t>(n.firstPcmMachNs)+static_cast<std::int64_t>(n.bridgeSteadyNs)-static_cast<std::int64_t>(n.bridgeMachNs);
        std::ofstream result(out/(run?"warm.json":"cold.json"));result<<std::setprecision(17)<<"{\"first_pcm_measured\":"<<(n.firstPcmMachNs!=0)<<",\"preset\":"<<ph::jsonString(preset)<<",\"speed_micros\":"<<micros<<",\"device_id\":"<<n.deviceId<<",\"device_rate\":"<<n.deviceRate<<",\"device_buffer_frames\":"<<n.deviceBufferFrames
            <<",\"prepare_return_s\":"<<prepared<<",\"play_requested_s\":"<<double(play-start)*1e-9<<",\"play_return_s\":"<<double(playReturned-start)*1e-9<<",\"first_callback_s\":"<<(n.firstPcmMachNs?double(firstSteady-static_cast<std::int64_t>(start))*1e-9:-1)
            <<",\"play_to_first_callback_s\":"<<(n.firstPcmMachNs?double(firstSteady-static_cast<std::int64_t>(play))*1e-9:-1)<<",\"metadata_s\":"<<s.metadata.wallSeconds<<",\"identity_s\":"<<s.identity.wallSeconds<<",\"analysis_s\":"<<s.analysis.wallSeconds<<",\"map_s\":"<<s.timeMap.wallSeconds<<",\"prefill_s\":"<<s.prefill.wallSeconds
            <<",\"bridge_uncertainty_s\":"<<double(n.bridgeUncertaintyNs)*1e-9<<",\"startup_timing_valid\":"<<(n.firstPcmMachNs&&n.bridgeUncertaintyNs<=1000000)
            <<",\"analysis_cpu_s\":"<<s.analysis.threadCpuSeconds<<",\"published_worker_cycle_cpu_s\":"<<workerCpu<<",\"process_cpu_s\":"<<processCpu()-cpuStart<<",\"peak_rss_bytes\":"<<usage.ru_maxrss
            <<",\"av_construction_s\":"<<n.avConstruction.wallSeconds<<",\"av_start_s\":"<<n.avStart.wallSeconds<<",\"analysis_hit\":"<<s.analysisHit<<",\"bytes_hashed\":"<<s.bytesHashed<<",\"raw_published_frames\":"<<c.producedFrames<<",\"raw_consumed_frames\":"<<c.consumedFrames<<",\"raw_sha256\":"<<ph::jsonString(engine.rawPcmSha())
            <<",\"callback_calls\":"<<n.callbackCalls<<",\"callback_max_ns\":"<<n.maxCallbackNs<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"hal_misses\":"<<n.halWindowMisses<<",\"host_missing\":"<<n.hostMissing<<",\"host_backwards\":"<<n.hostBackwards<<",\"host_cadence_errors\":"<<n.hostCadenceErrors<<",\"sample_errors\":"<<n.sampleErrors<<",\"format_errors\":"<<n.formatErrors<<",\"missing_frames\":"<<c.missingFrames<<",\"rejected_writes\":"<<c.rejectedWrites
            <<",\"allocation_measured\":false,\"callback_cpp_allocations\":null,\"error\":"<<ph::jsonString(c.error+n.error)<<"}\n";
        if(!n.firstPcmMachNs||records.empty()||!c.error.empty()||!n.error.empty())throw std::runtime_error("Legacy startup not measured");
    }
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
