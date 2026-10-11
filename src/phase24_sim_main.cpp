#include "prototype/Phase24PlaybackPipeline.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <sys/resource.h>
#include <thread>
#include <vector>

int main(int argc,char** argv) {
    if (argc!=3) {
        std::cerr<<"Usage: phase24_sim input.wav switch-at-output-seconds\n";
        return 2;
    }
    try {
        using Clock=std::chrono::steady_clock;
        const auto begin=Clock::now();
        ts::prototype::Phase24PlaybackPipeline pipeline(argv[1]);
        const auto analyzed=Clock::now();
        pipeline.start();
        if (!pipeline.waitForPrefill(std::min<std::size_t>(16384,pipeline.inputFrames()*2),
                                     std::chrono::seconds(120)))
            throw std::runtime_error("Prefill timed out");
        const auto prefilled=Clock::now();
        constexpr std::array<std::size_t,7> blocks={64,128,256,512,1024,2048,4096};
        std::array<std::vector<float>,2> scratch={std::vector<float>(4096),std::vector<float>(4096)};
        float* ptr[]={scratch[0].data(),scratch[1].data()};
        std::uint64_t digest=14695981039346656037ULL;
        std::size_t pulls=0,nonfinite=0;
        float peak=0;
        bool requested=false;
        const auto threshold=static_cast<std::size_t>(std::stod(argv[2])*pipeline.sampleRate());
        const auto deadline=Clock::now()+std::chrono::minutes(10);
        while (!pipeline.drained()) {
            if (!requested && pipeline.snapshot().presented>=threshold) {
                if (!pipeline.requestThreeQuarter(pipeline.snapshot().presented))
                    throw std::runtime_error("Speed request rejected");
                requested=true;
            }
            const auto available=pipeline.available();
            if (!available) {
                if (pipeline.finished()) pipeline.rethrowWorkerError();
                if (Clock::now()>deadline) throw std::runtime_error("DSP timed out");
                std::this_thread::sleep_for(std::chrono::microseconds(100));
                continue;
            }
            const auto count=std::min(available,blocks[pulls%blocks.size()]);
            if (pipeline.pullAudio(ptr,count)!=count) throw std::runtime_error("FIFO underflow");
            for (std::size_t i=0;i<count;++i) for (std::size_t c=0;c<pipeline.channels();++c) {
                const auto value=scratch[c][i];
                if (!std::isfinite(value)) ++nonfinite;
                peak=std::max(peak,std::abs(value));
                std::uint32_t bits=0;
                std::memcpy(&bits,&value,4);
                digest^=bits;digest*=1099511628211ULL;
            }
            ++pulls;
        }
        pipeline.rethrowWorkerError();
        const auto result=pipeline.snapshot();
        pipeline.stop();
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        std::cout<<"analysis_seconds="<<std::chrono::duration<double>(analyzed-begin).count()<<'\n'
                 <<"prefill_seconds="<<std::chrono::duration<double>(prefilled-analyzed).count()<<'\n'
                 <<"processing_wall_seconds="<<std::chrono::duration<double>(Clock::now()-prefilled).count()<<'\n'
                 <<"input_frames="<<pipeline.inputFrames()<<'\n'
                 <<"output_frames="<<result.outputLength<<'\n'
                 <<"presented_frames="<<result.presented<<'\n'
                 <<"request_output="<<result.requestedOutput<<'\n'
                 <<"applied_output="<<result.appliedOutput<<'\n'
                 <<"completion_output="<<result.completionOutput<<'\n'
                 <<"fifo_high_water="<<result.fifoHighWater<<'\n'
                 <<"fifo_rejected_writes="<<result.rejectedWrites<<'\n'
                 <<"underrun_frames="<<result.underrunFrames<<'\n'
                 <<"peak="<<peak<<'\n'
                 <<"nonfinite="<<nonfinite<<'\n'
                 <<"max_worker_chunk_ms="<<result.maxWorkerChunkSeconds*1000<<'\n'
                 <<"peak_rss_mib="<<usage.ru_maxrss/1048576.0<<'\n'
                 <<"raw_digest="<<digest<<'\n';
        return requested && result.requestState==ts::prototype::SpeedRequestState::Applied &&
            !result.rejectedWrites && !result.underrunFrames && !nonfinite &&
            result.presented==result.outputLength ? 0 : 4;
    } catch (const std::exception& error) {
        std::cerr<<"Phase 24 simulator: "<<error.what()<<'\n';
        return 1;
    }
}
