#include "audio/WavReader.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: wav_metrics file.wav [file.wav ...]\n";
        return 2;
    }
    try {
        std::cout << std::fixed << std::setprecision(6);
        for (int file = 1; file < argc; ++file) {
            const auto audio = ts::WavReader::read(argv[file]);
            const auto frames = audio.channels.front().size();
            double peak = 0, sumSquares = 0, leftSquares = 0, rightSquares = 0, cross = 0;
            std::uint64_t overOne = 0;
            for (std::size_t i = 0; i < frames; ++i) {
                for (const auto& channel : audio.channels) {
                    const double value = channel[i];
                    peak = std::max(peak, std::abs(value));
                    sumSquares += value * value;
                    if (std::abs(value) > 1.0) ++overOne;
                }
                if (audio.channels.size() == 2) {
                    const double left = audio.channels[0][i], right = audio.channels[1][i];
                    leftSquares += left * left;
                    rightSquares += right * right;
                    cross += left * right;
                }
            }
            const double rms = std::sqrt(sumSquares / (frames * audio.channels.size()));
            std::cout << "file=" << argv[file] << " rate=" << audio.sampleRate
                      << " channels=" << audio.channels.size() << " frames=" << frames
                      << " duration_s=" << double(frames) / audio.sampleRate
                      << " rms=" << rms << " peak=" << peak
                      << " samples_over_1=" << overOne;
            if (audio.channels.size() == 2)
                std::cout << " lr_rms_ratio=" << std::sqrt(leftSquares / rightSquares)
                          << " lr_correlation=" << cross / std::sqrt(leftSquares * rightSquares);
            if (audio.channels.size() == 2) {
                std::vector<double> correlations;
                const auto window = static_cast<std::size_t>(audio.sampleRate);
                for (std::size_t start = 0; start + window <= frames; start += window) {
                    double sumL = 0, sumR = 0, sumLL = 0, sumRR = 0, sumLR = 0;
                    for (std::size_t i = start; i < start + window; ++i) {
                        const double left = audio.channels[0][i], right = audio.channels[1][i];
                        sumL += left; sumR += right;
                        sumLL += left * left; sumRR += right * right; sumLR += left * right;
                    }
                    const double covariance = sumLR - sumL * sumR / window;
                    const double varianceL = sumLL - sumL * sumL / window;
                    const double varianceR = sumRR - sumR * sumR / window;
                    if (varianceL > window * 1e-6 && varianceR > window * 1e-6)
                        correlations.push_back(covariance / std::sqrt(varianceL * varianceR));
                }
                if (!correlations.empty()) {
                    const auto negative = std::count_if(correlations.begin(), correlations.end(),
                        [](double value) { return value < 0; });
                    std::sort(correlations.begin(), correlations.end());
                    std::cout << " corr_1s_p10=" << correlations[correlations.size() / 10]
                              << " corr_1s_median=" << correlations[correlations.size() / 2]
                              << " corr_1s_p90=" << correlations[correlations.size() * 9 / 10]
                              << " corr_1s_negative_fraction=" << double(negative) / correlations.size();
                }
            }
            std::cout << " finite=yes\n";
        }
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n'; return 1;
    }
}
