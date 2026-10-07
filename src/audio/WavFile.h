#pragma once

#include <cstdint>
#include <vector>

namespace ts {
struct AudioBuffer {
    std::uint32_t sampleRate = 0;
    // DSP always uses planar float, regardless of the WAV's interleaved storage.
    std::vector<std::vector<float>> channels;
};
}
