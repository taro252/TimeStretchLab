#include "dsp/Phase18PcmCache.h"
#include "audio/WavStream.h"
#include <CommonCrypto/CommonDigest.h>
#include <algorithm>
#include <array>
#include <bit>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <fcntl.h>
#include <unistd.h>

namespace ts {
namespace {
using Clock=std::chrono::steady_clock;
constexpr std::size_t digestBlockFrames=4096;
constexpr std::size_t maximumBlockBytes=digestBlockFrames*2*4;
struct Fd {
    int value=-1;
    explicit Fd(int fd=-1):value(fd) {}
    ~Fd() { if (value>=0) close(value); }
    Fd(const Fd&)=delete;
    Fd& operator=(const Fd&)=delete;
    int release() { const int fd=value;value=-1;return fd; }
};
int lockFile(const std::filesystem::path& path,int mode,bool nonblocking=false) {
    const int fd=open(path.c_str(),O_RDWR|O_CREAT,0600);
    if (fd<0) throw std::runtime_error("Cannot open cache lock: "+path.string());
    if (flock(fd,mode|(nonblocking ? LOCK_NB : 0))!=0) {
        close(fd);
        if (nonblocking && (errno==EWOULDBLOCK || errno==EAGAIN)) return -1;
        throw std::runtime_error("Cannot lock cache: "+path.string());
    }
    return fd;
}
void readExact(int fd,void* destination,std::size_t bytes,std::uint64_t offset) {
    auto* output=static_cast<unsigned char*>(destination);
    while (bytes) {
        const auto count=pread(fd,output,bytes,static_cast<off_t>(offset));
        if (count<0 && errno==EINTR) continue;
        if (count<=0) throw std::runtime_error("PCM cache read failed or truncated");
        output+=count;bytes-=static_cast<std::size_t>(count);offset+=count;
    }
}
std::uint16_t get16(const unsigned char* p) { return std::uint16_t(p[0])|(std::uint16_t(p[1])<<8); }
std::uint32_t get32(const unsigned char* p) {
    return std::uint32_t(p[0])|(std::uint32_t(p[1])<<8)|
        (std::uint32_t(p[2])<<16)|(std::uint32_t(p[3])<<24);
}
bool sameStat(const struct stat& a,const struct stat& b) {
    return a.st_dev==b.st_dev && a.st_ino==b.st_ino && a.st_size==b.st_size &&
        a.st_mtimespec.tv_sec==b.st_mtimespec.tv_sec &&
        a.st_mtimespec.tv_nsec==b.st_mtimespec.tv_nsec &&
        a.st_ctimespec.tv_sec==b.st_ctimespec.tv_sec &&
        a.st_ctimespec.tv_nsec==b.st_ctimespec.tv_nsec;
}
bool keyName(const std::string& value) {
    return value.size()==64 && std::all_of(value.begin(),value.end(),[](char c) {
        return (c>='0' && c<='9') || (c>='a' && c<='f');
    });
}
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

VerifiedPcmCache::VerifiedPcmCache(int dataFd,int lockFd,std::size_t frames,
    std::size_t channels,std::uint32_t rate,
    std::vector<std::array<unsigned char,32>> hashes)
    : dataFd_(dataFd),lockFd_(lockFd),frames_(frames),channels_(channels),
      rate_(rate),hashes_(std::move(hashes)) {}
VerifiedPcmCache::~VerifiedPcmCache() {
    if (dataFd_>=0) close(dataFd_);
    if (lockFd_>=0) close(lockFd_);
}
void VerifiedPcmCache::readFrames(std::size_t first,std::size_t count,
    float* const* output) const {
    static_assert(std::endian::native==std::endian::little);
    if (first>frames_ || count>frames_-first) throw std::out_of_range("Cache read past end");
    std::array<unsigned char,maximumBlockBytes> bytes{};
    std::size_t written=0;
    while (written<count) {
        const auto block=(first+written)/digestBlockFrames;
        const auto blockStart=block*digestBlockFrames;
        const auto blockCount=std::min(digestBlockFrames,frames_-blockStart);
        const auto byteCount=blockCount*channels_*sizeof(float);
        readExact(dataFd_,bytes.data(),byteCount,44ULL+blockStart*channels_*sizeof(float));
        std::array<unsigned char,32> digest{};
        CC_SHA256(bytes.data(),static_cast<CC_LONG>(byteCount),digest.data());
        if (digest!=hashes_.at(block)) throw std::runtime_error("PCM cache block hash mismatch");
        const auto offset=first+written-blockStart;
        const auto take=std::min(count-written,blockCount-offset);
        for (std::size_t i=0;i<take;++i) for (std::size_t c=0;c<channels_;++c) {
            float value;
            std::memcpy(&value,bytes.data()+((offset+i)*channels_+c)*sizeof(float),sizeof(float));
            output[c][written+i]=value;
        }
        written+=take;
    }
}

Phase18PcmCache::Phase18PcmCache(std::filesystem::path source,
    std::filesystem::path directory,StretchConfig config,Phase19CachePolicy policy)
    : source_(std::move(source)),directory_(std::move(directory)),
      config_(std::move(config)),policy_(policy) {
    if (policy_.maximumBytes==0 || !(policy_.freeSpaceFraction>0 && policy_.freeSpaceFraction<=1))
        throw std::invalid_argument("Invalid PCM cache capacity policy");
    if (config_.timeRatio!=2.0 || config_.qualityMode!=QualityMode::Experimental ||
        !config_.enableMultiResolution || !config_.enablePhaseLocking ||
        !config_.enableTransientHandling || !config_.enableAdaptiveTimeMapping ||
        !config_.enablePreciseTransientAnchoring || !config_.enableStereoCoherence)
        throw std::invalid_argument("Cache requires frozen 0.50x Experimental3500 config");
    Phase13StreamingEngine validateFrozen(config_);
    Fd opened(open(source_.c_str(),O_RDONLY|O_NOFOLLOW));
    sourceFd_=opened.value;
    if (sourceFd_<0) throw std::runtime_error("Cannot open cache input");
    struct stat inputBefore{},pathBefore{},inputAfter{},pathAfter{};
    if (fstat(sourceFd_,&inputBefore)!=0 || stat(source_.c_str(),&pathBefore)!=0 ||
        !sameStat(inputBefore,pathBefore) || !S_ISREG(inputBefore.st_mode))
        throw std::runtime_error("Cache input changed while opening");
    WavStreamReader input(source_);
    rate_=input.sampleRate();channels_=input.channels();frames_=input.frames()*2;
    if (rate_!=config_.sampleRate || channels_!=static_cast<std::size_t>(config_.channels))
        throw std::invalid_argument("Cache input/config mismatch");
    inputHash_=shaFile(source_);
    if (fstat(sourceFd_,&inputAfter)!=0 || stat(source_.c_str(),&pathAfter)!=0 ||
        !sameStat(inputBefore,inputAfter) || !sameStat(inputBefore,pathAfter))
        throw std::runtime_error("Cache input changed during initial verification");
    sourceDev_=inputAfter.st_dev;sourceIno_=inputAfter.st_ino;sourceSize_=inputAfter.st_size;
    sourceMtimeSec_=inputAfter.st_mtimespec.tv_sec;
    sourceMtimeNsec_=inputAfter.st_mtimespec.tv_nsec;
    sourceCtimeSec_=inputAfter.st_ctimespec.tv_sec;
    sourceCtimeNsec_=inputAfter.st_ctimespec.tv_nsec;
    environment_=environment();
    const std::string identity="phase18-cache-v1|"+inputHash_+"|speed=0.50|ratio=2|Experimental3500|"
        "8192/2048,4096/1024,1024/256|LP250,LP3500|phase-lock=1|transient=1|"
        "time-map=1|anchor=1|stereo=1|float32-raw|"+
        std::to_string(rate_)+"|"+std::to_string(channels_)+"|"+
        TS_PHASE18_DSP_FINGERPRINT+"|"+environment_;
    key_=shaBytes(identity);
    dataPath_=directory_/(key_+".wav");
    metadataPath_=directory_/(key_+".meta");
    cleanupOrphans();
    opened.release();
}
Phase18PcmCache::~Phase18PcmCache() { wait();verified_.reset();if (sourceFd_>=0) close(sourceFd_); }

void Phase18PcmCache::checkInputIdentity() const {
    struct stat descriptor{},pathname{};
    if (fstat(sourceFd_,&descriptor)!=0 || stat(source_.c_str(),&pathname)!=0 ||
        static_cast<std::uint64_t>(descriptor.st_dev)!=sourceDev_ ||
        static_cast<std::uint64_t>(descriptor.st_ino)!=sourceIno_ ||
        descriptor.st_size!=static_cast<off_t>(sourceSize_) ||
        descriptor.st_mtimespec.tv_sec!=sourceMtimeSec_ ||
        descriptor.st_mtimespec.tv_nsec!=sourceMtimeNsec_ ||
        descriptor.st_ctimespec.tv_sec!=sourceCtimeSec_ ||
        descriptor.st_ctimespec.tv_nsec!=sourceCtimeNsec_ ||
        !sameStat(descriptor,pathname))
        throw std::runtime_error("Input changed after TimeMap preparation; reload required");
}

std::optional<std::filesystem::path> Phase18PcmCache::validPath(double* validationSeconds) const {
    const auto begin=Clock::now();
    const auto finish=[&] {
        if (validationSeconds)
            *validationSeconds=std::chrono::duration<double>(Clock::now()-begin).count();
    };
    checkInputIdentity();
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

std::shared_ptr<const VerifiedPcmCache> Phase18PcmCache::acquireVerified(
    double* validationSeconds) {
    const auto begin=Clock::now();
    const auto finish=[&] {
        if (validationSeconds)
            *validationSeconds=std::chrono::duration<double>(Clock::now()-begin).count();
    };
    checkInputIdentity();
    if (verified_) { finish();return verified_; }
    std::filesystem::create_directories(directory_);
    Fd keyLock(lockFile(directory_/(key_+".lock"),LOCK_SH,true));
    if (keyLock.value<0) { finish();return {}; }
    try {
        std::ifstream meta(metadataPath_);
        if (!meta) { finish();return {}; }
        const std::string content((std::istreambuf_iterator<char>(meta)),{});
        if (field(content,"key")!=key_ || field(content,"input_sha256")!=inputHash_ ||
            field(content,"environment")!=environment_ ||
            field(content,"frames")!=std::to_string(frames_) ||
            field(content,"sample_rate")!=std::to_string(rate_) ||
            field(content,"channels")!=std::to_string(channels_)) {
            finish();return {};
        }
        Fd data(open(dataPath_.c_str(),O_RDONLY|O_NOFOLLOW));
        if (data.value<0) { finish();return {}; }
        struct stat before{},after{},pathname{};
        if (fstat(data.value,&before)!=0 || !S_ISREG(before.st_mode) ||
            stat(dataPath_.c_str(),&pathname)!=0 || !sameStat(before,pathname) ||
            before.st_size!=static_cast<off_t>(44ULL+frames_*channels_*4)) {
            finish();return {};
        }
        std::array<unsigned char,44> header{};
        readExact(data.value,header.data(),header.size(),0);
        if (std::memcmp(header.data(),"RIFF",4)!=0 ||
            std::memcmp(header.data()+8,"WAVEfmt ",8)!=0 ||
            std::memcmp(header.data()+36,"data",4)!=0 ||
            get32(header.data()+16)!=16 || get16(header.data()+20)!=3 ||
            get16(header.data()+22)!=channels_ || get32(header.data()+24)!=rate_ ||
            get32(header.data()+40)!=frames_*channels_*4) {
            finish();return {};
        }
        CC_SHA256_CTX whole;
        CC_SHA256_Init(&whole);
        CC_SHA256_Update(&whole,header.data(),static_cast<CC_LONG>(header.size()));
        std::vector<std::array<unsigned char,32>> blockHashes;
        blockHashes.reserve((frames_+digestBlockFrames-1)/digestBlockFrames);
        std::array<unsigned char,maximumBlockBytes> bytes{};
        for (std::size_t at=0;at<frames_;at+=digestBlockFrames) {
            const auto count=std::min(digestBlockFrames,frames_-at);
            const auto byteCount=count*channels_*4;
            readExact(data.value,bytes.data(),byteCount,44ULL+at*channels_*4);
            CC_SHA256_Update(&whole,bytes.data(),static_cast<CC_LONG>(byteCount));
            std::array<unsigned char,32> digest{};
            CC_SHA256(bytes.data(),static_cast<CC_LONG>(byteCount),digest.data());
            blockHashes.push_back(digest);
        }
        std::array<unsigned char,32> digest{};
        CC_SHA256_Final(digest.data(),&whole);
        if (hex(digest.data(),digest.size())!=field(content,"sha256") ||
            fstat(data.value,&after)!=0 || !sameStat(before,after)) {
            finish();return {};
        }
        auto* snapshot=new VerifiedPcmCache(data.value,keyLock.value,
            frames_,channels_,rate_,std::move(blockHashes));
        data.release();keyLock.release();
        verified_=std::shared_ptr<const VerifiedPcmCache>(snapshot);
        std::error_code ignored;
        std::filesystem::last_write_time(metadataPath_,
            std::filesystem::file_time_type::clock::now(),ignored);
        finish();return verified_;
    } catch (...) { finish();return {}; }
}

void Phase18PcmCache::cleanupOrphans() {
    std::filesystem::create_directories(directory_);
    Fd policy(lockFile(directory_/".policy.lock",LOCK_EX,true));
    if (policy.value<0) return;
    for (const auto& entry:std::filesystem::directory_iterator(directory_)) {
        const auto name=entry.path().filename().string();
        if (name.size()<68 || !keyName(name.substr(0,64)) ||
            name.compare(64,1,".")!=0)
            continue;
        const bool temporary=name.find(".tmp.")!=std::string::npos &&
            (entry.path().extension()==".wav" || entry.path().extension()==".meta");
        const bool unpublished=name.size()==68 && entry.path().extension()==".wav" &&
            !std::filesystem::exists(directory_/(name.substr(0,64)+".meta"));
        if (!temporary && !unpublished) continue;
        Fd keyLock(lockFile(directory_/(name.substr(0,64)+".lock"),LOCK_EX,true));
        if (keyLock.value<0) continue;
        std::error_code ignored;
        if (entry.is_regular_file(ignored)) std::filesystem::remove(entry.path(),ignored);
    }
}

bool Phase18PcmCache::ensureCapacity(std::uint64_t neededBytes) {
    // Caller owns .policy.lock, which serializes reservation, LRU eviction,
    // generation and publication across different keys and processes.
    struct Candidate {
        std::filesystem::path data,meta;
        std::filesystem::file_time_type used;
        std::uint64_t bytes=0;
        std::string key;
    };
    std::vector<Candidate> candidates;
    std::uint64_t usedBytes=0;
    for (const auto& entry:std::filesystem::directory_iterator(directory_)) {
        const auto name=entry.path().filename().string();
        if (entry.path().extension()!=".meta" || name.size()!=69 ||
            !keyName(name.substr(0,64))) continue;
        const auto candidateData=directory_/(name.substr(0,64)+".wav");
        std::error_code ignored;
        const auto bytes=std::filesystem::file_size(candidateData,ignored);
        if (ignored) continue;
        usedBytes+=bytes;
        if (name.substr(0,64)!=key_) {
            auto used=std::filesystem::last_write_time(entry.path(),ignored);
            if (ignored) used=std::filesystem::file_time_type::min();
            candidates.push_back({candidateData,entry.path(),used,bytes,name.substr(0,64)});
        }
    }
    const auto space=std::filesystem::space(directory_);
    const auto freePlusCache=static_cast<long double>(space.available)+usedBytes;
    const auto fractionLimit=static_cast<std::uint64_t>(
        std::min<long double>(freePlusCache*policy_.freeSpaceFraction,
                              static_cast<long double>(policy_.maximumBytes)));
    const auto budget=std::min(policy_.maximumBytes,fractionLimit);
    if (neededBytes>budget) return false;
    std::sort(candidates.begin(),candidates.end(),[](const Candidate& a,const Candidate& b) {
        return a.used<b.used;
    });
    for (const auto& item:candidates) {
        if (usedBytes+neededBytes<=budget &&
            std::filesystem::space(directory_).available>=neededBytes) break;
        Fd keyLock(lockFile(directory_/(item.key+".lock"),LOCK_EX,true));
        if (keyLock.value<0) continue; // active playback or generation
        std::error_code ignored;
        std::filesystem::remove(item.meta,ignored);
        if (ignored) continue;
        std::filesystem::remove(item.data,ignored);
        if (ignored) continue;
        usedBytes-=item.bytes;
    }
    return usedBytes+neededBytes<=budget &&
        std::filesystem::space(directory_).available>=neededBytes;
}

void Phase18PcmCache::beginGeneration() {
    if (worker_.joinable()) {
        if (!generationFinished()) return;
        worker_.join();
    }
    if (acquireVerified()) return;
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
        Fd keyLock(lockFile(directory_/(key_+".lock"),LOCK_EX,true));
        if (keyLock.value<0) {
            // Another process owns this key. It will publish or fail; normal
            // DSP playback and the Phase 16 fallback remain available.
            finished_.store(true,std::memory_order_release);
            return;
        }
        Fd policy(lockFile(directory_/".policy.lock",LOCK_EX));
        for (const auto& entry:std::filesystem::directory_iterator(directory_)) {
            const auto name=entry.path().filename().string();
            if (name.rfind(key_+".",0)==0 && name.find(".tmp.")!=std::string::npos) {
                std::error_code ignored;
                if (entry.is_regular_file(ignored)) std::filesystem::remove(entry.path(),ignored);
            }
        }
        if (validPath()) {
            generationSeconds_.store(std::chrono::duration<double>(Clock::now()-begin).count());
            finished_.store(true,std::memory_order_release);
            return;
        }
        {
            std::error_code ignored;
            std::filesystem::remove(metadataPath_,ignored);
            std::filesystem::remove(dataPath_,ignored);
        }
        const auto bytes=static_cast<std::uint64_t>(frames_)*channels_*4;
        if (bytes>std::numeric_limits<std::uint32_t>::max()-36)
            throw std::runtime_error("RIFF cache exceeds 4 GiB limit");
        if (!ensureCapacity(44+bytes))
            throw std::runtime_error("PCM cache capacity or free-space limit");
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
