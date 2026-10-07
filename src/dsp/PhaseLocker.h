#pragma once
#include <complex>
#include <cstddef>
#include <vector>

namespace ts {
struct SpectralPeak {
    int bin = 0;
    float position = 0;
    float magnitude = 0;
};

// Frame-local peak map. It owns no channel history, allowing a future shared
// stereo peak map without changing the peak detection algorithm.
class PhaseLocker {
public:
    explicit PhaseLocker(std::size_t fftSize, float relativeThreshold = 0.001f);
    void reset();
    void analyzePeaks(const std::complex<float>* spectrum, std::size_t binCount);
    void lock(std::vector<double>& synthesisPhase, std::complex<float>* output) const;
    const std::vector<SpectralPeak>& peaks() const { return peaks_; }
    const std::vector<int>& ownerPeak() const { return ownerPeak_; }
    const std::vector<float>& magnitudes() const { return magnitude_; }
private:
    std::size_t binCount_;
    float relativeThreshold_;
    std::vector<float> magnitude_, phase_;
    std::vector<int> ownerPeak_;
    std::vector<SpectralPeak> peaks_;
};
}
