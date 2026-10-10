#include "audio/WavStream.h"
#include "dsp/Phase14PlaybackPipeline.h"
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <new>
#include <stdexcept>
#include <thread>
#include <vector>

namespace {
thread_local bool insideCallback=false;
std::atomic<std::uint64_t> callbackAllocations{0};
void check(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void* allocate(std::size_t n,std::size_t alignment=alignof(std::max_align_t)) {
    if (insideCallback) callbackAllocations.fetch_add(1,std::memory_order_relaxed);
    void* result=nullptr;
    if (posix_memalign(&result,alignment,n ? n : 1)!=0) throw std::bad_alloc();
    return result;
}
bool sameFile(const std::filesystem::path& a,const std::filesystem::path& b) {
    std::ifstream x(a,std::ios::binary),y(b,std::ios::binary);
    return std::equal(std::istreambuf_iterator<char>(x),std::istreambuf_iterator<char>(),
                      std::istreambuf_iterator<char>(y),std::istreambuf_iterator<char>());
}
ts::StretchConfig config() {
    ts::StretchConfig c;
    c.sampleRate=48000;
    c.channels=2;
    c.timeRatio=2.0;
    c.enableMultiResolution=true;
    c.qualityMode=ts::QualityMode::Experimental;
    c.enablePhaseLocking=true;
    c.enableTransientHandling=true;
    c.enableAdaptiveTimeMapping=true;
    c.enablePreciseTransientAnchoring=true;
    c.enableStereoCoherence=true;
    return c;
}
void fifoTest() {
    ts::Phase14AudioFifo fifo(2,8192);
    std::array<float,400> left{},right{},outL{},outR{};
    for (std::size_t i=0;i<left.size();++i) { left[i]=float(i);right[i]=-float(i); }
    const float* source[]={left.data(),right.data()};
    float* output[]={outL.data(),outR.data()};
    check(fifo.write(source,400),"FIFO write");
    check(fifo.read(output,400)==400,"FIFO read count");
    for (std::size_t i=0;i<400;++i) check(outL[i]==left[i] && outR[i]==right[i],"FIFO data");
    check(fifo.read(output,400)==0,"FIFO empty count");
    for (auto value:outL) check(value==0,"FIFO underrun zero fill");
    check(!fifo.write(source,8193),"FIFO overflow rejected");
    check(fifo.rejectedWrites()==1,"FIFO overflow counted");
    // Independent producer/consumer threads repeatedly cross the ring boundary.
    std::atomic<bool> finished{false},bad{false};
    std::thread producer([&] {
        for (std::size_t base=0;base<200000;base+=400) {
            for (std::size_t i=0;i<400;++i) {left[i]=float(base+i);right[i]=-float(base+i);}
            while (fifo.free()<400) std::this_thread::yield();
            if (!fifo.write(source,400)) bad.store(true);
        }
        finished.store(true);
    });
    std::size_t consumed=0;
    while (consumed<200000) {
        if (fifo.available()<400) { std::this_thread::yield(); continue; }
        if (fifo.read(output,400)!=400) bad.store(true);
        for (std::size_t i=0;i<400;++i)
            if (outL[i]!=float(consumed+i) || outR[i]!=-float(consumed+i)) bad.store(true);
        consumed+=400;
    }
    producer.join();
    check(finished.load() && !bad.load(),"Concurrent FIFO corruption");
}
}

void* operator new(std::size_t n) { return allocate(n); }
void* operator new[](std::size_t n) { return allocate(n); }
void* operator new(std::size_t n,std::align_val_t a) { return allocate(n,static_cast<std::size_t>(a)); }
void* operator new[](std::size_t n,std::align_val_t a) { return allocate(n,static_cast<std::size_t>(a)); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p,std::size_t) noexcept { std::free(p); }
void operator delete[](void* p,std::size_t) noexcept { std::free(p); }
void operator delete(void* p,std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p,std::align_val_t) noexcept { std::free(p); }
void operator delete(void* p,std::size_t,std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p,std::size_t,std::align_val_t) noexcept { std::free(p); }

int main() {
    const auto dir=std::filesystem::temp_directory_path()/
        ("phase14_test_"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directories(dir);
    try {
        fifoTest();
        constexpr std::size_t frames=48000;
        std::array<std::vector<float>,2> samples={std::vector<float>(frames),std::vector<float>(frames)};
        for (std::size_t i=0;i<frames;++i) {
            const float x=.2f*std::sin(2*3.141592653589793*437.3*i/48000.0)+(i==12000?.7f:0);
            samples[0][i]=x;samples[1][i]=x*.8f;
        }
        const float* source[]={samples[0].data(),samples[1].data()};
        const auto input=dir/"in.wav",baseline=dir/"baseline.wav";
        {
            ts::WavStreamWriter w(input,48000,2,frames);w.write(source,frames);w.finish();
        }
        {
            ts::WavStreamWriter w(baseline,48000,2,frames*2);
            ts::Phase13StreamingEngine(config()).processFile(input,[&](const float* const* p,std::size_t n){w.write(p,n);});
            w.finish();
        }
        ts::Phase14PlaybackPipeline pipeline(config());
        pipeline.prepare(input);
        {
            std::array<float,64> a{},b{};
            float* p[]={a.data(),b.data()};
            insideCallback=true;
            check(pipeline.pullAudio(p,64)==0,"Cold FIFO should underflow");
            insideCallback=false;
            check(pipeline.statistics().underrunCalls==1 && pipeline.statistics().underrunFrames==64,
                  "Pipeline underrun counters");
            for (float value:a) check(value==0,"Pipeline underrun zero fill");
        }
        for (const std::size_t block:{64,128,256,512,1024,2048,4096,0}) {
            const auto output=dir/("out"+std::to_string(block)+".wav");
            ts::WavStreamWriter w(output,48000,2,frames*2);
            const auto capacity=block ? block : 4096;
            std::array<std::vector<float>,2> scratch={std::vector<float>(capacity),std::vector<float>(capacity)};
            float* pointers[]={scratch[0].data(),scratch[1].data()};
            const float* constPointers[]={scratch[0].data(),scratch[1].data()};
            pipeline.start();
            check(pipeline.waitForPrefill(16384,std::chrono::seconds(10)),"Prefill timed out");
            std::size_t pulled=0;
            std::size_t requestIndex=0;
            constexpr std::array<std::size_t,7> varying={64,4096,128,2048,256,1024,512};
            while (pulled<frames*2) {
                const auto n=std::min(block ? block : varying[requestIndex++%varying.size()],frames*2-pulled);
                while (pipeline.availableOutputFrames()<n) {
                    pipeline.rethrowWorkerError();
                    std::this_thread::yield();
                }
                insideCallback=true;
                const auto count=pipeline.pullAudio(pointers,n);
                insideCallback=false;
                check(count==n,"Unexpected underrun");
                w.write(constPointers,n);
                pulled+=n;
            }
            w.finish();
            while (!pipeline.workerFinished()) std::this_thread::yield();
            pipeline.rethrowWorkerError();
            check(pipeline.drained(),"EOS not drained");
            check(pipeline.statistics().fifoRejectedWrites==0,"FIFO overflow");
            check(pipeline.statistics().underrunCalls==0,"FIFO underrun");
            pipeline.stop();
            check(sameFile(baseline,output),"Block partition changed DSP output");
        }
        check(callbackAllocations.load()==0,"Callback allocated memory");
        pipeline.start();
        pipeline.stop();
        pipeline.start();
        check(pipeline.waitForPrefill(16384,std::chrono::seconds(10)),"Restart prefill failed");
        pipeline.stop();
        std::filesystem::remove_all(dir);
        std::cout << "Phase 14: FIFO concurrency, overflow/underrun, 7 fixed + mixed callback sizes, allocation, restart, exact WAV match passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << " (files: " << dir << ")\n";
        return 1;
    }
}
