#include "dsp/STFT.h"
#include <cmath>
#include <numbers>

namespace ts {
STFT::STFT(std::size_t size) : fft_(size), window_(size), scratch_(size) {
    // Periodic Hann aligns overlapping frames at integer hop distances.
    for (std::size_t i = 0; i < size; ++i)
        window_[i] = 0.5f * (1.0f - std::cos(2.0 * std::numbers::pi * i / size));
}
void STFT::analyze(const float* input, std::complex<float>* spectrum) {
    for (std::size_t i = 0; i < size(); ++i) scratch_[i] = input[i] * window_[i];
    fft_.forward(scratch_.data(), spectrum);
}
void STFT::synthesize(const std::complex<float>* spectrum, float* output) {
    fft_.inverse(spectrum, output);
    for (std::size_t i = 0; i < size(); ++i) output[i] *= window_[i];
}
}
