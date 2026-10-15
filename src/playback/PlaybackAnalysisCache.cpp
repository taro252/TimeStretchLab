#include "playback/PlaybackAnalysisCache.h"
#include "audio/WavStream.h"
#include "prototype/Phase45PcmDigest.h"
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/mount.h>
#include <array>
#include <sstream>
#include <algorithm>
#include <stdexcept>
namespace ts::playback {
namespace {
// Only the frozen Phase13 detector configuration is accepted by its constructor.
constexpr auto version="phase13-v1:mid4096-hop1024:experimental3500:frozen-events-and-precise-anchors";
struct Identity {
    dev_t device{};ino_t inode{};off_t size{};timespec modified{},changed{},born{};std::uint32_t generation=0;
    bool operator==(const Identity& b)const{return device==b.device&&inode==b.inode&&size==b.size&&generation==b.generation&&modified.tv_sec==b.modified.tv_sec&&modified.tv_nsec==b.modified.tv_nsec&&changed.tv_sec==b.changed.tv_sec&&changed.tv_nsec==b.changed.tv_nsec&&born.tv_sec==b.born.tv_sec&&born.tv_nsec==b.born.tv_nsec;}
    std::string key()const{std::ostringstream s;s<<device<<':'<<inode<<':'<<size<<':'<<generation<<':'<<modified.tv_sec<<':'<<modified.tv_nsec<<':'<<changed.tv_sec<<':'<<changed.tv_nsec<<':'<<born.tv_sec<<':'<<born.tv_nsec<<':'<<version;return s.str();}
};
Identity identity(int fd){struct stat s{};if(fstat(fd,&s)||!S_ISREG(s.st_mode))throw std::runtime_error("Regular readable input required");return {s.st_dev,s.st_ino,s.st_size,s.st_mtimespec,s.st_ctimespec,s.st_birthtimespec,s.st_gen};}
StretchConfig detectorConfig(const WavStreamReader& r){StretchConfig c;c.sampleRate=r.sampleRate();c.channels=static_cast<int>(r.channels());c.timeRatio=2;c.enableMultiResolution=true;c.qualityMode=QualityMode::Experimental;c.enablePhaseLocking=true;c.enableTransientHandling=true;c.enableAdaptiveTimeMapping=true;c.enablePreciseTransientAnchoring=true;c.enableStereoCoherence=true;return c;}
}
class PinnedInput {
public:
    explicit PinnedInput(const std::filesystem::path& path):selected_(path){fd_=open(path.c_str(),O_RDONLY|O_CLOEXEC);if(fd_<0)throw std::runtime_error("Cannot pin input");try{id_=identity(fd_);struct statfs fs{};strong_=fstatfs(fd_,&fs)==0&&std::string(fs.f_fstypename)=="apfs";}catch(...){close(fd_);throw;}}
    ~PinnedInput(){close(fd_);}PinnedInput(const PinnedInput&)=delete;
    std::filesystem::path path()const{return "/dev/fd/"+std::to_string(fd_);}
    void validate()const{if(!(identity(fd_)==id_))throw std::runtime_error("Pinned input changed; re-prepare required");}
    void validateSelection()const{const auto current=open(selected_.c_str(),O_RDONLY|O_CLOEXEC);if(current<0)throw std::runtime_error("Input selection disappeared");bool same=false;try{same=identity(current)==id_;}catch(...){close(current);throw;}close(current);if(!same)throw std::runtime_error("Input replaced during preparation");validate();}
    bool strong()const{return strong_;}std::string key()const{return id_.key();}
    std::string sha(std::uint64_t& bytes)const{prototype::Phase45PcmDigest digest;std::array<char,65536> b{};off_t at=0;for(;;){auto n=pread(fd_,b.data(),b.size(),at);if(n<0)throw std::runtime_error("Input hash read failed");if(!n)break;digest.update(b.data(),n);at+=n;bytes+=n;}validate();return digest.finish();}
private:
    int fd_=-1;Identity id_;std::filesystem::path selected_;bool strong_=false;
};
std::filesystem::path AnalysisLease::path()const{return input->path();}
void AnalysisLease::validate()const{input->validate();}
struct PlaybackAnalysisCache::Entry {
    std::string key;std::shared_ptr<const SharedInputAnalysis> data;bool pending=true;
    std::exception_ptr error;std::condition_variable cv;std::uint64_t used=0;
};
PlaybackAnalysisCache::PlaybackAnalysisCache(std::size_t capacity,std::size_t maxEntries){stats_.limitBytes=capacity;stats_.maxEntries=maxEntries;}
std::shared_ptr<PlaybackAnalysisCache> PlaybackAnalysisCache::sharedDefault(){static auto cache=std::make_shared<PlaybackAnalysisCache>();return cache;}
void PlaybackAnalysisCache::evictLocked(std::size_t reservation,std::size_t extraEntries){while(stats_.residentBytes+reservation>stats_.limitBytes||entries_.size()+extraEntries>stats_.maxEntries){auto victim=entries_.end();for(auto it=entries_.begin();it!=entries_.end();++it)if(!(*it)->pending&&(*it)->data&&(*it)->data.use_count()==1&&(victim==entries_.end()||(*it)->used<(*victim)->used))victim=it;if(victim==entries_.end())break;stats_.residentBytes-=(*victim)->data->bytes;entries_.erase(victim);++stats_.evictions;}}
void PlaybackAnalysisCache::setCapacity(std::size_t n){std::lock_guard lock(mutex_);stats_.limitBytes=n;evictLocked();}
AnalysisCacheDiagnostics PlaybackAnalysisCache::diagnostics()const{std::lock_guard lock(mutex_);auto s=stats_;s.entries=entries_.size();return s;}
AnalysisLease PlaybackAnalysisCache::acquire(const std::filesystem::path& path,StartupDiagnostics& timing){
    StageClock identityClock;auto input=std::make_shared<PinnedInput>(path);WavStreamReader reader(input->path());timing.metadata=identityClock.elapsed();
    const auto key=input->key()+":"+std::to_string(reader.sampleRate())+":"+std::to_string(reader.channels())+":"+std::to_string(reader.frames());
    std::shared_ptr<Entry> entry;bool retain=false;
    {std::unique_lock lock(mutex_);evictLocked();retain=input->strong()&&stats_.limitBytes>0&&stats_.maxEntries>0;
     if(retain)for(auto& e:entries_)if(e->key==key){entry=e;break;}
     if(entry){timing.analysisSharedFlight=entry->pending;if(entry->pending)++stats_.sharedFlights;entry->cv.wait(lock,[&]{return !entry->pending;});if(entry->error)std::rethrow_exception(entry->error);input->validateSelection();timing.analysisHit=true;++stats_.hits;entry->used=++clock_;timing.identity=identityClock.elapsed();return {entry->data,input};}
     entry=std::make_shared<Entry>();entry->key=key;entry->used=++clock_;if(retain){evictLocked(0,1);if(entries_.size()<stats_.maxEntries)entries_.push_back(entry);else retain=false;}
    }
    try{
        auto data=std::make_shared<SharedInputAnalysis>();data->origin=input;data->version=version;
        std::uint64_t hashed=0;data->contentSha256=input->sha(hashed);input->validateSelection();timing.identity=identityClock.elapsed();
        StageClock analysisClock;data->analysis=Phase13StreamingEngine(detectorConfig(reader)).analyzeTransientEvents(input->path());timing.analysis=analysisClock.elapsed();input->validateSelection();
        data->bytes=sizeof(SharedInputAnalysis)+data->analysis.memoryBytes()+data->contentSha256.capacity()+data->version.capacity()+sizeof(PinnedInput)+key.capacity();
        {std::lock_guard lock(mutex_);++stats_.analyses;stats_.bytesHashed+=hashed;entry->data=data;entry->pending=false;if(retain){evictLocked(data->bytes);if(stats_.residentBytes+data->bytes<=stats_.limitBytes)stats_.residentBytes+=data->bytes;
          else entries_.erase(std::remove(entries_.begin(),entries_.end(),entry),entries_.end());}
          entry->cv.notify_all();}
        return {data,input};
    }catch(...){std::lock_guard lock(mutex_);entry->error=std::current_exception();entry->pending=false;entry->cv.notify_all();entries_.erase(std::remove(entries_.begin(),entries_.end(),entry),entries_.end());throw;}
}
}
