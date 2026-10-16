#include "prototype/Phase59Control.h"
#include <array>
#include <iostream>
#include <thread>
struct Record {std::uint64_t serial=0;std::array<std::uint64_t,1024> words{};};
int main(){
    ts::prototype::phase59::ValueMailbox<Record> mailbox;
    std::atomic<bool> done{false},bad{false};constexpr std::uint64_t count=30000;
    std::thread writer([&]{for(std::uint64_t i=1;i<=count;++i){
        Record r;r.serial=i;for(std::size_t j=0;j<r.words.size();++j)r.words[j]=i^j;
        mailbox.publish(r);
    }done=true;});
    std::uint64_t last=0;
    while(!done.load()||last<count){if(auto value=mailbox.read()){const auto& r=*value;
        if(r.serial<last)bad=true;last=r.serial;
        for(std::size_t j=0;j<r.words.size();++j)if(r.words[j]!=(r.serial^j))bad=true;
    }else std::this_thread::yield();}
    writer.join();std::cout<<"ValueMailbox "<<(bad?"FAIL":"PASS")<<" last="<<last<<'\n';return bad?1:0;
}
