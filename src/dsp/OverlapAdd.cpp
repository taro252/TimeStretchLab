#include "dsp/OverlapAdd.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace ts {
OverlapAdd::OverlapAdd(std::size_t capacity) : signal_(capacity), weight_(capacity) {}
void OverlapAdd::reset() {
    std::fill(signal_.begin(), signal_.end(), 0.0f);
    std::fill(weight_.begin(), weight_.end(), 0.0f);
}
void OverlapAdd::add(const float* frame, const float* window, std::size_t size, long long start) {
    if (start < 0 || static_cast<std::size_t>(start) + size > signal_.size())
        throw std::out_of_range("OverlapAdd capacity exceeded");
    for (std::size_t i = 0; i < size; ++i) {
        const auto p = static_cast<std::size_t>(start) + i;
        signal_[p] += frame[i];
        // Analysis and synthesis both apply Hann, so divide by their product.
        weight_[p] += window[i] * window[i];
    }
}
std::vector<float> OverlapAdd::finish(std::size_t size, std::size_t padding) const {
    if (padding + size > signal_.size()) throw std::out_of_range("Output exceeds OLA capacity");
    std::vector<float> output(size);
    for (std::size_t i = 0; i < size; ++i) {
        const auto p = padding + i;
        output[i] = weight_[p] > 1e-8f ? signal_[p] / weight_[p] : 0.0f;
    }
    return output;
}
}
