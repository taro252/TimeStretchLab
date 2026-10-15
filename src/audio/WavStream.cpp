#include "audio/WavStream.h"
#include <algorithm>
#include <bit>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <cerrno>

namespace ts {
namespace {
std::uint16_t u16(const unsigned char* p) {
    return std::uint16_t(p[0]) | (std::uint16_t(p[1]) << 8);
}
std::uint32_t u32(const unsigned char* p) {
    return std::uint32_t(p[0]) | (std::uint32_t(p[1]) << 8) |
           (std::uint32_t(p[2]) << 16) | (std::uint32_t(p[3]) << 24);
}
void put16(std::ostream& out, std::uint16_t value) {
    const char bytes[2] = {char(value), char(value >> 8)};
    out.write(bytes, 2);
}
void put32(std::ostream& out, std::uint32_t value) {
    const char bytes[4] = {char(value), char(value >> 8), char(value >> 16), char(value >> 24)};
    out.write(bytes, 4);
}
}
bool WavStreamReader::readPinned(void* buffer,std::size_t bytes,std::streamoff at) {
    auto* p=static_cast<char*>(buffer);std::size_t done=0;
    while(done<bytes){const auto n=pread(descriptor_,p+done,bytes-done,at+done);
        if(n<0&&errno==EINTR)continue;if(n<=0)return false;done+=static_cast<std::size_t>(n);}
    return true;
}
WavStreamReader::~WavStreamReader(){if(descriptor_>=0)close(descriptor_);}
WavStreamReader::WavStreamReader(const std::filesystem::path& path) {
    if(path.string().starts_with("/dev/fd/")){
        auto fd=std::stoi(path.string().substr(8));descriptor_=fcntl(fd,F_DUPFD_CLOEXEC,0);
        if(descriptor_<0)throw std::runtime_error("Cannot duplicate pinned WAV");
    }else{input_.open(path,std::ios::binary);if(!input_)throw std::runtime_error("Cannot open WAV: "+path.string());}
    try {
    std::streamoff position=0;
    const auto read=[&](void* p,std::size_t n){if(descriptor_>=0){auto ok=readPinned(p,n,position);position+=n;return ok;}return bool(input_.read(static_cast<char*>(p),n));};
    const auto seek=[&](std::streamoff at){if(descriptor_>=0){position=at;return true;}input_.seekg(at);return bool(input_);};
    const auto tell=[&](){return descriptor_>=0?position:static_cast<std::streamoff>(input_.tellg());};
    unsigned char header[12];
    if (!read(header,12) ||
        std::memcmp(header, "RIFF", 4) || std::memcmp(header+8, "WAVE", 4))
        throw std::runtime_error("Expected RIFF/WAVE");
    bool haveFormat = false, haveData = false;
    std::uint32_t dataBytes = 0;
    while ((descriptor_>=0||input_) && !(haveFormat && haveData)) {
        unsigned char chunk[8];
        if (!read(chunk,8)) break;
        const auto size = u32(chunk+4);
        const auto content = tell();
        if (!std::memcmp(chunk, "fmt ", 4)) {
            if (size < 16 || size > 4096) throw std::runtime_error("Unsupported fmt chunk");
            std::vector<unsigned char> fmt(size);
            if (!read(fmt.data(),size))
                throw std::runtime_error("Truncated WAV format");
            format_ = u16(fmt.data());
            channels_ = u16(fmt.data()+2);
            sampleRate_ = u32(fmt.data()+4);
            blockAlign_ = u16(fmt.data()+12);
            bytesPerSample_ = u16(fmt.data()+14)/8;
            haveFormat = true;
        } else if (!std::memcmp(chunk, "data", 4)) {
            dataOffset_ = static_cast<std::streamoff>(content);
            dataBytes = size;
            haveData = true;
        }
        if (!seek(content + static_cast<std::streamoff>(size + (size & 1u)))) throw std::runtime_error("Truncated WAV chunk");
    }
    if (!haveFormat || !haveData || (channels_ != 1 && channels_ != 2) ||
        (sampleRate_ != 44100 && sampleRate_ != 48000) ||
        !((format_ == 1 && bytesPerSample_ == 2) ||
          (format_ == 3 && bytesPerSample_ == 4)) ||
        blockAlign_ != channels_*bytesPerSample_ || dataBytes % blockAlign_)
        throw std::runtime_error("Supported WAV: mono/stereo, 44.1/48 kHz, PCM16/float32");
    std::streamoff length=0;
    if(descriptor_>=0){struct stat st{};if(fstat(descriptor_,&st))throw std::runtime_error("Pinned WAV stat failed");length=st.st_size;}
    else{input_.clear();input_.seekg(0,std::ios::end);length=static_cast<std::streamoff>(input_.tellg());}
    if (length < dataOffset_ + dataBytes)
        throw std::runtime_error("Truncated WAV data");
    frames_ = dataBytes/blockAlign_;
    cache_.resize(cacheFrames_*blockAlign_);
    }catch(...){if(descriptor_>=0){close(descriptor_);descriptor_=-1;}throw;}
}
void WavStreamReader::load(std::size_t frame) {
    cacheStart_ = frame/cacheFrames_*cacheFrames_;
    cacheCount_ = std::min(cacheFrames_, frames_-cacheStart_);
    const auto bytes=cacheCount_*blockAlign_;const auto at=dataOffset_+static_cast<std::streamoff>(cacheStart_*blockAlign_);
    if(descriptor_>=0){if(!readPinned(cache_.data(),bytes,at))throw std::runtime_error("Truncated pinned WAV data");}
    else{input_.clear();input_.seekg(at);if(!input_.read(reinterpret_cast<char*>(cache_.data()),static_cast<std::streamsize>(bytes)))throw std::runtime_error("Truncated WAV data");}
}
float WavStreamReader::sample(std::size_t channel, std::size_t frame) {
    if (channel >= channels_ || frame >= frames_) throw std::out_of_range("WAV sample outside input");
    if (!cacheCount_ || frame < cacheStart_ || frame >= cacheStart_+cacheCount_) load(frame);
    const auto* p = cache_.data()+(frame-cacheStart_)*blockAlign_+channel*bytesPerSample_;
    const float value = format_ == 1
        ? static_cast<std::int16_t>(u16(p))/32768.0f
        : std::bit_cast<float>(u32(p));
    if (!std::isfinite(value)) throw std::runtime_error("Non-finite WAV sample");
    return value;
}
WavStreamWriter::WavStreamWriter(const std::filesystem::path& path, std::uint32_t rate,
                                 std::size_t channels, std::size_t frames)
    : output_(path, std::ios::binary), channels_(channels), expectedFrames_(frames) {
    if (!output_) throw std::runtime_error("Cannot create WAV: " + path.string());
    const auto bytes = std::uint64_t(frames)*channels*4;
    if ((channels != 1 && channels != 2) || (rate != 44100 && rate != 48000) ||
        bytes > std::numeric_limits<std::uint32_t>::max()-36)
        throw std::invalid_argument("Unsupported WAV output");
    output_.write("RIFF", 4); put32(output_, std::uint32_t(36+bytes)); output_.write("WAVE", 4);
    output_.write("fmt ", 4); put32(output_, 16); put16(output_, 3);
    put16(output_, std::uint16_t(channels)); put32(output_, rate);
    put32(output_, rate*std::uint32_t(channels)*4);
    put16(output_, std::uint16_t(channels*4)); put16(output_, 32);
    output_.write("data", 4); put32(output_, std::uint32_t(bytes));
}
void WavStreamWriter::write(const float* const* channels, std::size_t frames) {
    if (writtenFrames_+frames > expectedFrames_) throw std::out_of_range("Too many output samples");
    buffer_.resize(frames*channels_*4);
    for (std::size_t i = 0; i < frames; ++i) for (std::size_t c = 0; c < channels_; ++c) {
        const float value = channels[c][i];
        if (!std::isfinite(value)) throw std::runtime_error("Non-finite output sample");
        const auto bits = std::bit_cast<std::uint32_t>(value);
        const auto offset = (i*channels_+c)*4;
        for (int byte = 0; byte < 4; ++byte)
            buffer_[offset+byte] = static_cast<unsigned char>(bits >> (byte*8));
    }
    output_.write(reinterpret_cast<const char*>(buffer_.data()),
                  static_cast<std::streamsize>(buffer_.size()));
    if (!output_) throw std::runtime_error("WAV write failed");
    writtenFrames_ += frames;
}
void WavStreamWriter::finish() {
    if (writtenFrames_ != expectedFrames_) throw std::runtime_error("Incomplete WAV output");
    output_.flush();
    if (!output_) throw std::runtime_error("WAV write failed");
}
}
