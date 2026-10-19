#include "../src/platform/macos/ProgressiveMacPlaybackEngine.mm"
#include <bit>
#include <fstream>
#include <iostream>
using namespace ts::playback;
static void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
template<class P> static void waitFor(P predicate){const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(120);while(!predicate()){check(std::chrono::steady_clock::now()<limit,"PCM/descriptor timeout");std::this_thread::sleep_for(std::chrono::microseconds(100));}}
struct PeriodAudit {
    std::vector<float> expected,raw,processed;
    std::size_t channels=0,start=0,length=0,n=0,rawFrames=0,frames=0,errors=0;
    // Independent formula over oracle samples; does not read correction values
    // reported by the engine and does not call its boundary implementation.
    float expectedAt(std::size_t frame,std::size_t channel)const noexcept{
        const auto cycle=frame/length,at=frame%length;
        auto value=expected[at*channels+channel];const auto last=expected[(length-1)*channels+channel],first=expected[channel];
        if(at>=length-n){const auto j=at-(length-n);if(j+1==n)return last*.5f+first*.5f;const auto t=float(j+1)/float(n);const auto w=t*t*(3.f-2.f*t);return value-(last-first)*.5f*w;}
        if(cycle&&at<n){if(!at)return last*.5f+first*.5f;const auto t=1.f-float(at)/float(n);const auto w=t*t*(3.f-2.f*t);return value+(last-first)*.5f*w;}
        return value;
    }
    static void source(void* pointer,const float*const* pcm,std::size_t count,std::size_t at,std::uint64_t,std::uint64_t,std::uint64_t)noexcept{
        auto& a=*static_cast<PeriodAudit*>(pointer);if(at!=a.start+a.rawFrames%a.length||a.rawFrames+count>a.raw.size()/a.channels){++a.errors;return;}
        for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<a.channels;++c){const auto value=pcm[c][i],expected=a.expected[((a.rawFrames+i)%a.length)*a.channels+c];if(!std::isfinite(value)||std::bit_cast<std::uint32_t>(value)!=std::bit_cast<std::uint32_t>(expected))++a.errors;a.raw[(a.rawFrames+i)*a.channels+c]=value;}
        a.rawFrames+=count;
    }
    static void output(void* pointer,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& a=*static_cast<PeriodAudit*>(pointer);if(span.callbackFrame!=a.frames||a.frames+span.frames>a.processed.size()/a.channels){++a.errors;return;}
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<a.channels;++c){const auto value=pcm[c][i],expected=a.expectedAt(a.frames+i,c);if(!std::isfinite(value)||std::bit_cast<std::uint32_t>(value)!=std::bit_cast<std::uint32_t>(expected))++a.errors;a.processed[(a.frames+i)*a.channels+c]=value;}
        a.frames+=span.frames;
    }
};
static void run(const char* path,unsigned speed,bool candidate,unsigned callback,std::size_t a,std::size_t b,unsigned cycles,const char* oracle=nullptr,std::size_t oa=0,std::size_t ob=0,const char* output=nullptr){
    ts::prototype::phase58::Configuration c;c.speedMicros=speed;c.candidate=candidate;c.residentInput=true;c.verifyPcm=false;
    Pipeline base(path,c);base.start();check(base.waitUntilReady(std::chrono::seconds(120)),"base Ready");waitFor([&]{return base.finalAnalysisAvailable();});
    auto reference=base.createLoopSeek(a,b,speed);auto repeating=base.createLoopSeek(a,b,speed);repeating->enableLoopReuse(a);base.stop();
    reference->start();check(reference->waitUntilReady(std::chrono::seconds(120)),"reference Ready");const auto begin=reference->outputStartFrame(),end=reference->loopOutputEndFrame(),length=end-begin;
    PeriodAudit audit;audit.channels=reference->channels();audit.start=begin;audit.length=length;audit.n=std::min<std::size_t>(reference->sampleRate()/200,length/4);audit.expected.resize(length*audit.channels);
    std::array<std::array<float,4096>,2> pcm{};float* ptr[]{pcm[0].data(),pcm[1].data()};std::size_t at=0;
    while(at<length){const auto count=std::min<std::size_t>(4096,length-at);waitFor([&]{return reference->available()>=count;});auto r=reference->pullAudio(ptr,count);check(r.received==count,"reference FIFO");for(std::size_t i=0;i<count;++i)for(std::size_t j=0;j<audit.channels;++j)audit.expected[(at+i)*audit.channels+j]=ptr[j][i];at+=count;}
    reference->stop();reference.reset();
    if(oracle){check(begin==oa&&end==ob,"independent map coordinates");std::ifstream f(oracle,std::ios::binary);f.seekg(begin*audit.channels*sizeof(float));std::vector<float> raw(audit.expected.size());f.read(reinterpret_cast<char*>(raw.data()),raw.size()*sizeof(float));check(bool(f)&&std::memcmp(raw.data(),audit.expected.data(),raw.size()*sizeof(float))==0,"independent fixed RAW");audit.expected=std::move(raw);}
    audit.raw.resize(length*cycles*audit.channels);audit.processed.resize(audit.raw.size());
    repeating->start();check(repeating->waitUntilReady(std::chrono::seconds(120)),"repeat Ready");
    RenderTarget target;target.pipeline=repeating.get();target.epoch=11;target.presented=begin;target.loopEnd=end;target.loopID=73;target.loopA=a;target.loopB=b;
    RenderState state;state.target=&target;state.rate=repeating->sampleRate();state.channels=unsigned(audit.channels);state.active=true;state.localEpoch=11;state.observerContext=&audit;state.epochObserver=PeriodAudit::source;state.outputObserver=PeriodAudit::output;state.loopRecords.resize(256);
    struct Buffers {UInt32 count;AudioBuffer buffers[2];} buffers{};buffers.count=state.channels;AudioTimeStamp stamp{};stamp.mFlags=kAudioTimeStampSampleTimeValid;BOOL silent=NO;
    const auto total=length*cycles;
    while(audit.frames<total){const auto count=std::min<std::size_t>(callback,total-audit.frames);waitFor([&]{check(!repeating->failed(),"reused worker failure");return repeating->available()>=count+512;});
        for(unsigned ch=0;ch<state.channels;++ch)buffers.buffers[ch]={1,UInt32(count*sizeof(float)),pcm[ch].data()};
        render(&state,&silent,&stamp,static_cast<AVAudioFrameCount>(count),reinterpret_cast<AudioBufferList*>(&buffers));stamp.mSampleTime+=count;check(!state.loopMissed,"actual callback missed");
    }
    state.active=false;repeating->stop();check(!audit.errors&&audit.rawFrames==total&&state.callbackFrame==total&&state.loopCycles==cycles,"RAW/correction/period drift");
    const auto written=state.boundaryWritten.load();check(written==cycles,"boundary event count");
    for(std::uint64_t index=written>64?written-64:0;index<written;++index){auto event=state.boundaryRing[index%64].read();check(event&&event->cycle==index+1&&event->callbackFrame==(index+1)*length&&!event->overlapFrames,"Sigma L or ring event");}
    const auto d=repeating->diagnostics();check(d.finalDataAvailable&&!d.missingFrames&&d.loopReuse.mapBuilds==1&&d.loopReuse.workerCreations==2,"bounded ownership/reuse");
    if(output){const std::filesystem::path out=output;check(std::filesystem::create_directories(out),"existing capture output");for(const auto& item:{std::pair{"raw.f32",&audit.raw},std::pair{"processed.f32",&audit.processed}}){std::ofstream f(out/item.first,std::ios::binary);f.write(reinterpret_cast<const char*>(item.second->data()),item.second->size()*sizeof(float));}
        std::ofstream f(out/"capture.json");f<<"{\"PASS\":true,\"rate\":"<<state.rate<<",\"channels\":"<<state.channels<<",\"start\":"<<begin<<",\"end\":"<<end<<",\"period_frames\":"<<length<<",\"boundary_frames\":"<<audit.n<<",\"cycles\":"<<cycles<<",\"output_frames\":"<<total<<",\"raw_bit_errors\":"<<audit.errors<<",\"map_builds\":"<<d.loopReuse.mapBuilds<<",\"workers\":"<<d.loopReuse.workerCreations<<",\"cache_bytes\":"<<d.loopReuse.cacheBytes<<"}\n";
    }
    std::cout<<"PASS callback="<<callback<<" speed="<<speed<<" A="<<a<<" B="<<b<<" L="<<length<<" cycles="<<cycles<<" SigmaL="<<total<<" errors="<<audit.errors<<'\n';
}
int main(int argc,char** argv){try{
    if(argc==10){run(argv[1],std::stoul(argv[2]),std::string(argv[3])=="candidate",4096,std::stoull(argv[4]),std::stoull(argv[5]),3,argv[6],std::stoull(argv[7]),std::stoull(argv[8]),argv[9]);return 0;}
    check(argc==2||argc==3,"input [--long]");ts::WavStreamReader input(argv[1]);
    if(argc==3){run(argv[1],2000000,true,4096,17,input.sampleRate()/10+17,4100);return 0;}
    for(bool candidate:{false,true})for(auto speed:{400000u,1000000u,2000000u})for(auto callback:{64u,128u,512u,4096u})run(argv[1],speed,candidate,callback,17,input.sampleRate()/10+17,5);
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
