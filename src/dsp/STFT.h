#pragma once
#include "dsp/FFTAccelerate.h"
#include <complex>
#include <vector>

namespace ts {
class STFT {
public:
    explicit STFT(std::size_t fftSize);
    std::size_t size() const { return window_.size(); }
    const std::vector<float>& window() const { return window_; }
    void analyze(const float* input, std::complex<float>* spectrum);
    void synthesize(const std::complex<float>* spectrum, float* output);
private:
    FFTAccelerate fft_;
    std::vector<float> window_, scratch_;
};
}
