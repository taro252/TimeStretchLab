#pragma once
#include "audio/WavFile.h"
#include <filesystem>

namespace ts {
class WavReader {
public:
    static AudioBuffer read(const std::filesystem::path& path);
};
}
