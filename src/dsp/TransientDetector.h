#pragma once
#include <cstddef>
#include <limits>
#include <vector>

namespace ts {
struct TransientConfig {
    float logGain = 10.0f;
    float sensitivity = 3.0f;
    float minimumFlux = 0.02f;
    float resetStrengthThreshold = 0.25f;
    int historyFrames = 12;
    int cooldownFrames = 2;
    int lookbackFrames = 1;
};

struct TransientFrame {
    double spectralFlux = 0;
    double logEnergy = 0;
    double previousLogEnergy = 0;
    double threshold = 0;
    float strength = 0;
    bool detected = false;
    bool resetApplied = false;
};

// Offline detector: collect log-spectral flux, then use previous-frame
// median/MAD and one-frame look-ahead to select shared reset positions.
class TransientDetector {
public:
    TransientDetector(std::size_t binCount, TransientConfig config);
    void reset();
    void pushMagnitudes(const float* combinedMagnitudes);
    void finalize(std::size_t activeFrameCount = std::numeric_limits<std::size_t>::max());
    const std::vector<TransientFrame>& frames() const { return frames_; }
    bool resetAt(std::size_t frame) const { return frames_[frame].resetApplied; }
    std::size_t transientCount() const { return transientCount_; }
private:
    double median(std::vector<double>& values) const;
    std::size_t binCount_;
    TransientConfig config_;
    std::vector<float> previousLog_;
    double previousLogSum_ = 0;
    std::vector<TransientFrame> frames_;
    std::size_t transientCount_ = 0;
};
}
