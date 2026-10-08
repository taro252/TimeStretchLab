#pragma once
#include "dsp/FFTAccelerate.h"
#include <complex>
#include <cstddef>
#include <vector>

namespace ts {
// Centered, symmetric FIR crossover implemented by FFT overlap-add.
// For identical inputs, high + LP(low-mid) + LP(mid-high) is exactly unity.
class MultiResolutionCrossover {
public:
    explicit MultiResolutionCrossover(double sampleRate);
    void combine(const std::vector<float>& low, const std::vector<float>& mid,
                 const std::vector<float>& high, std::vector<float>& output);
    std::size_t workingMemoryBytes() const;
private:
    struct Filter {
        std::size_t taps;
        std::vector<std::complex<float>> response;
    };
    static constexpr std::size_t fftSize_ = 4096;
    FFTAccelerate fft_;
    Filter low_, high_;
    std::vector<float> block_, transformed_;
    std::vector<std::complex<float>> spectrum_;
    static Filter makeFilter(FFTAccelerate& fft, std::size_t taps,
                             double cutoff, double rate);
    void addFilteredDifference(const std::vector<float>& positive,
                               const std::vector<float>& negative,
                               const Filter& filter, std::vector<float>& output);
};
}
