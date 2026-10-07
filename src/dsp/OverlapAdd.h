#pragma once
#include <cstddef>
#include <vector>

namespace ts {
class OverlapAdd {
public:
    explicit OverlapAdd(std::size_t capacity);
    void reset();
    void add(const float* frame, const float* window, std::size_t frameSize, long long start);
    std::vector<float> finish(std::size_t outputSize, std::size_t padding) const;
private:
    std::vector<float> signal_, weight_;
};
}
