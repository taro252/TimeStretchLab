// Unpaced correctness/performance probe. Its supply counts do not prove realtime safety.
#include "playback/Phase54ReferenceCheck.h"
#include <sys/resource.h>
#include <iostream>
#include <iomanip>
using namespace ts::playback;
double processCpu(){rusage r{};getrusage(RUSAGE_SELF,&r);return r.ru_utime.tv_sec+r.ru_utime.tv_usec*1e-6+r.ru_stime.tv_sec+r.ru_stime.tv_usec*1e-6;}
int main(int argc,char** argv){try{
    if(argc<6)throw std::invalid_argument("input speed candidate|baseline seconds [repeat|no-cache|once]");
    const double speed=std::stod(argv[2]),seconds=std::stod(argv[4]);const auto preset=std::string(argv[3])=="baseline"?Preset::Baseline:Preset::Candidate;
    const std::string mode=argv[5];auto config=preset==Preset::Candidate?Configuration::candidate(speed):Configuration::baseline(speed);
    config.verifyRawPcm=true;config.reuseAnalysis=mode!="no-cache";config.analysisCache=std::make_shared<PlaybackAnalysisCache>();
    PlaybackEngine engine;if(!engine.prepare(argv[1],config))throw std::runtime_error(engine.getPlaybackDiagnostics().error);
    std::cout<<std::setprecision(17)<<"attempt,input_seconds,seek_wall_s,process_cpu_s,analysis_hit,analysis_runs,bytes_hashed,analysis_bytes,rss_bytes,output_start,published_end,PCM_CORRECTNESS\n";
    for(unsigned attempt=0;attempt<(mode=="repeat"?3u:1u);++attempt){
        auto cpu=processCpu();auto id=engine.seekToInputSeconds(seconds);auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(120);SeekSnapshot seek;
        for(;;){seek=engine.getSeekSnapshot();if(seek.id==id&&seek.status!=SeekStatus::Pending&&seek.status!=SeekStatus::Preparing)break;
            if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("Seek timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
        const auto cpuElapsed=processCpu()-cpu;
        if(seek.status!=SeekStatus::Completed||seek.readyNs<seek.observedNs)throw std::runtime_error("Seek not completed: "+seek.reason);
        const auto start=engine.getPlaybackDiagnostics().outputStartFrame;
        // Freeze the prepared FIFO range for a finite independent prefix comparison.
        engine.stop();const auto diag=engine.getPlaybackDiagnostics();const auto timing=engine.getStartupDiagnostics();
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        auto expected=verification::referenceHash(argv[1],speed,preset,{},start,diag.producedFrames);
        const bool matches=engine.rawPcmSha()==expected;
        std::cout<<attempt<<','<<seconds<<','<<double(seek.readyNs-seek.observedNs)*1e-9<<','<<cpuElapsed<<','<<timing.analysisHit<<','<<timing.analysisRuns<<','<<timing.bytesHashed<<','<<timing.analysisBytes<<','<<usage.ru_maxrss<<','<<start<<','<<diag.producedFrames<<','<<(matches?"PASS":"FAIL")<<'\n';
        if(!matches||diag.missingFrames||!diag.error.empty())return 2;
        if(attempt+1<(mode=="repeat"?3u:1u)&&!engine.prepare(argv[1],config))throw std::runtime_error("Repeat prepare failed");
    }
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
