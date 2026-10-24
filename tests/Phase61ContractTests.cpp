#include "playback/ProgressiveContract.h"
#include <iostream>
#include <limits>
using namespace ts::playback::progressive;
void require(bool v){if(!v)throw std::runtime_error("Phase61 contract");}
template<class F>void rejects(F f){bool bad=false;try{f();}catch(const std::exception&){bad=true;}require(bad);}
int main(){try{
    for(auto rate:{44100u,48000u}){
        const std::uint64_t n=rate*17+113;
        for(auto frame:{0ULL,1ULL,12289ULL,50003ULL})require(inputFrameForSeconds(double(frame)/rate,rate,n)==frame);
        require(inputFrameForSeconds(double(n)/rate,rate,n)==n);
        rejects([&]{inputFrameForSeconds(std::nextafter(double(n)/rate,std::numeric_limits<double>::infinity()),rate,n);});
        for(double s:{-1.,-.000001,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()})rejects([&]{inputFrameForSeconds(s,rate,n);});
    }
    for(unsigned p=40;p<=200;++p)require(speedMicros(p/100.)==p*10000);
    require(Capabilities{}.contractVersion==4&&Capabilities{}.seekRequests&&!Capabilities{}.seek);
    require(Capabilities{}.maxConcurrentSessions==1&&Capabilities{}.maxRenderEpochs==2);
    for(auto s:{SeekState::Pending,SeekState::Preparing,SeekState::Ready})require(!terminal(s));
    for(auto s:{SeekState::Completed,SeekState::Replaced,SeekState::Cancelled,SeekState::Rejected,SeekState::Failed})require(terminal(s));
    std::cout<<"PASS strict seconds/frame endpoints, 161 speeds, seek states, closed capability gate\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
