#include "dsp/RingOverlapAdd.h"
#include <algorithm>
#include <stdexcept>

namespace ts {
RingOverlapAdd::RingOverlapAdd(std::size_t capacity)
    : signal_(capacity), weight_(capacity) {
    if (capacity == 0) throw std::invalid_argument("Empty OLA ring");
}
void RingOverlapAdd::reset() {
    std::fill(signal_.begin(),signal_.end(),0.0f);
    std::fill(weight_.begin(),weight_.end(),0.0f);
    base_=0;
}
void RingOverlapAdd::add(const float* frame, const float* window,
                         std::size_t size, long long start) {
    if (start < 0 || static_cast<std::size_t>(start) < base_ ||
        static_cast<std::size_t>(start)+size > base_+signal_.size())
        throw std::out_of_range("OLA ring capacity exceeded");
    for (std::size_t i = 0; i < size; ++i) {
        const auto slot = (static_cast<std::size_t>(start)+i)%signal_.size();
        signal_[slot] += frame[i];
        weight_[slot] += window[i]*window[i];
    }
}
float RingOverlapAdd::pop() {
    const auto slot = base_%signal_.size();
    const float result = weight_[slot] > 1e-8f ? signal_[slot]/weight_[slot] : 0.0f;
    signal_[slot] = 0;
    weight_[slot] = 0;
    ++base_;
    return result;
}
float RingOverlapAdd::preview(std::size_t absoluteSample) const {
    if (absoluteSample<base_ || absoluteSample>=base_+signal_.size())
        return 0;
    const auto slot=absoluteSample%signal_.size();
    return weight_[slot]>1e-8f ? signal_[slot]/weight_[slot] : 0.0f;
}
}
