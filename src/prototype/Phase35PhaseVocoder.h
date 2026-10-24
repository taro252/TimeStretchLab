#pragma once
#include "dsp/PhaseLocker.h"
#include <complex>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace ts::prototype {
class Phase35PhaseVocoder {
public:
    // 同じprocessの入力だけを借用する。入力変更/次frame/reset/resync前まで有効。
    struct InputPolarView {
        const Phase35PhaseVocoder* owner=nullptr;
        const std::complex<float>* input=nullptr;
        const float* magnitude=nullptr;
        const float* phase=nullptr;
        std::size_t bins=0;
        std::uint64_t frame=0;
        bool validFor(const Phase35PhaseVocoder&,const std::complex<float>*,std::size_t)const noexcept;
        bool phaseValid(std::size_t bin)const noexcept{return bin>0&&bin<bins&&magnitude&&magnitude[bin]>=1e-7f;}
    };
    InputPolarView inputPolarView()const noexcept;
    Phase35PhaseVocoder(std::size_t fftSize, int analysisHop, bool enablePhaseLocking = false,
                 double sampleRate = 44100.0);
    void reset();
    // Hs is the distance from the preceding synthesis frame, including fractional timing.
    void process(const std::complex<float>* input, std::complex<float>* output,
                 double synthesisHop, bool resetPhase = false,
                 bool selectiveReset = false, float eventStrength = 1.0f,
                 const std::vector<int>* sharedOwners = nullptr,
                 int analysisHopOverride = 0);
    // Replace the persistent phase with a waveform-aligned analysis frame.
    // Magnitudes and output timing remain those of the scheduled frame.
    void resynchronize(const std::complex<float>* scheduled,
                       const std::complex<float>* aligned,
                       std::complex<float>* output,
                       const std::vector<int>* sharedOwners = nullptr);
    void setOutputPhase(std::size_t bin, double phase);
    const PhaseLocker& phaseLocker() const { return phaseLocker_; }
private:
    std::size_t size_;
    int analysisHop_;
    double sampleRate_;
    std::vector<bool> initialized_;
    std::vector<bool> resyncPending_;
    std::vector<double> previousPhase_, synthesisPhase_;
    std::vector<float> previousMagnitude_;
    // Frame-local reuse only. Persistent phase update order remains unchanged.
    std::vector<float> inputMagnitudeCache_,inputPhaseCache_;
    struct FrameWitness {
        const Phase35PhaseVocoder* owner=nullptr;
        const std::complex<float>* input=nullptr;
        std::uint64_t frame=0;
        FrameWitness()=default;
        FrameWitness(const FrameWitness&)noexcept{} // checkpointには借用寿命をコピーしない
        FrameWitness& operator=(const FrameWitness&)noexcept{owner=nullptr;input=nullptr;++frame;return *this;}
    } cacheWitness_;
    bool enablePhaseLocking_;
    PhaseLocker phaseLocker_;
};
inline bool Phase35PhaseVocoder::InputPolarView::validFor(const Phase35PhaseVocoder& v,
    const std::complex<float>* p,std::size_t n)const noexcept {
    return owner==&v&&v.cacheWitness_.owner==&v&&input==p&&v.cacheWitness_.input==p&&bins==n&&bins==v.size_/2+1&&
        frame==v.cacheWitness_.frame&&magnitude==v.inputMagnitudeCache_.data()&&phase==v.inputPhaseCache_.data();
}
inline Phase35PhaseVocoder::InputPolarView Phase35PhaseVocoder::inputPolarView()const noexcept {
    if(cacheWitness_.owner!=this||!cacheWitness_.input)return {};
    return {this,cacheWitness_.input,inputMagnitudeCache_.data(),inputPhaseCache_.data(),size_/2+1,cacheWitness_.frame};
}
}
