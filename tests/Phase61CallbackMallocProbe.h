#pragma once
#include <cstdint>
extern "C" {
void phase61_heap_begin() noexcept;
void phase61_heap_end() noexcept;
void phase61_heap_reset() noexcept; // only while render is quiescent
std::uint64_t phase61_heap_allocations() noexcept;
std::uint64_t phase61_heap_frees() noexcept;
}
