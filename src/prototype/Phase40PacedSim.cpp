#include "prototype/Phase39PlaybackPipeline.h"
#include "audio/WavStream.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>
#include <atomic>
#include <array>
#include <cstdlib>
#include <sys/resource.h>

using namespace ts;
using namespace ts::prototype;
namespace {
struct LoadThreads {
    std::atomic<bool> stop{false};
    std::vector<std::thread> threads;
    ~LoadThreads() {
        stop.store(true);
        for (auto& thread:threads) if (thread.joinable()) thread.join();
    }
};
struct UnderrunEvent {
    std::uint64_t unixNs=0,lastPublicationNs=0;
    std::size_t callback=0,available=0,wanted=0,received=0;
    double wakeLateSeconds=0,callbackSeconds=0;
};
struct CallbackEvent {
    std::uint64_t unixNs=0,lastPublicationNs=0;
    std::size_t callback=0,available=0,wanted=0,received=0;
    double wakeLateSeconds=0,callbackSeconds=0;
};
}
int main(int argc,char** argv) {
    if (argc<7 || argc>13) {
        std::cerr<<"phase40_paced_sim input.wav from to request_seconds A|B|C "
                    "callback_frames [fifo lead dsp_block load_percent metrics.csv delay-density|safe-density]\n";
        return 2;
    }
    try {
        WavStreamReader reader(argv[1]);
        const auto from=Phase39Speed::fromDouble(std::stod(argv[2]));
        const auto to=Phase39Speed::fromDouble(std::stod(argv[3]));
        const double requestSeconds=std::stod(argv[4]);
        const std::string label=argv[5];
        const auto strategy=label=="A" ? Phase39Planning::A :
            label=="B" ? Phase39Planning::B :
            label=="C" ? Phase39Planning::C :
            label=="C0" ? Phase39Planning::C0 :
            throw std::invalid_argument("Unknown planner");
        const auto block=static_cast<std::size_t>(std::stoull(argv[6]));
        if (block<64 || block>1024) throw std::invalid_argument("Callback size");
        const auto fifo=argc>=8 ? std::stoull(argv[7]) : 16384;
        const auto lead=argc>=9 ? std::stoull(argv[8]) : 12288;
        const auto dsp=argc>=10 ? std::stoull(argv[9]) : 2048;
        const auto load=argc>=11 ? std::stod(argv[10]) : 0.0;
        if (load<0 || load>100) throw std::invalid_argument("Load percent");
        const auto density=argc==13 && std::string(argv[12])=="delay-density" ?
            Phase39DensityDiagnostic::AfterRamp : argc==13 &&
            std::string(argv[12])=="safe-density" ?
            Phase39DensityDiagnostic::SafeGuarded : Phase39DensityDiagnostic::Immediate;
        if (argc==13 && density==Phase39DensityDiagnostic::Immediate)
            throw std::invalid_argument("Unknown density diagnostic");
        if (density==Phase39DensityDiagnostic::AfterRamp &&
            (from.value()>=0.50 || to.value()<0.50))
            throw std::invalid_argument("delay-density supports low-to-high only");
        const bool traceEvents=std::getenv("PHASE44_TRACE_EVENTS")!=nullptr;
        Phase39PlaybackPipeline pipeline(argv[1],from,fifo,dsp,lead,strategy,density,
                                        traceEvents);
        pipeline.start();
        if (!pipeline.waitForPrefill(std::min<std::size_t>(lead,8192),
                                     std::chrono::seconds(60)))
            throw std::runtime_error("Prefill timeout");
        std::vector<std::vector<float>> audio(reader.channels(),std::vector<float>(block));
        std::vector<float*> ptr(reader.channels());
        for (std::size_t c=0;c<ptr.size();++c) ptr[c]=audio[c].data();
        LoadThreads loadThreads;
        if (load>0) for (int thread=0;thread<4;++thread)
            loadThreads.threads.emplace_back([&] {
                std::uint64_t counter=0;
                while (!loadThreads.stop.load()) {
                    const auto begin=std::chrono::steady_clock::now();
                    const auto busy=std::chrono::duration<double>(load/100000.0);
                    while (std::chrono::steady_clock::now()-begin<busy) {
                        counter=counter*1664525U+1013904223U;
                        std::atomic_signal_fence(std::memory_order_seq_cst);
                    }
                    std::this_thread::sleep_until(begin+std::chrono::milliseconds(1));
                }
                (void)counter;
            });
        const auto start=std::chrono::steady_clock::now();
        auto deadline=start;
        const auto period=std::chrono::duration<double>(double(block)/reader.sampleRate());
        const auto requestAt=std::chrono::duration<double>(requestSeconds);
        bool requested=false;
        std::size_t presentedTimeline=0,pcmConsumed=0,missing=0;
        std::size_t underrunCalls=0,maxRun=0,run=0,lateWakeups=0,callbackOverruns=0;
        double maxCallbackSeconds=0;
        std::uint64_t requestNs=0,firstAudibleNs=0;
        const bool injectUnderrun=std::getenv("PHASE44_FORCE_UNDERRUN")!=nullptr;
        bool injected=false;
        std::array<UnderrunEvent,4096> underrunEvents{};
        std::vector<CallbackEvent> callbackEvents;
        if (traceEvents) callbackEvents.resize(65536);
        std::size_t eventCount=0,eventOverflow=0,callbackIndex=0;
        while (!pipeline.drained()) {
            deadline+=std::chrono::duration_cast<std::chrono::steady_clock::duration>(period);
            std::this_thread::sleep_until(deadline);
            // Control work is deliberately outside the measured render path.
            if (!requested && std::chrono::steady_clock::now()-start>=requestAt) {
                if (pipeline.requestSpeed(to,pcmConsumed)!=Phase39RequestResult::Accepted)
                    throw std::runtime_error("Request rejected");
                requestNs=pipeline.snapshot().requestNs;
                requested=true;
            }
            const auto state=pipeline.snapshot();
            const auto callbackStart=std::chrono::steady_clock::now();
            ++callbackIndex;
            if (callbackStart-deadline>period) ++lateWakeups;
            const auto need=state.outputLength>pcmConsumed ?
                std::min(block,state.outputLength-pcmConsumed) : 0;
            if (!need && !pipeline.finished()) {
                // A speed change may lengthen EOS; the worker will publish it.
                continue;
            }
            const bool skip=injectUnderrun && !injected && need>0;
            if (skip) injected=true;
            const auto availableBefore=pipeline.available();
            const auto lastPublication=pipeline.lastPublishedUnixNs();
            const auto count=need && !skip ? pipeline.pullAudio(ptr.data(),need) : 0;
            if (count<need) {
                if (traceEvents) {
                    if (eventCount<underrunEvents.size()) {
                        auto& event=underrunEvents[eventCount++];
                        event.unixNs=static_cast<std::uint64_t>(
                            std::chrono::duration_cast<std::chrono::nanoseconds>(
                                std::chrono::system_clock::now().time_since_epoch()).count());
                        event.lastPublicationNs=lastPublication;
                        event.callback=callbackIndex;
                        event.available=availableBefore;
                        event.wanted=need;
                        event.received=count;
                        event.wakeLateSeconds=std::chrono::duration<double>(
                            callbackStart-deadline).count();
                    } else ++eventOverflow;
                }
                for (auto& channel:audio)
                    std::fill(channel.begin()+count,channel.begin()+need,0.0f);
                missing+=need-count;++underrunCalls;
                run+=need-count;maxRun=std::max(maxRun,run);
            } else run=0;
            // The hardware presentation clock always advances, even after a
            // zero-filled callback. The raw FIFO read position advances only
            // by the actual PCM consumed; neither clock is rewound.
            presentedTimeline+=need;
            pcmConsumed+=count;
            if (requested && !firstAudibleNs &&
                state.state==Phase39RequestState::Applied &&
                pcmConsumed>=state.appliedOutput)
                firstAudibleNs=static_cast<std::uint64_t>(
                    std::chrono::duration_cast<std::chrono::nanoseconds>(
                        callbackStart.time_since_epoch()).count());
            const auto seconds=std::chrono::duration<double>(
                std::chrono::steady_clock::now()-callbackStart).count();
            if (traceEvents) {
                auto& event=callbackEvents[(callbackIndex-1)%callbackEvents.size()];
                event.unixNs=static_cast<std::uint64_t>(
                    std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::system_clock::now().time_since_epoch()).count());
                event.lastPublicationNs=lastPublication;
                event.callback=callbackIndex;
                event.available=availableBefore;
                event.wanted=need;
                event.received=count;
                event.wakeLateSeconds=std::chrono::duration<double>(
                    callbackStart-deadline).count();
                event.callbackSeconds=seconds;
            }
            if (traceEvents && count<need && eventCount)
                underrunEvents[eventCount-1].callbackSeconds=seconds;
            maxCallbackSeconds=std::max(maxCallbackSeconds,seconds);
            if (seconds>period.count()) ++callbackOverruns;
            if (presentedTimeline>reader.frames()*6+reader.sampleRate()*30)
                throw std::runtime_error("Paced EOS timeout");
        }
        pipeline.rethrowWorkerError();
        const auto state=pipeline.snapshot();
        const double appliedCallbackMs=firstAudibleNs>requestNs ?
            double(firstAudibleNs-requestNs)/1e6 : -1.0;
        const double coordinateMs=state.appliedOutput>state.requestedOutput ?
            1000.0*double(state.appliedOutput-state.requestedOutput)/reader.sampleRate() : 0;
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        std::cout<<"strategy="<<label<<"\ncallback_frames="<<block
                 <<"\nplan_outcome="<<static_cast<int>(state.planOutcome)
                 <<"\noutput_frames="<<state.outputLength
                 <<"\npcm_consumed="<<pcmConsumed
                 <<"\npresented_timeline="<<presentedTimeline
                 <<"\nmissing_frames="<<missing
                 <<"\nunderrun_calls="<<underrunCalls
                 <<"\nmax_consecutive_missing_frames="<<maxRun
                 <<"\nrejected_writes="<<state.rejectedWrites
                 <<"\nlate_wakeups="<<lateWakeups
                 <<"\ncallback_overruns="<<callbackOverruns
                 <<"\nmax_callback_seconds="<<maxCallbackSeconds
                 <<"\nmax_worker_wall_seconds="<<state.maxWorkerChunkSeconds
                 <<"\nmax_worker_cycle_seconds="<<state.maxWorkerCycleSeconds
                 <<"\nmax_worker_cycle_cpu_seconds="<<state.maxWorkerCycleCpuSeconds
                 <<"\np95_worker_cycle_seconds="<<pipeline.workerCycleP95Seconds()
                 <<"\np99_worker_cycle_seconds="<<pipeline.workerCycleP99Seconds()
                 <<"\nmax_worker_cpu_seconds="<<state.maxWorkerCpuSeconds
                 <<"\nmax_fifo_wait_seconds="<<state.maxFifoWaitSeconds
                 <<"\nfifo_wait_seconds="<<double(state.fifoWaitNanoseconds)/1e9
                 <<"\nworker_chunks_over_100ms="<<state.workerChunksOver100Ms
                 <<"\nworker_qos_applied="<<state.workerQosApplied
                 <<"\nplan_ms="<<state.planMilliseconds
                 <<"\ncoordinate_delay_ms="<<coordinateMs
                 <<"\napplied_callback_delay_ms="<<appliedCallbackMs
                 <<"\nfifo_high_water="<<state.fifoHighWater
                 <<"\npeak_rss_bytes="<<usage.ru_maxrss
                 <<"\ncpu_user_seconds="
                 <<usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6
                 <<"\ncpu_system_seconds="
                 <<usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6
                 <<"\nmajor_faults="<<usage.ru_majflt
                 <<"\nminor_faults="<<usage.ru_minflt<<'\n';
        const bool completed=requested && state.planOutcome==Phase39Outcome::Applied &&
            state.state==Phase39RequestState::Applied &&
            pcmConsumed>=state.completionOutput;
        std::cout<<"request_state="<<(completed ? "Completed" : "Incomplete")
                 <<"\neos_drained="<<pipeline.drained()
                 <<"\nworker_errors=0\n";
        if (traceEvents && argc>=12) {
            const auto blocks=pipeline.allBlockProfiles();
            std::ofstream workerCsv(std::string(argv[11])+".workers.csv");
            workerCsv<<"output_start,start_unix_ns,end_unix_ns,thread_id,cycle_wall_s,"
                         "cycle_cpu_s,dsp_wall_s,dsp_cpu_s,fifo_wait_s,fifo_write_s,"
                         "plan_wall_s,plan_cpu_s,mutex_wait_s,mutex_hold_s,"
                         "wav_wall_s,wav_cpu_s,fft_wall_s,fft_cpu_s,"
                         "phase_wall_s,phase_cpu_s,ola_wall_s,ola_cpu_s,"
                         "fir_wall_s,fir_cpu_s\n";
            for (const auto& item:blocks) {
                workerCsv<<item.outputStart<<','<<item.startUnixNs<<','<<item.endUnixNs
                         <<','<<item.threadId<<','<<item.fullCycleWallSeconds<<','
                         <<item.fullCycleCpuSeconds<<','<<item.chunkWallSeconds<<','
                         <<item.chunkCpuSeconds<<','<<item.fifoWaitSeconds<<','
                         <<item.fifoWriteSeconds<<','<<item.planWallSeconds<<','
                         <<item.planCpuSeconds<<','<<item.mutexWaitSeconds<<','
                         <<item.mutexHoldSeconds;
                for (const auto& stage:item.work.stages)
                    workerCsv<<','<<stage.wallSeconds<<','<<stage.threadCpuSeconds;
                workerCsv<<'\n';
            }
            std::ofstream eventCsv(std::string(argv[11])+".underruns.csv");
            eventCsv<<"callback,unix_ns,available,wanted,received,missing,"
                        "last_publication_ns,next_publication_ns,wake_late_s,callback_s\n";
            for (std::size_t i=0;i<eventCount;++i) {
                const auto& event=underrunEvents[i];
                const auto next=std::find_if(blocks.begin(),blocks.end(),
                    [&](const auto& block){ return block.endUnixNs>event.unixNs; });
                eventCsv<<event.callback<<','<<event.unixNs<<','<<event.available
                        <<','<<event.wanted<<','<<event.received<<','
                        <<event.wanted-event.received<<','<<event.lastPublicationNs
                        <<','<<(next==blocks.end() ? 0 : next->endUnixNs)<<','
                        <<event.wakeLateSeconds<<','<<event.callbackSeconds<<'\n';
            }
            std::ofstream callbackCsv(std::string(argv[11])+".callbacks.csv");
            callbackCsv<<"callback,unix_ns,available,wanted,received,missing,"
                           "last_publication_ns,wake_late_s,callback_s\n";
            const auto retained=std::min(callbackIndex,callbackEvents.size());
            for (std::size_t i=0;i<retained;++i) {
                const auto index=(callbackIndex-retained+i)%callbackEvents.size();
                const auto& event=callbackEvents[index];
                callbackCsv<<event.callback<<','<<event.unixNs<<','<<event.available
                           <<','<<event.wanted<<','<<event.received<<','
                           <<event.wanted-event.received<<','<<event.lastPublicationNs
                           <<','<<event.wakeLateSeconds<<','<<event.callbackSeconds<<'\n';
            }
            std::cout<<"underrun_event_overflow="<<eventOverflow<<'\n';
        }
        if (argc>=12) {
            std::ofstream csv(argv[11]);
            csv<<"requested_output,requested_input,fence,published,prepared,"
                   "first_mutable,first_safe,next_event,protection_end,applied,"
                   "completion,safe_frames,held_frames,skipped_events,plan_ms,"
                   "density_input,density_candidates,weight_low,weight_mid,weight_high\n";
            for (const auto& metric:pipeline.planMetrics()) {
                const auto& p=metric.plan;
                csv<<metric.requestedOutput<<','<<metric.requestedInput<<','
                   <<metric.planningFence<<','<<metric.published<<','
                   <<metric.prepared<<','<<p.firstMutableFrame<<','
                   <<p.firstSafeFrame<<','<<p.nextEventFrame<<','
                   <<p.protectionEndFrame<<','<<p.appliedOutputSample<<','
                   <<p.completionOutputSample<<','<<p.safeFramesUsed<<','
                   <<p.heldFrames<<','<<p.protectedEventsSkipped<<','
                   <<metric.planMilliseconds<<','<<metric.firstDensityChangedInput<<','
                   <<metric.densityCandidatesTried<<','<<metric.densityMinimumWeight[0]<<','
                   <<metric.densityMinimumWeight[1]<<','<<metric.densityMinimumWeight[2]<<'\n';
            }
        }
        pipeline.stop();
        if (!completed || !pipeline.drained() || missing || underrunCalls ||
            state.rejectedWrites || callbackOverruns ||
            pcmConsumed!=state.outputLength ||
            presentedTimeline!=state.outputLength) return 1;
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"Phase 40 paced simulation: "<<error.what()<<'\n';
        return 1;
    }
}
