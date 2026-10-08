#include "dsp/PartialTracker.h"
#include "dsp/PhaseVocoder.h"
#include "dsp/STFT.h"
#include "dsp/FFTAccelerate.h"
#include "dsp/TimeStretchEngine.h"
#include "dsp/ChunkedTimeStretchEngine.h"
#include "audio/WavReader.h"
#include "audio/WavWriter.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <filesystem>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
constexpr int rate=48000, fftSize=4096, hop=1024;
using Signal=std::vector<float>;
Signal glide() {
    Signal signal(rate*6);
    for (std::size_t i=0;i<signal.size();++i) {
        const double t=double(i)/rate;
        signal[i]=0.3f*std::sin(2*std::numbers::pi*(400*t+50*t*t/6));
    }
    return signal;
}
Signal harmonics() {
    Signal signal(rate*4);
    double phase=0;
    for (std::size_t i=0;i<signal.size();++i) {
        const double t=double(i)/rate;
        const double cents=10*std::sin(2*std::numbers::pi*5*t);
        phase+=2*std::numbers::pi*120*std::pow(2.0,cents/1200)/rate;
        double value=0;
        for (int h=1;h<=12;++h) value+=0.23*std::sin(h*phase)/h;
        signal[i]=value;
    }
    return signal;
}
void run(const Signal& signal,bool moving) {
    ts::STFT stft(fftSize);
    ts::PhaseVocoder vocoder(fftSize,hop,true,rate);
    ts::PhaseLocker peaks(fftSize);
    ts::PartialTracker tracker(fftSize,hop,rate,1);
    std::vector<float> frame(fftSize);
    std::vector<std::complex<float>> spectrum(fftSize/2+1),output(fftSize/2+1);
    int previousId=-1,stable=0,eligible=0,minBin=fftSize,maxBin=0;
    for (std::size_t frameIndex=0;frameIndex*hop<signal.size();++frameIndex) {
        for (int i=0;i<fftSize;++i) {
            const auto inputSample=static_cast<long long>(frameIndex*hop+i)-fftSize/2;
            frame[i]=inputSample>=0 && inputSample<static_cast<long long>(signal.size())
                ? signal[inputSample] : 0;
        }
        stft.analyze(frame.data(),spectrum.data());
        peaks.analyzePeaks(spectrum.data(),spectrum.size());
        vocoder.process(spectrum.data(),output.data(),frameIndex?hop*2:0,
                        false,false,0,&peaks.ownerPeak());
        tracker.process(peaks,{spectrum.data(),nullptr},{output.data(),nullptr},
                        {&vocoder,nullptr},frameIndex?hop*2:0,false);
        tracker.synchronize({output.data(),nullptr});
        if (frameIndex<8 || frameIndex+8>signal.size()/hop) continue;
        if (moving) {
            int strongest=-1;
            float magnitude=0;
            for (const auto& peak:peaks.peaks()) if (peak.position*rate/fftSize>=350 &&
                peak.position*rate/fftSize<=550 && peak.magnitude>magnitude) {
                strongest=peak.bin; magnitude=peak.magnitude;
            }
            if (strongest<0) continue;
            const int id=tracker.trackIdForBin(strongest);
            if (id<0) throw std::runtime_error("Moving sine lost its partial track");
            if (previousId>=0 && id==previousId) ++stable;
            ++eligible;
            previousId=id;
            minBin=std::min(minBin,strongest);
            maxBin=std::max(maxBin,strongest);
        }
        for (const auto& value:output) if (!std::isfinite(value.real()) ||
                                       !std::isfinite(value.imag()))
            throw std::runtime_error("Nonfinite tracked spectrum");
    }
    const auto ratio=tracker.continuityRatio();
    std::cout << "moving=" << moving << " continuity=" << ratio
              << " lifetime_frames=" << tracker.averageLifetimeFrames()
              << " average_tracks=" << tracker.averageTrackCount()
              << " switches=" << tracker.stats().trackSwitches << '\n';
    if (moving && (stable<double(eligible)*0.9 || maxBin-minBin<3 || ratio<0.85))
        throw std::runtime_error("Gliding partial identity was not continuous");
    if (!moving && (ratio<0.65 || tracker.averageTrackCount()<7))
        throw std::runtime_error("Harmonic track continuity too low");
}
std::pair<double,double> vibratoMetrics(const Signal& signal) {
    constexpr int size=8192,step=2048;
    ts::FFTAccelerate fft(size);
    std::vector<float> frame(size);
    std::vector<std::complex<float>> spectrum(size/2+1);
    std::vector<double> frequencies,magnitudes;
    for (std::size_t start=rate/2;start+size+rate/2<signal.size();start+=step) {
        for (int i=0;i<size;++i)
            frame[i]=signal[start+i]*float(0.5-0.5*std::cos(2*std::numbers::pi*i/size));
        fft.forward(frame.data(),spectrum.data());
        int peak=int(std::llround(440.0*size/rate));
        for (int k=peak-5;k<=peak+5;++k)
            if (std::abs(spectrum[k])>std::abs(spectrum[peak])) peak=k;
        const double a=std::log(std::abs(spectrum[peak-1])+1e-12);
        const double b=std::log(std::abs(spectrum[peak])+1e-12);
        const double c=std::log(std::abs(spectrum[peak+1])+1e-12);
        const double denominator=a-2*b+c;
        const double offset=std::abs(denominator)>1e-12 ?
            std::clamp(0.5*(a-c)/denominator,-0.5,0.5) : 0;
        frequencies.push_back((peak+offset)*rate/size);
        magnitudes.push_back(std::abs(spectrum[peak]));
    }
    std::sort(frequencies.begin(),frequencies.end());
    const auto low=frequencies[frequencies.size()/20];
    const auto high=frequencies[frequencies.size()*19/20];
    const double depth=600*std::log2(high/low);
    double mean=0,squares=0;
    for (const double value:magnitudes) { mean+=value; squares+=value*value; }
    mean/=magnitudes.size();
    const double cv=std::sqrt(squares/magnitudes.size()-mean*mean)/mean;
    return {depth,cv};
}
void vibratoRegression() {
    Signal input(rate*4);
    double phase=0;
    for (std::size_t i=0;i<input.size();++i) {
        const double cents=20*std::sin(2*std::numbers::pi*6*i/rate);
        phase+=2*std::numbers::pi*440*std::pow(2.0,cents/1200)/rate;
        input[i]=0.25f*std::sin(phase);
    }
    for (const double speed:{0.75,0.5}) {
        ts::StretchConfig config;
        config.sampleRate=rate;config.channels=1;config.timeRatio=1/speed;
        config.enablePhaseLocking=true;config.enableMultiResolution=true;
        const auto baseline=ts::TimeStretchEngine(config).processOffline({input})[0];
        config.enablePartialTracking=true;
        const auto tracked=ts::TimeStretchEngine(config).processOffline({input})[0];
        const auto [baseDepth,baseCv]=vibratoMetrics(baseline);
        const auto [trackedDepth,trackedCv]=vibratoMetrics(tracked);
        std::cout << "speed=" << speed << " base_depth_cents=" << baseDepth
                  << " tracked_depth_cents=" << trackedDepth
                  << " base_magnitude_cv=" << baseCv
                  << " tracked_magnitude_cv=" << trackedCv << '\n';
        if (std::abs(baseDepth-trackedDepth)>2.0 || trackedCv>baseCv+0.02)
            throw std::runtime_error("Tracking changed vibrato depth or amplitude modulation");
    }
}
void streamingAgreement() {
    constexpr std::size_t length=rate*2;
    ts::AudioBuffer audio{rate,std::vector<std::vector<float>>(2,std::vector<float>(length))};
    for (std::size_t i=0;i<length;++i) {
        const double t=double(i)/rate;
        audio.channels[0][i]=0.19f*std::sin(2*std::numbers::pi*(410*t+25*t*t))+
                             (i==rate/2 ? 0.3f : 0.0f);
        audio.channels[1][i]=0.82f*audio.channels[0][i];
    }
    const auto base=std::filesystem::temp_directory_path()/"phase6_streaming";
    const auto inputPath=base.string()+"_in.wav";
    const auto outputPath=base.string()+"_out.wav";
    ts::WavWriter::write(inputPath,audio);
    ts::StretchConfig config;
    config.sampleRate=rate;config.channels=2;config.timeRatio=2;
    config.enablePhaseLocking=true;config.enablePartialTracking=true;
    config.enableTransientHandling=true;config.enableAdaptiveTimeMapping=true;
    config.enablePreciseTransientAnchoring=true;config.enableStereoCoherence=true;
    config.enableMultiResolution=true;
    const auto offline=ts::TimeStretchEngine(config).processOffline(audio.channels);
    ts::ChunkedTimeStretchEngine(config).processWav(inputPath,outputPath);
    const auto streaming=ts::WavReader::read(outputPath);
    double maximum=0;
    for (int c=0;c<2;++c) for (std::size_t i=0;i<offline[c].size();++i)
        maximum=std::max(maximum,std::abs(double(offline[c][i])-streaming.channels[c][i]));
    std::filesystem::remove(inputPath);std::filesystem::remove(outputPath);
    std::cout << "tracked_offline_streaming_max_difference=" << maximum << '\n';
    if (maximum>=1e-5) throw std::runtime_error("Tracked streaming/offline mismatch");
}
}
int main() {
    try { run(glide(),true); run(harmonics(),false); vibratoRegression(); streamingAgreement(); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
