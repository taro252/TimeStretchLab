#include "prototype/Phase39PlaybackPipeline.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <sys/resource.h>
#include <cstdlib>
#include <new>

#ifdef PHASE41_ALLOC_COUNT
namespace { thread_local std::uint64_t phase41NewCalls=0; }
void* operator new(std::size_t size) {
    if (void* ptr=std::malloc(size)) { ++phase41NewCalls; return ptr; }
    throw std::bad_alloc();
}
void* operator new[](std::size_t size) {
    if (void* ptr=std::malloc(size)) { ++phase41NewCalls; return ptr; }
    throw std::bad_alloc();
}
void operator delete(void* ptr) noexcept { std::free(ptr); }
void operator delete[](void* ptr) noexcept { std::free(ptr); }
void operator delete(void* ptr,std::size_t) noexcept { std::free(ptr); }
void operator delete[](void* ptr,std::size_t) noexcept { std::free(ptr); }
#endif

using namespace ts;
using namespace ts::prototype;
int main(int argc,char** argv) {
    if (argc<5 || argc>14 || argc==12 || argc==13) {
        std::cerr<<"Usage: phase39_sim input.wav output.wav initial_speed "
                    "output_seconds:target_speed[,...] [callback_frames] [plans.csv] [dsp_block_frames] [A|B|C|C0] [hold-density|delay-density|safe-density|normal] [profile.csv|-] [component.csv first last]\n";
        return 2;
    }
    try {
        const auto begin=std::chrono::steady_clock::now();
        rusage usageBefore{};getrusage(RUSAGE_SELF,&usageBefore);
        const auto initial=Phase39Speed::fromDouble(std::stod(argv[3]));
        const bool capture=std::string(argv[2])!="-";
        const std::size_t callback=argc>=6 ? std::stoull(argv[5]) : 512;
        if (callback<64 || callback>4096) throw std::invalid_argument("Callback frames");
        const std::size_t dspBlock=argc>=8 ? std::stoull(argv[7]) : 2048;
        const std::string strategy=argc>=9 ? argv[8] : "A";
        const auto planning=strategy=="A" ? Phase39Planning::A :
            strategy=="B" ? Phase39Planning::B :
            strategy=="C" ? Phase39Planning::C :
            strategy=="C0" ? Phase39Planning::C0 :
            throw std::invalid_argument("Planning strategy must be A, B, C or C0");
        const std::string densityOption=argc>=10 ? argv[9] : "";
        const auto densityDiagnostic=densityOption=="hold-density" ?
            Phase39DensityDiagnostic::HoldInitial : densityOption=="delay-density" ?
            Phase39DensityDiagnostic::AfterRamp : densityOption=="safe-density" ?
            Phase39DensityDiagnostic::SafeGuarded : Phase39DensityDiagnostic::Immediate;
        if (argc>=10 && densityOption!="hold-density" && densityOption!="delay-density" &&
            densityOption!="safe-density" && densityOption!="normal")
            throw std::invalid_argument("Unknown diagnostic density option");
        if ((densityDiagnostic==Phase39DensityDiagnostic::HoldInitial ||
             densityDiagnostic==Phase39DensityDiagnostic::AfterRamp) && initial.value()>=0.50)
            throw std::invalid_argument("Density diagnostic requires initial speed below 0.50");
        struct Request { std::size_t output; Phase39Speed speed; };
        std::vector<Request> requests;
        WavStreamReader reader(argv[1]);
        const auto rate=reader.sampleRate();
        const std::string schedule=argv[4];
        if (schedule!="-") {
            std::size_t start=0;
            while (start<schedule.size()) {
                const auto comma=schedule.find(',',start);
                const auto entry=schedule.substr(start,comma==std::string::npos ?
                    std::string::npos : comma-start);
                const auto colon=entry.find(':');
                if (colon==std::string::npos) throw std::invalid_argument("Schedule");
                requests.push_back({static_cast<std::size_t>(std::llround(
                    std::stod(entry.substr(0,colon))*rate)),
                    Phase39Speed::fromDouble(std::stod(entry.substr(colon+1)))});
                if (comma==std::string::npos) break;
                start=comma+1;
            }
        }
        if (densityDiagnostic==Phase39DensityDiagnostic::AfterRamp &&
            (requests.size()!=1 || requests[0].speed.value()<0.50))
            throw std::invalid_argument("delay-density supports one low-to-high request only");
        const bool profileEnabled=argc>=11 && std::string(argv[10])!="-";
        std::function<std::uint64_t()> allocationCounter;
#ifdef PHASE41_ALLOC_COUNT
        if (profileEnabled) allocationCounter=[] { return phase41NewCalls; };
#endif
        Phase39PlaybackPipeline pipeline(argv[1],initial,16384,dspBlock,12288,
            planning,densityDiagnostic,profileEnabled,
            argc==14 ? std::filesystem::path(argv[11]) : std::filesystem::path{},
            argc==14 ? std::stoull(argv[12]) : 0,
            argc==14 ? std::stoull(argv[13]) : 0,
            std::move(allocationCounter));
        pipeline.start();
        if (!pipeline.waitForPrefill(std::min<std::size_t>(8192,
            static_cast<std::size_t>(std::llround(reader.frames()*initial.timeRatio()))),
            std::chrono::seconds(120))) {
            if (pipeline.finished()) pipeline.rethrowWorkerError();
            throw std::runtime_error("Prefill timeout");
        }
        std::vector<std::vector<float>> output(reader.channels());
        std::vector<std::vector<float>> block(reader.channels(),std::vector<float>(callback));
        std::vector<float*> pointers(reader.channels());
        for (std::size_t c=0;c<reader.channels();++c) pointers[c]=block[c].data();
        std::size_t next=0,presented=0;
        double maxCallbackSeconds=0;
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::minutes(30);
        while (!pipeline.drained()) {
            const auto snapshot=pipeline.snapshot();
            if (next<requests.size() && presented>=requests[next].output &&
                (next==0 || (snapshot.state==Phase39RequestState::Applied &&
                             presented>=snapshot.completionOutput))) {
                const auto accepted=pipeline.requestSpeed(requests[next].speed,presented);
                if (accepted!=Phase39RequestResult::Accepted)
                    throw std::runtime_error("Speed request rejected");
                ++next;
            }
            const auto count=std::min(callback,pipeline.available());
            if (!count) {
                if (pipeline.finished()) pipeline.rethrowWorkerError();
                if (std::chrono::steady_clock::now()>deadline)
                    throw std::runtime_error("Simulation timeout");
                std::this_thread::sleep_for(std::chrono::microseconds(100));
                continue;
            }
            const auto callbackBegin=std::chrono::steady_clock::now();
            if (pipeline.pullAudio(pointers.data(),count)!=count)
                throw std::runtime_error("Unexpected FIFO underrun");
            maxCallbackSeconds=std::max(maxCallbackSeconds,
                std::chrono::duration<double>(std::chrono::steady_clock::now()-
                                              callbackBegin).count());
            if (capture) for (std::size_t c=0;c<reader.channels();++c)
                output[c].insert(output[c].end(),block[c].begin(),block[c].begin()+count);
            presented+=count;
        }
        pipeline.rethrowWorkerError();
        if (profileEnabled) {
            std::ofstream profile(argv[10]);
            profile<<"output_start,chunk_wall_s,chunk_thread_cpu_s,fifo_wait_s,cpp_new_calls,"
                "wav_wall_s,wav_cpu_s,fft_wall_s,fft_cpu_s,phase_wall_s,phase_cpu_s,"
                "ifft_ola_wall_s,ifft_ola_cpu_s,fir_wall_s,fir_cpu_s\n";
            for (const auto& block:pipeline.slowestBlocks()) {
                profile<<block.outputStart<<','<<block.chunkWallSeconds<<','
                    <<block.chunkCpuSeconds<<','<<block.fifoWaitSeconds<<','
                    <<block.cppNewCalls;
                for (const auto& stage:block.work.stages)
                    profile<<','<<stage.wallSeconds<<','<<stage.threadCpuSeconds;
                profile<<'\n';
            }
        }
        const auto snapshot=pipeline.snapshot();
        if (presented!=snapshot.outputLength || next!=requests.size() ||
            pipeline.planMetrics().size()!=requests.size() ||
            snapshot.underrunFrames || snapshot.rejectedWrites)
            throw std::runtime_error("EOS, request or FIFO mismatch");
        if (capture) {
            WavStreamWriter writer(argv[2],rate,reader.channels(),presented);
            std::vector<const float*> source(reader.channels());
            for (std::size_t start=0;start<presented;start+=4096) {
                const auto count=std::min<std::size_t>(4096,presented-start);
                for (std::size_t c=0;c<reader.channels();++c) source[c]=output[c].data()+start;
                writer.write(source.data(),count);
            }
            writer.finish();
        }
        if (argc>=7) {
            std::ofstream csv(argv[6]);
            csv<<"generation,requested_output,requested_input,from,target,planning_fence,"
                   "prepared,published,applied_frame,applied_output,completion_output,"
                   "density_input,map_bytes,plan_ms,next_low,next_mid,next_high,"
                   "last_low,last_mid,last_high,ola_low,ola_mid,ola_high,fir_low,fir_high,"
                   "paused_at_protected_events,first_mutable_frame,first_safe_frame,"
                   "next_event_frame,protection_end_frame,safe_frames_used,held_frames,"
                   "protected_events_skipped,density_candidates,density_hop_low,"
                   "density_hop_mid,density_hop_high,density_weight_low,"
                   "density_weight_mid,density_weight_high,hop_step_low,hop_step_mid,"
                   "hop_step_high,local_speed_low_min,local_speed_mid_min,"
                   "local_speed_high_min,local_speed_low_max,local_speed_mid_max,"
                   "local_speed_high_max\n";
            for (const auto& metric:pipeline.planMetrics())
                csv<<metric.generation<<','<<metric.requestedOutput<<','
                   <<metric.requestedInput<<','<<metric.from.value()<<','
                   <<metric.target.value()<<','<<metric.planningFence<<','
                   <<metric.prepared<<','<<metric.published<<','
                   <<metric.plan.appliedFrame<<','<<metric.plan.appliedOutputSample<<','
                   <<metric.plan.completionOutputSample<<','
                   <<metric.firstDensityChangedInput<<','<<metric.timeMapBytes<<','
                   <<metric.planMilliseconds<<','
                   <<metric.firstUnprocessedResolutionInputs[0]<<','
                   <<metric.firstUnprocessedResolutionInputs[1]<<','
                   <<metric.firstUnprocessedResolutionInputs[2]<<','
                   <<metric.lastProcessedResolutionInputs[0]<<','
                   <<metric.lastProcessedResolutionInputs[1]<<','
                   <<metric.lastProcessedResolutionInputs[2]<<','
                   <<metric.finalizedOla[0]<<','<<metric.finalizedOla[1]<<','
                   <<metric.finalizedOla[2]<<','
                   <<metric.firstUnprocessedFirSources[0]<<','
                   <<metric.firstUnprocessedFirSources[1]<<','
                   <<int(metric.plan.protectedEventsPaused)<<','
                   <<metric.plan.firstMutableFrame<<','<<metric.plan.firstSafeFrame<<','
                   <<metric.plan.nextEventFrame<<','<<metric.plan.protectionEndFrame<<','
                   <<metric.plan.safeFramesUsed<<','<<metric.plan.heldFrames<<','
                   <<metric.plan.protectedEventsSkipped<<','
                   <<metric.densityCandidatesTried<<','
                   <<metric.densityMaximumHop[0]<<','<<metric.densityMaximumHop[1]<<','
                   <<metric.densityMaximumHop[2]<<','
                   <<metric.densityMinimumWeight[0]<<','<<metric.densityMinimumWeight[1]<<','
                   <<metric.densityMinimumWeight[2]<<','
                   <<metric.densityMaximumHopStep[0]<<','<<metric.densityMaximumHopStep[1]<<','
                   <<metric.densityMaximumHopStep[2]<<','
                   <<metric.densityMinimumLocalSpeed[0]<<','
                   <<metric.densityMinimumLocalSpeed[1]<<','
                   <<metric.densityMinimumLocalSpeed[2]<<','
                   <<metric.densityMaximumLocalSpeed[0]<<','
                   <<metric.densityMaximumLocalSpeed[1]<<','
                   <<metric.densityMaximumLocalSpeed[2]<<'\n';
        }
        std::cout<<"frames="<<presented<<"\nchanges="<<next
                 <<"\nunderrun="<<snapshot.underrunFrames
                 <<"\nrejected_writes="<<snapshot.rejectedWrites
                 <<"\nfifo_high_water="<<snapshot.fifoHighWater
                 <<"\nmax_worker_chunk_seconds="<<snapshot.maxWorkerChunkSeconds
                 <<"\nmax_worker_cpu_seconds="<<snapshot.maxWorkerCpuSeconds
                 <<"\nmax_fifo_wait_seconds="<<snapshot.maxFifoWaitSeconds
                 <<"\nmax_fifo_write_seconds="<<snapshot.maxFifoWriteSeconds
                 <<"\nmax_history_mutex_wait_seconds="<<snapshot.maxHistoryMutexWaitSeconds
                 <<"\nplan_cpu_ms="<<snapshot.planCpuMilliseconds
                 <<"\nfifo_wait_seconds="<<double(snapshot.fifoWaitNanoseconds)/1e9
                 <<"\nworker_chunks_over_100ms="<<snapshot.workerChunksOver100Ms
                 <<"\np95_worker_chunk_seconds="<<pipeline.workerChunkP95Seconds()
                 <<"\np99_worker_chunk_seconds="<<pipeline.workerChunkP99Seconds()
                 <<"\nmax_callback_seconds="<<maxCallbackSeconds;
        rusage usageAfter{};getrusage(RUSAGE_SELF,&usageAfter);
        const auto seconds=[](const timeval& time) {
            return time.tv_sec+time.tv_usec/1000000.0;
        };
        std::cout<<"\nwall_seconds="<<std::chrono::duration<double>(
            std::chrono::steady_clock::now()-begin).count()
                 <<"\nuser_cpu_seconds="<<seconds(usageAfter.ru_utime)-
                    seconds(usageBefore.ru_utime)
                 <<"\npeak_rss_bytes="<<usageAfter.ru_maxrss
                 <<"\nmajor_faults="<<usageAfter.ru_majflt-usageBefore.ru_majflt
                 <<"\nminor_faults="<<usageAfter.ru_minflt-usageBefore.ru_minflt<<'\n';
        pipeline.stop();
    } catch (const std::exception& error) {
        std::cerr<<"Phase 39: "<<error.what()<<'\n';return 1;
    }
}
