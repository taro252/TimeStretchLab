#include "dsp/StereoPhaseCoherence.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace ts {
StereoPhaseCoherence::StereoPhaseCoherence(std::size_t fftSize, double sampleRate,
                                           float strength, float lowFrequencyStrength)
    : fftSize_(fftSize), sampleRate_(sampleRate), strength_(strength),
      lowFrequencyStrength_(lowFrequencyStrength), previousIpd_(fftSize / 2 + 1),
      valid_(fftSize / 2 + 1, false), weights_(fftSize / 2 + 1) {
    if (fftSize < 16 || !std::isfinite(sampleRate) || sampleRate <= 0 ||
        !std::isfinite(strength) || strength < 0 || strength > 1 ||
        !std::isfinite(lowFrequencyStrength) || lowFrequencyStrength < 0 || lowFrequencyStrength > 1)
        throw std::invalid_argument("Invalid stereo coherence configuration");
}
void StereoPhaseCoherence::reset() {
    std::fill(valid_.begin(), valid_.end(), false);
    std::fill(previousIpd_.begin(), previousIpd_.end(), 0.0);
    std::fill(weights_.begin(), weights_.end(), 0.0f);
    weightSum_ = 0;
    weightedBins_ = 0;
}
void StereoPhaseCoherence::process(const std::complex<float>* leftInput,
                                   const std::complex<float>* rightInput,
                                   std::complex<float>* leftOutput,
                                   std::complex<float>* rightOutput,
                                   PhaseVocoder& leftVocoder, PhaseVocoder& rightVocoder,
                                   const std::vector<int>& owners) {
    constexpr double twoPi = 2 * std::numbers::pi;
    for (std::size_t k = 1; k < fftSize_ / 2; ++k) {
        weights_[k] = 0;
        const double leftMag = std::abs(leftInput[k]), rightMag = std::abs(rightInput[k]);
        if (std::min(leftMag, rightMag) < 1e-7) {
            valid_[k] = false;
            continue;
        }
        const double ipd = std::remainder(double(std::arg(rightInput[k])) -
                                          std::arg(leftInput[k]), twoPi);
        const double stability = valid_[k]
            ? std::clamp(1.0 - std::abs(std::remainder(ipd - previousIpd_[k], twoPi)) / 1.2,
                         0.0, 1.0) : 0.0;
        previousIpd_[k] = ipd;
        valid_[k] = true;
        const int owner = owners[k];
        if (owner < 1 || std::abs(owner - static_cast<int>(k)) > 3) continue;
        const auto combined = [&](std::size_t bin) {
            return std::hypot(double(std::abs(leftInput[bin])),
                              double(std::abs(rightInput[bin])));
        };
        const double peak = combined(static_cast<std::size_t>(owner));
        double localMean = 0;
        int count = 0;
        for (int j = -8; j <= 8; ++j) {
            const auto bin = owner + j;
            if (bin < 1 || bin >= static_cast<int>(fftSize_ / 2)) continue;
            localMean += combined(static_cast<std::size_t>(bin));
            ++count;
        }
        localMean /= count;
        const double tonality = std::clamp((peak / (localMean + 1e-12) - 1.5) / 3.0, 0.0, 1.0);
        const double balance = 2 * std::min(leftMag, rightMag) / (leftMag + rightMag + 1e-12);
        const double frequency = k * sampleRate_ / fftSize_;
        const double lowBlend = frequency <= 150 ? 1.0 :
            (frequency >= 500 ? 0.0 : (500.0 - frequency) / 350.0);
        const double lowFactor = 1.0 + lowFrequencyStrength_ * lowBlend;
        const double weight = std::clamp(strength_ * balance * tonality * stability *
                                         lowFactor, 0.0, 1.0);
        weights_[k] = static_cast<float>(weight);
        weightSum_ += weight;
        ++weightedBins_;
        if (weight < 1e-6) continue;
        // The stronger channel provides the anchor. Preserve the input's signed
        // R-minus-L phase difference when forming the other channel's target.
        const bool leftReference = leftMag >= rightMag;
        const double reference = std::arg(leftReference ? leftOutput[k] : rightOutput[k]);
        const double target = std::remainder(reference + (leftReference ? ipd : -ipd), twoPi);
        auto& other = leftReference ? rightOutput[k] : leftOutput[k];
        const double independent = std::arg(other);
        const auto blend = (1.0 - weight) * std::polar(1.0, independent) +
                           weight * std::polar(1.0, target);
        if (std::abs(blend) < 1e-10) continue;
        const double finalPhase = std::arg(blend);
        other = std::polar(std::abs(other), static_cast<float>(finalPhase));
        (leftReference ? rightVocoder : leftVocoder).setOutputPhase(k, finalPhase);
    }
}
}
