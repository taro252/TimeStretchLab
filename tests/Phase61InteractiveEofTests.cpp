// Focused real callback test: the old FIFO is genuinely empty at the switch.
#define main phase61IncludedVerificationMain
#include "Phase61InteractiveNativeTests.cpp"
#undef main
struct EofCapture {
    OutputAudit audit;std::vector<float> post;std::size_t written=0,channels;
    EofCapture(std::size_t ch,std::size_t frames):audit(ch,frames),post(ch*frames),channels(ch){}
    static void source(void* ctx,const float*const* p,std::size_t n,std::size_t at,std::uint64_t gen,std::uint64_t epoch,std::uint64_t session)noexcept{
        auto& x=*static_cast<EofCapture*>(ctx);OutputAudit::source(&x.audit,p,n,at,gen,epoch,session);
    }
    static void output(void* ctx,const float*const* p,const ProgressiveOutputSpan& s)noexcept{
        auto& x=*static_cast<EofCapture*>(ctx);OutputAudit::output(&x.audit,p,s);
        if((x.written+s.frames)*x.channels>x.post.size()){++x.audit.errors;return;}
        for(std::size_t i=0;i<s.frames;++i)for(std::size_t c=0;c<x.channels;++c)x.post[(x.written+i)*x.channels+c]=p[c][i];x.written+=s.frames;
    }
};
int main(int argc,char** argv){if(argc!=3)return 1;int result=2;std::thread control([&]{try{
    const std::filesystem::path out=argv[2];require(std::filesystem::create_directories(out),"existing evidence");SmallDeviceBuffer buffer(true);
    ts::WavStreamReader input(argv[1]);EofCapture capture(input.channels(),input.sampleRate()*24ULL);
    ProgressiveMacPlaybackEngine e;ProgressiveOptions o;o.initialSpeed=.5;o.allowUnvalidatedFastLocalSeek=true;o.observerContext=&capture;
    o.observeEpochPcm=EofCapture::source;o.observeOutputPcm=EofCapture::output;
    o.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();callbackCounting=false;},[]()noexcept{return callbackNew;}};
    phase61_heap_reset();e.prepare(argv[1],o);wait(e,State::Ready);e.play();firstPcm(e);
    const auto end=e.requestFastLocalSeekToInputFrame(input.frames()-1);require(end.accepted,"near EOF");
    const auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(10);
    while(!capture.audit.switchObserved){require(std::chrono::steady_clock::now()<limit,"first transition");std::this_thread::sleep_for(std::chrono::microseconds(20));}
    const auto receipt=e.requestFastLocalSeekToInputFrame(input.frames()*3/5+17);require(receipt.accepted,"could not queue during first transition");
    const auto done=waitSeek(e,receipt.id);require(done.oldFifoAtSwitchFrames==0,"old FIFO was not empty");
    std::this_thread::sleep_for(std::chrono::milliseconds(35));e.stop();
    std::uint64_t oldReceived=0,mixed=0;for(std::size_t i=0;i<capture.audit.count;++i){const auto& s=capture.audit.spans[i];if(s.newEpoch==done.renderEpoch&&s.mixedFrames){oldReceived+=s.oldReceivedFrames;mixed+=s.mixedFrames;}}
    const auto d=e.getPlaybackDiagnostics();const auto n=e.getNativeDiagnostics();
    require(!oldReceived&&mixed==input.sampleRate()/200&&!capture.audit.errors&&!capture.audit.raw.errors&&!d.missingFrames,"EOF fallback / raw / mixed PCM");
    require(!phase61_heap_allocations()&&!phase61_heap_frees()&&d.callbackCppNew&&!*d.callbackCppNew,"callback allocation/release");
    for(const auto& x:e.closedEpochs()){const auto& m=x.pipeline.scheduling;require(!m.active&&m.joins==m.leaves&&m.leaves==m.restores,"retired lifetime");}
    std::ofstream raw(out/"post_transition.f32",std::ios::binary);raw.write(reinterpret_cast<const char*>(capture.post.data()),capture.written*capture.channels*sizeof(float));raw.close();
    std::ofstream history(out/"seeks.json");operations(history,e.seekHistory());
    std::ofstream summary(out/"summary.json");summary<<"{\"functional\":true,\"rate\":"<<input.sampleRate()<<",\"channels\":"<<capture.channels<<",\"old_fifo\":"<<done.oldFifoAtSwitchFrames<<",\"old_received\":"<<oldReceived<<",\"mixed_frames\":"<<mixed<<",\"post_frames\":"<<capture.written<<",\"missing\":"<<d.missingFrames<<",\"callback_new\":"<<*d.callbackCppNew<<",\"heap_calls\":"<<phase61_heap_allocations()<<",\"heap_frees\":"<<phase61_heap_frees()<<",\"callback_deadlines\":"<<n.deadlineMisses<<",\"worker_deadlines\":"<<d.workerDeadlineMisses<<"}\n";
    buffer.restore();result=0;std::cout<<"PASS genuinely empty old FIFO, no expected-EOF underrun, recorded post-mix PCM\n";
}catch(const std::exception& ex){std::cerr<<ex.what()<<'\n';}});control.join();return result;}
