#include "audio/WavReader.h"
#include <bit>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>

namespace ts {
namespace {
std::uint16_t u16(const unsigned char* p) { return std::uint16_t(p[0]) | (std::uint16_t(p[1]) << 8); }
std::uint32_t u32(const unsigned char* p) {
    return std::uint32_t(p[0]) | (std::uint32_t(p[1]) << 8) |
           (std::uint32_t(p[2]) << 16) | (std::uint32_t(p[3]) << 24);
}
void exact(std::istream& in, char* p, std::streamsize size) {
    if (!in.read(p, size)) throw std::runtime_error("Truncated WAV file");
}
}

AudioBuffer WavReader::read(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot open WAV: " + path.string());
    unsigned char header[12];
    exact(in, reinterpret_cast<char*>(header), 12);
    if (std::memcmp(header, "RIFF", 4) || std::memcmp(header + 8, "WAVE", 4))
        throw std::runtime_error("Expected RIFF/WAVE");

    std::uint16_t format = 0, count = 0, bits = 0, blockAlign = 0;
    std::uint32_t rate = 0;
    std::vector<unsigned char> data;
    bool haveFmt = false, haveData = false;
    while (in && !(haveFmt && haveData)) {
        unsigned char chunk[8];
        if (!in.read(reinterpret_cast<char*>(chunk), 8)) break;
        const auto size = u32(chunk + 4);
        if (!std::memcmp(chunk, "fmt ", 4)) {
            if (size < 16 || size > 4096) throw std::runtime_error("Unsupported fmt chunk");
            std::vector<unsigned char> fmt(size);
            exact(in, reinterpret_cast<char*>(fmt.data()), size);
            format = u16(fmt.data()); count = u16(fmt.data() + 2);
            rate = u32(fmt.data() + 4); blockAlign = u16(fmt.data() + 12);
            bits = u16(fmt.data() + 14);
            haveFmt = true;
        } else if (!std::memcmp(chunk, "data", 4)) {
            data.resize(size);
            exact(in, reinterpret_cast<char*>(data.data()), size);
            haveData = true;
        } else {
            in.seekg(size, std::ios::cur);
            if (!in) throw std::runtime_error("Truncated WAV chunk");
        }
        if (size & 1) in.seekg(1, std::ios::cur);
    }
    if (!haveFmt || !haveData) throw std::runtime_error("Missing WAV fmt/data chunk");
    if (count < 1 || count > 2 || (rate != 44100 && rate != 48000) ||
        !((format == 1 && bits == 16) || (format == 3 && bits == 32)) ||
        blockAlign != count * (bits / 8) || data.size() % blockAlign)
        throw std::runtime_error("Supported WAV: mono/stereo, 44.1/48 kHz, PCM16/float32");

    const auto frames = data.size() / blockAlign;
    AudioBuffer audio{rate, std::vector<std::vector<float>>(count, std::vector<float>(frames))};
    for (std::size_t i = 0; i < frames; ++i) for (std::size_t c = 0; c < count; ++c) {
        const auto* p = data.data() + i * blockAlign + c * (bits / 8);
        float value;
        if (format == 1) value = static_cast<std::int16_t>(u16(p)) / 32768.0f;
        else value = std::bit_cast<float>(u32(p));
        if (!std::isfinite(value)) throw std::runtime_error("Non-finite WAV sample");
        audio.channels[c][i] = value;
    }
    return audio;
}
}
