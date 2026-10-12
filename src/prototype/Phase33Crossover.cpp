#include "audio/WavStream.h"
#include "dsp/MultiResolutionCrossover.h"
#include "dsp/StreamingCrossover.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

// Diagnostic decomposition of the frozen crossover identity:
// final = high + LP250(low - mid) + LP3500(mid - high)
//       = LP250(low) + [LP3500(mid)-LP250(mid)] + [high-LP3500(high)].
// The second form isolates effective low, mid, high contributions.
int main(int argc, char** argv) {
    if (argc != 6) {
        std::cerr << "Usage: phase33_crossover low.wav mid.wav high.wav final.wav output-prefix\n";
        return 2;
    }
    try {
        std::array<ts::WavStreamReader,4> reader{
            ts::WavStreamReader(argv[1]),ts::WavStreamReader(argv[2]),
            ts::WavStreamReader(argv[3]),ts::WavStreamReader(argv[4])};
        const auto length=reader[0].frames();
        const auto channels=reader[0].channels();
        const auto rate=reader[0].sampleRate();
        for (const auto& item:reader)
            if (item.frames()!=length || item.channels()!=channels || item.sampleRate()!=rate)
                throw std::invalid_argument("Input WAV geometry differs");
        if (!channels || channels>2) throw std::invalid_argument("Unsupported channel count");
        ts::MultiResolutionCrossover coefficients(rate,250.0,3500.0);
        std::vector<std::unique_ptr<ts::StreamingFIR>> lowLow,lowMid,highMid,highHigh;
        for (std::size_t c=0;c<channels;++c) {
            lowLow.emplace_back(std::make_unique<ts::StreamingFIR>(coefficients.lowFilter(),length));
            lowMid.emplace_back(std::make_unique<ts::StreamingFIR>(coefficients.lowFilter(),length));
            highMid.emplace_back(std::make_unique<ts::StreamingFIR>(coefficients.highFilter(),length));
            highHigh.emplace_back(std::make_unique<ts::StreamingFIR>(coefficients.highFilter(),length));
        }
        const std::filesystem::path prefix=argv[5];
        std::array<std::unique_ptr<ts::WavStreamWriter>,3> writers;
        constexpr std::array<const char*,3> names{"low","mid","high"};
        for (std::size_t i=0;i<3;++i)
            writers[i]=std::make_unique<ts::WavStreamWriter>(
                prefix.string()+"_"+names[i]+".wav",rate,channels,length);
        constexpr std::size_t block=16384;
        std::array<std::vector<std::vector<float>>,3> samples;
        std::array<std::vector<const float*>,3> pointers;
        for (std::size_t i=0;i<3;++i) {
            samples[i].assign(channels,std::vector<float>(block));
            pointers[i].resize(channels);
            for (std::size_t c=0;c<channels;++c) pointers[i][c]=samples[i][c].data();
        }
        double squaredDifference=0,squaredFinal=0;
        float maxDifference=0;
        for (std::size_t start=0;start<length;start+=block) {
            const auto count=std::min(block,length-start);
            for (std::size_t i=0;i<count;++i)
                for (std::size_t c=0;c<channels;++c) {
                    const auto n=start+i;
                    const float low=lowLow[c]->next(n,[&](std::size_t k) {
                        return reader[0].sample(c,k);
                    });
                    const float mid=highMid[c]->next(n,[&](std::size_t k) {
                        return reader[1].sample(c,k);
                    })-lowMid[c]->next(n,[&](std::size_t k) {
                        return reader[1].sample(c,k);
                    });
                    const float high=reader[2].sample(c,n)-highHigh[c]->next(n,[&](std::size_t k) {
                        return reader[2].sample(c,k);
                    });
                    samples[0][c][i]=low;
                    samples[1][c][i]=mid;
                    samples[2][c][i]=high;
                    const float original=reader[3].sample(c,n);
                    const float residual=(low+mid+high)-original;
                    maxDifference=std::max(maxDifference,std::abs(residual));
                    squaredDifference+=double(residual)*residual;
                    squaredFinal+=double(original)*original;
                }
            for (std::size_t r=0;r<3;++r) writers[r]->write(pointers[r].data(),count);
        }
        for (auto& writer:writers) writer->finish();
        const double total=double(length*channels);
        std::cout<<std::setprecision(12)
                 <<"frames="<<length<<'\n'
                 <<"max_reconstruction_difference="<<maxDifference<<'\n'
                 <<"rms_reconstruction_difference="<<std::sqrt(squaredDifference/total)<<'\n'
                 <<"relative_rms_difference="<<std::sqrt(squaredDifference/std::max(squaredFinal,1e-30))<<'\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"Phase 33 crossover: "<<error.what()<<'\n';
        return 1;
    }
}
