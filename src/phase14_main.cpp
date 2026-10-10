#include "audio/WavStream.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <exception>
#include <iostream>
#include <memory>
#include <string>
#include <sys/resource.h>
#include <thread>
#include <vector>

namespace {
using Clock=std::chrono::steady_clock;
std::uint64_t fnv=14695981039346656037ULL;
void hash(float value) {
    std::uint32_t bits;
    std::memcpy(&bits,&value,sizeof bits);
    fnv^=bits;
    fnv*=1099511628211ULL;
}
}

int main(int argc,char** argv) {
    if (argc<3 || argc>6) {
        std::cerr << "Usage: phase14_sim input.wav output.wav|- [callback_frames=512] [worker_frames=8192] [accelerated_pace=0]\n";
        return 2;
    }
    try {
        const auto callbackFrames=argc>=4 ? std::stoul(argv[3]) : 512UL;
        const auto workerFrames=argc>=5 ? std::stoul(argv[4]) : 8192UL;
        const auto pace=argc>=6 ? std::stod(argv[5]) : 0.0;
        if (callbackFrames<64 || callbackFrames>4096) throw std::invalid_argument("Callback frames must be 64..4096");
        if (pace<0 || pace>32) throw std::invalid_argument("Pace factor must be 0..32");
        ts::WavStreamReader input(argv[1]);
        ts::StretchConfig config;
        config.sampleRate=input.sampleRate();
        config.channels=static_cast<int>(input.channels());
        config.timeRatio=2.0;
        config.enableMultiResolution=true;
        config.qualityMode=ts::QualityMode::Experimental;
        config.enablePhaseLocking=true;
        config.enableTransientHandling=true;
        config.enableAdaptiveTimeMapping=true;
        config.enablePreciseTransientAnchoring=true;
        config.enableStereoCoherence=true;
        ts::Phase14PlaybackPipeline pipeline(config,131072,workerFrames);
        pipeline.prepare(argv[1]);
        std::unique_ptr<ts::WavStreamWriter> writer;
        if (std::string(argv[2])!="-")
            writer=std::make_unique<ts::WavStreamWriter>(argv[2],input.sampleRate(),
                                                         input.channels(),pipeline.outputFrames());
        std::vector<std::vector<float>> scratch(input.channels(),std::vector<float>(callbackFrames));
        std::vector<float*> pointers(input.channels());
        std::vector<const float*> constPointers(input.channels());
        for (std::size_t c=0;c<input.channels();++c) {
            pointers[c]=scratch[c].data();
            constPointers[c]=scratch[c].data();
        }
        pipeline.start();
        const auto prefill=std::min<std::size_t>(16384,pipeline.outputFrames());
        if (!pipeline.waitForPrefill(prefill,std::chrono::seconds(60)))
            throw std::runtime_error("Prefill failed");
        double worstCallback=0;
        std::size_t pulled=0,callbackCalls=0;
        const auto playbackStart=Clock::now();
        while (pulled<pipeline.outputFrames()) {
            const auto request=std::min<std::size_t>(callbackFrames,pipeline.outputFrames()-pulled);
            if (pace>0) {
                const auto deadline=playbackStart+std::chrono::duration_cast<Clock::duration>(
                    std::chrono::duration<double>(double(pulled)/input.sampleRate()/pace));
                std::this_thread::sleep_until(deadline);
            } else {
                // Exact-output harness waits; paced mode never waits for the FIFO.
                while (pipeline.availableOutputFrames()<request) {
                    if (pipeline.workerFinished()) {
                        pipeline.rethrowWorkerError();
                        throw std::runtime_error("DSP finished before expected output length");
                    }
                    std::this_thread::sleep_for(std::chrono::microseconds(100));
                }
            }
            const auto begin=Clock::now();
            const auto count=pipeline.pullAudio(pointers.data(),request);
            worstCallback=std::max(worstCallback,std::chrono::duration<double>(Clock::now()-begin).count());
            if (count!=request) throw std::runtime_error("Unexpected FIFO underrun");
            ++callbackCalls;
            if (writer) writer->write(constPointers.data(),count);
            for (std::size_t i=0;i<count;++i) for (std::size_t c=0;c<input.channels();++c) {
                if (!std::isfinite(scratch[c][i])) throw std::runtime_error("Non-finite output sample");
                hash(scratch[c][i]);
            }
            pulled+=count;
        }
        if (writer) writer->finish();
        while (!pipeline.workerFinished()) std::this_thread::sleep_for(std::chrono::microseconds(100));
        pipeline.rethrowWorkerError();
        const auto stats=pipeline.statistics();
        if (!pipeline.drained() || pulled!=pipeline.outputFrames()) throw std::runtime_error("EOS not drained");
        pipeline.stop();
        rusage usage{};
        getrusage(RUSAGE_SELF,&usage);
        std::cout << "input_frames=" << input.frames() << '\n'
                  << "output_frames=" << pulled << '\n'
                  << "sample_fnv64=" << fnv << '\n'
                  << "analysis_seconds=" << stats.analysisSeconds << '\n'
                  << "dsp_seconds=" << stats.dspSeconds << '\n'
                  << "dsp_active_seconds=" << stats.dspActiveSeconds << '\n'
                  << "prefill_seconds=" << stats.prefillSeconds << '\n'
                  << "prefill_frames=" << prefill << '\n'
                  << "max_worker_chunk_seconds=" << stats.maxWorkerChunkSeconds << '\n'
                  << "max_callback_seconds=" << worstCallback << '\n'
                  << "callback_calls=" << callbackCalls << '\n'
                  << "fifo_high_water_frames=" << stats.fifoHighWaterFrames << '\n'
                  << "fifo_rejected_writes=" << stats.fifoRejectedWrites << '\n'
                  << "underrun_calls=" << stats.underrunCalls << '\n'
                  << "underrun_frames=" << stats.underrunFrames << '\n'
                  << "peak_rss_bytes=" << usage.ru_maxrss << '\n'
                  << "accelerated_pace=" << pace << '\n';
    } catch (const std::exception& error) {
        std::cerr << "Phase 14: " << error.what() << '\n';
        return 1;
    }
}
