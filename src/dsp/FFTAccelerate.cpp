#include "dsp/FFTAccelerate.h"
#include <algorithm>
#include <cstdint>
#include <stdexcept>

namespace ts {
float* FFTAccelerate::alignedWorkspace(std::vector<float>& storage) {
    const auto address = reinterpret_cast<std::uintptr_t>(storage.data());
    const auto aligned = (address + 63u) & ~std::uintptr_t(63u);
    return reinterpret_cast<float*>(aligned + 16u);
}
FFTAccelerate::FFTAccelerate(std::size_t fftSize)
    : size_(fftSize), log2Size_(0), setup_(nullptr),
      realStorage_(fftSize + (fftSize == 1024 ? 24 : 0)),
      imagStorage_(fftSize + (fftSize == 1024 ? 24 : 0)),
      real_(fftSize == 1024 ? alignedWorkspace(realStorage_) : realStorage_.data()),
      imag_(fftSize == 1024 ? alignedWorkspace(imagStorage_) : imagStorage_.data()) {
    if (fftSize < 16 || (fftSize & (fftSize - 1)))
        throw std::invalid_argument("FFT size must be a power of two >= 16");
    for (auto n = fftSize; n > 1; n >>= 1) ++log2Size_;
    setup_ = vDSP_create_fftsetup(log2Size_, kFFTRadix2);
    if (!setup_) throw std::runtime_error("vDSP FFT setup failed");
}
FFTAccelerate::~FFTAccelerate() { vDSP_destroy_fftsetup(setup_); }
void FFTAccelerate::forward(const float* input, std::complex<float>* output) {
    std::copy_n(input, size_, real_);
    std::fill_n(imag_, size_, 0.0f);
    DSPSplitComplex split{real_, imag_};
    vDSP_fft_zip(setup_, &split, 1, log2Size_, FFT_FORWARD);
    for (std::size_t k = 0; k <= size_ / 2; ++k) output[k] = {real_[k], imag_[k]};
}
void FFTAccelerate::inverse(const std::complex<float>* input, float* output) {
    real_[0] = input[0].real(); imag_[0] = 0;
    real_[size_ / 2] = input[size_ / 2].real(); imag_[size_ / 2] = 0;
    for (std::size_t k = 1; k < size_ / 2; ++k) {
        real_[k] = input[k].real(); imag_[k] = input[k].imag();
        real_[size_ - k] = real_[k]; imag_[size_ - k] = -imag_[k];
    }
    DSPSplitComplex split{real_, imag_};
    vDSP_fft_zip(setup_, &split, 1, log2Size_, FFT_INVERSE);
    const float scale = 1.0f / static_cast<float>(size_);
    for (std::size_t i = 0; i < size_; ++i) output[i] = real_[i] * scale;
}
}
