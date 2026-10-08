#include "audio/WavReader.h"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "Usage: wav_compare reference.wav current.wav\n";
        return 2;
    }
    try {
        const auto previous = ts::WavReader::read(argv[1]);
        const auto current = ts::WavReader::read(argv[2]);
        if (previous.sampleRate != current.sampleRate ||
            previous.channels.size() != current.channels.size() ||
            previous.channels[0].size() != current.channels[0].size())
            throw std::invalid_argument("WAV formats or lengths differ");
        double maxDifference = 0, sumDifferenceSquared = 0;
        std::size_t changed = 0, firstAboveTolerance = std::numeric_limits<std::size_t>::max();
        std::size_t maximumFrame = 0, maximumChannel = 0, aboveTolerance = 0;
        const auto frames = current.channels[0].size();
        for (std::size_t c = 0; c < current.channels.size(); ++c)
            for (std::size_t i = 0; i < frames; ++i) {
                const double difference = double(current.channels[c][i]) - previous.channels[c][i];
                if (std::abs(difference) > maxDifference) {
                    maxDifference = std::abs(difference);
                    maximumFrame = i; maximumChannel = c;
                }
                if (std::abs(difference) >= 1e-5) {
                    ++aboveTolerance;
                    firstAboveTolerance = std::min(firstAboveTolerance, i);
                }
                sumDifferenceSquared += difference * difference;
                if (difference != 0) ++changed;
            }
        std::cout << std::fixed << std::setprecision(10)
                  << "reference=" << argv[1] << " current=" << argv[2]
                  << " frames=" << frames << " max_difference=" << maxDifference
                  << " rms_difference=" << std::sqrt(sumDifferenceSquared / (frames * current.channels.size()))
                  << " changed_samples=" << changed
                  << " above_1e-5=" << aboveTolerance
                  << " first_above_frame=" << (firstAboveTolerance == std::numeric_limits<std::size_t>::max()
                     ? -1LL : static_cast<long long>(firstAboveTolerance))
                  << " max_frame=" << maximumFrame << " max_channel=" << maximumChannel << '\n';
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n'; return 1;
    }
}
