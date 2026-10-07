#include "dsp/PhaseLocker.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace ts {
PhaseLocker::PhaseLocker(std::size_t fftSize, float relativeThreshold)
    : binCount_(fftSize / 2 + 1), relativeThreshold_(relativeThreshold),
      magnitude_(binCount_), phase_(binCount_), ownerPeak_(binCount_, -1) {
    if (fftSize < 16 || !std::isfinite(relativeThreshold) || relativeThreshold <= 0)
        throw std::invalid_argument("Invalid PhaseLocker configuration");
    peaks_.reserve(binCount_); // No peak-list allocation in the audio frame loop.
}
void PhaseLocker::reset() {
    peaks_.clear();
    std::fill(ownerPeak_.begin(), ownerPeak_.end(), -1);
    std::fill(magnitude_.begin(), magnitude_.end(), 0.0f);
    std::fill(phase_.begin(), phase_.end(), 0.0f);
}
void PhaseLocker::analyzePeaks(const std::complex<float>* spectrum, std::size_t binCount) {
    if (binCount != binCount_) throw std::invalid_argument("Spectrum bin count mismatch");
    peaks_.clear();
    std::fill(ownerPeak_.begin(), ownerPeak_.end(), -1);
    float frameMax = 0;
    for (std::size_t k = 0; k < binCount_; ++k) {
        magnitude_[k] = std::abs(spectrum[k]);
        phase_[k] = magnitude_[k] >= 1e-7f
            ? std::atan2(spectrum[k].imag(), spectrum[k].real()) : 0.0f;
        frameMax = std::max(frameMax, magnitude_[k]);
    }
    // Below this floor, every bin is below the vocoder's phase-tracking floor.
    if (frameMax < 1e-7f) return;
    const float threshold = std::max(1e-7f, frameMax * relativeThreshold_);
    for (std::size_t k = 1; k + 1 < binCount_; ++k) {
        if (magnitude_[k] < threshold || magnitude_[k] <= magnitude_[k - 1] ||
            magnitude_[k] < magnitude_[k + 1]) continue;
        // Log-parabolic interpolation is for diagnostics and frequency estimates;
        // integer bins continue to define the stable midpoint owner map.
        constexpr double epsilon = 1e-12;
        const double a = std::log(std::max(double(magnitude_[k - 1]), epsilon));
        const double b = std::log(std::max(double(magnitude_[k]), epsilon));
        const double c = std::log(std::max(double(magnitude_[k + 1]), epsilon));
        const double denominator = a - 2 * b + c;
        const double offset = std::abs(denominator) > 1e-12
            ? std::clamp(0.5 * (a - c) / denominator, -0.5, 0.5) : 0.0;
        peaks_.push_back({static_cast<int>(k), static_cast<float>(k + offset), magnitude_[k]});
    }
    if (peaks_.empty()) return;
    // With sorted local maxima, the integer midpoint belongs to the left peak.
    std::size_t peakIndex = 0;
    for (std::size_t k = 1; k + 1 < binCount_; ++k) {
        while (peakIndex + 1 < peaks_.size() &&
               static_cast<int>(k) > (peaks_[peakIndex].bin + peaks_[peakIndex + 1].bin) / 2)
            ++peakIndex;
        ownerPeak_[k] = peaks_[peakIndex].bin;
    }
}
void PhaseLocker::lock(std::vector<double>& synthesisPhase, std::complex<float>* output) const {
    if (peaks_.empty()) return; // Phase 1 fallback for silent/peakless frames.
    constexpr double twoPi = 2.0 * std::numbers::pi;
    for (std::size_t k = 1; k + 1 < binCount_; ++k) {
        const int owner = ownerPeak_[k];
        if (owner < 0 || static_cast<int>(k) == owner || magnitude_[k] < 1e-7f) continue;
        // Identity phase locking preserves each bin's within-frame phase offset
        // from its owner peak. The anchor itself retains Phase 1 propagation.
        const double relative = std::remainder(double(phase_[k]) - phase_[owner], twoPi);
        const double locked = std::remainder(synthesisPhase[owner] + relative, twoPi);
        // Keep the persistent state equal to the phase actually sent to the IFFT.
        // A region member may become a peak or change owners in the next frame.
        synthesisPhase[k] = locked;
        output[k] = std::polar(magnitude_[k], static_cast<float>(locked));
    }
}
}
