#pragma once
#include <chrono>
#include <ctime>
#include <cstdint>
namespace ts::playback {
struct StageTiming {double wallSeconds=0,threadCpuSeconds=0;};
inline double threadCpuSeconds(){timespec t{};if(clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t))return 0;return double(t.tv_sec)+t.tv_nsec*1e-9;}
struct StageClock {
    std::chrono::steady_clock::time_point wall=std::chrono::steady_clock::now();double cpu=threadCpuSeconds();
    StageTiming elapsed()const{return {std::chrono::duration<double>(std::chrono::steady_clock::now()-wall).count(),threadCpuSeconds()-cpu};}
};
struct StartupDiagnostics {
    StageTiming prepare,pipeline,metadata,identity,analysis,timeMap,workerInitialization,prefill;
    bool analysisHit=false,analysisSharedFlight=false;
    std::size_t analysisBytes=0,cacheResidentBytes=0,cacheLimitBytes=0;
    std::uint64_t analysisRuns=0,cacheHits=0,bytesHashed=0;
};
}
