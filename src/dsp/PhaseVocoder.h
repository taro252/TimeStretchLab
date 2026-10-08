#pragma once
#include "dsp/PhaseLocker.h"
#include <complex>
#include <cstddef>
#include <vector>

namespace ts {
class PhaseVocoder {
public:
    PhaseVocoder(std::size_t fftSize, int analysisHop, bool enablePhaseLocking = false,
                 double sampleRate = 44100.0);
    void reset();
    // Hs is the distance from the preceding synthesis frame, including fractional timing.
    void process(const std::complex<float>* input, std::complex<float>* output,
                 double synthesisHop, bool resetPhase = false,
                 bool selectiveReset = false, float eventStrength = 1.0f);
    const PhaseLocker& phaseLocker() const { return phaseLocker_; }
private:
    std::size_t size_;
    int analysisHop_;
    double sampleRate_;
    std::vector<bool> initialized_;
    std::vector<double> previousPhase_, synthesisPhase_;
    std::vector<float> previousMagnitude_;
    bool enablePhaseLocking_;
    PhaseLocker phaseLocker_;
};
}
