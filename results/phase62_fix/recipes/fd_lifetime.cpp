#include "prototype/Phase58RealtimePipeline.h"
#include <libproc.h>
#include <sys/stat.h>
#include <unistd.h>
#include <array>
#include <chrono>
#include <fstream>
#include <iostream>
#include <thread>
#include <set>
using ts::prototype::phase58::RealtimePipeline;
static void check(bool v,const char* why){if(!v)throw std::runtime_error(why);}
static std::set<std::pair<int,std::uint64_t>> descriptors(const struct stat& source,bool privateOnly=false){
 std::array<proc_fdinfo,1024> rows{};const int bytes=proc_pidinfo(getpid(),PROC_PIDLISTFDS,0,rows.data(),int(sizeof(rows)));
 check(bytes>0&&bytes<int(sizeof(rows)),"cannot enumerate complete FD list");std::set<std::pair<int,std::uint64_t>> result;
 for(int i=0;i<bytes/int(sizeof(rows[0]));++i){struct stat value{};const int fd=int(rows[i].proc_fd);
  if(fstat(fd,&value)==0&&S_ISREG(value.st_mode)&&value.st_size==source.st_size&&((!privateOnly&&value.st_dev==source.st_dev&&value.st_ino==source.st_ino)||value.st_nlink==0))result.emplace(fd,std::uint64_t(value.st_ino));
 }return result;
}
template<class P> static void wait(P p){const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(!p()){check(std::chrono::steady_clock::now()<end,"watchdog");std::this_thread::sleep_for(std::chrono::microseconds(100));}}
int main(int argc,char** argv){try{
 check(argc==3,"input output.json");struct stat source{};check(stat(argv[1],&source)==0,"input stat");
 const auto baseline=descriptors(source);check(baseline.empty(),"input unexpectedly open before test");std::ofstream out(argv[2]);out<<"{\"samples\":[";bool comma=false;
 for(bool candidate:{true,false}){
  ts::prototype::phase58::Configuration config;config.residentInput=true;config.verifyPcm=false;config.speedMicros=2000000;config.candidate=candidate;
  auto base=std::make_unique<RealtimePipeline>(argv[1],config);base->start();check(base->waitUntilReady(std::chrono::seconds(30)),"base Ready");wait([&]{return base->finalAnalysisAvailable();});
  auto loop=base->createLoopSeek(17,4817,2000000);loop->enableLoopReuse(17);loop->start();check(loop->waitUntilReady(std::chrono::seconds(30)),"loop Ready");
  base->stop();base.reset();const auto pinned=descriptors(source);check(!pinned.empty()&&pinned.size()<=8,"input lost or FD bound exceeded after parent destruction");
  auto next=loop->createLoopSeek(17,4817,2000000);next->enableLoopReuse(17);next->start();check(next->waitUntilReady(std::chrono::seconds(30)),"second owner Ready");
  wait([&]{return next->finalAnalysisAvailable();});const auto twoOwners=descriptors(source);const auto twoOwnerSnapshots=descriptors(source,true);check(!twoOwners.empty()&&twoOwners.size()<=8,"two-owner FD bound");
  std::array<std::array<float,512>,2> pcm{};float* p[]{pcm[0].data(),pcm[1].data()};std::size_t at=0;const auto period=loop->loopOutputEndFrame()-loop->loopOutputStartFrame();
  while(at<period*1000){const auto n=std::min<std::size_t>(512,std::min(period*1000-at,period-at%period));wait([&]{return loop->available()>=n||loop->failed();});check(!loop->failed(),"loop generation failed");auto r=loop->pullAudio(p,n);check(r.received==n,"FD test supply");at+=n;}
  const auto steady=descriptors(source);check(steady.size()<=8&&descriptors(source,true)==twoOwnerSnapshots,"snapshot FD set grew or changed across 1000 reused periods");
  const auto d=loop->diagnostics();check(d.sourceHashPasses==1&&d.sourceSnapshotCreations==1&&d.residentLockCalls==1,"source lease duplicated");
  loop->stop();loop.reset();check(!descriptors(source).empty(),"second owner lost shared FD");next->stop();next.reset();const auto after=descriptors(source);check(after==baseline,"input or private snapshot FD survived last owner destruction");
  if(comma)out<<',';comma=true;out<<"{\"preset\":\""<<(candidate?"candidate":"baseline")<<"\",\"periods\":1000,\"after_parent_destroy\":"<<pinned.size()<<",\"two_owners\":"<<twoOwners.size()<<",\"after_1000_periods\":"<<steady.size()<<",\"after_last_owner_destroy\":"<<after.size()<<"}";
 }
 out<<"],\"PASS\":true,\"scope\":\"non-Sandbox pipeline FD lifetime; Sandbox and Merodoa are separate gates\"}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
