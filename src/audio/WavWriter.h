#pragma once
#include "audio/WavFile.h"
#include <filesystem>

namespace ts {
class WavWriter {
public:
    // Writes IEEE float32 WAV without peak normalization.
    static void write(const std::filesystem::path& path, const AudioBuffer& audio);
};
}
