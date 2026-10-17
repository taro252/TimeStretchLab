#include "Phase61CallbackMallocProbe.h"
#include <atomic>
#include <cstdlib>
#include <malloc/malloc.h>

// Verification dylib only. dyld interposes callers in the executable/frameworks,
// excluding this dylib so that calls below reach the real allocator directly.
namespace {
thread_local bool enabled=false;
thread_local std::uint64_t calls=0,releases=0;
std::atomic<std::uint64_t> totalCalls{0},totalReleases{0};
void* observed_malloc(std::size_t n){if(enabled)++calls;return malloc(n);}
void observed_free(void* p){if(enabled&&p)++releases;free(p);}
void* observed_calloc(std::size_t n,std::size_t s){if(enabled)++calls;return calloc(n,s);}
void* observed_realloc(void* p,std::size_t n){if(enabled){++calls;if(p)++releases;}return realloc(p,n);}
int observed_posix(void** p,std::size_t a,std::size_t n){if(enabled)++calls;return posix_memalign(p,a,n);}
void* observed_zone_malloc(malloc_zone_t* z,std::size_t n){if(enabled)++calls;return malloc_zone_malloc(z,n);}
void observed_zone_free(malloc_zone_t* z,void* p){if(enabled&&p)++releases;malloc_zone_free(z,p);}
void* observed_zone_calloc(malloc_zone_t* z,std::size_t n,std::size_t s){if(enabled)++calls;return malloc_zone_calloc(z,n,s);}
void* observed_zone_realloc(malloc_zone_t* z,void* p,std::size_t n){if(enabled){++calls;if(p)++releases;}return malloc_zone_realloc(z,p,n);}
#define PAIR(replacement,original) {reinterpret_cast<const void*>(replacement),reinterpret_cast<const void*>(original)}
__attribute__((used,section("__DATA,__interpose"))) const struct {const void* replacement;const void* original;} interposed[]={
    PAIR(observed_malloc,malloc),PAIR(observed_free,free),PAIR(observed_calloc,calloc),PAIR(observed_realloc,realloc),PAIR(observed_posix,posix_memalign),
    PAIR(observed_zone_malloc,malloc_zone_malloc),PAIR(observed_zone_free,malloc_zone_free),PAIR(observed_zone_calloc,malloc_zone_calloc),PAIR(observed_zone_realloc,malloc_zone_realloc)};
}
extern "C" void phase61_heap_begin()noexcept{calls=releases=0;enabled=true;}
extern "C" void phase61_heap_end()noexcept{enabled=false;totalCalls.fetch_add(calls,std::memory_order_relaxed);totalReleases.fetch_add(releases,std::memory_order_relaxed);}
extern "C" void phase61_heap_reset()noexcept{totalCalls=0;totalReleases=0;}
extern "C" std::uint64_t phase61_heap_allocations()noexcept{return totalCalls.load();}
extern "C" std::uint64_t phase61_heap_frees()noexcept{return totalReleases.load();}
