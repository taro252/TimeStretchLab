#include "dsp/SinusoidalResidualEngine.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <numbers>
#include <stdexcept>

namespace ts {
namespace {
constexpr double twoPi=2*std::numbers::pi;
double clamp01(double x) { return std::clamp(x,0.0,1.0); }
double energy(const std::vector<float>& x) {
    double sum=0;
    for (float sample:x) sum+=double(sample)*sample;
    return sum;
}
}
SinusoidalResidualEngine::SinusoidalResidualEngine(SinusoidalResidualConfig config)
    : config_(config),fft_(config.fftSize),window_(config.fftSize),
      frame_(config.fftSize),spectrum_(config.fftSize/2+1) {
    if (!std::isfinite(config.sampleRate) || config.sampleRate<=0 ||
        !std::isfinite(config.timeRatio) || config.timeRatio<=0 ||
        config.fftSize!=4096 || config.analysisHop<128 ||
        config.analysisHop>config.fftSize/2 ||
        config.maximumTracksPerFrame<1 || config.maximumTracksPerFrame>256)
        throw std::invalid_argument("Invalid sinusoidal/residual configuration");
    for (std::size_t i=0;i<window_.size();++i)
        window_[i]=static_cast<float>(0.5-0.5*std::cos(twoPi*i/window_.size()));
}
void SinusoidalResidualEngine::analyze(const std::vector<float>& input) {
    inputLength_=input.size();
    frameCount_=input.empty() ? 0 : (input.size()+config_.analysisHop-1)/config_.analysisHop+1;
    tracks_.clear();masks_.clear();masks_.reserve(frameCount_);
    activeTrackSum_=births_=deaths_=0;
    const int bins=static_cast<int>(config_.fftSize/2+1);
    const double windowSum=config_.fftSize*0.5;
    const int half=static_cast<int>(config_.fftSize/2);
    std::vector<Peak> peaks;
    peaks.reserve(bins);
    for (std::size_t frameIndex=0;frameIndex<frameCount_;++frameIndex) {
        const auto center=frameIndex*config_.analysisHop;
        for (std::size_t n=0;n<config_.fftSize;++n) {
            const long long position=static_cast<long long>(center)+
                static_cast<long long>(n)-half;
            frame_[n]=(position>=0 && position<static_cast<long long>(input.size()))
                ? input[position]*window_[n] : 0;
        }
        fft_.forward(frame_.data(),spectrum_.data());
        float frameMaximum=0;
        for (const auto& bin:spectrum_) frameMaximum=std::max(frameMaximum,std::abs(bin));
        peaks.clear();
        if (frameMaximum>1e-7f) for (int k=2;k<bins-2;++k) {
            const double frequency=double(k)*config_.sampleRate/config_.fftSize;
            if (frequency<70 || frequency>6500) continue;
            const double mag=std::abs(spectrum_[k]);
            if (mag<frameMaximum*0.012 || mag<std::abs(spectrum_[k-1]) ||
                mag<=std::abs(spectrum_[k+1])) continue;
            double neighborhood=0;
            int count=0;
            for (int d=-6;d<=6;++d) if (d<-1 || d>1) {
                neighborhood+=std::abs(spectrum_[k+d]);++count;
            }
            if (mag/(neighborhood/count+1e-12)<2.2) continue;
            const double a=std::log(std::max(double(std::abs(spectrum_[k-1])),1e-12));
            const double b=std::log(std::max(mag,1e-12));
            const double c=std::log(std::max(double(std::abs(spectrum_[k+1])),1e-12));
            const double denominator=a-2*b+c;
            const double delta=std::abs(denominator)>1e-12
                ? std::clamp(0.5*(a-c)/denominator,-0.5,0.5) : 0;
            const double peakMagnitude=std::exp(b-0.5*denominator*delta*delta);
            peaks.push_back({(k+delta)*config_.sampleRate/config_.fftSize,
                             2*peakMagnitude/windowSum,
                             std::remainder(double(std::arg(spectrum_[k]))+
                                            std::numbers::pi*k,twoPi),k+delta});
        }
        std::sort(peaks.begin(),peaks.end(),[](const Peak& a,const Peak& b) {
            return a.amplitude>b.amplitude;
        });
        if (peaks.size()>config_.maximumTracksPerFrame)
            peaks.resize(config_.maximumTracksPerFrame);
        std::vector<float> mask(bins);
        for (const auto& peak:peaks) {
            const int low=std::max(0,int(std::floor(peak.bin))-5);
            const int high=std::min(bins-1,int(std::ceil(peak.bin))+5);
            for (int k=low;k<=high;++k) {
                const double distance=(k-peak.bin)/2.0;
                mask[k]=std::max(mask[k],static_cast<float>(
                    std::exp(-0.5*distance*distance)));
            }
        }
        masks_.push_back(std::move(mask));
        std::vector<unsigned char> matched(tracks_.size());
        for (const auto& peak:peaks) {
            int best=-1;
            double bestCost=std::numeric_limits<double>::infinity();
            for (std::size_t i=0;i<tracks_.size();++i) {
                const auto& track=tracks_[i];
                if (!track.active || matched[i] || track.missedFrames>2) continue;
                const auto& previous=track.nodes.back();
                double predicted=previous.frequencyHz;
                if (track.nodes.size()>1) {
                    const auto& older=track.nodes[track.nodes.size()-2];
                    const double dt=double(previous.center-older.center);
                    if (dt>0) predicted+=(previous.frequencyHz-older.frequencyHz)*
                        double(center-previous.center)/dt;
                }
                const double difference=std::abs(peak.frequencyHz-predicted);
                const double gate=std::max(25.0,peak.frequencyHz*0.055);
                if (difference>gate) continue;
                const double magnitudeCost=std::abs(std::log((peak.amplitude+1e-9)/
                                                          (previous.amplitude+1e-9)));
                const double cost=difference/gate+0.18*magnitudeCost+
                                  0.15*track.missedFrames;
                if (cost<bestCost) { bestCost=cost;best=static_cast<int>(i); }
            }
            if (best<0) {
                SinusoidalTrack track;
                track.id=static_cast<int>(tracks_.size());
                track.nodes.push_back({center,peak.frequencyHz,peak.amplitude,peak.phase});
                tracks_.push_back(std::move(track));
                matched.push_back(1);
                ++births_;
            } else {
                auto& track=tracks_[best];
                track.nodes.push_back({center,peak.frequencyHz,peak.amplitude,peak.phase});
                track.missedFrames=0;
                matched[best]=1;
            }
        }
        std::size_t active=0;
        for (std::size_t i=0;i<tracks_.size();++i) {
            auto& track=tracks_[i];
            if (!track.active) continue;
            if (!matched[i] && ++track.missedFrames>2) {
                track.active=false;++deaths_;
            } else ++active;
        }
        activeTrackSum_+=active;
    }
    for (auto& track:tracks_) if (track.active) {
        track.active=false;++deaths_;
    }
}
void SinusoidalResidualEngine::renderSinusoids(std::vector<float>& output,double ratio) const {
    std::fill(output.begin(),output.end(),0);
    if (output.empty()) return;
    const double fade=std::min(128.0,double(config_.analysisHop)*ratio/4);
    for (const auto& track:tracks_) {
        if (track.nodes.size()<2) continue;
        const auto& first=track.nodes.front();
        const auto& last=track.nodes.back();
        const double firstOut=first.center*ratio;
        const double lastOut=last.center*ratio;
        const auto start=static_cast<std::size_t>(std::max(0.0,std::floor(firstOut-fade)));
        const auto stop=static_cast<std::size_t>(std::min(double(output.size()),
            std::ceil(lastOut+fade)));
        double phase=first.analysisPhase+twoPi*first.frequencyHz*
            (double(start)-firstOut)/config_.sampleRate;
        std::size_t segment=0;
        for (std::size_t n=start;n<stop;++n) {
            const double sourcePosition=n/ratio;
            while (segment+2<track.nodes.size() &&
                   sourcePosition>track.nodes[segment+1].center) ++segment;
            const auto& a=track.nodes[segment];
            const auto& b=track.nodes[std::min(segment+1,track.nodes.size()-1)];
            const double u=b.center>a.center ?
                clamp01((sourcePosition-a.center)/double(b.center-a.center)) : 0;
            double frequency=a.frequencyHz+(b.frequencyHz-a.frequencyHz)*u;
            if (b.center>a.center) {
                const double distance=double(b.center-a.center);
                const double expected=twoPi*0.5*(a.frequencyHz+b.frequencyHz)*
                    distance/config_.sampleRate;
                // Resolve the measured phase difference on this partial's
                // own trajectory. Integrate the resulting frequency; never
                // overwrite the oscillator phase at an STFT frame boundary.
                const double correction=std::remainder(
                    b.analysisPhase-a.analysisPhase-expected,twoPi)*
                    config_.sampleRate/(twoPi*distance);
                frequency+=correction;
            }
            double amplitude=a.amplitude+(b.amplitude-a.amplitude)*u;
            if (n<firstOut) amplitude*=clamp01((n-(firstOut-fade))/fade);
            if (n>lastOut) amplitude*=clamp01((lastOut+fade-n)/fade);
            output[n]+=static_cast<float>(amplitude*std::cos(phase));
            phase+=twoPi*frequency/config_.sampleRate;
            if (std::abs(phase)>1e6) phase=std::remainder(phase,twoPi);
        }
    }
}
void SinusoidalResidualEngine::synthesizeResidual(
    const std::vector<float>& residual,std::vector<float>& output) const {
    const auto bins=config_.fftSize/2+1;
    std::vector<std::vector<float>> magnitudes(frameCount_,std::vector<float>(bins));
    FFTAccelerate fft(config_.fftSize);
    std::vector<float> time(config_.fftSize);
    std::vector<std::complex<float>> spectrum(bins);
    const long long half=static_cast<long long>(config_.fftSize/2);
    for (std::size_t frame=0;frame<frameCount_;++frame) {
        const long long center=static_cast<long long>(frame*config_.analysisHop);
        for (std::size_t n=0;n<config_.fftSize;++n) {
            const long long at=center+static_cast<long long>(n)-half;
            time[n]=(at>=0 && at<static_cast<long long>(residual.size()))
                ? residual[at]*window_[n] : 0;
        }
        fft.forward(time.data(),spectrum.data());
        for (std::size_t k=0;k<bins;++k)
            // A tracked partial's leftover energy is coherent leakage, not
            // noise. Suppress it smoothly before randomizing residual phase.
            magnitudes[frame][k]=std::abs(spectrum[k])*(1-masks_[frame][k]);
    }
    std::vector<double> sums(output.size()),weights(output.size());
    std::uint32_t random=0x9e3779b9u;
    const auto outputFrames=(output.size()+config_.analysisHop-1)/config_.analysisHop+1;
    for (std::size_t frame=0;frame<outputFrames;++frame) {
        const long long center=static_cast<long long>(frame*config_.analysisHop);
        const double sourceFrame=double(center)/config_.timeRatio/config_.analysisHop;
        const auto left=std::min(static_cast<std::size_t>(sourceFrame),frameCount_-1);
        const auto right=std::min(left+1,frameCount_-1);
        const double u=clamp01(sourceFrame-left);
        spectrum[0]={0,0};spectrum[bins-1]={0,0};
        for (std::size_t k=1;k+1<bins;++k) {
            const double magnitude=magnitudes[left][k]*(1-u)+magnitudes[right][k]*u;
            random^=random<<13;random^=random>>17;random^=random<<5;
            const double phase=twoPi*double(random)/double(UINT32_MAX);
            spectrum[k]=std::polar(static_cast<float>(magnitude),static_cast<float>(phase));
        }
        fft.inverse(spectrum.data(),time.data());
        for (std::size_t n=0;n<config_.fftSize;++n) {
            const long long at=center+static_cast<long long>(n)-half;
            if (at<0 || at>=static_cast<long long>(output.size())) continue;
            const double w=window_[n];
            sums[at]+=time[n]*w;
            weights[at]+=w*w;
        }
    }
    for (std::size_t n=0;n<output.size();++n)
        output[n]=weights[n]>1e-8 ? static_cast<float>(sums[n]/weights[n]) : 0;
    // Independent random phases lower coherent overlap energy. Match the
    // residual's global RMS while retaining its time-varying envelope.
    const double inputRms=std::sqrt(energy(residual)/std::max(std::size_t(1),residual.size()));
    const double outputRms=std::sqrt(energy(output)/std::max(std::size_t(1),output.size()));
    const double gain=outputRms>1e-10 ? std::clamp(inputRms/outputRms,0.5,2.0) : 1;
    for (float& sample:output) sample=static_cast<float>(sample*gain);
}
void SinusoidalResidualEngine::writeTracks(const std::filesystem::path& path) const {
    std::ofstream file(path);
    if (!file) throw std::runtime_error("Cannot write sinusoidal tracks");
    file << std::setprecision(17)
         << "trackId,centerSample,frequencyHz,amplitude,analysisPhase\n";
    for (const auto& track:tracks_) for (const auto& node:track.nodes)
        file << track.id << ',' << node.center << ',' << node.frequencyHz << ','
             << node.amplitude << ',' << node.analysisPhase << '\n';
}
SinusoidalResidualResult SinusoidalResidualEngine::processMono(
    const std::vector<float>& input,const std::filesystem::path& trackCsv) {
    for (float sample:input) if (!std::isfinite(sample))
        throw std::invalid_argument("Nonfinite sinusoidal/residual input");
    analyze(input);
    SinusoidalResidualResult result;
    result.sinusoidalInput.resize(input.size());
    renderSinusoids(result.sinusoidalInput,1);
    result.residualInput.resize(input.size());
    for (std::size_t n=0;n<input.size();++n)
        result.residualInput[n]=input[n]-result.sinusoidalInput[n];
    const double desired=std::round(input.size()*config_.timeRatio);
    if (!std::isfinite(desired) || desired<0 ||
        desired>double(std::numeric_limits<std::size_t>::max()/4))
        throw std::length_error("Sinusoidal/residual output too large");
    const auto length=static_cast<std::size_t>(desired);
    result.sinusoidalOutput.resize(length);
    result.residualOutput.resize(length);
    result.output.resize(length);
    if (config_.timeRatio==1) {
        result.sinusoidalOutput=result.sinusoidalInput;
        result.residualOutput=result.residualInput;
    } else if (!input.empty()) {
        renderSinusoids(result.sinusoidalOutput,config_.timeRatio);
        synthesizeResidual(result.residualInput,result.residualOutput);
    }
    for (std::size_t n=0;n<length;++n)
        result.output[n]=result.sinusoidalOutput[n]+result.residualOutput[n];
    auto& stats=result.stats;
    stats.frames=frameCount_;
    stats.trackBirths=births_;
    stats.trackDeaths=deaths_;
    stats.averageActiveTracks=frameCount_ ? double(activeTrackSum_)/frameCount_ : 0;
    const double seconds=double(input.size())/config_.sampleRate;
    stats.birthsPerSecond=seconds>0 ? births_/seconds : 0;
    stats.deathsPerSecond=seconds>0 ? deaths_/seconds : 0;
    std::vector<double> lifetimes;
    lifetimes.reserve(tracks_.size());
    for (const auto& track:tracks_) if (!track.nodes.empty())
        lifetimes.push_back((track.nodes.back().center-track.nodes.front().center+
                             config_.analysisHop)/config_.sampleRate);
    if (!lifetimes.empty()) {
        const auto middle=lifetimes.begin()+lifetimes.size()/2;
        std::nth_element(lifetimes.begin(),middle,lifetimes.end());
        stats.medianTrackLifetimeSeconds=*middle;
    }
    const double inputEnergy=energy(input);
    stats.explainedEnergyRatio=inputEnergy>1e-12 ?
        energy(result.sinusoidalInput)/inputEnergy : 0;
    stats.residualInputRmsRatio=inputEnergy>1e-12 ?
        std::sqrt(energy(result.residualInput)/inputEnergy) : 0;
    if (!trackCsv.empty()) writeTracks(trackCsv);
    return result;
}
}
