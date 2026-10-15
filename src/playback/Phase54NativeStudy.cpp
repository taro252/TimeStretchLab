#include "platform/macos/MacPlaybackEngine.h"
#include "playback/Phase54ReferenceCheck.h"
#include "prototype/Phase47EvidenceFile.h"
#include <fstream>
#include <iostream>
#include <iomanip>
#include <cmath>
#include <sys/resource.h>
using namespace ts;using namespace ts::playback;using namespace ts::playback::verification;
thread_local bool inCallback=false;std::atomic<std::uint64_t> allocations{0};
void* operator new(std::size_t n){if(inCallback)++allocations;if(auto p=std::malloc(n?n:1))return p;throw std::bad_alloc();}void* operator new[](std::size_t n){return ::operator new(n);}void operator delete(void*p)noexcept{std::free(p);}void operator delete[](void*p)noexcept{std::free(p);}
void enter()noexcept{inCallback=true;}void leave()noexcept{inCallback=false;}std::uint64_t count()noexcept{return allocations.load();}
using Clock=std::chrono::steady_clock;
int main(int argc,char**argv){try{if(argc<7)throw std::invalid_argument("input preset speed output mode fade [silent]");
 auto input=std::filesystem::path(argv[1]),out=std::filesystem::path(argv[4]);if(std::filesystem::exists(out))throw std::runtime_error("Fresh output required");std::filesystem::create_directories(out);
 auto preset=std::string(argv[2])=="candidate"?Preset::Candidate:Preset::Baseline;auto speed=std::stod(argv[3]);const std::string mode=argv[5];const auto fade=std::stoul(argv[6]);bool silent=argc>7;WavStreamReader metadata(input);
 MacPlaybackEngine e;auto cfg=preset==Preset::Candidate?Configuration::candidate(speed):Configuration::baseline(speed);cfg.verifyRawPcm=true;
 MacOptions options;options.playbackGain=silent?0:.5f;options.recordCallbacks=true;options.allocationHooks={enter,leave,count};options.seekFadeFrames=fade;
 StageClock prepare;if(!e.prepare(input,cfg,options))throw std::runtime_error("prepare: "+e.getPlaybackDiagnostics().error+e.getNativeDiagnostics().error);auto prepareTime=prepare.elapsed();
 StageClock play;if(!e.play())throw std::runtime_error("play");auto playTime=play.elapsed();auto begin=Clock::now();
 struct Saved {Diagnostics core;MacDiagnostics native;std::vector<MacCallbackRecord> callbacks;double initial;std::vector<prototype::Phase39PlanMetric> plans;std::string hash;};std::vector<Saved> graphs;
 const auto capture=[&](double initial){graphs.push_back({e.getPlaybackDiagnostics(),e.getNativeDiagnostics(),e.callbackRecords(),initial,e.plans(),e.rawPcmSha()});};
 prototype::Phase47EvidenceFile actions(out/"actions.csv");auto& action=actions.stream();action<<"elapsed_s,operation,id,state\n";
 std::vector<std::pair<double,std::string>> schedule;
 if(mode=="smoke")schedule={{.5,"seek6"},{.6,"seek2"},{.7,"seek4"},{1.5,"pause"},{1.6,"seeknear"},{1.8,"resume"},{2.2,"speed2"},{3.,"seek2"},{4.,"stop"},{4.15,"play"}};
 else if(mode=="long")schedule={{1.,"middle"}};
 else if(mode=="route")schedule={{.5,"late"},{.52,"route"}};
 else if(mode!="eos")throw std::invalid_argument("mode");
 std::size_t index=0;double currentInitial=speed;bool timedOut=false;
 while(true){auto elapsed=std::chrono::duration<double>(Clock::now()-begin).count();auto seek=e.getSeekSnapshot();if(seek.status==SeekStatus::Completed)currentInitial=seek.initialSpeed;
  while(index<schedule.size()&&elapsed>=schedule[index].first){auto op=schedule[index++].second;std::uint64_t id=0;bool ok=true;
   if(op=="seeknear")id=e.seekToInputSeconds(.1);else if(op=="seek6")id=e.seekToInputSeconds(6);else if(op=="seek2")id=e.seekToInputSeconds(2);else if(op=="seek4")id=e.seekToInputSeconds(4);else if(op=="seek5")id=e.seekToInputSeconds(5);
   else if(op=="middle")id=e.seekToInputFrame(metadata.frames()/2);else if(op=="late")id=e.seekToInputFrame(metadata.frames()*9/10);
   else if(op=="pause")ok=e.pause();else if(op=="resume")ok=e.resume();else if(op=="speed2")id=e.setSpeed(2);else if(op=="route")e.simulateDeviceChangeForTest();
   else if(op=="stop"){e.stop();capture(currentInitial);}else if(op=="play"){currentInitial=e.getRequestedSpeed();ok=e.play();}
   if(!ok)throw std::runtime_error("action failed: "+op);action<<elapsed<<','<<op<<','<<id<<','<<name(e.getPlaybackState())<<'\n';
  }
  auto state=e.getPlaybackState();if(state==PlaybackState::Failed)break;if(state==PlaybackState::Ended)break;if(mode=="route"&&state==PlaybackState::Stopped)break;
  if(elapsed>metadata.frames()/double(metadata.sampleRate())/speed*4+30){timedOut=true;break;}std::this_thread::sleep_for(std::chrono::milliseconds(1));
 }
 const auto ended=e.getPlaybackState()==PlaybackState::Ended;const auto route=e.getPlaybackDiagnostics().reason==StopReason::RouteChanged;
 if(!ended&&!route)e.stop();capture(currentInitial);actions.commit();auto nativeEnd=graphs.back().native;auto coreEnd=graphs.back().core;
 rusage usage{};getrusage(RUSAGE_SELF,&usage);auto playbackRss=usage.ru_maxrss;auto playbackCpu=usage.ru_utime.tv_sec+usage.ru_utime.tv_usec*1e-6+usage.ru_stime.tv_sec+usage.ru_stime.tv_usec*1e-6;
 bool audio=!timedOut&&index==schedule.size()&&(ended||mode=="route"&&route),measure=true,pcm=true;
 if(ended)audio&=coreEnd.consumedFrames==coreEnd.outputLength;
 std::size_t callbackRows=0;std::uint64_t missing=0;double callbackMax=0;
 for(std::size_t i=0;i<graphs.size();++i){auto& g=graphs[i];prototype::Phase47EvidenceFile csv(out/("callbacks_"+std::to_string(i)+".csv"));auto& s=csv.stream();s<<"sequence,epoch,session,start_ns,end_ns,host_ns,sample_time,flags,requested,wanted,received,output,fifo\n";
  for(auto&r:g.callbacks){s<<std::setprecision(17)<<r.sequence<<','<<r.epoch<<','<<r.raw.session<<','<<r.startNs<<','<<r.endNs<<','<<r.hostNs<<','<<r.sampleTime<<','<<r.timestampFlags<<','<<r.requested<<','<<r.raw.wanted<<','<<r.raw.received<<','<<r.raw.outputBefore<<','<<r.raw.fifoBefore<<'\n';missing+=r.raw.wanted-r.raw.received;}
  csv.commit();callbackRows+=g.callbacks.size();auto& n=g.native;callbackMax=std::max(callbackMax,double(n.maxCallbackNs)*1e-6);
  audio&=!g.core.lifetimeMissingFrames&&!g.core.rejectedWrites&&!g.core.concurrentRenders&&g.core.error.empty()&&!n.deadlineMisses&&!n.formatErrors&&!n.callbackCppAllocations;
  measure&=n.allocationMeasured&&!n.hostMissing&&!n.hostBackwards&&!n.hostCadenceErrors&&!n.sampleErrors&&!n.halWindowMisses&&!n.callbackRecordsDropped&&n.error.empty()&&g.callbacks.size()==n.callbackCalls;
  pcm&=referenceHash(input,g.initial,preset,g.plans,g.core.outputStartFrame,g.core.producedFrames)==g.hash;
 }
 for(auto& segment:e.closedSegmentEvidence()){pcm&=referenceHash(input,segment.initialSpeed,segment.preset,segment.plans,segment.outputStart,segment.publishedEnd)==segment.rawPcmSha256;audio&=segment.workerError.empty()&&!segment.missingFrames;}
 auto seeks=e.seekHistory();prototype::Phase47EvidenceFile seeksFile(out/"seeks.csv");auto& ss=seeksFile.stream();ss<<"id,session,input,output,speed,status,observed_ns,ready_ns,replans\n";
 for(auto& s:seeks){measure&=s.observedNs>0&&s.readyNs>=s.observedNs;ss<<s.id<<','<<s.session<<','<<s.requestedInputFrame<<','<<s.outputFrame<<','<<s.initialSpeed<<','<<name(s.status)<<','<<s.observedNs<<','<<s.readyNs<<','<<s.replans<<'\n';audio&=s.status==SeekStatus::Completed||s.status==SeekStatus::Replaced||s.status==SeekStatus::Cancelled;}
 seeksFile.commit();auto startup=e.getStartupDiagnostics();prototype::Phase47EvidenceFile result(out/"summary.txt");auto& r=result.stream();r<<std::setprecision(17)
 <<"AUDIO_QUALITY="<<(audio?"PASS":"FAIL")<<"\nMEASUREMENT_QUALITY="<<(measure?"PASS":"FAIL")<<"\nPCM_CORRECTNESS="<<(pcm?"PASS":"FAIL")<<"\nVERDICT="<<(audio&&measure&&pcm?"PASS":"FAIL")
 <<"\nmode="<<mode<<"\nsource_rate="<<metadata.sampleRate()<<"\nchannels="<<metadata.channels()<<"\ndevice="<<nativeEnd.deviceId<<"\ndevice_rate="<<nativeEnd.deviceRate<<"\ndevice_buffer="<<nativeEnd.deviceBufferFrames
 <<"\nprepare_wall_s="<<prepareTime.wallSeconds<<"\nprepare_thread_cpu_s="<<prepareTime.threadCpuSeconds<<"\nplay_wall_s="<<playTime.wallSeconds<<"\nplay_thread_cpu_s="<<playTime.threadCpuSeconds
 <<"\nmissing_frames="<<missing<<"\nlifetime_missing_frames="<<coreEnd.lifetimeMissingFrames<<"\ncallback_rows="<<callbackRows<<"\ncallback_max_ms="<<callbackMax
 <<"\ncallback_overruns="<<nativeEnd.deadlineMisses<<"\ncallback_allocations="<<count()<<"\nworker_max_wall_s="<<coreEnd.maxWorkerWallSeconds<<"\nworker_max_cpu_s="<<coreEnd.maxWorkerCpuSeconds
 <<"\nanalysis_hit="<<startup.analysisHit<<"\nanalysis_runs="<<startup.analysisRuns<<"\ncache_hits="<<startup.cacheHits<<"\nanalysis_bytes="<<startup.analysisBytes<<"\ncache_resident_bytes="<<startup.cacheResidentBytes
 <<"\nplayback_rss_bytes="<<playbackRss<<"\nplayback_process_cpu_s="<<playbackCpu<<"\neos="<<ended<<"\nroute="<<route<<"\nsilent="<<silent<<"\nfade="<<fade<<"\nseek_count="<<seeks.size()<<"\nexpected_frames="<<coreEnd.outputLength<<"\nconsumed_frames="<<coreEnd.consumedFrames<<'\n';result.commit();
 std::cout<<(audio&&measure&&pcm?"PASS":"FAIL")<<" missing="<<missing<<" PCM="<<pcm<<" measurement="<<measure<<'\n';return audio&&measure&&pcm?0:2;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
