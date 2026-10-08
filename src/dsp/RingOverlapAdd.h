#pragma once
#include <cstddef>
#include <vector>

namespace ts {
// Stores only samples that may still receive a future synthesis window.
class RingOverlapAdd {
public:
    explicit RingOverlapAdd(std::size_t capacity);
    void add(const float* frame, const float* window, std::size_t size, long long start);
    float pop();
    std::size_t nextAbsoluteSample() const { return base_; }
    std::size_t capacity() const { return signal_.size(); }
private:
    std::vector<float> signal_, weight_;
    std::size_t base_ = 0;
};
}
