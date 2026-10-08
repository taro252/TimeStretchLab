#include "dsp/StreamingCrossover.h"

namespace ts {
StreamingFIR::StreamingFIR(const MultiResolutionCrossover::Filter& filter,
                           std::size_t outputLength)
    : taps_(filter.taps), center_(filter.taps/2),
      blockLength_(fftSize_-filter.taps+1), outputLength_(outputLength),
      response_(filter.response), spectrum_(fftSize_/2+1),
      block_(fftSize_), transformed_(fftSize_), accum_(16384) {}
StreamingCrossoverChannel::StreamingCrossoverChannel(
    const MultiResolutionCrossover& filters, std::size_t outputLength)
    : low_(filters.lowFilter(), outputLength),
      high_(filters.highFilter(), outputLength) {}
}
