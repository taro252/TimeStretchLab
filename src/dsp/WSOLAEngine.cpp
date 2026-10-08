#include "dsp/WSOLAEngine.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <numbers>
#include <stdexcept>

namespace ts {
WSOLAEngine::WSOLAEngine(WSOLAConfig config):config_(config),window_(config.windowSize) {
    if (!std::isfinite(config.sampleRate) || config.sampleRate<=0 ||
        !std::isfinite(config.timeRatio) || config.timeRatio<=0 ||
        config.windowSize<256 || config.windowSize>16384 ||
        config.synthesisHop<1 || config.synthesisHop>config.windowSize/2 ||
        config.searchRadius<0 || config.searchRadius>4096)
        throw std::invalid_argument("Invalid WSOLA configuration");
    // Symmetric Hann; divide the sum of overlapping window weights after OLA.
    for (std::size_t i=0;i<window_.size();++i)
        window_[i]=static_cast<float>(0.5-0.5*std::cos(
            2*std::numbers::pi*i/(window_.size()-1)));
}
double WSOLAEngine::inputMid(const std::vector<std::vector<float>>& input,
                             long long sample) const {
    if (sample<0 || sample>=static_cast<long long>(input[0].size())) return 0;
    if (input.size()==1) return input[0][sample];
    return 0.5*(double(input[0][sample])+input[1][sample]);
}
double WSOLAEngine::outputMid(const std::vector<std::vector<float>>& sums,
                              const std::vector<float>& weights,std::size_t sample) const {
    if (sample>=weights.size() || weights[sample]<1e-8f) return 0;
    if (sums.size()==1) return sums[0][sample]/weights[sample];
    return 0.5*(double(sums[0][sample])+sums[1][sample])/weights[sample];
}
double WSOLAEngine::correlation(const std::vector<std::vector<float>>& input,
    const std::vector<std::vector<float>>& sums,const std::vector<float>& weights,
    long long outputStart,long long candidateInputStart) const {
    double dot=0,outPower=0,inPower=0;
    // The earlier grains cover this interval; skip the Hann's very quiet edge.
    const int first=static_cast<int>(config_.synthesisHop/4);
    const int last=static_cast<int>(config_.windowSize-config_.synthesisHop-
                                    config_.synthesisHop/4);
    const int stride=std::max(1,int(config_.windowSize/512));
    for (int p=first;p<last;p+=stride) {
        const double a=outputMid(sums,weights,outputStart+p);
        const double b=inputMid(input,candidateInputStart+p-
                                   static_cast<long long>(config_.windowSize/2));
        dot+=a*b;outPower+=a*a;inPower+=b*b;
    }
    if (outPower<1e-12 || inPower<1e-12) return 0;
    return dot/std::sqrt(outPower*inPower);
}
std::vector<std::vector<float>> WSOLAEngine::processOffline(
    const std::vector<std::vector<float>>& input,
    const std::filesystem::path& diagnosticsCsv) {
    if ((input.size()!=1 && input.size()!=2) ||
        (input.size()==2 && input[0].size()!=input[1].size()))
        throw std::invalid_argument("WSOLA accepts matching mono/stereo channels");
    for (const auto& channel:input) for (float sample:channel)
        if (!std::isfinite(sample)) throw std::invalid_argument("Nonfinite WSOLA input");
    grains_.clear();
    if (input[0].empty()) return std::vector<std::vector<float>>(input.size());
    const double desired=std::round(input[0].size()*config_.timeRatio);
    if (!std::isfinite(desired) || desired<0 ||
        desired>double(std::numeric_limits<std::size_t>::max()/2))
        throw std::length_error("WSOLA output too large");
    const auto outputLength=static_cast<std::size_t>(desired);
    const auto padding=config_.windowSize/2;
    const auto capacity=outputLength+config_.windowSize*2;
    std::vector<std::vector<float>> sums(input.size(),std::vector<float>(capacity));
    std::vector<float> weights(capacity);
    const double analysisHop=double(config_.synthesisHop)/config_.timeRatio;
    double expected=0;
    std::size_t grain=0;
    for (std::size_t outputStart=0;
         outputStart<outputLength+padding;
         outputStart+=config_.synthesisHop,expected+=analysisHop,++grain) {
        const long long planned=std::llround(expected);
        long long selected=planned;
        double bestCorrelation=0;
        bool searched=false;
        if (grain && planned>=static_cast<long long>(padding+config_.searchRadius) &&
            planned+static_cast<long long>(padding+config_.searchRadius)<
                static_cast<long long>(input[0].size())) {
            searched=true;
            double best=0;
            int bestOffset=0;
            const int radius=config_.searchRadius;
            for (int offset=-radius;offset<=radius;offset+=16) {
                const double score=correlation(input,sums,weights,outputStart,planned+offset);
                if (score>best) {best=score;bestOffset=offset;}
            }
            const int coarse=bestOffset;
            for (int offset=std::max(-radius,coarse-15);
                 offset<=std::min(radius,coarse+15);++offset) {
                const double score=correlation(input,sums,weights,outputStart,planned+offset);
                if (score>best) {best=score;bestOffset=offset;}
            }
            selected=planned+bestOffset;
            bestCorrelation=best;
        }
        grains_.push_back({grain,expected,selected,
                           static_cast<int>(selected-planned),bestCorrelation,outputStart,searched});
        for (std::size_t i=0;i<window_.size();++i) {
            const auto out=outputStart+i;
            const auto in=selected+static_cast<long long>(i)-static_cast<long long>(padding);
            const float weight=window_[i];
            weights[out]+=weight;
            if (in>=0 && in<static_cast<long long>(input[0].size()))
                for (std::size_t c=0;c<input.size();++c)
                    sums[c][out]+=input[c][in]*weight;
        }
    }
    std::vector<std::vector<float>> result(input.size(),std::vector<float>(outputLength));
    for (std::size_t c=0;c<input.size();++c)
        for (std::size_t i=0;i<outputLength;++i) {
            const auto at=i+padding;
            result[c][i]=weights[at]>1e-8f ? sums[c][at]/weights[at] : 0;
        }
    if (!diagnosticsCsv.empty()) {
        std::ofstream csv(diagnosticsCsv);
        if (!csv) throw std::runtime_error("Cannot write WSOLA diagnostics");
        csv << std::setprecision(17);
        csv << "grainIndex,expectedAnalysisSample,selectedAnalysisSample,offsetSamples,maxCorrelation,outputSample,searched\n";
        for (const auto& item:grains_)
            csv << item.grainIndex << ',' << item.expectedAnalysisSample << ','
                << item.selectedAnalysisSample << ',' << item.offsetSamples << ','
                << item.maxCorrelation << ',' << item.outputSample << ',' << item.searched << '\n';
    }
    return result;
}
WSOLAStats WSOLAEngine::stats() const {
    WSOLAStats summary;
    summary.grainCount=grains_.size();
    if (grains_.empty()) return summary;
    std::vector<double> offsets,correlations;
    offsets.reserve(grains_.size());correlations.reserve(grains_.size());
    for (const auto& grain:grains_) {
        if (!grain.searched) continue;
        offsets.push_back(std::abs(grain.offsetSamples));
        correlations.push_back(grain.maxCorrelation);
    }
    if (offsets.empty()) return summary;
    for (std::size_t i=0;i<offsets.size();++i) {
        summary.averageAbsoluteOffset+=offsets[i];
        summary.averageCorrelation+=correlations[i];
    }
    summary.averageAbsoluteOffset/=offsets.size();
    summary.averageCorrelation/=offsets.size();
    std::sort(offsets.begin(),offsets.end());
    std::sort(correlations.begin(),correlations.end());
    summary.p95AbsoluteOffset=offsets[std::min(offsets.size()-1,
        static_cast<std::size_t>(std::floor(0.95*(offsets.size()-1))))];
    summary.p10Correlation=correlations[static_cast<std::size_t>(
        std::floor(0.10*(correlations.size()-1)))];
    return summary;
}
}
