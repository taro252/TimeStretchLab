#pragma once
#include <Accelerate/Accelerate.h>
#include <complex>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace ts {
class FFTAccelerate {
public:
    explicit FFTAccelerate(std::size_t fftSize);
    ~FFTAccelerate();
    FFTAccelerate(const FFTAccelerate&) = delete;
    FFTAccelerate& operator=(const FFTAccelerate&) = delete;
    std::size_t size() const { return size_; }
    // Spectrum contains N/2+1 bins, including DC and Nyquist.
    void forward(const float* timeDomain, std::complex<float>* spectrum);
    void inverse(const std::complex<float>* spectrum, float* timeDomain);
private:
    std::size_t size_;
    vDSP_Length log2Size_;
    FFTSetup setup_;
    // The 1024-point path needs a fixed SIMD alignment; other sizes retain
    // their Phase 1–5 storage layout for exact regression compatibility.
    std::vector<float> realStorage_, imagStorage_;
    float* real_ = nullptr;
    float* imag_ = nullptr;
    static float* alignedWorkspace(std::vector<float>& storage);
};
}
