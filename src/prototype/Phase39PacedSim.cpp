#include "prototype/Phase39PlaybackPipeline.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

int main(int argc,char** argv) {
    if (argc!=5 && argc!=7) {
        std::cerr<<"Usage: phase39_paced_sim input.wav initial_speed target_speed request_seconds "
                    "[fifo_frames lead_frames]\n";
        return 2;
    }
    try {
        const ts::WavStreamReader reader(argv[1]);
        const auto initial=ts::prototype::Phase39Speed::fromDouble(std::stod(argv[2]));
        const auto target=ts::prototype::Phase39Speed::fromDouble(std::stod(argv[3]));
        const auto requestAt=static_cast<std::size_t>(std::llround(
            std::stod(argv[4])*reader.sampleRate()));
        const auto fifo=argc==7 ? std::stoull(argv[5]) : 16384;
        const auto lead=argc==7 ? std::stoull(argv[6]) : 12288;
        ts::prototype::Phase39PlaybackPipeline pipeline(argv[1],initial,fifo,2048,lead);
        pipeline.start();
        if (!pipeline.waitForPrefill(std::min<std::size_t>(lead,8192),std::chrono::seconds(30)))
            throw std::runtime_error("prefill timeout");
        constexpr std::size_t block=512;
        std::vector<std::vector<float>> buffers(reader.channels(),std::vector<float>(block));
        std::vector<float*> pointers(reader.channels());
        for (std::size_t c=0;c<reader.channels();++c) pointers[c]=buffers[c].data();
        auto deadline=std::chrono::steady_clock::now();
        const auto period=std::chrono::duration<double>(double(block)/reader.sampleRate());
        bool requested=false;
        std::size_t callbacks=0,readFrames=0,missed=0;
        double maxCallback=0;
        while (!pipeline.drained()) {
            deadline+=std::chrono::duration_cast<std::chrono::steady_clock::duration>(period);
            std::this_thread::sleep_until(deadline);
            if (!requested && callbacks*block>=requestAt) {
                const auto answer=pipeline.requestSpeed(target,readFrames);
                if (answer!=ts::prototype::Phase39RequestResult::Accepted)
                    throw std::runtime_error("request not accepted");
                requested=true;
            }
            const auto begin=std::chrono::steady_clock::now();
            const auto expected=pipeline.finished() ?
                std::min(block,pipeline.snapshot().outputLength-readFrames) : block;
            const auto count=pipeline.pullAudio(pointers.data(),expected);
            const auto duration=std::chrono::duration<double>(
                std::chrono::steady_clock::now()-begin).count();
            maxCallback=std::max(maxCallback,duration);
            readFrames+=count;missed+=expected-count;++callbacks;
            if (callbacks>reader.frames()*3/block+1000)
                throw std::runtime_error("paced simulation did not reach EOS");
        }
        pipeline.rethrowWorkerError();
        const auto snapshot=pipeline.snapshot();
        std::cout<<"read_frames="<<readFrames<<" output_frames="<<snapshot.outputLength
                 <<"\nmissed_frames="<<missed
                 <<"\nunderrun_frames="<<snapshot.underrunFrames
                 <<"\nrejected_writes="<<snapshot.rejectedWrites
                 <<"\nmax_callback_seconds="<<maxCallback
                 <<"\nmax_worker_chunk_seconds="<<snapshot.maxWorkerChunkSeconds
                 <<"\nplans="<<pipeline.planMetrics().size()<<'\n';
        pipeline.stop();
        if (!requested || pipeline.planMetrics().size()!=1 ||
            readFrames!=snapshot.outputLength) return 1;
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"Phase 39 paced simulation: "<<error.what()<<'\n';
        return 1;
    }
}
