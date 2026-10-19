#include "prototype/Phase58RealtimePipeline.h"
#include <iostream>
using namespace ts::prototype::phase58;
static void check(bool b,const char* why){if(!b)throw std::runtime_error(why);}
template<class F> void wait(F f){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(30);while(!f()){check(std::chrono::steady_clock::now()<end,"pipeline wait timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
int main(int argc,char** argv){try{
    check(argc==2,"input.wav required");
    for(bool candidate:{true,false}){
        Configuration c;c.speedMicros=1000000;c.candidate=candidate;c.residentInput=true;c.dynamicTransitions=true;c.verifyPcm=false;c.scheduling=WorkerScheduling::AudioWorkgroup;
        c.analysisChunk=4096;c.analysisDelayMs=5;
        RealtimePipeline source(argv[1],c);source.start();check(source.waitUntilReady(std::chrono::seconds(30)),"source Ready");
        check(!source.finalAnalysisAvailable(),"early analysis fixture already complete");
        const auto frozen=source.diagnostics().consumed;wait([&]{return source.stoppedPosition().has_value();});
        const auto position=source.stoppedPosition();check(position->output==frozen&&position->input==0,"Ready capture");
        const auto begin=std::chrono::steady_clock::now();auto next=source.createSeek(position->input,750000);next->start();
        check(next->waitUntilReady(std::chrono::seconds(30)),"early analysis rebuild deadlocked behind full source FIFO");
        check(source.diagnostics().consumed==frozen&&source.available()>=12288,"source FIFO advanced or emptied");
        check(next->diagnostics().consumed==next->outputStartFrame()&&next->diagnostics().reusedAnalysis,"next consumed/reanalysis");
        next->stop();
        // Finished synthesis may still have valid tail PCM; requestSpeed rejects
        // this old epoch, while stopped preparation must use a fresh epoch.
        auto tail=source.createSeek(source.inputFrames()-13,1000000);tail->start();check(tail->waitUntilReady(std::chrono::seconds(30)),"tail Ready");wait([&]{return tail->finished();});
        check(tail->available()==13&&tail->requestSpeed(750000,tail->outputStartFrame()).result==ts::prototype::Phase39RequestResult::Stopped,"dspDone tail precondition");
        auto sample=tail->stoppedPosition();wait([&]{sample=tail->stoppedPosition();return sample.has_value();});check(sample->input==source.inputFrames()-13,"unconsumed exact target rounded");
        auto changed=tail->createSeek(sample->input,1250000);changed->start();check(changed->waitUntilReady(std::chrono::seconds(30)),"dspDone rebuild");check(tail->available()==13&&changed->diagnostics().consumed==changed->outputStartFrame(),"tail preparation consumed");changed->stop();tail->stop();
        auto eof=source.createSeek(source.inputFrames(),400000);eof->start();check(eof->waitUntilReady(std::chrono::seconds(30))&&eof->finished()&&!eof->available(),"empty EOF not Ready");
        wait([&]{return eof->stoppedPosition().has_value();});check(eof->stoppedPosition()->input==source.inputFrames(),"EOF position");eof->stop();
        for(unsigned i=0;i<8;++i){auto cancelled=source.createSeek(source.inputFrames()/2,400000+i*10000);cancelled->start();cancelled->stop();check(cancelled->diagnostics().finalDataAvailable,"cancel join not finalized");}
        source.stop();check(source.diagnostics().finalDataAvailable,"source not joined");
        std::cout<<"PASS candidate="<<candidate<<" early-analysis/full-FIFO/dspDone-tail/EOF/cancel-x8 preparation_ms="<<std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count()<<'\n';
    }
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
