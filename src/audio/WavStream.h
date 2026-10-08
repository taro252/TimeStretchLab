#pragma once
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <vector>

namespace ts {
class WavStreamReader {
public:
    explicit WavStreamReader(const std::filesystem::path& path);
    std::uint32_t sampleRate() const { return sampleRate_; }
    std::size_t channels() const { return channels_; }
    std::size_t frames() const { return frames_; }
    float sample(std::size_t channel, std::size_t frame);
private:
    static constexpr std::size_t cacheFrames_ = 65536;
    std::ifstream input_;
    std::streamoff dataOffset_ = 0;
    std::uint32_t sampleRate_ = 0;
    std::size_t channels_ = 0, frames_ = 0, bytesPerSample_ = 0, blockAlign_ = 0;
    std::uint16_t format_ = 0;
    std::size_t cacheStart_ = 0, cacheCount_ = 0;
    std::vector<unsigned char> cache_;
    void load(std::size_t frame);
};

class WavStreamWriter {
public:
    WavStreamWriter(const std::filesystem::path& path, std::uint32_t sampleRate,
                    std::size_t channels, std::size_t frames);
    void write(const float* const* channels, std::size_t frames);
    void finish();
private:
    std::ofstream output_;
    std::size_t channels_, expectedFrames_, writtenFrames_ = 0;
    std::vector<unsigned char> buffer_;
};
}
