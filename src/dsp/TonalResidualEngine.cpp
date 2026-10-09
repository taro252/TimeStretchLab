#include "dsp/TonalResidualEngine.h"
#include "dsp/FFTAccelerate.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdint>
#include <limits>
#include <numbers>
#include <stdexcept>

namespace ts {
namespace {
constexpr double twoPi=2*std::numbers::pi;
double energy(const std::vector<float>& x) {
    double total=0;
    for (float value:x) total+=double(value)*value;
    return total;
}
double f0FromSpectrum(const std::vector<std::complex<float>>& spectrum,
                      double rate,std::size_t size) {
    double best=0,bestScore=0;
    for (int candidate=80;candidate<=400;candidate+=2) {
        double score=0;
        for (int harmonic=1;harmonic<=12;++harmonic) {
            const auto center=static_cast<int>(std::llround(
                double(candidate*harmonic)*size/rate));
            if (center+1>=static_cast<int>(spectrum.size())) break;
            double maximum=0;
            for (int delta=-1;delta<=1;++delta)
                maximum=std::max(maximum,double(std::norm(spectrum[center+delta])));
            score+=maximum/harmonic;
        }
        if (score>bestScore) {bestScore=score;best=candidate;}
    }
    return best;
}
void analyzeFrame(const std::vector<float>& signal,std::size_t center,
                  const std::vector<float>& window,FFTAccelerate& fft,
                  std::vector<float>& time,
                  std::vector<std::complex<float>>& spectrum) {
    const auto half=static_cast<long long>(window.size()/2);
    for (std::size_t n=0;n<window.size();++n) {
        const auto at=static_cast<long long>(center)+static_cast<long long>(n)-half;
        time[n]=(at>=0 && at<static_cast<long long>(signal.size()))
            ? signal[at]*window[n] : 0;
    }
    fft.forward(time.data(),spectrum.data());
}
void reconstruct(const std::vector<std::vector<std::complex<float>>>& spectra,
                 std::vector<float>& output,const std::vector<float>& window,
                 std::size_t hop,FFTAccelerate& fft,std::vector<float>& time) {
    std::vector<double> sum(output.size()),weight(output.size());
    const auto half=static_cast<long long>(window.size()/2);
    for (std::size_t frame=0;frame<spectra.size();++frame) {
        fft.inverse(spectra[frame].data(),time.data());
        const auto center=static_cast<long long>(frame*hop);
        for (std::size_t n=0;n<window.size();++n) {
            const auto at=center+static_cast<long long>(n)-half;
            if (at<0 || at>=static_cast<long long>(output.size())) continue;
            const double w=window[n];
            sum[at]+=time[n]*w;
            weight[at]+=w*w;
        }
    }
    for (std::size_t n=0;n<output.size();++n)
        output[n]=weight[n]>1e-8 ? static_cast<float>(sum[n]/weight[n]) : 0;
}
}

TonalResidualEngine::TonalResidualEngine(SinusoidalResidualConfig config):config_(config) {
    if (config.residualPhaseMode!=ResidualPhaseMode::Random)
        throw std::invalid_argument("Phase 9C requires the unchanged Phase 9A default");
}

TonalResidualResult TonalResidualEngine::processMono(
    const std::vector<float>& input,const std::filesystem::path& trackCsv) {
    SinusoidalResidualEngine primaryEngine(config_);
    auto primaryResult=primaryEngine.processMono(input,trackCsv);
    TonalResidualResult result;
    result.primary=std::move(primaryResult.sinusoidalOutput);
    result.primaryStats=primaryResult.stats;
    result.tonalInput.resize(input.size());
    result.noiseInput.resize(input.size());
    const auto length=result.primary.size();
    result.tonalOutput.resize(length);
    result.noiseOutput.resize(length);
    result.primaryAndTonal.resize(length);
    result.output.resize(length);
    if (input.empty()) return result;

    const auto size=config_.fftSize,bins=size/2+1,hop=config_.analysisHop;
    const auto frameCount=(input.size()+hop-1)/hop+1;
    FFTAccelerate fft(size);
    std::vector<float> window(size),time(size);
    for (std::size_t n=0;n<size;++n)
        window[n]=static_cast<float>(0.5-0.5*std::cos(twoPi*n/size));
    std::vector<std::complex<float>> sourceSpectrum(bins),residualSpectrum(bins);
    std::vector<std::vector<std::complex<float>>> tonalFrames(frameCount),noiseFrames(frameCount);
    double maskSum=0,maskCount=0;
    for (std::size_t frame=0;frame<frameCount;++frame) {
        const auto center=frame*hop;
        analyzeFrame(input,center,window,fft,time,sourceSpectrum);
        analyzeFrame(primaryResult.residualInput,center,window,fft,time,residualSpectrum);
        const double f0=f0FromSpectrum(sourceSpectrum,config_.sampleRate,size);
        // An almost line-only residual has no stochastic component to
        // randomize. This cue is independent of the estimated F0.
        double bandMean=0,bandLogMean=0;
        std::size_t bandCount=0;
        for (std::size_t k=1;k<bins;++k) {
            const double hz=k*config_.sampleRate/size;
            if (hz<80 || hz>8000) continue;
            const double power=std::norm(residualSpectrum[k])+1e-14;
            bandMean+=power;
            bandLogMean+=std::log(power);
            ++bandCount;
        }
        const double frameFlatness=bandCount && bandMean>1e-10 ?
            std::exp(bandLogMean/bandCount)/(bandMean/bandCount) : 1;
        const double pureToneConfidence=std::clamp(
            (0.0001-frameFlatness)/0.00008,0.0,1.0);
        auto& tonal=tonalFrames[frame];
        auto& noise=noiseFrames[frame];
        tonal.resize(bins);noise.resize(bins);
        for (std::size_t k=0;k<bins;++k) {
            const double magnitude=std::abs(residualSpectrum[k]);
            double local=0,logSum=0;
            const auto lo=k>6?k-6:0;
            const auto hi=std::min(bins-1,k+6);
            for (auto j=lo;j<=hi;++j) {
                const double neighbor=std::abs(residualSpectrum[j])+1e-12;
                local+=neighbor;logSum+=std::log(neighbor);
            }
            const double count=hi-lo+1;
            local/=count;
            const double flatness=std::exp(logSum/count)/(local+1e-12);
            const double peakness=std::clamp((magnitude/(local+1e-12)-1.2)/2.5,0.0,1.0);
            const double frequency=k*config_.sampleRate/size;
            double harmonic=0;
            if (f0>0 && frequency>=65 && frequency<=8000) {
                const double multiple=std::max(1.0,std::round(frequency/f0));
                const double distance=std::abs(frequency-multiple*f0);
                const double width=std::max(12.0,0.07*f0);
                harmonic=std::exp(-0.5*(distance/width)*(distance/width));
            }
            double stability=0;
            if (frame>0) {
                const double previous=std::abs(tonalFrames[frame-1][k]+noiseFrames[frame-1][k]);
                stability=std::exp(-std::abs(std::log((magnitude+1e-8)/(previous+1e-8))));
            }
            // All four cues contribute, with harmonic proximity dominant for
            // leaked pure-vowel harmonics. The mask is always strictly soft.
            const double localWeight=std::clamp(0.01+0.96*harmonic+
                0.18*peakness*(1-flatness)*(0.4+0.6*stability),0.01,0.99);
            const double weight=localWeight+(0.999-localWeight)*pureToneConfidence;
            tonal[k]=residualSpectrum[k]*static_cast<float>(weight);
            noise[k]=residualSpectrum[k]*static_cast<float>(1-weight);
            maskSum+=weight*magnitude*magnitude;
            maskCount+=magnitude*magnitude;
        }
    }
    result.meanTonalMask=maskCount>0?maskSum/maskCount:0;
    reconstruct(tonalFrames,result.tonalInput,window,hop,fft,time);
    reconstruct(noiseFrames,result.noiseInput,window,hop,fft,time);

    std::vector<std::vector<float>> tonalMagnitude(frameCount,std::vector<float>(bins));
    std::vector<std::vector<float>> noiseMagnitude(frameCount,std::vector<float>(bins));
    std::vector<std::vector<float>> phases(frameCount,std::vector<float>(bins));
    for (std::size_t frame=0;frame<frameCount;++frame)
        for (std::size_t k=0;k<bins;++k) {
            tonalMagnitude[frame][k]=std::abs(tonalFrames[frame][k]);
            noiseMagnitude[frame][k]=std::abs(noiseFrames[frame][k]);
            phases[frame][k]=std::arg(tonalFrames[frame][k]);
        }
    const auto outputFrames=(length+hop-1)/hop+1;
    std::vector<std::vector<std::complex<float>>> tonalOutFrames(outputFrames,
        std::vector<std::complex<float>>(bins));
    std::vector<std::vector<std::complex<float>>> noiseOutFrames(outputFrames,
        std::vector<std::complex<float>>(bins));
    std::vector<double> carriedPhase(bins);
    for (std::size_t k=0;k<bins;++k) carriedPhase[k]=phases[0][k];
    std::uint32_t random=0x9e3779b9u;
    for (std::size_t frame=0;frame<outputFrames;++frame) {
        const double sourceFrame=double(frame)/config_.timeRatio;
        const auto left=std::min(static_cast<std::size_t>(sourceFrame),frameCount-1);
        const auto right=std::min(left+1,frameCount-1);
        const double u=std::clamp(sourceFrame-left,0.0,1.0);
        for (std::size_t k=1;k+1<bins;++k) {
            const double tonal=tonalMagnitude[left][k]*(1-u)+tonalMagnitude[right][k]*u;
            const double noise=noiseMagnitude[left][k]*(1-u)+noiseMagnitude[right][k]*u;
            if (frame>0) {
                const double expected=twoPi*k*hop/size;
                const double deviation=right>left ? std::remainder(
                    double(phases[right][k])-phases[left][k]-expected,twoPi) : 0;
                carriedPhase[k]+=expected+deviation;
                if (std::abs(carriedPhase[k])>1e6)
                    carriedPhase[k]=std::remainder(carriedPhase[k],twoPi);
            }
            tonalOutFrames[frame][k]=std::polar(static_cast<float>(tonal),
                                                 static_cast<float>(carriedPhase[k]));
            random^=random<<13;random^=random>>17;random^=random<<5;
            noiseOutFrames[frame][k]=std::polar(static_cast<float>(noise),
                static_cast<float>(twoPi*double(random)/UINT32_MAX));
        }
    }
    reconstruct(tonalOutFrames,result.tonalOutput,window,hop,fft,time);
    reconstruct(noiseOutFrames,result.noiseOutput,window,hop,fft,time);
    // One shared gain preserves the tonal/noise balance and the exact sum of
    // the exported diagnostic components.
    double residualEnergy=0;
    for (std::size_t n=0;n<length;++n) {
        const double sum=result.tonalOutput[n]+result.noiseOutput[n];
        residualEnergy+=sum*sum;
    }
    const double sourceRms=std::sqrt(energy(primaryResult.residualInput)/input.size());
    const double outputRms=std::sqrt(residualEnergy/length);
    const double gain=outputRms>1e-10 ? std::clamp(sourceRms/outputRms,0.5,2.0) : 1;
    for (std::size_t n=0;n<length;++n) {
        result.tonalOutput[n]=static_cast<float>(result.tonalOutput[n]*gain);
        result.noiseOutput[n]=static_cast<float>(result.noiseOutput[n]*gain);
        result.primaryAndTonal[n]=result.primary[n]+result.tonalOutput[n];
        result.output[n]=result.primaryAndTonal[n]+result.noiseOutput[n];
    }
    return result;
}
}
