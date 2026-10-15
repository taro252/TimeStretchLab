#pragma once
#include "prototype/Phase56PinnedWav.h"
namespace ts::prototype::phase57 {
// FD shared by all three DSP readers; the analysis adapter has its own pread FD.
class PinnedInput {
    std::filesystem::path selected_;int fd_=-1;struct stat original_{};
    phase56::PinnedWavSource source_;
    static bool same(const struct stat& a,const struct stat& b){auto t=[](timespec x,timespec y){return x.tv_sec==y.tv_sec&&x.tv_nsec==y.tv_nsec;};return a.st_dev==b.st_dev&&a.st_ino==b.st_ino&&a.st_size==b.st_size&&a.st_gen==b.st_gen&&t(a.st_mtimespec,b.st_mtimespec)&&t(a.st_ctimespec,b.st_ctimespec)&&t(a.st_birthtimespec,b.st_birthtimespec);}
public:
    PinnedInput(const std::filesystem::path& p,std::uint64_t g):selected_(p),source_(p,g){fd_=open(p.c_str(),O_RDONLY|O_CLOEXEC);if(fd_<0)throw std::runtime_error("Cannot pin DSP source");if(fstat(fd_,&original_)){close(fd_);fd_=-1;throw std::runtime_error("Cannot identify DSP source");}}
    ~PinnedInput(){if(fd_>=0)close(fd_);}
    PinnedInput(const PinnedInput&)=delete;
    auto dspPath()const{return std::filesystem::path("/dev/fd/"+std::to_string(fd_));}
    auto rate()const{return source_.rate();}auto channels()const{return source_.channels();}auto frames()const{return source_.frames();}
    void validate(phase56::ProgressiveAnalysisSession& a){struct stat current{},choice{};const int fd=open(selected_.c_str(),O_RDONLY|O_CLOEXEC);const bool valid=fd_>=0&&fstat(fd_,&current)==0&&fd>=0&&fstat(fd,&choice)==0&&same(original_,current)&&same(original_,choice);if(fd>=0)close(fd);if(!valid)throw std::runtime_error("DSP input changed/replaced/unavailable");source_.validate(a);}
    std::size_t appendNext(phase56::ProgressiveAnalysisSession& a,std::size_t n){validate(a);return source_.appendNext(a,n);}
    void finish(phase56::ProgressiveAnalysisSession& a){validate(a);source_.finish(a);}
    void injectReadFailureForTest(){source_.injectReadFailureForTest();}
};
}
