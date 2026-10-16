#include "prototype/Phase58FixSnapshotMailbox.h"
#include <array>
#include <thread>
#include <iostream>
using ts::prototype::phase58::BorrowedSnapshotMailbox;
struct Snapshot {
    std::uint64_t serial;
    std::array<std::uint64_t,1024> data;
    std::atomic<unsigned>& alive;
    Snapshot(std::uint64_t value,std::atomic<unsigned>& count):serial(value),alive(count){++alive;for(std::size_t i=0;i<data.size();++i)data[i]=serial^i;}
    ~Snapshot(){--alive;}
};
int main(){try{
    std::atomic<unsigned> alive{0},peak{0};std::atomic<bool> done{false},bad{false};
    constexpr std::uint64_t iterations=20000;
    {
        BorrowedSnapshotMailbox<Snapshot> mailbox;
        std::thread publisher([&]{for(std::uint64_t i=1;i<=iterations;++i){
            std::shared_ptr<const Snapshot> value=std::make_shared<Snapshot>(i,alive);
            auto now=alive.load(),old=peak.load();while(old<now&&!peak.compare_exchange_weak(old,now)){}
            while(!mailbox.tryPublish(value))std::this_thread::yield();
            if(mailbox.ownerCount()>3)bad=true;
        }done=true;});
        std::uint64_t seen=mailbox.initialTag,last=0;const Snapshot* current=nullptr;
        while(!done.load()||last<iterations){
            if(auto lease=mailbox.acquire(seen)){
                const auto* next=lease->get();
                if(!next||next->serial<=last||(lease->tag()>>2)!=next->serial)bad=true;
                for(std::size_t j=0;j<next->data.size();++j)if(next->data[j]!=(next->serial^j))bad=true;
                if(current)for(std::size_t j=0;j<current->data.size();++j)if(current->data[j]!=(last^j))bad=true;
                last=next->serial;current=next;seen=lease->tag();lease->commit();
            }else std::this_thread::yield();
        }
        publisher.join();if(mailbox.ownerCount()>3||peak.load()>4)bad=true;
    }
    if(bad.load()||alive.load())throw std::runtime_error("Snapshot lifetime, ordering or capacity violation");
    std::cout<<"Phase58 Fix borrowed mailbox PASS peak="<<peak<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
