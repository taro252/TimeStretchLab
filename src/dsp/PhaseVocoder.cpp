#include "dsp/PhaseVocoder.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace ts {
PhaseVocoder::PhaseVocoder(std::size_t size, int hop, bool enablePhaseLocking, double sampleRate)
    : size_(size), analysisHop_(hop), sampleRate_(sampleRate), initialized_(size / 2 + 1, false),
      resyncPending_(size / 2 + 1,false),
      previousPhase_(size / 2 + 1), synthesisPhase_(size / 2 + 1),
      previousMagnitude_(size / 2 + 1),
      enablePhaseLocking_(enablePhaseLocking), phaseLocker_(size) {
    if (hop <= 0 || !std::isfinite(sampleRate) || sampleRate <= 0)
        throw std::invalid_argument("Invalid analysis hop or sample rate");
}
void PhaseVocoder::reset() {
    std::fill(initialized_.begin(), initialized_.end(), false);
    std::fill(resyncPending_.begin(), resyncPending_.end(), false);
    std::fill(previousPhase_.begin(), previousPhase_.end(), 0.0);
    std::fill(synthesisPhase_.begin(), synthesisPhase_.end(), 0.0);
    std::fill(previousMagnitude_.begin(), previousMagnitude_.end(), 0.0f);
    phaseLocker_.reset();
}
void PhaseVocoder::process(const std::complex<float>* input, std::complex<float>* output,
                           double synthesisHop, bool resetPhase,
                           bool selectiveReset, float eventStrength,
                           const std::vector<int>* sharedOwners,int analysisHopOverride) {
    constexpr double pi = std::numbers::pi;
    // DC and Nyquist must remain real for a real-valued inverse transform.
    output[0] = {input[0].real(), 0.0f};
    output[size_ / 2] = {input[size_ / 2].real(), 0.0f};
    for (std::size_t k = 1; k < size_ / 2; ++k) {
        const int analysisDistance=analysisHopOverride>0 && resyncPending_[k]
            ? analysisHopOverride : analysisHop_;
        resyncPending_[k]=false;
        const double magnitude = std::abs(input[k]);
        if (magnitude < 1e-7) {
            output[k] = {0, 0};
            // A later reappearance is a new onset: the previous phase no longer
            // represents a sample exactly one analysis hop in the past.
            initialized_[k] = false;
            previousPhase_[k] = 0.0;
            synthesisPhase_[k] = 0.0;
            previousMagnitude_[k] = 0.0f;
            continue;
        }
        const double phase = std::atan2(input[k].imag(), input[k].real());
        // At an onset, align the output and persistent state with this frame's
        // analysis phase; propagation across an attack would smear its timing.
        if ((resetPhase && !selectiveReset) || !initialized_[k]) synthesisPhase_[k] = phase;
        else {
            const double binOmega = 2.0 * pi * k / size_;
            const double expected = binOmega * analysisDistance;
            const double residual = std::remainder(phase - previousPhase_[k] - expected, 2.0 * pi);
            // Basic bin-wise propagation retains a sinusoid between FFT bins at its pitch.
            synthesisPhase_[k] = std::remainder(
                synthesisPhase_[k] + (binOmega + residual / analysisDistance) * synthesisHop, 2.0 * pi);
            if (resetPhase && selectiveReset) {
                const double rise = std::max(0.0, magnitude - previousMagnitude_[k]);
                const double relativeRise = std::clamp(rise / (magnitude + 1e-7), 0.0, 1.0);
                const double frequency = k * sampleRate_ / size_;
                const double lowWeight = frequency <= 120 ? 0.2 :
                    (frequency >= 250 ? 1.0 :
                     0.2 + 0.8 * (0.5 - 0.5 * std::cos(pi * (frequency - 120) / 130)));
                const double amount = std::clamp(double(eventStrength) *
                    relativeRise * lowWeight, 0.0, 1.0);
                if (amount > 0) {
                    const auto propagated = std::polar(1.0, synthesisPhase_[k]);
                    const auto analyzed = std::polar(1.0, phase);
                    const auto blended = (1 - amount) * propagated + amount * analyzed;
                    if (std::abs(blended) > 1e-10) synthesisPhase_[k] = std::arg(blended);
                }
            }
        }
        previousPhase_[k] = phase;
        previousMagnitude_[k] = static_cast<float>(magnitude);
        initialized_[k] = true;
        output[k] = std::polar(static_cast<float>(magnitude), static_cast<float>(synthesisPhase_[k]));
    }
    if (enablePhaseLocking_) {
        if (sharedOwners) PhaseLocker::lockWithOwners(input, output, synthesisPhase_, *sharedOwners);
        else {
            phaseLocker_.analyzePeaks(input, size_ / 2 + 1);
            phaseLocker_.lock(synthesisPhase_, output);
        }
    }
}
void PhaseVocoder::resynchronize(const std::complex<float>* scheduled,
                                 const std::complex<float>* aligned,
                                 std::complex<float>* output,
                                 const std::vector<int>* sharedOwners) {
    constexpr double twoPi=2.0*std::numbers::pi;
    for (std::size_t k=1;k<size_/2;++k) {
        const float magnitude=std::abs(scheduled[k]);
        const float alignedMagnitude=std::abs(aligned[k]);
        if (magnitude<1e-7f || alignedMagnitude<1e-7f) {
            if (magnitude<1e-7f) {
                output[k]={0,0}; initialized_[k]=false;
                previousPhase_[k]=synthesisPhase_[k]=0;
                previousMagnitude_[k]=0;
                resyncPending_[k]=false;
            }
            continue;
        }
        const double phase=std::arg(aligned[k]);
        previousPhase_[k]=synthesisPhase_[k]=phase;
        previousMagnitude_[k]=magnitude;
        initialized_[k]=true;
        resyncPending_[k]=true;
        output[k]=std::polar(magnitude,static_cast<float>(phase));
    }
    // Preserve the scheduled peak ownership while using the aligned frame's
    // relative phase. Also update persistent state to exactly match IFFT phase.
    const auto& owners=sharedOwners ? *sharedOwners : phaseLocker_.ownerPeak();
    for (std::size_t k=1;k<size_/2;++k) {
        const int owner=owners[k];
        if (owner<1 || static_cast<std::size_t>(owner)==k ||
            std::abs(scheduled[k])<1e-7f || std::abs(aligned[k])<1e-7f ||
            std::abs(aligned[owner])<1e-7f || !initialized_[owner]) continue;
        const double relative=std::remainder(double(std::arg(aligned[k]))-
                                             std::arg(aligned[owner]),twoPi);
        const double phase=std::remainder(synthesisPhase_[owner]+relative,twoPi);
        synthesisPhase_[k]=phase;
        output[k]=std::polar(std::abs(scheduled[k]),static_cast<float>(phase));
    }
}
void PhaseVocoder::setOutputPhase(std::size_t bin, double phase) {
    if (bin == 0 || bin >= size_ / 2) return;
    synthesisPhase_[bin] = phase;
}
}
