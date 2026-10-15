#include "prototype/Phase56ProgressiveAnalysis.h"
#include "prototype/Phase56PinnedWav.h"
#include "audio/WavWriter.h"
#include <cmath>
#include <filesystem>
#include <future>
#include <iostream>
#include <thread>
#include <unistd.h>
using namespace ts;using namespace ts::prototype::phase56;
void check(bool b,const char* text){if(!b)throw std::runtime_error(text);}
template<class F>void rejects(F f){bool failed=false;try{f();}catch(...){failed=true;}check(failed,"Expected rejection");}
int main(){auto dir=std::filesystem::temp_directory_path()/("phase56_"+std::to_string(getpid()));try{
    std::filesystem::create_directories(dir);
    for(auto horizon:{16u,128u,4096u,16384u}){
        IncrementalEvents events;std::size_t closed=0;
        for(std::size_t i=0;i<horizon;++i){TransientFrame f;
            if(i>=4&&i%4==0)f={.25+.5*double(i)/double(horizon+4),10,1,.02,1,false,false};
            events.push(i,f,[&](auto&){++closed;});check(closed==0,"Unbounded event chain sealed early");}
        events.finish([&](const auto& e){++closed;check(e.onsetFrame==4&&e.endFrame==horizon-4,"Chain endpoint");});check(closed==1,"Chain EOS closure");
    }
    // A provisional last maximum must never be classified before its successor.
    IncrementalDetector detector;TransientFrame f{};
    detector.push(f,true);for(int i=0;i<8;++i)detector.push({0,1,1,0,0,false,false},true);
    detector.push({.3,10,1,0,0,false,false},true);check(!detector.frames().back().detected,"Premature local maximum");
    detector.push({.8,20,10,0,0,false,false},true);check(!detector.frames()[9].detected,"Provisional decision was not overturned");detector.finish();check(detector.frames()[10].detected,"EOS maximum missing");
    {
        // The existing Phase37 map rejects a negative first compressed anchor.
        MapPrefixBuilder map;TransientEvent e{1,1,1,1,1};TransientAnchor a{1,1977,3001,55,true};
        rejects([&]{map.close(e,a);});
        std::vector<float> early(32768);early[3001]=.75f;const float* input[]={early.data()};
        ProgressiveAnalysisSession session(48000,1,91);rejects([&]{session.appendInput(91,0,input,early.size());});
        check(session.getSnapshot()->hasError&&!session.getSnapshot()->isFinal&&session.getSnapshot()->mapThroughNode==0,"Unsafe compression map was published");
    }
    std::vector<float> pcm(48000*2);for(std::size_t i=0;i<pcm.size();++i)pcm[i]=.1f*std::sin(i*.07);pcm[10001]=.8f;
    const float* p[]={pcm.data()};
    ProgressiveAnalysisSession a(48000,1,1),b(48000,1,2);
    a.appendInput(1,0,p,12000);auto held=a.getSnapshot();a.cancel();a.advanceAnalysis();
    check(a.getSnapshot()->isCancelled&&!a.getSnapshot()->isFinal,"Cancellation became EOS");
    check(!held->isCancelled&&held->inputGeneration==1,"Held snapshot mutated");
    b.appendInput(2,0,p,pcm.size());auto beforeEos=b.getSnapshot();check(!beforeEos->isFinal,"Chunk became EOS");
    b.cancel();b.finishInput(2);check(b.getSnapshot()->isCancelled&&!b.getSnapshot()->isFinal,"Near-EOS cancel");
    ProgressiveAnalysisSession committing(48000,1,21);committing.appendInput(21,0,p,pcm.size());
    committing.finishInput(21,[&]{committing.cancel();});
    check(committing.getSnapshot()->isCancelled&&!committing.getSnapshot()->isFinal,"Cancel at EOS commit became success");
    ProgressiveAnalysisSession invalid(48000,1,3);rejects([&]{invalid.appendInput(4,0,p,10);});check(invalid.getSnapshot()->hasError&&!invalid.getSnapshot()->isFinal,"Generation error state");
    ProgressiveAnalysisSession gap(48000,1,4);rejects([&]{gap.appendInput(4,1,p,10);});check(gap.getSnapshot()->hasError,"Gap not rejected");
    ProgressiveAnalysisSession nan(48000,1,5);float bad=std::numeric_limits<float>::quiet_NaN();const float* badp[]={&bad};rejects([&]{nan.appendInput(5,0,badp,1);});check(nan.getSnapshot()->hasError,"NaN not rejected");
    ProgressiveAnalysisSession oom(48000,1,6,{48000*10,16000});auto old=oom.getSnapshot();rejects([&]{oom.appendInput(6,0,p,pcm.size());});
    check(oom.getSnapshot()->hasError&&oom.getSnapshot()->error==AnalysisError::Allocation&&!old->hasError,"Allocation failure not preserved");
    {
        ProgressiveAnalysisSession budget(48000,1,61,{48000,128*1024});
        std::vector<std::shared_ptr<const AnalysisSnapshot>> retained;bool failed=false;
        for(std::size_t i=0;i<5000;++i){try{budget.appendInput(61,i,p,1);retained.push_back(budget.getSnapshot());}catch(const std::bad_alloc&){failed=true;break;}}
        check(failed&&budget.getSnapshot()->error==AnalysisError::Allocation,"Retained snapshots bypassed memory budget");
        check(!retained.front()->hasError&&retained.front()->receivedInputFrames==1,"Retained metadata mutated on failure");
        check(budget.statistics().snapshotPeakBytes<=128*1024,"Snapshot budget exceeded");
    }
    ProgressiveAnalysisSession final(48000,1,7);final.appendInput(7,0,p,17);final.finishInput(7);final.cancel();check(final.getSnapshot()->isFinal&&!final.getSnapshot()->isCancelled,"Cancel after completed EOS");rejects([&]{final.appendInput(7,17,p,1);});check(final.getSnapshot()->isFinal,"Post-EOS misuse changed completion");
    // Producer plus simultaneous snapshot readers, two independent requests.
    ProgressiveAnalysisSession shared(48000,1,8);std::atomic<bool> done{false};
    auto producer=std::async(std::launch::async,[&]{try{for(std::size_t i=0;i<pcm.size();i+=317){const float* chunk[]={pcm.data()+i};shared.appendInput(8,i,chunk,std::min<std::size_t>(317,pcm.size()-i));}shared.finishInput(8);done=true;}catch(...){done=true;throw;}});
    std::size_t last=0;while(!done.load()){auto s=shared.getSnapshot();check(s->inputGeneration==8&&s->receivedInputFrames>=last,"Concurrent snapshot publication");last=s->receivedInputFrames;}
    producer.get();check(shared.getSnapshot()->isFinal,"Concurrent completion");
    {
        ProgressiveAnalysisSession stopping(48000,1,81);std::atomic<bool> completed{false};
        auto worker=std::async(std::launch::async,[&]{try{for(std::size_t i=0;i<pcm.size();i+=1024){const float* chunk[]={pcm.data()+i};stopping.appendInput(81,i,chunk,std::min<std::size_t>(1024,pcm.size()-i));if(stopping.getSnapshot()->isCancelled)break;}completed=true;}catch(...){completed=true;throw;}});
        while(stopping.getSnapshot()->featureThrough<4&&!completed.load())std::this_thread::yield();
        stopping.cancel();worker.get();if(!stopping.getSnapshot()->isCancelled)stopping.advanceAnalysis();
        check(stopping.getSnapshot()->isCancelled&&!stopping.getSnapshot()->isFinal,"Async cancellation during analysis");
    }
    AudioBuffer audio;audio.sampleRate=48000;audio.channels={pcm};auto file=dir/"source.wav";WavWriter::write(file,audio);
    {
        PinnedWavSource one(file,10),two(file,11);ProgressiveAnalysisSession x(one.rate(),one.channels(),10),y(two.rate(),two.channels(),11);
        auto first=std::async(std::launch::async,[&]{while(one.appendNext(x,5003)){}one.finish(x);});
        auto second=std::async(std::launch::async,[&]{while(two.appendNext(y,7168)){}two.finish(y);});first.get();second.get();
        check(x.getSnapshot()->detectorThrough==y.getSnapshot()->detectorThrough,"Concurrent source readers differ");
        for(std::size_t i=0;i<x.getSnapshot()->mapThroughNode;++i)for(unsigned s=0;s<x.getSnapshot()->speedCount;++s)check(x.getSnapshot()->maps[s].at(i)==y.getSnapshot()->maps[s].at(i),"Shared source map differs");
    }
    {PinnedWavSource source(file,12);ProgressiveAnalysisSession x(48000,1,12);source.appendNext(x,8192);auto replaced=dir/"new.wav";WavWriter::write(replaced,audio);std::filesystem::rename(replaced,file);rejects([&]{source.appendNext(x,8192);});check(x.getSnapshot()->hasError&&!x.getSnapshot()->isFinal,"Replacement accepted as EOS");}
    {PinnedWavSource source(file,121);ProgressiveAnalysisSession x(48000,1,121);x.cancel();rejects([&]{source.appendNext(x,8192);});check(x.getSnapshot()->isCancelled&&!x.getSnapshot()->isFinal,"File adapter cancellation became successful input");}
    {PinnedWavSource source(file,13);ProgressiveAnalysisSession x(48000,1,13);source.appendNext(x,8192);source.injectReadFailureForTest();rejects([&]{source.appendNext(x,8192);});check(x.getSnapshot()->error==AnalysisError::InputRead,"Read failure unreported");}
    {PinnedWavSource source(file,131);ProgressiveAnalysisSession x(48000,1,131);source.appendNext(x,8192);std::filesystem::permissions(file,std::filesystem::perms::none);rejects([&]{source.appendNext(x,8192);});std::filesystem::permissions(file,std::filesystem::perms::owner_read|std::filesystem::perms::owner_write);check(x.getSnapshot()->hasError&&!x.getSnapshot()->isFinal,"Permission loss became normal EOS");}
    {PinnedWavSource source(file,14);ProgressiveAnalysisSession x(48000,1,14);source.appendNext(x,8192);std::filesystem::resize_file(file,44);rejects([&]{source.appendNext(x,8192);});check(x.getSnapshot()->hasError,"Truncation accepted");}
    std::filesystem::remove_all(dir);std::cout<<"Phase56 detector/event chains 16/128/4096/16384, immutable/concurrent snapshots, cancellation, generations, OOM, pinned files PASS\n";return 0;
}catch(const std::exception& e){std::filesystem::remove_all(dir);std::cerr<<e.what()<<'\n';return 1;}}
