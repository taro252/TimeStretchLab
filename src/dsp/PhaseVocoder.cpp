#include "dsp/PhaseVocoder.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace ts {
PhaseVocoder::PhaseVocoder(std::size_t size, int hop)
    : size_(size), analysisHop_(hop), initialized_(size / 2 + 1, false),
      previousPhase_(size / 2 + 1), synthesisPhase_(size / 2 + 1) {
    if (hop <= 0) throw std::invalid_argument("Analysis hop must be positive");
}
void PhaseVocoder::reset() {
    std::fill(initialized_.begin(), initialized_.end(), false);
    std::fill(previousPhase_.begin(), previousPhase_.end(), 0.0);
    std::fill(synthesisPhase_.begin(), synthesisPhase_.end(), 0.0);
}
void PhaseVocoder::process(const std::complex<float>* input, std::complex<float>* output, double synthesisHop) {
    constexpr double pi = std::numbers::pi;
    // DC and Nyquist must remain real for a real-valued inverse transform.
    output[0] = {input[0].real(), 0.0f};
    output[size_ / 2] = {input[size_ / 2].real(), 0.0f};
    for (std::size_t k = 1; k < size_ / 2; ++k) {
        const double magnitude = std::abs(input[k]);
        if (magnitude < 1e-7) {
            output[k] = {0, 0};
            // A later reappearance is a new onset: the previous phase no longer
            // represents a sample exactly one analysis hop in the past.
            initialized_[k] = false;
            previousPhase_[k] = 0.0;
            synthesisPhase_[k] = 0.0;
            continue;
        }
        const double phase = std::atan2(input[k].imag(), input[k].real());
        if (!initialized_[k]) synthesisPhase_[k] = phase;
        else {
            const double binOmega = 2.0 * pi * k / size_;
            const double expected = binOmega * analysisHop_;
            const double residual = std::remainder(phase - previousPhase_[k] - expected, 2.0 * pi);
            // Basic bin-wise propagation retains a sinusoid between FFT bins at its pitch.
            synthesisPhase_[k] = std::remainder(
                synthesisPhase_[k] + (binOmega + residual / analysisHop_) * synthesisHop, 2.0 * pi);
        }
        previousPhase_[k] = phase;
        initialized_[k] = true;
        output[k] = std::polar(static_cast<float>(magnitude), static_cast<float>(synthesisPhase_[k]));
    }
}
}
