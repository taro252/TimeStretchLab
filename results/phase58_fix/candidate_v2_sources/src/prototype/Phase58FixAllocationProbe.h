#pragma once
#include <cstdint>
namespace ts::prototype::phase58 {
// Verification executables can count their global C++ new entry points.
// Worker-local counters never cause callback locks or cross-thread traffic.
inline thread_local bool countDspAllocations=false;
inline thread_local std::uint64_t dspAllocations=0;
inline thread_local bool dspAllocationProbeAvailable=false;
inline void noteDspAllocation() noexcept {dspAllocationProbeAvailable=true;if(countDspAllocations)++dspAllocations;}
}
