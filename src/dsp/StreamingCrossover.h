#pragma once
#include "dsp/FFTAccelerate.h"
#include "dsp/MultiResolutionCrossover.h"
#include <algorithm>
#include <complex>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace ts {
// Streaming counterpart of MultiResolutionCrossover::addFilteredDifference.
// It uses the same 4096-point FFT blocks and filter responses, preserving the
// original block boundaries across output chunks.
class StreamingFIR {
public:
    StreamingFIR(const MultiResolutionCrossover::Filter& filter, std::size_t outputLength);
    template<class Source> float next(std::size_t index, Source&& source) {
        if (index != base_) throw std::logic_error("Non-sequential FIR retrieval");
        while (nextBlock_ < outputLength_ && nextBlock_ <= index + center_) {
            std::fill(block_.begin(), block_.end(), 0.0f);
            const auto count = std::min(blockLength_, outputLength_-nextBlock_);
            for (std::size_t i = 0; i < count; ++i)
                block_[i] = source(nextBlock_+i);
            fft_.forward(block_.data(), spectrum_.data());
            for (std::size_t k = 0; k < spectrum_.size(); ++k)
                spectrum_[k] *= response_[k];
            fft_.inverse(spectrum_.data(), transformed_.data());
            const auto valid = count + taps_ - 1;
            for (std::size_t i = 0; i < valid; ++i) {
                const auto target = static_cast<long long>(nextBlock_+i) -
                    static_cast<long long>(center_);
                if (target < 0 || static_cast<std::size_t>(target) >= outputLength_) continue;
                const auto position = static_cast<std::size_t>(target);
                if (position < base_ || position >= base_+accum_.size())
                    throw std::out_of_range("FIR ring capacity exceeded");
                accum_[position%accum_.size()] += transformed_[i];
            }
            nextBlock_ += blockLength_;
        }
        const auto slot = index%accum_.size();
        const float result = accum_[slot];
        accum_[slot] = 0;
        ++base_;
        return result;
    }
    std::size_t ringSize() const { return accum_.size(); }
private:
    static constexpr std::size_t fftSize_ = 4096;
    FFTAccelerate fft_{fftSize_};
    std::size_t taps_, center_, blockLength_, outputLength_, nextBlock_ = 0, base_ = 0;
    std::vector<std::complex<float>> response_, spectrum_;
    std::vector<float> block_, transformed_, accum_;
};

class StreamingCrossoverChannel {
public:
    StreamingCrossoverChannel(const MultiResolutionCrossover& filters,
                              std::size_t outputLength);
    template<class GetSample> float next(std::size_t index, GetSample&& get) {
        const float high = get(2,index);
        const float lowDifference = low_.next(index, [&](std::size_t i) {
            return get(0,i)-get(1,i);
        });
        const float highDifference = high_.next(index, [&](std::size_t i) {
            return get(1,i)-get(2,i);
        });
        float result = high;
        result += lowDifference;
        result += highDifference;
        return result;
    }
    std::size_t ringSize() const { return low_.ringSize()+high_.ringSize(); }
private:
    StreamingFIR low_, high_;
};
}
