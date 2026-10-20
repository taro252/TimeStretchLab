// The real renderer, driven off line. This is not a HAL deadline or acoustic test.
// With an oracle argument, RAW comes from the separately built frozen reference.
// Without it, the test proves sequence/correction only, not DSP independence.
#include "../src/platform/macos/ProgressiveMacPlaybackEngine.mm"
#include <bit>
#include <fstream>
#include <iostream>

using namespace ts::playback;
static void require(bool value,const char* reason){if(!value)throw std::runtime_error(reason);}
template<class P> static void waitFor(P predicate){
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(120);
    while(!predicate()){require(std::chrono::steady_clock::now()<deadline,"boundary fixture timeout");std::this_thread::sleep_for(std::chrono::microseconds(100));}
}
static bool same(float a,float b)noexcept{return std::bit_cast<std::uint32_t>(a)==std::bit_cast<std::uint32_t>(b);}
struct SeekCase {std::string label;std::size_t input=0,output=0,requestedR=0;};
struct Reference {
    unsigned speed=1000000,loopMillis=100;bool candidate=true,independent=false,minimumPeriod=false;
    std::size_t a=17,b=0,oa=0,ob=0,channels=0,rate=0,oldNearInput=0,oldNearOutput=0;
    std::vector<float> raw;std::vector<SeekCase> cases;
};
static Reference reference(const char* path,unsigned speed,bool candidate,const char* oracle=nullptr,std::size_t expectedA=0,std::size_t expectedB=0,unsigned loopMillis=100,bool includeOldNear=false,bool minimumPeriod=false){
    ts::prototype::phase58::Configuration config;config.speedMicros=speed;config.candidate=candidate;config.residentInput=true;config.verifyPcm=false;
    auto source=std::make_unique<Pipeline>(path,config);source->start();require(source->waitUntilReady(std::chrono::seconds(120)),"reference source Ready");
    waitFor([&]{return source->finalAnalysisAvailable();});
    Reference result;result.speed=speed;result.candidate=candidate;result.loopMillis=loopMillis;result.rate=source->sampleRate();result.channels=source->channels();
    require(loopMillis>=100&&loopMillis<=std::uint64_t(source->inputFrames())*1000/result.rate,"loop_ms is >=100 and must fit in the input");
    result.b=result.a+std::uint64_t(result.rate)*loopMillis/1000;
    require(result.b<=source->inputFrames(),"input must contain A=17 plus loop_ms");
    result.oa=source->fixedOutputFrameForInput(result.a);result.ob=source->fixedOutputFrameForInput(result.b);
    if(minimumPeriod){
        const auto target=result.oa+512;std::size_t low=result.a,high=result.b;
        while(low<high){const auto middle=low+(high-low)/2;if(source->fixedOutputFrameForInput(middle)<target)low=middle+1;else high=middle;}
        require(low<result.b&&source->fixedOutputFrameForInput(low)==target,"512-output-frame period not representable by this Map");
        result.b=low;result.ob=target;result.minimumPeriod=true;result.loopMillis=0; // internal fixture, below public 100ms admission
    }
    const auto n=result.rate/200;
    auto mapped=[&](std::size_t input){return source->fixedOutputFrameForInput(input);};
    auto locate=[&](std::size_t remaining,const char* label){
        const auto target=result.ob-remaining;std::size_t low=result.a,high=result.b;
        while(low<high){const auto middle=low+(high-low)/2;if(mapped(middle)<target)low=middle+1;else high=middle;}
        if(low<result.b&&mapped(low)==target){result.cases.push_back({label,low,target,remaining});return;}
        std::cout<<"{\"case\":\""<<label<<"\",\"requested_R\":"<<remaining<<",\"status\":\"NOT_REPRESENTABLE_BY_INTEGER_INPUT\",\"speed\":"<<speed<<"}\n";
        // A stretched Map can skip an output coordinate. Test both realizable
        // neighbours instead of pretending an input frame is an output frame.
        if(low>result.a)result.cases.push_back({std::string(label)+"_below_input",low-1,mapped(low-1),remaining});
        if(low<result.b)result.cases.push_back({std::string(label)+"_above_input",low,mapped(low),remaining});
    };
    locate(0,"R0");locate(n-1,"R_N_minus_1");locate(n,"R_N");locate(n+1,"R_N_plus_1");
    result.cases.push_back({"B_minus_1",result.b-1,mapped(result.b-1),0});
    result.cases.push_back({"A",result.a,result.oa,0});
    result.cases.push_back({"midpoint",result.a+(result.b-result.a)/2,mapped(result.a+(result.b-result.a)/2),0});
    if(minimumPeriod){locate(1,"phase_first");locate(511,"phase_last");locate(32,"phase_middle_64");locate(64,"phase_middle_128");locate(256,"phase_middle_512");}
    // The optional old-source fixture crosses B strictly inside the entry
    // window. It chooses an integer input by the Map, not by subtracting N
    // input samples from B.
    if(includeOldNear){
        const auto oldTarget=result.ob-n/2;std::size_t low=result.a,high=result.b;
        while(low<high){const auto middle=low+(high-low)/2;if(mapped(middle)<oldTarget)low=middle+1;else high=middle;}
        result.oldNearInput=low;result.oldNearOutput=mapped(low);
        require(low<result.b&&result.oldNearOutput<result.ob&&result.ob-result.oldNearOutput<n,"cannot represent an old-source 0<R<N fixture");
    }
    auto finite=source->createLoopSeek(result.a,result.b,speed);source->stop();source.reset();
    finite->start();require(finite->waitUntilReady(std::chrono::seconds(120)),"finite reference Ready");
    require(finite->outputStartFrame()==result.oa&&finite->loopOutputEndFrame()==result.ob,"finite reference Map");
    const auto length=result.ob-result.oa;require(length>=512,"full period must remain >=512");result.raw.resize(length*result.channels);
    std::array<std::array<float,4096>,2> pcm{};float* pointers[]{pcm[0].data(),pcm[1].data()};std::size_t offset=0;
    while(offset<length){const auto count=std::min<std::size_t>(4096,length-offset);waitFor([&]{return finite->available()>=count;});const auto pulled=finite->pullAudio(pointers,count);require(pulled.received==count&&pulled.outputBefore==result.oa+offset,"finite reference span");
        for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<result.channels;++c)result.raw[(offset+i)*result.channels+c]=pointers[c][i];offset+=count;}
    finite->stop();finite.reset();
    if(oracle){require(result.oa==expectedA&&result.ob==expectedB,"frozen oracle Map coordinates");std::ifstream file(oracle,std::ios::binary);file.seekg(result.oa*result.channels*sizeof(float));std::vector<float> expected(result.raw.size());
        require(bool(file.read(reinterpret_cast<char*>(expected.data()),expected.size()*sizeof(float))),"frozen oracle RAW read");
        require(std::memcmp(result.raw.data(),expected.data(),expected.size()*sizeof(float))==0,"finite RAW differs from independent oracle");result.raw=std::move(expected);result.independent=true;}
    for(float sample:result.raw)require(std::isfinite(sample),"nonfinite reference RAW");return result;
}
struct Audit {
    const Reference& ref;std::size_t initial=0,remaining=0,n=0,oldInitial=0,oldRemaining=0;
    std::size_t freshFrames=0,oldFrames=0,oldObservedBs=0,outputFrames=0,rawErrors=0,outputErrors=0,spanErrors=0,nonfinite=0,spans=0;
    explicit Audit(const Reference& r,std::size_t c,std::size_t old):ref(r),initial(c==r.ob?r.oa:c),remaining(r.ob-c),n(r.rate/200),oldInitial(old==r.ob?r.oa:old),oldRemaining(r.ob-old){}
    std::size_t length()const noexcept{return ref.ob-ref.oa;}
    std::size_t offset(std::size_t frame,bool old=false)const noexcept{return ((old?oldInitial:initial)-ref.oa+frame)%length();}
    float rawAt(std::size_t frame,std::size_t channel,bool old=false)const noexcept{return ref.raw[offset(frame,old)*ref.channels+channel];}
    float corrected(std::size_t frame,std::size_t channel,bool old=false)const noexcept{
        // Independent formula, deliberately not PeriodBoundary::head/tail.
        const auto at=offset(frame,old),window=std::min(n,length()/4);auto value=rawAt(frame,channel,old);
        const auto last=ref.raw[(length()-1)*ref.channels+channel],first=ref.raw[channel];
        if(at>=length()-window){const auto j=at-(length()-window);if(j+1==window)return last*.5f+first*.5f;const float t=float(j+1)/float(window);return value-(last-first)*.5f*(t*t*(3.f-2.f*t));}
        const auto firstRemaining=old?oldRemaining:remaining;const bool previous=firstRemaining?frame>=firstRemaining:frame>=length();
        if(previous&&at<window){if(!at)return last*.5f+first*.5f;const float t=1.f-float(at)/float(window);value+=(last-first)*.5f*(t*t*(3.f-2.f*t));}
        return value;
    }
    static void source(void* pointer,const float*const* pcm,std::size_t count,std::size_t at,std::uint64_t,std::uint64_t,std::uint64_t session)noexcept{
        auto& audit=*static_cast<Audit*>(pointer);const bool old=session==11;auto& consumed=old?audit.oldFrames:audit.freshFrames;
        const auto expectedAt=audit.ref.oa+audit.offset(consumed,old);if(at!=expectedAt)++audit.rawErrors;
        // Every observed source span must end at or before B. A FIFO can hold
        // multiple cycles, but one observation cannot conceal the wrap.
        if(at+count>audit.ref.ob)++audit.spanErrors;
        for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<audit.ref.channels;++c){const auto expected=audit.rawAt(consumed+i,c,old);if(!same(pcm[c][i],expected))++audit.rawErrors;if(!std::isfinite(pcm[c][i]))++audit.nonfinite;}
        if(old&&at+count==audit.ref.ob)++audit.oldObservedBs;
        consumed+=count;
    }
    static void output(void* pointer,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& audit=*static_cast<Audit*>(pointer);if(!span.frames||span.callbackFrame!=audit.outputFrames)++audit.spanErrors;++audit.spans;
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<audit.ref.channels;++c){const auto frame=audit.outputFrames+i;auto expected=audit.corrected(frame,c);
            if(frame<audit.n){const auto gain=float(frame+1)/float(audit.n);expected=audit.corrected(frame,c,true)*(1.f-gain)+expected*gain;}
            if(!same(pcm[c][i],expected))++audit.outputErrors;if(!std::isfinite(pcm[c][i]))++audit.nonfinite;}
        audit.outputFrames+=span.frames;
    }
};
static unsigned runCase(const char* path,const Reference& reference,const SeekCase& selected,unsigned callback,bool oldNearB=false){
    ts::prototype::phase58::Configuration config;config.speedMicros=reference.speed;config.candidate=reference.candidate;config.residentInput=true;config.verifyPcm=false;
    auto source=std::make_unique<Pipeline>(path,config);source->start();require(source->waitUntilReady(std::chrono::seconds(120)),"case source Ready");waitFor([&]{return source->finalAnalysisAvailable();});
    const auto oldInput=oldNearB?reference.oldNearInput:reference.a,oldOutput=oldNearB?reference.oldNearOutput:reference.oa;
    auto old=source->createLoopSeek(oldInput,reference.b,reference.speed);source->stop();source.reset();
    // The unstarted old owner already pins the immutable input/analysis. Build
    // fresh only after retiring the source, so this fixture also has <=2 owners.
    auto fresh=old->createLoopSeek(selected.input,reference.b,reference.speed);
    old->enableLoopReuse(reference.a);fresh->enableLoopReuse(reference.a);
    old->start();fresh->start();require(old->waitUntilReady(std::chrono::seconds(120))&&fresh->waitUntilReady(std::chrono::seconds(120)),"entry pair Ready");
    require(fresh->outputStartFrame()==selected.output&&fresh->loopOutputStartFrame()==reference.oa&&fresh->loopOutputEndFrame()==reference.ob,"entry target or full period changed");
    require(old->outputStartFrame()==oldOutput,"old requested input/output changed");
    RenderTarget first,second;first.pipeline=old.get();second.pipeline=fresh.get();first.epoch=11;second.epoch=12;first.session=11;second.session=12;first.presented=oldOutput;second.presented=selected.output;
    first.loopEnd=second.loopEnd=reference.ob;first.loopID=second.loopID=73;first.loopA=second.loopA=reference.a;first.loopB=second.loopB=reference.b;
    Audit audit(reference,selected.output,oldOutput);RenderState state;state.channels=unsigned(reference.channels);state.rate=reference.rate;state.active=true;state.target=&first;state.loopRecords.resize(256);
    state.observerContext=&audit;state.epochObserver=Audit::source;state.outputObserver=Audit::output;
    auto& handoff=state.handoff;handoff.oldTarget=&first;handoff.newTarget=&second;handoff.output.prepare(unsigned(reference.rate));handoff.phase=SwitchPhase::Requested;
    std::array<std::array<float,4096>,2> pcm{};struct Buffers {UInt32 count;AudioBuffer values[2];} buffers{};buffers.count=state.channels;
    AudioTimeStamp stamp{};stamp.mFlags=kAudioTimeStampSampleTimeValid;BOOL silent=NO;
    const auto total=std::max(audit.remaining+2*audit.length()+audit.n+1,reference.minimumPeriod?std::size_t(3*4096)+audit.n+1:std::size_t(0));
    while(audit.outputFrames<total){const auto count=std::min<std::size_t>(callback,total-audit.outputFrames);
        waitFor([&]{require(!old->failed()&&!fresh->failed(),"entry worker failed");return fresh->available()>=count+512&&old->available()>=audit.n;});
        for(unsigned c=0;c<state.channels;++c)buffers.values[c]={1,UInt32(count*sizeof(float)),pcm[c].data()};
        render(&state,&silent,&stamp,static_cast<AVAudioFrameCount>(count),reinterpret_cast<AudioBufferList*>(&buffers));stamp.mSampleTime+=count;
        if(state.loopMissed){std::cerr<<"entry failure label="<<selected.label<<" input="<<selected.input<<" R="<<audit.remaining<<" N="<<audit.n<<" callback="<<callback<<" presented="<<second.presented<<" B="<<reference.ob<<" cursor="<<handoff.output.cursor<<" reason="<<int(state.loopFailure.load())<<'\n';throw std::runtime_error("entry render safety stop");}
    }
    state.active=false;old->stop();fresh->stop();
    const auto expectedCycles=audit.remaining?1+(total-audit.remaining)/audit.length():total/audit.length();
    require(audit.outputFrames==total&&audit.freshFrames==total&&audit.oldFrames==audit.n,"entry PCM ownership or length");
    require(audit.oldObservedBs==(oldNearB?1u:0u),"old source B crossing missing or counted twice");
    if(oldNearB)require(old->loopReadCycle()==1&&first.presented==reference.oa+audit.n-audit.oldRemaining,"old RAW wrap/correction did not continue from A");
    require(!audit.rawErrors&&!audit.outputErrors&&!audit.spanErrors&&!audit.nonfinite,"entry RAW/correction/span mismatch");
    require(state.loopCycles==expectedCycles&&state.boundaryWritten==expectedCycles,"initial seek or natural wrap counted incorrectly");
    unsigned phaseMask=0;require(state.boundaryWritten<=64,"boundary audit ring overflow");
    for(std::uint64_t i=0;i<state.boundaryWritten;++i){const auto event=state.boundaryRing[i%64].read();const auto position=audit.remaining?audit.remaining+i*audit.length():(i+1)*audit.length();
        require(event&&event->cycle==i+1&&event->callbackFrame==position&&event->oldOutputEnd==reference.ob&&event->newOutputStart==reference.oa&&!event->overlapFrames,"entry cumulative B coordinate");}
    for(std::uint64_t i=0;i<state.boundaryWritten;++i){const auto event=state.boundaryRing[i%64].read();const auto offset=event->callbackFrame%callback;
        if(offset==1)phaseMask|=1;if(offset==callback/2)phaseMask|=2;if(offset==callback-1)phaseMask|=4;}
    require(!state.loopSafetyFrames&&!state.oldMissing&&!state.newMissing,"entry unexpected padding/missing");
    require(!old->diagnostics().missingFrames&&!fresh->diagnostics().missingFrames,"entry FIFO underflow");
    std::cout<<"{\"case\":\""<<selected.label<<"\",\"input\":"<<selected.input<<",\"R\":"<<audit.remaining<<",\"N\":"<<audit.n<<",\"loop_ms\":"<<reference.loopMillis<<",\"old_near_B\":"<<(oldNearB?"true":"false")<<",\"old_input\":"<<oldInput<<",\"old_R\":"<<audit.oldRemaining<<",\"old_PCM_Bs\":"<<audit.oldObservedBs<<",\"callback\":"<<callback<<",\"speed\":"<<reference.speed<<",\"preset\":\""<<(reference.candidate?"candidate":"baseline")<<"\",\"frames\":"<<total<<",\"cycles\":"<<expectedCycles<<",\"independent_DSP_RAW\":"<<(reference.independent?"true":"false")<<",\"status\":\"PASS\"}\n";
    return phaseMask;
}
int main(int argc,char** argv){try{
    const bool oldNearB=argc>1&&std::string(argv[argc-1])=="--old-near-b";
    const bool minimumPeriod=argc>1+(oldNearB?1:0)&&std::string(argv[argc-1-(oldNearB?1:0)])=="--period512";
    const auto arguments=argc-(oldNearB?1:0)-(minimumPeriod?1:0);
    require(arguments==2||arguments==4||arguments==7||arguments==8,"input [speed preset [oracle.raw OA OB [loop_ms=100]]] [--period512] [--old-near-b]");
    const auto speed=arguments>=4?std::stoul(argv[2]):1000000u;const bool candidate=arguments<4||std::string(argv[3])=="candidate";
    const auto loopMillis=arguments==8?std::stoul(argv[7]):100UL;require(loopMillis<=UINT32_MAX,"loop_ms overflow");
    const bool hasOracle=arguments>=7&&std::string(argv[4])!="-";
    const auto ref=reference(argv[1],unsigned(speed),candidate,hasOracle?argv[4]:nullptr,hasOracle?std::stoull(argv[5]):0,hasOracle?std::stoull(argv[6]):0,unsigned(loopMillis),oldNearB,minimumPeriod);
    std::size_t executed=0;for(auto callback:{64u,128u,512u,4096u}){unsigned phaseMask=0;for(const auto& selected:ref.cases){phaseMask|=runCase(argv[1],ref,selected,callback);++executed;if(oldNearB){phaseMask|=runCase(argv[1],ref,selected,callback,true);++executed;}}
        if(minimumPeriod){require(phaseMask==7,"B near callback start/middle/end not observed");std::cout<<"{\"period_frames\":512,\"callback\":"<<callback<<",\"phase_mask\":"<<phaseMask<<",\"status\":\"PHASE_COVERAGE_PASS\"}\n";}}
    const auto baseCases=4*ref.cases.size(),oldCases=oldNearB?baseCases:0;
    std::cout<<"{\"suite\":\"phase62_dynamic_boundary\",\"expected\":"<<baseCases+oldCases<<",\"executed\":"<<executed<<",\"base_cases\":"<<baseCases<<",\"old_near_B_cases\":"<<oldCases<<",\"loop_ms\":"<<ref.loopMillis<<",\"status\":\"PASS\",\"realtime\":false,\"callback_allocation_probe\":\"NOT_RUN\",\"independent_DSP_RAW\":"<<(ref.independent?"true":"false")<<"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
