#pragma once
#include "dsp/PhaseVocoder.h"
#include <complex>
#include <cstddef>
#include <vector>

namespace ts {
// Joint stereo phase correction applied after the two ordinary vocoders.
// Magnitudes remain channel-local, so level differences and panning survive.
class StereoPhaseCoherence {
public:
    StereoPhaseCoherence(std::size_t fftSize, double sampleRate, float strength,
                         float lowFrequencyStrength);
    void reset();
    void process(const std::complex<float>* leftInput, const std::complex<float>* rightInput,
                 std::complex<float>* leftOutput, std::complex<float>* rightOutput,
                 PhaseVocoder& leftVocoder, PhaseVocoder& rightVocoder,
                 const std::vector<int>& owners);
    const std::vector<float>& weights() const { return weights_; }
    double averageWeight() const { return weightedBins_ ? weightSum_ / weightedBins_ : 0.0; }
private:
    std::size_t fftSize_;
    double sampleRate_;
    float strength_, lowFrequencyStrength_;
    std::vector<double> previousIpd_;
    std::vector<bool> valid_;
    std::vector<float> weights_;
    double weightSum_ = 0;
    std::size_t weightedBins_ = 0;
};
}
