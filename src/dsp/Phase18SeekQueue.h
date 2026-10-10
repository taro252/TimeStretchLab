#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <utility>

namespace ts {
// Single control-side requester may replace an in-flight preparation. The
// callback never accesses this queue; old requests are discarded by version.
class Phase18SeekQueue {
public:
    std::uint64_t post(std::size_t outputFrame) {
        std::lock_guard guard(mutex_);
        target_=outputFrame;
        return version_.fetch_add(1,std::memory_order_release)+1;
    }
    std::pair<std::uint64_t,std::size_t> latest() const {
        std::lock_guard guard(mutex_);
        return {version_.load(std::memory_order_acquire),target_};
    }
    bool superseded(std::uint64_t version) const noexcept {
        return version_.load(std::memory_order_acquire)!=version;
    }
private:
    mutable std::mutex mutex_;
    std::size_t target_=0;
    std::atomic<std::uint64_t> version_{0};
};
}
