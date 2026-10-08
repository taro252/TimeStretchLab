#include "dsp/MultiResolutionCrossover.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace ts {
MultiResolutionCrossover::MultiResolutionCrossover(double sampleRate)
    : fft_(fftSize_), low_(makeFilter(fft_, 2049, 250, sampleRate)),
      high_(makeFilter(fft_, 513, 3500, sampleRate)),
      block_(fftSize_), transformed_(fftSize_), spectrum_(fftSize_/2+1) {}
MultiResolutionCrossover::Filter MultiResolutionCrossover::makeFilter(
    FFTAccelerate& fft, std::size_t taps, double cutoff, double rate) {
    if (rate <= 0 || cutoff <= 0 || cutoff >= rate/2 || taps > fftSize_ || taps % 2 == 0)
        throw std::invalid_argument("Invalid crossover filter");
    std::vector<float> impulse(fftSize_);
    const auto center = static_cast<long long>(taps/2);
    double sum = 0;
    for (std::size_t i = 0; i < taps; ++i) {
        const auto x = static_cast<long long>(i)-center;
        const double sinc = x == 0 ? 2*cutoff/rate :
            std::sin(2*std::numbers::pi*cutoff*x/rate)/(std::numbers::pi*x);
        const double window = 0.42 - 0.5*std::cos(2*std::numbers::pi*i/(taps-1)) +
                              0.08*std::cos(4*std::numbers::pi*i/(taps-1));
        impulse[i] = static_cast<float>(sinc*window);
        sum += impulse[i];
    }
    for (std::size_t i = 0; i < taps; ++i) impulse[i] /= static_cast<float>(sum);
    Filter filter{taps, std::vector<std::complex<float>>(fftSize_/2+1)};
    fft.forward(impulse.data(), filter.response.data());
    return filter;
}
void MultiResolutionCrossover::addFilteredDifference(
    const std::vector<float>& positive, const std::vector<float>& negative,
    const Filter& filter, std::vector<float>& output) {
    const auto length = output.size();
    const auto blockLength = fftSize_ - filter.taps + 1;
    const auto center = static_cast<long long>(filter.taps/2);
    for (std::size_t start = 0; start < length; start += blockLength) {
        std::fill(block_.begin(), block_.end(), 0.0f);
        const auto count = std::min(blockLength, length-start);
        for (std::size_t i = 0; i < count; ++i)
            block_[i] = positive[start+i] - negative[start+i];
        fft_.forward(block_.data(), spectrum_.data());
        for (std::size_t k = 0; k < spectrum_.size(); ++k)
            spectrum_[k] *= filter.response[k];
        fft_.inverse(spectrum_.data(), transformed_.data());
        const auto valid = count + filter.taps - 1;
        for (std::size_t i = 0; i < valid; ++i) {
            const auto target = static_cast<long long>(start+i)-center;
            if (target >= 0 && static_cast<std::size_t>(target) < length)
                output[static_cast<std::size_t>(target)] += transformed_[i];
        }
    }
}
void MultiResolutionCrossover::combine(const std::vector<float>& low,
                                        const std::vector<float>& mid,
                                        const std::vector<float>& high,
                                        std::vector<float>& output) {
    if (low.size() != mid.size() || low.size() != high.size())
        throw std::invalid_argument("Crossover input lengths differ");
    output = high;
    addFilteredDifference(low, mid, low_, output);
    addFilteredDifference(mid, high, high_, output);
}
std::size_t MultiResolutionCrossover::workingMemoryBytes() const {
    return (block_.size()+transformed_.size())*sizeof(float) +
        (spectrum_.size()+low_.response.size()+high_.response.size())*sizeof(std::complex<float>);
}
}
