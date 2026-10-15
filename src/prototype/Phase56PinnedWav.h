#pragma once
#include "prototype/Phase56ProgressiveAnalysis.h"
#include "audio/WavStream.h"
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
namespace ts::prototype::phase56 {
// Experimental file adapter. Same FD/path identity fields as Phase54 PinnedInput;
// no completed-analysis cache, no hashing shortcut, no audio-callback access.
class PinnedWavSource {
    std::filesystem::path selected_;std::uint64_t generation_;int fd_=-1;
    struct stat identity_{};std::unique_ptr<WavStreamReader> reader_;std::size_t position_=0;
    static bool same(const struct stat& a,const struct stat& b){
        const auto time=[](timespec a,timespec b){return a.tv_sec==b.tv_sec&&a.tv_nsec==b.tv_nsec;};
        return a.st_dev==b.st_dev&&a.st_ino==b.st_ino&&a.st_size==b.st_size&&a.st_gen==b.st_gen&&
            time(a.st_mtimespec,b.st_mtimespec)&&time(a.st_ctimespec,b.st_ctimespec)&&time(a.st_birthtimespec,b.st_birthtimespec);
    }
public:
    PinnedWavSource(const std::filesystem::path& path,std::uint64_t generation):selected_(path),generation_(generation){
        fd_=open(path.c_str(),O_RDONLY|O_CLOEXEC);if(fd_<0)throw std::runtime_error("Cannot pin source");
        try{if(fstat(fd_,&identity_)||!S_ISREG(identity_.st_mode))throw std::runtime_error("Regular source required");reader_=std::make_unique<WavStreamReader>("/dev/fd/"+std::to_string(fd_));}
        catch(...){close(fd_);throw;}
    }
    ~PinnedWavSource(){reader_.reset();if(fd_>=0)close(fd_);}
    PinnedWavSource(const PinnedWavSource&)=delete;
    std::uint32_t rate()const{return reader_->sampleRate();}
    std::size_t channels()const{return reader_->channels();}
    std::size_t frames()const{return reader_->frames();}
    void validate(ProgressiveAnalysisSession& session){
        struct stat current{};
        if(fd_<0||fstat(fd_,&current)){session.failInput(generation_,AnalysisError::InputRead);throw std::runtime_error("Pinned source read failed");}
        const int selected=open(selected_.c_str(),O_RDONLY|O_CLOEXEC);struct stat choice{};
        const bool ok=selected>=0&&fstat(selected,&choice)==0&&same(identity_,current)&&same(identity_,choice);
        if(selected>=0)close(selected);
        if(!ok){session.failInput(generation_,AnalysisError::InputChanged);throw std::runtime_error("Pinned source changed/replaced/unavailable");}
    }
    std::size_t appendNext(ProgressiveAnalysisSession& session,std::size_t maximum){
        try{
            validate(session);const auto count=std::min({maximum,frames()-position_,std::size_t(131072)});
            std::vector<std::vector<float>> b(channels(),std::vector<float>(count));std::array<const float*,2> p{};
            for(std::size_t c=0;c<channels();++c){for(std::size_t i=0;i<count;++i)b[c][i]=reader_->sample(c,position_+i);p[c]=b[c].data();}
            validate(session);session.appendInput(generation_,position_,p.data(),count);
            if(session.getSnapshot()->isCancelled)throw std::runtime_error("Pinned source analysis cancelled");
            position_+=count;return count;
        }catch(...){if(!session.getSnapshot()->hasError&&!session.getSnapshot()->isCancelled)session.failInput(generation_,AnalysisError::InputRead);throw;}
    }
    void finish(ProgressiveAnalysisSession& session){validate(session);if(position_!=frames())throw std::logic_error("Source not fully consumed");session.finishInput(generation_);}
    void injectReadFailureForTest(){if(fd_>=0)close(fd_);fd_=-1;}
};
}
