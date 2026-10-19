#pragma once
#include <fstream>
// Included after the actual callback implementation by Phase62RenderTests.mm.
struct OfflineLoopCapture {
    std::size_t channels=0,start=0,end=0,oldFrames=0,newFrames=0,outputFrames=0,errors=0;
    std::vector<float> oldRaw,newRaw,mixed;
    static void source(void* context,const float*const* p,std::size_t n,std::size_t at,std::uint64_t,std::uint64_t epoch,std::uint64_t)noexcept{
        auto& a=*static_cast<OfflineLoopCapture*>(context);auto& frames=epoch==11?a.oldFrames:a.newFrames;auto& output=epoch==11?a.oldRaw:a.newRaw;
        if(at!=a.start+frames||at+n>a.end||((frames+n)*a.channels)>output.size()){++a.errors;return;}
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<a.channels;++c)output[(frames+i)*a.channels+c]=p[c][i];frames+=n;
    }
    static void output(void* context,const float*const* p,const ts::playback::ProgressiveOutputSpan& span)noexcept{
        auto& a=*static_cast<OfflineLoopCapture*>(context);if((a.outputFrames+span.frames)*a.channels>a.mixed.size()){++a.errors;return;}
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<a.channels;++c)a.mixed[(a.outputFrames+i)*a.channels+c]=p[c][i];a.outputFrames+=span.frames;
    }
};
static int captureLoopPcm(int argc,char** argv){
    using namespace ts::playback;check(argc==10,"input speed preset A B reference OA OB output");
    const auto speed=std::stoul(argv[2]);const auto a=std::stoull(argv[4]),b=std::stoull(argv[5]);const auto start=std::stoull(argv[7]),end=std::stoull(argv[8]);
    const std::filesystem::path folder=argv[9];check(std::filesystem::create_directories(folder),"capture folder exists");
    ts::prototype::phase58::Configuration c;c.speedMicros=static_cast<std::uint32_t>(speed);c.candidate=std::string(argv[3])=="candidate";c.residentInput=true;c.verifyPcm=false;
    Pipeline base(argv[1],c);base.start();check(base.waitUntilReady(std::chrono::seconds(30)),"base Ready");while(!base.finalAnalysisAvailable())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    auto old=base.createLoopSeek(a,b,static_cast<std::uint32_t>(speed));old->start();check(old->waitUntilReady(std::chrono::seconds(30)),"old Ready");auto fresh=base.createLoopSeek(a,b,static_cast<std::uint32_t>(speed));fresh->start();check(fresh->waitUntilReady(std::chrono::seconds(30)),"new Ready");
    check(old->outputStartFrame()==start&&old->loopOutputEndFrame()==end,"independent boundary map");
    OfflineLoopCapture capture;capture.channels=base.channels();capture.start=start;capture.end=end;const auto length=end-start;
    capture.oldRaw.resize(length*base.channels());capture.newRaw.resize(length*base.channels());capture.mixed.resize(2*length*base.channels());
    RenderTarget first,second;first.pipeline=old.get();second.pipeline=fresh.get();first.epoch=11;second.epoch=12;first.presented=start;second.presented=start;first.loopEnd=end;second.loopEnd=end;
    RenderState state;state.channels=static_cast<unsigned>(base.channels());state.rate=base.sampleRate();state.target=&first;state.active=true;state.observerContext=&capture;state.epochObserver=OfflineLoopCapture::source;state.outputObserver=OfflineLoopCapture::output;
    auto& h=state.handoff;h.oldTarget=&first;h.newTarget=&second;h.loopCycle=h.scheduledBoundary=true;h.loopID=1;h.inputA=a;h.inputB=b;h.boundaryEnd=end;h.output.prepare(base.sampleRate());h.phase=SwitchPhase::Requested;
    std::array<std::array<float,512>,2> pcm{};struct Buffers {UInt32 count;AudioBuffer buffers[2];} buffers{};buffers.count=state.channels;
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(60);AudioTimeStamp stamp{};stamp.mFlags=kAudioTimeStampSampleTimeValid;BOOL silent=NO;
    const auto finalPosition=end-h.output.length;
    while(state.target.load()==&first||second.presented<finalPosition){
        const std::size_t n=state.target.load()==&first?std::size_t(512):std::min<std::uint64_t>(512,finalPosition-second.presented);
        auto* current=state.target.load();const auto remaining=end-current->presented.load();
        const bool oldNotReady=h.phase.load()==SwitchPhase::Started&&old->available()<std::min(n,h.output.remaining());
        if(oldNotReady||current->pipeline->available()<std::min<std::uint64_t>(n,remaining)){check(std::chrono::steady_clock::now()<deadline,"capture supply timeout");std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
        for(unsigned ch=0;ch<state.channels;++ch)buffers.buffers[ch]={1,UInt32(n*sizeof(float)),pcm[ch].data()};
        render(&state,&silent,&stamp,static_cast<AVAudioFrameCount>(n),reinterpret_cast<AudioBufferList*>(&buffers));stamp.mSampleTime+=n;
        if(state.loopMissed){const auto x=old->diagnostics(),y=fresh->diagnostics();std::cerr<<"capture miss phase="<<unsigned(h.phase.load())<<" oldPresented="<<first.presented<<" newPresented="<<second.presented<<" oldEnd="<<end<<" N="<<h.output.length<<" cursor="<<h.output.cursor<<" oldAvailable="<<old->available()<<" newAvailable="<<fresh->available()<<" oldConsumed="<<x.consumed<<" newConsumed="<<y.consumed<<" oldMissing="<<x.missingFrames<<" newMissing="<<y.missingFrames<<" safety="<<state.loopSafetyFrames<<" requested="<<n<<'\n';throw std::runtime_error("capture miss");}
    }
    old->stop();fresh->stop();base.stop();check(!capture.errors,"capture observer bounds/order");check(first.presented==end&&state.loopCycles==1,"logical B");
    std::ifstream reference(argv[6],std::ios::binary);reference.seekg(start*capture.channels*sizeof(float));std::vector<float> expected(length*capture.channels);reference.read(reinterpret_cast<char*>(expected.data()),expected.size()*sizeof(float));check(bool(reference),"reference read");
    check(capture.oldFrames==length&&std::memcmp(capture.oldRaw.data(),expected.data(),capture.oldRaw.size()*sizeof(float))==0,"old RAW independent PCM");
    check(std::memcmp(capture.newRaw.data(),expected.data(),capture.newFrames*capture.channels*sizeof(float))==0,"new RAW independent PCM");
    auto save=[&](const char* name,const auto& values,std::size_t frames){std::ofstream f(folder/name,std::ios::binary);f.write(reinterpret_cast<const char*>(values.data()),frames*capture.channels*sizeof(float));};
    save("old_raw.f32",capture.oldRaw,capture.oldFrames);save("new_raw.f32",capture.newRaw,capture.newFrames);save("mixed.f32",capture.mixed,capture.outputFrames);
    std::ofstream meta(folder/"capture.json");meta<<"{\"PASS\":true,\"rate\":"<<state.rate<<",\"channels\":"<<capture.channels<<",\"start\":"<<start<<",\"end\":"<<end<<",\"overlap\":"<<h.output.length<<",\"old_frames\":"<<capture.oldFrames<<",\"new_frames\":"<<capture.newFrames<<",\"mixed_frames\":"<<capture.outputFrames<<",\"boundary_callback_frame\":"<<state.loopBoundary.read()->callbackFrame<<"}\n";
    return 0;
}
