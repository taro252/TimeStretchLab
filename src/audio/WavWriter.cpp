#include "audio/WavWriter.h"
#include <bit>
#include <cmath>
#include <fstream>
#include <limits>
#include <stdexcept>

namespace ts {
namespace {
void put16(std::ostream& out, std::uint16_t v) {
    const char b[2] = {char(v), char(v >> 8)}; out.write(b, 2);
}
void put32(std::ostream& out, std::uint32_t v) {
    const char b[4] = {char(v), char(v >> 8), char(v >> 16), char(v >> 24)}; out.write(b, 4);
}
}
void WavWriter::write(const std::filesystem::path& path, const AudioBuffer& audio) {
    const auto count = audio.channels.size();
    if ((count != 1 && count != 2) || (audio.sampleRate != 44100 && audio.sampleRate != 48000))
        throw std::invalid_argument("Unsupported channel count or sample rate");
    const auto frames = audio.channels.front().size();
    for (const auto& channel : audio.channels)
        if (channel.size() != frames) throw std::invalid_argument("Channel lengths differ");
    const auto bytes = std::uint64_t(frames) * count * 4;
    if (bytes > std::numeric_limits<std::uint32_t>::max() - 36)
        throw std::invalid_argument("WAV exceeds RIFF 4 GiB limit");
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("Cannot create WAV: " + path.string());
    out.write("RIFF", 4); put32(out, std::uint32_t(36 + bytes)); out.write("WAVE", 4);
    out.write("fmt ", 4); put32(out, 16); put16(out, 3); put16(out, std::uint16_t(count));
    put32(out, audio.sampleRate); put32(out, audio.sampleRate * std::uint32_t(count) * 4);
    put16(out, std::uint16_t(count * 4)); put16(out, 32);
    out.write("data", 4); put32(out, std::uint32_t(bytes));
    for (std::size_t i = 0; i < frames; ++i) for (std::size_t c = 0; c < count; ++c) {
        const float value = audio.channels[c][i];
        if (!std::isfinite(value)) throw std::runtime_error("Non-finite output sample");
        put32(out, std::bit_cast<std::uint32_t>(value));
    }
    if (!out) throw std::runtime_error("WAV write failed");
}
}
