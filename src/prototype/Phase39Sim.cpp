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

using namespace ts;
using namespace ts::prototype;
int main(int argc,char** argv) {
    if (argc<5 || argc>8) {
        std::cerr<<"Usage: phase39_sim input.wav output.wav initial_speed "
                    "output_seconds:target_speed[,...] [callback_frames] [plans.csv] [dsp_block_frames]\n";
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
        Phase39PlaybackPipeline pipeline(argv[1],initial,16384,dspBlock,12288);
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
                   "paused_at_protected_events\n";
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
                   <<int(metric.plan.protectedEventsPaused)<<'\n';
        }
        std::cout<<"frames="<<presented<<"\nchanges="<<next
                 <<"\nunderrun="<<snapshot.underrunFrames
                 <<"\nrejected_writes="<<snapshot.rejectedWrites
                 <<"\nfifo_high_water="<<snapshot.fifoHighWater
                 <<"\nmax_worker_chunk_seconds="<<snapshot.maxWorkerChunkSeconds
                 <<"\np95_worker_chunk_seconds="<<pipeline.workerChunkP95Seconds()
                 <<"\nmax_callback_seconds="<<maxCallbackSeconds;
        rusage usageAfter{};getrusage(RUSAGE_SELF,&usageAfter);
        const auto seconds=[](const timeval& time) {
            return time.tv_sec+time.tv_usec/1000000.0;
        };
        std::cout<<"\nwall_seconds="<<std::chrono::duration<double>(
            std::chrono::steady_clock::now()-begin).count()
                 <<"\nuser_cpu_seconds="<<seconds(usageAfter.ru_utime)-
                    seconds(usageBefore.ru_utime)
                 <<"\npeak_rss_bytes="<<usageAfter.ru_maxrss<<'\n';
        pipeline.stop();
    } catch (const std::exception& error) {
        std::cerr<<"Phase 39: "<<error.what()<<'\n';return 1;
    }
}
