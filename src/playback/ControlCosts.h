#pragma once
#include "playback/StartupDiagnostics.h"
#include <atomic>
#include <algorithm>
namespace ts::playback {
// Explicit normal-thread instrumentation. Nested wall/CPU values are inclusive,
// not additive. No callback caller; disabled scopes do not read a clock.
struct ControlCostValue {std::uint64_t calls=0,items=0,objectBytes=0;double cpuS=0,wallS=0;};
class ControlCostCounter {
    std::atomic<std::uint64_t> calls{0},items{0},bytes{0},cpuNs{0},wallNs{0};
public:
    void add(std::size_t count,std::size_t size,double cpu,double wall)noexcept {
        calls.fetch_add(1,std::memory_order_relaxed);items.fetch_add(count,std::memory_order_relaxed);bytes.fetch_add(size,std::memory_order_relaxed);
        cpuNs.fetch_add(std::uint64_t(std::max(0.,cpu)*1e9),std::memory_order_relaxed);wallNs.fetch_add(std::uint64_t(std::max(0.,wall)*1e9),std::memory_order_relaxed);
    }
    ControlCostValue value()const noexcept{return {calls.load(),items.load(),bytes.load(),cpuNs.load()*1e-9,wallNs.load()*1e-9};}
};
class ControlCostScope {
    ControlCostCounter* counter;double cpu=0;std::chrono::steady_clock::time_point wall{};
public:
    std::size_t items=0,objectBytes=0;
    ControlCostScope(ControlCostCounter& c,bool enabled):counter(enabled?&c:nullptr){if(counter){cpu=threadCpuSeconds();wall=std::chrono::steady_clock::now();}}
    ~ControlCostScope(){if(counter)counter->add(items,objectBytes,threadCpuSeconds()-cpu,std::chrono::duration<double>(std::chrono::steady_clock::now()-wall).count());}
};
}
