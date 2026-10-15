#include "playback/PlaybackAnalysisCache.h"
#include "playback/PlaybackEngine.h"
#include "audio/WavWriter.h"
#include <future>
#include <fstream>
#include <barrier>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <cmath>
#include <iostream>
using namespace ts;using namespace ts::playback;
void check(bool b,const char* message){if(!b)throw std::runtime_error(message);}
AudioBuffer audio(float gain=.1f){AudioBuffer a;a.sampleRate=48000;a.channels.resize(2,std::vector<float>(48000*3));for(std::size_t i=0;i<a.channels[0].size();++i)for(unsigned c=0;c<2;++c)a.channels[c][i]=gain*std::sin(2*3.141592653589793*437.3*i/48000+c*.2);return a;}
int main(){auto dir=std::filesystem::temp_directory_path()/("phase54_analysis_"+std::to_string(getpid()));try{
 prototype::Phase52WorkerOptions hooks;hooks.controlledStallMs=123;
 Configuration legacy{Preset::Baseline,.75,true,true,hooks};
 check(legacy.reuseAnalysis&&!legacy.analysisCache&&legacy.verificationHooks.controlledStallMs==123,"Phase53 aggregate configuration compatibility");
 RenderResult oldResult{1,2,3,4,5,6};check(oldResult.outputBefore==4&&oldResult.generation==5&&oldResult.lastPublicationNs==6&&oldResult.session==0,"Phase53 aggregate render result compatibility");
 std::filesystem::create_directory(dir);auto path=dir/"input.wav";WavWriter::write(path,audio());
 PlaybackAnalysisCache cache;StartupDiagnostics d;auto first=cache.acquire(path,d);check(!d.analysisHit,"cold hit");auto initial=cache.diagnostics();check(initial.analyses==1&&initial.bytesHashed==std::filesystem::file_size(path),"cold strong validation");
 StartupDiagnostics warm;auto same=cache.acquire(path,warm);check(warm.analysisHit&&same.data==first.data,"immutable reuse");check(cache.diagnostics().analyses==1&&cache.diagnostics().bytesHashed==initial.bytesHashed,"warm must not rehash/reanalyse");check(first.data->bytes>0,"memory accounting");
 struct stat before{};stat(path.c_str(),&before);int fd=open(path.c_str(),O_RDWR);float value=.42f;check(pwrite(fd,&value,4,44)==4,"mutate");timespec times[]={before.st_atimespec,before.st_mtimespec};futimens(fd,times);close(fd);
 bool invalid=false;try{first.validate();}catch(...){invalid=true;}check(invalid,"in-place mtime spoof invalidation");StartupDiagnostics changed;auto second=cache.acquire(path,changed);check(!changed.analysisHit&&second.data->contentSha256!=first.data->contentSha256,"changed content reanalysis");
 auto old=dir/"old.wav";std::filesystem::rename(path,old);WavWriter::write(path,audio(.2f));StartupDiagnostics replaced;auto third=cache.acquire(path,replaced);check(!replaced.analysisHit&&third.data->contentSha256!=second.data->contentSha256,"replacement identity");bool renamed=false;try{second.validate();}catch(...){renamed=true;}check(renamed,"rename conservatively invalidates ctime");
 auto link=dir/"link.wav";std::filesystem::create_symlink(path,link);StartupDiagnostics linked;auto through=cache.acquire(link,linked);check(linked.analysisHit&&through.data==third.data,"symlink same target");std::filesystem::remove(link);std::filesystem::create_symlink(old,link);StartupDiagnostics retarget;auto other=cache.acquire(link,retarget);check(other.data!=third.data,"symlink retarget");
 PlaybackAnalysisCache disabled(0);StartupDiagnostics off1,off2;auto a=disabled.acquire(path,off1);auto b=disabled.acquire(path,off2);check(!off2.analysisHit&&disabled.diagnostics().analyses==2&&disabled.diagnostics().residentBytes==0,"no-cache fallback");
 PlaybackAnalysisCache limited(third.data->bytes+128);StartupDiagnostics l1,l2;{auto lease=limited.acquire(path,l1);}auto lease=limited.acquire(old,l2);check(limited.diagnostics().residentBytes<=limited.diagnostics().limitBytes&&limited.diagnostics().evictions>=1,"LRU unused eviction");limited.setCapacity(0);lease.validate();check(limited.diagnostics().residentBytes>0,"active lease retained");lease={};limited.setCapacity(0);check(limited.diagnostics().residentBytes==0,"released lease eviction");
 PlaybackAnalysisCache concurrent;std::barrier start(8);std::vector<std::future<AnalysisLease>> work;for(int i=0;i<8;++i)work.push_back(std::async(std::launch::async,[&]{start.arrive_and_wait();StartupDiagnostics t;return concurrent.acquire(path,t);}));std::vector<AnalysisLease> result;for(auto& f:work)result.push_back(f.get());for(auto& r:result)check(r.data==result[0].data,"coalesced analysis");check(concurrent.diagnostics().analyses==1&&concurrent.diagnostics().hits==7,"single flight");
 PlaybackAnalysisCache countBound(32*1024*1024,1);{StartupDiagnostics t;auto lease=countBound.acquire(path,t);} {StartupDiagnostics t;auto lease=countBound.acquire(old,t);}check(countBound.diagnostics().entries<=1,"descriptor entry bound");
 auto broken=dir/"broken.wav";{std::ofstream f(broken);f<<"not a WAV";}bool refused=false;try{StartupDiagnostics t;cache.acquire(broken,t);}catch(...){refused=true;}check(refused,"corrupt source");std::filesystem::remove_all(dir);std::cout<<"immutable reuse, spoofed mtime/replacement/symlink invalidation, memory LRU, disabled cache, single flight PASS\n";return 0;
 }catch(const std::exception&e){std::filesystem::remove_all(dir);std::cerr<<e.what()<<'\n';return 1;}}
