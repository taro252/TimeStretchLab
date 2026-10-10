#include "dsp/Phase18PcmCache.h"
#include "audio/WavStream.h"
#include <CommonCrypto/CommonDigest.h>
#include <algorithm>
#include <array>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <sys/utsname.h>
#include <fcntl.h>
#include <unistd.h>

namespace ts {
namespace {
using Clock=std::chrono::steady_clock;
std::string hex(const unsigned char* bytes,std::size_t count) {
    static constexpr char digits[]="0123456789abcdef";
    std::string result;
    result.reserve(count*2);
    for (std::size_t i=0;i<count;++i) {result+=digits[bytes[i]>>4];result+=digits[bytes[i]&15];}
    return result;
}
std::string shaBytes(const std::string& value) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(value.data(),static_cast<CC_LONG>(value.size()),digest);
    return hex(digest,sizeof(digest));
}
std::string shaFile(const std::filesystem::path& path) {
    std::ifstream stream(path,std::ios::binary);
    if (!stream) throw std::runtime_error("Cannot hash file: "+path.string());
    CC_SHA256_CTX context;
    CC_SHA256_Init(&context);
    std::array<char,65536> buffer{};
    while (stream) {
        stream.read(buffer.data(),buffer.size());
        const auto count=stream.gcount();
        if (count>0) CC_SHA256_Update(&context,buffer.data(),static_cast<CC_LONG>(count));
    }
    if (!stream.eof()) throw std::runtime_error("File hash read failed");
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256_Final(digest,&context);
    return hex(digest,sizeof(digest));
}
std::string environment() {
    utsname info{};
    if (uname(&info)!=0) throw std::runtime_error("uname failed");
    return std::string(info.sysname)+"/"+info.release+"/"+info.machine+
        "/clang:"+__clang_version__+"/accelerate-system";
}
void syncFile(const std::filesystem::path& path) {
    const int descriptor=open(path.c_str(),O_RDONLY);
    if (descriptor<0) throw std::runtime_error("Cannot open cache for sync");
    const bool okay=fsync(descriptor)==0;
    close(descriptor);
    if (!okay) throw std::runtime_error("Cache sync failed");
}
std::string field(const std::string& metadata,const char* name) {
    const std::string prefix=std::string(name)+"=";
    std::istringstream lines(metadata);
    std::string line;
    while (std::getline(lines,line))
        if (line.rfind(prefix,0)==0) return line.substr(prefix.size());
    return {};
}
}

Phase18PcmCache::Phase18PcmCache(std::filesystem::path source,
    std::filesystem::path directory,StretchConfig config)
    : source_(std::move(source)),directory_(std::move(directory)),config_(std::move(config)) {
    if (config_.timeRatio!=2.0 || config_.qualityMode!=QualityMode::Experimental ||
        !config_.enableMultiResolution || !config_.enablePhaseLocking ||
        !config_.enableTransientHandling || !config_.enableAdaptiveTimeMapping ||
        !config_.enablePreciseTransientAnchoring || !config_.enableStereoCoherence)
        throw std::invalid_argument("Cache requires frozen 0.50x Experimental3500 config");
    Phase13StreamingEngine validateFrozen(config_);
    WavStreamReader input(source_);
    rate_=input.sampleRate();channels_=input.channels();frames_=input.frames()*2;
    if (rate_!=config_.sampleRate || channels_!=static_cast<std::size_t>(config_.channels))
        throw std::invalid_argument("Cache input/config mismatch");
    inputHash_=shaFile(source_);
    environment_=environment();
    const std::string identity="phase18-cache-v1|"+inputHash_+"|speed=0.50|ratio=2|Experimental3500|"
        "8192/2048,4096/1024,1024/256|LP250,LP3500|phase-lock=1|transient=1|"
        "time-map=1|anchor=1|stereo=1|float32-raw|"+
        std::to_string(rate_)+"|"+std::to_string(channels_)+"|"+
        TS_PHASE18_DSP_FINGERPRINT+"|"+environment_;
    key_=shaBytes(identity);
    dataPath_=directory_/(key_+".wav");
    metadataPath_=directory_/(key_+".meta");
}
Phase18PcmCache::~Phase18PcmCache() { wait(); }

std::optional<std::filesystem::path> Phase18PcmCache::validPath(double* validationSeconds) const {
    const auto begin=Clock::now();
    const auto finish=[&] {
        if (validationSeconds)
            *validationSeconds=std::chrono::duration<double>(Clock::now()-begin).count();
    };
    if (shaFile(source_)!=inputHash_)
        throw std::runtime_error("Input content changed after TimeMap preparation");
    try {
        if (!std::filesystem::exists(dataPath_) || !std::filesystem::exists(metadataPath_)) {
            finish();return std::nullopt;
        }
        std::ifstream meta(metadataPath_);
        const std::string content((std::istreambuf_iterator<char>(meta)),{});
        if (field(content,"key")!=key_ || field(content,"input_sha256")!=inputHash_ ||
            field(content,"environment")!=environment_ ||
            field(content,"frames")!=std::to_string(frames_) ||
            field(content,"sample_rate")!=std::to_string(rate_) ||
            field(content,"channels")!=std::to_string(channels_)) {
            finish();return std::nullopt;
        }
        const auto expected=44ULL+static_cast<std::uint64_t>(frames_)*channels_*4;
        if (std::filesystem::file_size(dataPath_)!=expected) {finish();return std::nullopt;}
        WavStreamReader reader(dataPath_);
        if (reader.frames()!=frames_ || reader.sampleRate()!=rate_ || reader.channels()!=channels_ ||
            shaFile(dataPath_)!=field(content,"sha256")) {finish();return std::nullopt;}
        finish();return dataPath_;
    } catch (...) {finish();return std::nullopt;}
}
void Phase18PcmCache::beginGeneration() {
    if (worker_.joinable()) {
        if (!generationFinished()) return;
        worker_.join();
    }
    if (validPath()) return;
    error_.clear();
    finished_.store(false,std::memory_order_release);
    worker_=std::thread([this] { generate(); });
}
void Phase18PcmCache::wait() {
    if (worker_.joinable()) worker_.join();
}
std::string Phase18PcmCache::generationError() const {
    if (!generationFinished()) return "generation still running";
    return error_;
}
void Phase18PcmCache::generate() {
    const auto begin=Clock::now();
    const auto unique=std::to_string(getpid())+"-"+
        std::to_string(std::chrono::duration_cast<std::chrono::nanoseconds>(
            begin.time_since_epoch()).count());
    const auto tempData=directory_/(key_+"."+unique+".tmp.wav");
    const auto tempMeta=directory_/(key_+"."+unique+".tmp.meta");
    try {
        std::filesystem::create_directories(directory_);
        if (shaFile(source_)!=inputHash_) throw std::runtime_error("Input changed before cache generation");
        WavStreamWriter writer(tempData,rate_,channels_,frames_);
        Phase13StreamingEngine engine(config_);
        const auto result=engine.processFile(source_,[&](const float* const* planes,std::size_t count){
            writer.write(planes,count);
        });
        writer.finish();
        if (shaFile(source_)!=inputHash_) throw std::runtime_error("Input changed during cache generation");
        if (result.processing.outputFrames!=frames_) throw std::runtime_error("Cache length mismatch");
        const auto outputHash=shaFile(tempData);
        WavStreamReader check(tempData);
        if (check.frames()!=frames_ || check.channels()!=channels_ || check.sampleRate()!=rate_ ||
            std::filesystem::file_size(tempData)!=44ULL+frames_*channels_*4)
            throw std::runtime_error("Cache WAV verification failed");
        std::ofstream meta(tempMeta,std::ios::binary);
        meta << "key=" << key_ << '\n' << "input_sha256=" << inputHash_ << '\n'
             << "environment=" << environment_ << '\n'
             << "frames=" << frames_ << '\n' << "sample_rate=" << rate_ << '\n'
             << "channels=" << channels_ << '\n' << "time_map_hash="
             << result.processing.timeMapHash << '\n' << "sha256=" << outputHash << '\n';
        meta.flush();
        if (!meta) throw std::runtime_error("Cache metadata write failed");
        meta.close();
        syncFile(tempData);syncFile(tempMeta);
        std::filesystem::rename(tempData,dataPath_);
        std::filesystem::rename(tempMeta,metadataPath_);
    } catch (const std::exception& exception) {
        error_=exception.what();
        std::error_code ignored;
        std::filesystem::remove(tempData,ignored);
        std::filesystem::remove(tempMeta,ignored);
    }
    generationSeconds_.store(std::chrono::duration<double>(Clock::now()-begin).count());
    finished_.store(true,std::memory_order_release);
}
}
