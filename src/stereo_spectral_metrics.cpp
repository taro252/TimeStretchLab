#include "audio/WavReader.h"
#include "dsp/FFTAccelerate.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <stdexcept>
#include <vector>

namespace {
constexpr std::size_t size = 4096;
struct Spectrum {
    std::array<std::vector<std::complex<float>>, 2> channels{
        std::vector<std::complex<float>>(size/2+1), std::vector<std::complex<float>>(size/2+1)};
};
Spectrum analyze(const ts::AudioBuffer& audio, std::size_t start, ts::FFTAccelerate& fft,
                 std::vector<float>& frame) {
    Spectrum result;
    for (int channel = 0; channel < 2; ++channel) {
        for (std::size_t i = 0; i < size; ++i)
            frame[i] = audio.channels[channel][start+i] *
                float(0.5 - 0.5*std::cos(2*std::numbers::pi*i/size));
        fft.forward(frame.data(), result.channels[channel].data());
    }
    return result;
}
struct Result {
    double ipdSum = 0, ildSum = 0, weightSum = 0, weightSquaredSum = 0;
    std::size_t bins = 0;
};
void accumulate(Result& result, const Spectrum& in, const Spectrum& out,
                double rate, double low, double high) {
    double maxMagnitude = 0;
    for (std::size_t k = 1; k < size/2; ++k)
        maxMagnitude = std::max(maxMagnitude,
            std::hypot(double(std::abs(in.channels[0][k])),
                       double(std::abs(in.channels[1][k]))));
    for (std::size_t k = 2; k+2 < size/2; ++k) {
        const double frequency = k*rate/size;
        if (frequency < low || frequency > high) continue;
        const double il = std::abs(in.channels[0][k]), ir = std::abs(in.channels[1][k]);
        const double ol = std::abs(out.channels[0][k]), oright = std::abs(out.channels[1][k]);
        const double combined = std::hypot(il,ir);
        if (combined < 0.03*maxMagnitude ||
            combined < std::hypot(double(std::abs(in.channels[0][k-1])),
                                  double(std::abs(in.channels[1][k-1]))) ||
            combined < std::hypot(double(std::abs(in.channels[0][k+1])),
                                  double(std::abs(in.channels[1][k+1]))) ||
            std::min({il,ir,ol,oright}) < 1e-5) continue;
        const double inputIpd = std::arg(in.channels[1][k])-std::arg(in.channels[0][k]);
        const double outputIpd = std::arg(out.channels[1][k])-std::arg(out.channels[0][k]);
        const double ipdError = std::remainder(outputIpd-inputIpd, 2*std::numbers::pi);
        const double ildError = 20*std::log10((ol*ir)/(oright*il));
        const double weight = std::sqrt(std::min(il,ir)*std::min(ol,oright));
        result.ipdSum += weight*ipdError*ipdError;
        result.ildSum += weight*ildError*ildError;
        result.weightSum += weight;
        result.weightSquaredSum += weight*weight;
        ++result.bins;
    }
}
}
int main(int argc, char** argv) {
    try {
        if (argc != 4) throw std::invalid_argument("Usage: stereo_spectral_metrics input.wav output.wav speed");
        const auto input = ts::WavReader::read(argv[1]);
        const auto output = ts::WavReader::read(argv[2]);
        const double speed = std::stod(argv[3]);
        if (input.channels.size() != 2 || output.channels.size() != 2 ||
            input.sampleRate != output.sampleRate || speed <= 0)
            throw std::invalid_argument("Expected matching stereo WAVs and positive speed");
        ts::FFTAccelerate fft(size);
        std::vector<float> frame(size);
        Result all, low;
        std::vector<std::size_t> lowCounts;
        std::vector<double> lowWindowErrors, lowWindowWeights;
        const auto step = static_cast<std::size_t>(input.sampleRate);
        for (std::size_t start = step; start+size < input.channels[0].size(); start += step) {
            const auto outputStart = static_cast<std::size_t>(std::llround(start/speed));
            if (outputStart+size >= output.channels[0].size()) break;
            const auto a = analyze(input,start,fft,frame);
            const auto b = analyze(output,outputStart,fft,frame);
            accumulate(all,a,b,input.sampleRate,40,10000);
            Result lowWindow;
            accumulate(lowWindow,a,b,input.sampleRate,40,150);
            low.ipdSum+=lowWindow.ipdSum;
            low.ildSum+=lowWindow.ildSum;
            low.weightSum+=lowWindow.weightSum;
            low.weightSquaredSum+=lowWindow.weightSquaredSum;
            low.bins+=lowWindow.bins;
            lowCounts.push_back(lowWindow.bins);
            lowWindowErrors.push_back(lowWindow.weightSum>0 ?
                std::sqrt(lowWindow.ipdSum/lowWindow.weightSum)*180/std::numbers::pi : 0);
            lowWindowWeights.push_back(lowWindow.weightSum);
        }
        auto sortedCounts=lowCounts;
        std::sort(sortedCounts.begin(),sortedCounts.end());
        const auto percentile=[&](double fraction) {
            return sortedCounts.empty() ? std::size_t(0) :
                sortedCounts[static_cast<std::size_t>(fraction*(sortedCounts.size()-1))];
        };
        const auto zero=std::count(lowCounts.begin(),lowCounts.end(),0);
        const auto one=std::count(lowCounts.begin(),lowCounts.end(),1);
        const auto twoToFour=std::count_if(lowCounts.begin(),lowCounts.end(),
            [](std::size_t n){return n>=2 && n<=4;});
        std::cout << std::fixed << std::setprecision(6)
                  << "input=" << argv[1] << " output=" << argv[2]
                  << " tonal_bins=" << all.bins
                  << " ipd_weighted_rms_deg=" <<
                     (all.weightSum ? std::sqrt(all.ipdSum/all.weightSum)*180/std::numbers::pi : 0)
                  << " ild_weighted_rms_db=" <<
                     (all.weightSum ? std::sqrt(all.ildSum/all.weightSum) : 0)
                  << " low_bins=" << low.bins
                  << " low_magnitude_effective_bins=" <<
                     (low.weightSquaredSum>0 ? low.weightSum*low.weightSum/low.weightSquaredSum : 0)
                  << " low_windows=" << lowCounts.size()
                  << " low_window_zero=" << zero
                  << " low_window_one=" << one
                  << " low_window_two_to_four=" << twoToFour
                  << " low_window_five_plus=" << lowCounts.size()-zero-one-twoToFour
                  << " low_window_p10=" << percentile(0.1)
                  << " low_window_median=" << percentile(0.5)
                  << " low_window_p90=" << percentile(0.9)
                  << " low_window_max=" << (sortedCounts.empty()?0:sortedCounts.back())
                  << " low_ipd_weighted_rms_deg=" <<
                     (low.weightSum ? std::sqrt(low.ipdSum/low.weightSum)*180/std::numbers::pi : 0)
                  << " low_bins_per_window=";
        for (std::size_t i=0;i<lowCounts.size();++i)
            std::cout << (i?",":"") << lowCounts[i];
        std::cout << " low_window_ipd_deg=";
        for (std::size_t i=0;i<lowWindowErrors.size();++i)
            std::cout << (i?",":"") << lowWindowErrors[i];
        std::cout << " low_window_weight=";
        for (std::size_t i=0;i<lowWindowWeights.size();++i)
            std::cout << (i?",":"") << lowWindowWeights[i];
        std::cout << '\n';
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << '\n'; return 1;
    }
}
