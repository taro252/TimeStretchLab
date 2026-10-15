// Isolated comparison of synchronous preparation and an asynchronous wrapper
// around exactly the SAME Phase54 full-track prepare/play barrier.
#include "playback/PlaybackEngine.h"
#include <future>
#include <iomanip>
#include <iostream>
#include <sys/resource.h>
using namespace ts::playback;
double cpu(){rusage r{};getrusage(RUSAGE_SELF,&r);return r.ru_utime.tv_sec+r.ru_utime.tv_usec*1e-6+r.ru_stime.tv_sec+r.ru_stime.tv_usec*1e-6;}
int main(int argc,char** argv){try{
    if(argc!=5)throw std::invalid_argument("Usage: phase55_startup_study input sync|async candidate|baseline speed");
    const bool async=std::string(argv[2])=="async";
    if(!async&&std::string(argv[2])!="sync")throw std::invalid_argument("Unknown mode");
    const bool baseline=std::string(argv[3])=="baseline";
    if(!baseline&&std::string(argv[3])!="candidate")throw std::invalid_argument("Unknown preset");
    auto cfg=baseline?Configuration::baseline(std::stod(argv[4])):Configuration::candidate(std::stod(argv[4]));
    cfg.analysisCache=std::make_shared<PlaybackAnalysisCache>();cfg.detailedDiagnostics=true;
    PlaybackEngine engine;
    for(unsigned pass=0;pass<2;++pass){
        StageClock overall;const auto startCpu=cpu();
        double prepareCompleted=0;
        auto work=[&]{if(!engine.prepare(argv[1],cfg))throw std::runtime_error(engine.getPlaybackDiagnostics().error);
            prepareCompleted=overall.elapsed().wallSeconds;
            if(!engine.play())throw std::runtime_error(engine.getPlaybackDiagnostics().error);};
        double dispatch=0;
        if(async){auto pending=std::async(std::launch::async,work);dispatch=overall.elapsed().wallSeconds;pending.get();}
        else {work();dispatch=overall.elapsed().wallSeconds;}
        const auto playable=overall.elapsed().wallSeconds;
        auto t=engine.getStartupDiagnostics();
        std::array<std::array<float,512>,2>b{};float* p[]{b[0].data(),b[1].data()};
        const auto got=engine.renderAudio(p,512,1); // offline pull, never an audio-device callback
        if(got.received!=512)throw std::runtime_error("Prepared FIFO not available");
        const auto firstPull=overall.elapsed().wallSeconds;
        const auto measuredCpu=cpu()-startCpu;
        engine.stop();const auto d=engine.getPlaybackDiagnostics();rusage r{};getrusage(RUSAGE_SELF,&r);
        std::cout<<std::setprecision(17)<<"{\"warm_analysis_cache\":"<<pass<<",\"async\":"<<async
            <<",\"dispatch_seconds\":"<<dispatch<<",\"playable_seconds\":"<<playable
            <<",\"first_offline_pull_seconds\":"<<firstPull<<",\"prepare_seconds\":"<<t.prepare.wallSeconds
            <<",\"analysis_seconds\":"<<t.analysis.wallSeconds<<",\"identity_seconds\":"<<t.identity.wallSeconds
            <<",\"analysis_completed_by_prepare_seconds\":"<<prepareCompleted
            <<",\"identity_analysis_stages_seconds\":"<<(t.identity.wallSeconds+t.analysis.wallSeconds)
            <<",\"first_generated_pcm_seconds\":null,\"first_device_callback_seconds\":null,\"callback_deadline_miss\":null"
            <<",\"prefill_seconds\":"<<t.prefill.wallSeconds<<",\"process_cpu_seconds\":"<<measuredCpu
            <<",\"peak_rss_bytes\":"<<r.ru_maxrss<<",\"analysis_bytes\":"<<t.analysisBytes
            <<",\"cache_resident_bytes\":"<<t.cacheResidentBytes<<",\"analysis_runs\":"<<t.analysisRuns
            <<",\"cache_hit\":"<<t.analysisHit<<",\"worker_max_seconds\":"<<d.maxWorkerWallSeconds
            <<",\"missing_frames\":"<<d.missingFrames<<",\"rejected_writes\":"<<d.rejectedWrites<<"}\n";
    }
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
