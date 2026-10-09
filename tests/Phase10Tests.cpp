#include "dsp/TimeStretchProcessor.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <new>
#include <numbers>
#include <stdexcept>
#include <string_view>
#include <sys/resource.h>
#include <thread>
#include <vector>

namespace {
std::atomic<std::uint64_t> allocationCount{0};
std::atomic<bool> trackAllocations{false};
void countedAllocation() noexcept {
    if (trackAllocations.load(std::memory_order_relaxed))
        allocationCount.fetch_add(1,std::memory_order_relaxed);
}
void check(bool condition,const char* reason) {
    if (!condition)throw std::runtime_error(reason);
}
double cpuSeconds(const rusage& usage) {
    return usage.ru_utime.tv_sec+usage.ru_utime.tv_usec/1e6+
           usage.ru_stime.tv_sec+usage.ru_stime.tv_usec/1e6;
}
template<class F> auto measured(F&& call) {
    trackAllocations.store(true,std::memory_order_relaxed);
    const auto result=call();
    trackAllocations.store(false,std::memory_order_relaxed);
    return result;
}
struct RunResult {
    std::vector<std::vector<float>> channels;
    std::size_t frames=0;
    ts::ProcessorStatistics statistics;
    std::size_t bytes=0;
};
RunResult run(std::size_t inputFrames,double speed,int channelCount,
              std::size_t inputBlock,std::size_t pullBlock,bool capture=true,
              double sampleRate=48000,bool repeatingInput=false) {
    ts::TimeStretchProcessor processor;
    processor.prepare(sampleRate,channelCount,4096);
    processor.setSpeed(speed);
    const auto bytes=processor.workingMemoryBytes();
    std::array<std::array<float,4096>,2> input{},output{};
    if (repeatingInput)for (std::size_t i=0;i<input[0].size();++i) {
        input[0][i]=static_cast<float>(0.1*std::sin(
            2*std::numbers::pi*437.3*i/sampleRate));
        input[1][i]=0.72f*input[0][i];
    }
    RunResult result;
    if (capture)result.channels.assign(channelCount,
        std::vector<float>(static_cast<std::size_t>(inputFrames/speed*1.2)+8192));
    std::size_t inputPosition=0,outputPosition=0;
    auto drain=[&] {
        while (processor.availableOutputFrames()>0) {
            const auto count=std::min(pullBlock,processor.availableOutputFrames());
            float* ptr[]={output[0].data(),output[1].data()};
            const auto got=measured([&]{return processor.pullOutput(ptr,count);});
            check(got==count,"Available output could not be pulled");
            for (int c=0;c<channelCount;++c)for (std::size_t i=0;i<got;++i) {
                check(std::isfinite(output[c][i]),"Nonfinite streamed output");
                if (capture) {
                    check(outputPosition+i<result.channels[c].size(),"Output storage exceeded");
                    result.channels[c][outputPosition+i]=output[c][i];
                }
            }
            outputPosition+=got;
        }
    };
    while (inputPosition<inputFrames) {
        const auto count=std::min({inputBlock,inputFrames-inputPosition,
                                   input[0].size()});
        for (int attempts=0;processor.availableInputCapacity()<count;++attempts) {
            check(attempts<100,"Producer backpressure stalled");
            measured([&]{return processor.process(4096);});
            drain();
        }
        if (!repeatingInput)for (std::size_t i=0;i<count;++i) {
            const auto sample=inputPosition+i;
            const double t=sample/sampleRate;
            const float signal=static_cast<float>(0.13*std::sin(
                2*std::numbers::pi*437.3*t)+
                0.06*std::sin(2*std::numbers::pi*82.41*t)+
                (sample%13031==7?0.12:0));
            input[0][i]=signal;
            input[1][i]=0.72f*signal;
        }
        const float* ptr[]={input[0].data(),input[1].data()};
        const auto pushed=measured([&]{return processor.pushInput(ptr,count);});
        check(pushed==count,"Input FIFO overrun");
        inputPosition+=pushed;
        measured([&]{return processor.process(4096);});
        drain();
        check(processor.workingMemoryBytes()==bytes,"Working memory grew");
    }
    measured([&]{processor.signalEndOfInput();return 0;});
    for (int attempts=0;attempts<100000 && !processor.drained();++attempts) {
        measured([&]{return processor.process(4096);});
        drain();
    }
    check(processor.drained(),"End-of-stream flush stalled");
    result.frames=outputPosition;
    result.statistics=processor.statistics();
    result.bytes=bytes;
    check(result.statistics.inputOverrunFrames==0,"Input FIFO overflow");
    check(result.statistics.outputUnderrunFrames==0,"Output FIFO underrun");
    if (capture)for (auto& channel:result.channels)channel.resize(outputPosition);
    return result;
}
void partitionAndAllocation() {
    for (int channels:{1,2})for (double speed:{.75,.5}) {
        allocationCount.store(0);
        const auto reference=run(48000*2,speed,channels,512,237);
        const auto expected=std::size_t(std::llround(48000*2/speed));
        check(reference.frames==expected,"Reference duration mismatch");
        check(allocationCount.load()==0,"Heap allocation after prepare");
        double worst=0;
        for (std::size_t block:{64,128,256,512,1024,2048,4096}) {
            allocationCount.store(0);
            const auto candidate=run(48000*2,speed,channels,block,911);
            check(candidate.frames==expected,"Block duration mismatch");
            check(allocationCount.load()==0,"Heap allocation after prepare");
            for (int c=0;c<channels;++c)for (std::size_t i=0;i<expected;++i)
                worst=std::max(worst,std::abs(double(reference.channels[c][i])-
                                               candidate.channels[c][i]));
        }
        std::cout << "speed=" << speed << " channels=" << channels
                  << " max_partition_difference=" << worst
                  << " working_memory_bytes=" << reference.bytes << '\n';
        check(worst<1e-6,"Output depends on block partition");
    }
}
void resetAndSpeedChange() {
    ts::TimeStretchProcessor processor;
    processor.prepare(48000,1,4096);
    processor.setSpeed(.5);
    check(processor.currentSpeed()==.5,"Initial speed not established");
    std::array<float,4096> input{},output{};
    for (std::size_t i=0;i<input.size();++i)
        input[i]=0.2f*std::sin(2*std::numbers::pi*440*i/48000);
    const float* inputPtr[]={input.data()};
    float* outputPtr[]={output.data()};
    auto first=processor.pushInput(inputPtr,input.size());
    check(first==input.size(),"Initial push failed");
    processor.process(4096);
    const auto n=processor.pullOutput(outputPtr,
        std::min(output.size(),processor.availableOutputFrames()));
    std::vector<float> reference(output.begin(),output.begin()+n);
    processor.reset();
    check(processor.availableOutputFrames()==0,"Reset left FIFO content");
    check(processor.statistics().resetCount==1,"Reset counter mismatch");
    first=processor.pushInput(inputPtr,input.size());
    check(first==input.size(),"Post-reset push failed");
    processor.process(4096);
    const auto repeated=processor.pullOutput(outputPtr,
        std::min(output.size(),processor.availableOutputFrames()));
    check(repeated==n && std::equal(reference.begin(),reference.end(),output.begin()),
          "Reset did not restore deterministic DSP state");
    processor.setSpeed(.75);
    check(processor.targetSpeed()==.75,"Target speed mismatch");
    check(processor.currentSpeed()<.75,"Active speed jumped immediately");
    for (int k=0;k<20;++k) {
        processor.pushInput(inputPtr,input.size());
        processor.process(4096);
        processor.pullOutput(outputPtr,
            std::min(output.size(),processor.availableOutputFrames()));
    }
    check(std::abs(processor.currentSpeed()-.75)<1e-6,
          "Speed ramp did not reach target");
    processor.reset();
    std::fill(output.begin(),output.end(),1.0f);
    check(processor.pullOutput(outputPtr,64)==0,"Unexpected output after reset");
    check(std::all_of(output.begin(),output.begin()+64,[](float x){return x==0;}),
          "Underflow did not fill silence");
    check(processor.statistics().outputUnderrunFrames==64,"Underflow counter mismatch");
}
void latencyProbe() {
    for (double speed:{.5,.75,1.0}) {
        ts::TimeStretchProcessor processor;
        processor.prepare(48000,1,4096);
        processor.setSpeed(speed);
        std::array<float,64> input{};
        const float* ptr[]={input.data()};
        std::size_t supplied=0;
        while (processor.availableOutputFrames()==0 && supplied<20000) {
            check(processor.pushInput(ptr,input.size())==input.size(),
                  "Latency probe input FIFO full");
            supplied+=input.size();
            processor.process(1);
        }
        const auto expected=processor.latency().startupInputFrames;
        std::cout << "speed=" << speed << " first_output_input_frames=" << supplied
                  << " latency_estimate=" << expected << '\n';
        check(supplied==expected,"Startup latency accounting mismatch");
    }
}
void concurrentPipeline() {
    constexpr std::size_t frames=48000*2;
    ts::TimeStretchProcessor processor;
    processor.prepare(48000,2,4096);
    processor.setSpeed(.5);
    std::vector<float> left(frames),right(frames);
    for (std::size_t i=0;i<frames;++i) {
        left[i]=static_cast<float>(0.2*std::sin(2*std::numbers::pi*220*i/48000));
        right[i]=0.8f*left[i];
    }
    std::atomic<bool> failed{false};
    std::size_t received=0;
    std::thread producer([&] {
        std::size_t position=0;
        while (position<frames && !failed.load()) {
            const auto count=std::min<std::size_t>(257,frames-position);
            if (processor.availableInputCapacity()<count) {
                std::this_thread::yield();continue;
            }
            const float* pointers[]={left.data()+position,right.data()+position};
            if (processor.pushInput(pointers,count)!=count)failed.store(true);
            position+=count;
        }
        processor.signalEndOfInput();
    });
    std::thread worker([&] {
        for (std::size_t attempts=0;attempts<10000000 && !processor.drained() &&
             !failed.load();++attempts) {
            processor.process(512);
            if (processor.faulted())failed.store(true);
            std::this_thread::yield();
        }
        if (!processor.drained())failed.store(true);
    });
    std::thread consumer([&] {
        std::array<float,333> l{},r{};
        float* pointers[]={l.data(),r.data()};
        for (std::size_t attempts=0;attempts<10000000 && !processor.drained() &&
             !failed.load();++attempts) {
            const auto ready=processor.availableOutputFrames();
            if (!ready) {std::this_thread::yield();continue;}
            const auto count=processor.pullOutput(pointers,std::min(ready,l.size()));
            for (std::size_t i=0;i<count;++i)
                if (!std::isfinite(l[i]) || !std::isfinite(r[i]))failed.store(true);
            received+=count;
        }
    });
    producer.join();worker.join();consumer.join();
    check(!failed.load() && processor.drained(),"Concurrent pipeline stalled");
    check(received==2*frames,"Concurrent pipeline duration mismatch");
    const auto stats=processor.statistics();
    check(stats.outputUnderrunFrames==0 && stats.inputOverrunFrames==0,
          "Concurrent FIFO overrun/underrun");
}
void stress() {
    constexpr std::size_t rate=48000,durationSeconds=1800;
    allocationCount.store(0);
    rusage before{};getrusage(RUSAGE_SELF,&before);
    const auto start=std::chrono::steady_clock::now();
    const auto result=run(rate*durationSeconds,1.0,2,4096,1024,false,rate,true);
    const double wall=std::chrono::duration<double>(
        std::chrono::steady_clock::now()-start).count();
    rusage after{};getrusage(RUSAGE_SELF,&after);
    check(result.frames==rate*durationSeconds,"30-minute duration mismatch");
    check(allocationCount.load()==0,"30-minute heap growth");
    std::cout << "stress_input_seconds=" << durationSeconds
              << " sample_rate=" << rate
              << " output_frames=" << result.frames
              << " worker_process_wall_seconds=" << result.statistics.processingNanoseconds/1e9
              << " cpu_seconds=" << cpuSeconds(after)-cpuSeconds(before)
              << " wall_seconds=" << wall
              << " peak_rss_bytes=" << after.ru_maxrss
              << " rss_growth_bound_bytes=" << after.ru_maxrss-before.ru_maxrss
              << " input_wait_calls=" << result.statistics.inputUnderrunCalls
              << " output_underrun_frames=" << result.statistics.outputUnderrunFrames
              << " input_high_water_frames=" << result.statistics.inputHighWaterFrames
              << " output_high_water_frames=" << result.statistics.outputHighWaterFrames
              << " allocations=" << allocationCount.load() << '\n';
}
void benchmark() {
    constexpr std::size_t rate=48000,durationSeconds=30;
    allocationCount.store(0);
    rusage before{};getrusage(RUSAGE_SELF,&before);
    const auto start=std::chrono::steady_clock::now();
    const auto result=run(rate*durationSeconds,.5,2,4096,1024,false,rate);
    const double wall=std::chrono::duration<double>(
        std::chrono::steady_clock::now()-start).count();
    rusage after{};getrusage(RUSAGE_SELF,&after);
    check(result.frames==rate*durationSeconds*2,"Benchmark duration mismatch");
    check(allocationCount.load()==0,"Benchmark heap allocation");
    std::cout << "benchmark_input_seconds=" << durationSeconds
              << " sample_rate=" << rate
              << " speed=0.5 channels=2"
              << " output_frames=" << result.frames
              << " worker_process_wall_seconds=" << result.statistics.processingNanoseconds/1e9
              << " cpu_seconds=" << cpuSeconds(after)-cpuSeconds(before)
              << " wall_seconds=" << wall
              << " peak_rss_bytes=" << after.ru_maxrss
              << " rss_growth_bound_bytes=" << after.ru_maxrss-before.ru_maxrss
              << " working_memory_bytes=" << result.bytes
              << " allocations=" << allocationCount.load() << '\n';
}
}

void* operator new(std::size_t n) {
    countedAllocation();
    if (void* p=std::malloc(n?n:1))return p;
    throw std::bad_alloc();
}
void* operator new[](std::size_t n) {
    countedAllocation();
    if (void* p=std::malloc(n?n:1))return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept {std::free(p);}
void operator delete[](void* p) noexcept {std::free(p);}
void operator delete(void* p,std::size_t) noexcept {std::free(p);}
void operator delete[](void* p,std::size_t) noexcept {std::free(p);}
void* operator new(std::size_t n,std::align_val_t alignment) {
    countedAllocation();
    void* p=nullptr;
    if (posix_memalign(&p,static_cast<std::size_t>(alignment),n?n:1)==0)return p;
    throw std::bad_alloc();
}
void* operator new[](std::size_t n,std::align_val_t alignment) {
    countedAllocation();
    void* p=nullptr;
    if (posix_memalign(&p,static_cast<std::size_t>(alignment),n?n:1)==0)return p;
    throw std::bad_alloc();
}
void operator delete(void* p,std::align_val_t) noexcept {std::free(p);}
void operator delete[](void* p,std::align_val_t) noexcept {std::free(p);}
void operator delete(void* p,std::size_t,std::align_val_t) noexcept {std::free(p);}
void operator delete[](void* p,std::size_t,std::align_val_t) noexcept {std::free(p);}

int main(int argc,char** argv) {
    try {
        if (argc==2 && std::string_view(argv[1])=="--stress")stress();
        else if (argc==2 && std::string_view(argv[1])=="--benchmark")benchmark();
        else {
            partitionAndAllocation();
            resetAndSpeedChange();
            latencyProbe();
            concurrentPipeline();
            std::cout << "phase10 PASS\n";
        }
    } catch (const std::exception& error) {
        std::cerr << "phase10 FAIL: " << error.what() << '\n';
        return 1;
    }
}
