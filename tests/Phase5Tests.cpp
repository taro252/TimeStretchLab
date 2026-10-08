#include "dsp/FFTAccelerate.h"
#include "dsp/MultiResolutionCrossover.h"
#include "dsp/TimeMap.h"
#include "dsp/TimeStretchEngine.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
constexpr int rate = 44100;
constexpr double piValue = std::numbers::pi;
using Audio = std::vector<std::vector<float>>;
void check(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
ts::StretchConfig config(double speed, bool multi, int channels = 1) {
    ts::StretchConfig c;
    c.sampleRate = rate; c.channels = channels; c.timeRatio = 1/speed;
    c.enablePhaseLocking = true; c.enableTransientHandling = true;
    c.enableAdaptiveTimeMapping = true; c.enablePreciseTransientAnchoring = true;
    c.enableStereoCoherence = true; c.enableMultiResolution = multi;
    if (multi) c.qualityMode = ts::QualityMode::Experimental;
    return c;
}
void finiteAndLength(const Audio& output, std::size_t inputLength, double speed) {
    for (const auto& channel : output) {
        check(channel.size() == std::size_t(std::llround(inputLength/speed)), "Wrong length");
        check(std::all_of(channel.begin(), channel.end(), [](float x){return std::isfinite(x);}),
              "Non-finite sample");
    }
}
struct Modulation { double meanHz=0, stdHz=0, magnitudeStdDb=0; };
Modulation modulation(const std::vector<float>& x, double expectedHz) {
    constexpr std::size_t fftSize = 16384;
    ts::FFTAccelerate fft(fftSize);
    std::vector<float> frame(fftSize);
    std::vector<std::complex<float>> spectrum(fftSize/2+1);
    std::vector<double> frequencies, levels;
    for (std::size_t start = rate/2; start+fftSize < x.size()-rate/2; start += rate/10) {
        for (std::size_t i = 0; i < fftSize; ++i)
            frame[i] = x[start+i]*float(0.5-0.5*std::cos(2*piValue*i/fftSize));
        fft.forward(frame.data(), spectrum.data());
        const auto center = std::size_t(std::llround(expectedHz*fftSize/rate));
        std::size_t peak = center;
        for (std::size_t k = std::max<std::size_t>(2,center-4); k <= center+4; ++k)
            if (std::abs(spectrum[k]) > std::abs(spectrum[peak])) peak = k;
        const auto a = std::log(std::abs(spectrum[peak-1])+1e-12);
        const auto b = std::log(std::abs(spectrum[peak])+1e-12);
        const auto c = std::log(std::abs(spectrum[peak+1])+1e-12);
        const auto denom = a-2*b+c;
        const auto offset = std::abs(denom)>1e-12 ? std::clamp(0.5*(a-c)/denom,-0.5,0.5) : 0;
        frequencies.push_back((peak+offset)*rate/fftSize);
        levels.push_back(20*std::log10(std::abs(spectrum[peak])+1e-12));
    }
    check(frequencies.size()>5, "Too few modulation frames");
    const auto mean = [](const std::vector<double>& values) {
        double sum=0; for (double value:values) sum+=value; return sum/values.size();
    };
    const auto stdev = [&](const std::vector<double>& values, double m) {
        double sum=0; for (double value:values) sum+=(value-m)*(value-m);
        return std::sqrt(sum/values.size());
    };
    const double f=mean(frequencies), l=mean(levels);
    return {f,stdev(frequencies,f),stdev(levels,l)};
}
Audio sine(double frequency, bool harmonic=false, int channels=1) {
    Audio x(channels,std::vector<float>(4*rate));
    for (std::size_t i=0;i<x[0].size();++i) {
        double value=0.5*std::sin(2*piValue*frequency*i/rate);
        if (harmonic) value += 0.2*std::sin(4*piValue*frequency*i/rate)+
                               0.1*std::sin(6*piValue*frequency*i/rate);
        for (int c=0;c<channels;++c) x[c][i]=float(value*(c==0?1:0.7));
    }
    return x;
}
struct Attack { double onset10OffsetMs=0, riseMs=0, timeToPeakMs=0, decay3Ms=0, decay10Ms=0;
    double preEcho=0, first20=0; std::size_t peak=0; };
Attack attack(const std::vector<float>& x, std::size_t expected) {
    const auto lo=expected>rate/20?expected-rate/20:0;
    const auto hi=std::min(x.size(),expected+rate/10);
    const auto radius=std::size_t(rate/2000); // 0.5 ms energy envelope
    std::vector<double> envelope(hi-lo);
    for (std::size_t i=lo;i<hi;++i) {
        double sum=0;
        const auto begin=i>radius?i-radius:0;
        const auto end=std::min(x.size(),i+radius+1);
        for (auto j=begin;j<end;++j) sum+=double(x[j])*x[j];
        envelope[i-lo]=std::sqrt(sum/(end-begin));
    }
    const auto peak=std::size_t(std::max_element(envelope.begin(),envelope.end())-envelope.begin());
    const double height=envelope[peak];
    auto crossingBefore=[&](double fraction){
        auto i=peak; while(i>0 && envelope[i-1]>=height*fraction)--i; return lo+i;
    };
    auto crossingAfter=[&](double fraction){
        auto i=peak; while(i+1<envelope.size() && envelope[i+1]>=height*fraction)++i;
        return lo+i;
    };
    Attack a;
    a.peak=lo+peak;
    const auto onset10=crossingBefore(0.1);
    a.onset10OffsetMs=1000.0*(double(onset10)-expected)/rate;
    a.riseMs=1000.0*(crossingBefore(0.9)-onset10)/rate;
    a.timeToPeakMs=1000.0*(a.peak-onset10)/rate;
    a.decay3Ms=1000.0*(crossingAfter(0.707)-a.peak)/rate;
    a.decay10Ms=1000.0*(crossingAfter(0.316)-a.peak)/rate;
    for (auto i=expected-rate/50;i<expected;++i) a.preEcho+=double(x[i])*x[i];
    for (auto i=expected;i<expected+rate/50;++i) a.first20+=double(x[i])*x[i];
    return a;
}
void testTone(double frequency,double speed,bool harmonic=false) {
    const auto input=sine(frequency,harmonic);
    ts::TimeStretchEngine baseline(config(speed,false)), engine(config(speed,true));
    const auto a=baseline.processOffline(input),b=engine.processOffline(input);
    finiteAndLength(b,input[0].size(),speed);
    const auto ma=modulation(a[0],frequency),mb=modulation(b[0],frequency);
    check(std::abs(mb.meanHz-frequency)<1.0, "Low-tone pitch shifted");
    std::cout<<"tone_hz="<<frequency<<" harmonic="<<harmonic<<" speed="<<speed
             <<" phase4_mean_hz="<<ma.meanHz<<" phase5_mean_hz="<<mb.meanHz
             <<" phase4_frequency_std_hz="<<ma.stdHz<<" phase5_frequency_std_hz="<<mb.stdHz
             <<" phase4_magnitude_std_db="<<ma.magnitudeStdDb
             <<" phase5_magnitude_std_db="<<mb.magnitudeStdDb<<'\n';
}
void testAttack(double speed,bool burst) {
    Audio input(1,std::vector<float>(3*rate));
    if (!burst) input[0][rate]=0.8f;
    else {
        std::mt19937 generator(42);
        std::normal_distribution<float> noise(0,0.3f);
        for(int i=0;i<rate/50;++i) input[0][rate+i]=noise(generator);
    }
    ts::TimeStretchEngine baseline(config(speed,false)),engine(config(speed,true));
    const auto a=baseline.processOffline(input),b=engine.processOffline(input);
    finiteAndLength(b,input[0].size(),speed);
    check(engine.lastEventCount()==baseline.lastEventCount() &&
          engine.lastAnchoredEventCount()==baseline.lastAnchoredEventCount() &&
          engine.lastAnchorMaxErrorSamples()==baseline.lastAnchorMaxErrorSamples(),
          "Shared transient event timing changed");
    if (!burst) check(engine.lastAnchoredEventCount()==1,
                      "Precise click anchor was lost");
    const auto expected=std::size_t(std::llround(rate/speed));
    const auto ma=attack(a[0],expected),mb=attack(b[0],expected);
    std::cout<<(burst?"noise_burst":"click")<<" speed="<<speed
             <<" phase4_onset10_offset_ms="<<ma.onset10OffsetMs
             <<" phase5_onset10_offset_ms="<<mb.onset10OffsetMs
             <<" phase4_rise_ms="<<ma.riseMs<<" phase5_rise_ms="<<mb.riseMs
             <<" phase4_time_to_peak_ms="<<ma.timeToPeakMs
             <<" phase5_time_to_peak_ms="<<mb.timeToPeakMs
             <<" phase4_decay3_ms="<<ma.decay3Ms<<" phase5_decay3_ms="<<mb.decay3Ms
             <<" phase4_decay10_ms="<<ma.decay10Ms<<" phase5_decay10_ms="<<mb.decay10Ms
             <<" phase4_pre_echo="<<ma.preEcho<<" phase5_pre_echo="<<mb.preEcho
             <<" phase4_first20="<<ma.first20<<" phase5_first20="<<mb.first20
             <<" peak_offset_samples="<<double(mb.peak)-ma.peak<<'\n';
}
void testCymbal(double speed) {
    Audio input(1,std::vector<float>(3*rate));
    std::mt19937 generator(711);
    std::normal_distribution<float> noise(0,0.1f);
    double previous=0;
    for(int i=0;i<rate/3;++i) {
        const double current=noise(generator);
        const double decay=std::exp(-18.0*i/rate);
        input[0][rate+i]=float((current-previous)*decay);
        previous=current;
    }
    ts::TimeStretchEngine baseline(config(speed,false)),engine(config(speed,true));
    const auto a=baseline.processOffline(input),b=engine.processOffline(input);
    finiteAndLength(b,input[0].size(),speed);
    const auto expected=std::size_t(std::llround(rate/speed));
    const auto ma=attack(a[0],expected),mb=attack(b[0],expected);
    std::cout<<"cymbal speed="<<speed
             <<" phase4_onset10_offset_ms="<<ma.onset10OffsetMs
             <<" phase5_onset10_offset_ms="<<mb.onset10OffsetMs
             <<" phase4_rise_ms="<<ma.riseMs<<" phase5_rise_ms="<<mb.riseMs
             <<" phase4_time_to_peak_ms="<<ma.timeToPeakMs
             <<" phase5_time_to_peak_ms="<<mb.timeToPeakMs
             <<" phase4_decay3_ms="<<ma.decay3Ms<<" phase5_decay3_ms="<<mb.decay3Ms
             <<" phase4_decay10_ms="<<ma.decay10Ms<<" phase5_decay10_ms="<<mb.decay10Ms
             <<" phase4_pre_echo="<<ma.preEcho<<" phase5_pre_echo="<<mb.preEcho
             <<" phase4_first20="<<ma.first20<<" phase5_first20="<<mb.first20
             <<" peak_offset_samples="<<double(mb.peak)-ma.peak<<'\n';
}
void testClickTrain(double speed) {
    Audio input(1,std::vector<float>(5*rate));
    for(int n=0;n<8;++n) input[0][rate+n*rate/2]=0.8f;
    ts::TimeStretchEngine baseline(config(speed,false)),engine(config(speed,true));
    const auto a=baseline.processOffline(input),b=engine.processOffline(input);
    finiteAndLength(b,input[0].size(),speed);
    check(engine.lastAnchoredEventCount()==8 &&
          engine.lastAnchoredEventCount()==baseline.lastAnchoredEventCount(),
          "Click train anchors changed");
    double maxInterval=0;
    std::size_t previous=0;
    for(int n=0;n<8;++n) {
        const auto expected=std::size_t(std::llround((rate+n*rate/2)/speed));
        const auto measured=attack(b[0],expected).peak;
        if(n) maxInterval=std::max(maxInterval,
            std::abs((double(measured)-previous)-rate/(2*speed))*1000/rate);
        previous=measured;
    }
    check(maxInterval<=3.0,"Click interval timing regressed");
    std::cout<<"click_train speed="<<speed<<" anchored="<<engine.lastAnchoredEventCount()
             <<" max_interval_error_ms="<<maxInterval<<'\n';
}
void testStereo(double speed) {
    const auto input=sine(110,false,2);
    ts::TimeStretchEngine baseline(config(speed,false,2)),engine(config(speed,true,2));
    const auto a=baseline.processOffline(input),b=engine.processOffline(input);
    finiteAndLength(b,input[0].size(),speed);
    auto ratio=[](const Audio& x){double left=0,right=0;
        for(std::size_t i=0;i<x[0].size();++i){left+=double(x[0][i])*x[0][i];right+=double(x[1][i])*x[1][i];}
        return std::sqrt(right/left);
    };
    check(std::abs(ratio(b)-0.7)<0.03,"Stereo panning changed");
    std::cout<<"stereo speed="<<speed<<" phase4_right_left="<<ratio(a)
             <<" phase5_right_left="<<ratio(b)<<'\n';
}
void testCrossover() {
    ts::MultiResolutionCrossover crossover(rate);
    std::vector<float> impulse(16384),silence(16384),low,mid,high;
    impulse[4096]=1;
    crossover.combine(impulse,silence,silence,low);
    crossover.combine(silence,impulse,silence,mid);
    crossover.combine(silence,silence,impulse,high);
    for(std::size_t i=0;i<impulse.size();++i)
        check(std::abs(double(low[i])+mid[i]+high[i]-impulse[i])<1e-5,
              "Crossover weights do not sum to unity");
    ts::FFTAccelerate fft(16384);
    std::vector<std::complex<float>> spectrum(8193);
    auto weight=[&](const std::vector<float>& x,double hz){
        fft.forward(x.data(),spectrum.data());
        return std::abs(spectrum[std::size_t(std::llround(hz*16384/rate))]);
    };
    const double low100=weight(low,100),low350=weight(low,350);
    const double mid1000=weight(mid,1000),mid4500=weight(mid,4500);
    const double high2500=weight(high,2500),high5000=weight(high,5000);
    check(low100>0.98 && low350<0.02 && mid1000>0.98 && mid4500<0.02 &&
          high2500<0.02 && high5000>0.98,"Crossover band limits failed");
    std::cout<<"crossover low100="<<low100<<" low350="<<low350
             <<" mid1000="<<mid1000<<" mid4500="<<mid4500
             <<" high2500="<<high2500<<" high5000="<<high5000<<'\n';
}
}
int main() {
    try {
        std::cout<<std::fixed<<std::setprecision(6);
        check(!ts::StretchConfig{}.enableMultiResolution,"Multiresolution must default OFF");
        ts::TimeMap map(1024,{0,1365,2731},{});
        check(map.outputPositionForInputSample(1024)==1365 &&
              map.outputPositionForInputSample(512)==682.5,"Time map interpolation failed");
        ts::MultiResolutionCrossover crossover(rate);
        std::vector<float> same(2000),result;
        for(std::size_t i=0;i<same.size();++i)same[i]=float(std::sin(2*piValue*55*i/rate));
        crossover.combine(same,same,same,result);
        check(result==same,"Crossover unity failed");
        testCrossover();
        for(double speed:{0.75,0.5,0.4}) {
            for(double frequency:{55.0,82.41,110.0})testTone(frequency,speed);
            if(speed==0.5)testTone(110,speed,true);
            if(speed!=0.4) {testAttack(speed,false);testAttack(speed,true);testCymbal(speed);testClickTrain(speed);testStereo(speed);}
        }
        std::cout<<"PASS: Phase 5 tests\n";
    } catch(const std::exception& e) {
        std::cerr<<"FAIL: "<<e.what()<<'\n';return 1;
    }
}
