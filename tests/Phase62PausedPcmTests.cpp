// Only reuse normal-thread file/hash/spawn helpers. No helper runs in render.
#define main phase62DynamicPcmHelpersMain
#include "Phase62DynamicPcmTests.cpp"
#undef main
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include <atomic>
#include <sstream>

namespace paused_pcm {
using namespace ts::playback;
using State=progressive::State;
constexpr const char* fixedSha="de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748";

void state(ProgressiveMacPlaybackEngine& engine,State wanted) {
    waitFor([&]{const auto s=engine.getStateSnapshot();require(s.state!=State::Failed,s.error);return s.state==wanted;},"native state");
}
std::string contents(const fs::path& path) {
    std::ifstream file(path);require(bool(file),"reference statistics missing");
    return {std::istreambuf_iterator<char>(file),std::istreambuf_iterator<char>()};
}
std::uint64_t number(const std::string& text,const char* key) {
    const auto at=text.find(std::string("\"")+key+'"');require(at!=std::string::npos,"reference JSON key missing");
    const auto colon=text.find(':',at);require(colon!=std::string::npos,"reference JSON malformed");return std::stoull(text.substr(colon+1));
}
std::array<std::size_t,3> positions(const std::string& text) {
    const auto at=text.find("\"positions\"");require(at!=std::string::npos,"reference positions missing");
    const auto begin=text.find('[',at),end=text.find(']',begin);require(begin!=std::string::npos&&end!=std::string::npos,"reference positions malformed");
    std::istringstream stream(text.substr(begin+1,end-begin-1));std::array<std::size_t,3> result{};std::string field;
    for(auto& value:result){require(bool(std::getline(stream,field,',')),"reference positions incomplete");value=std::stoull(field);}
    require(!std::getline(stream,field,','),"unexpected reference position count");return result;
}

// Storage and reference ownership are fixed before armed=true. The callback
// writes one bounded producer stream, no locks/allocations/I/O or engine calls.
struct Capture {
    std::atomic<bool> armed{false};
    std::atomic<std::size_t> frames{0},outputFrames{0};
    std::atomic<std::uint64_t> rawErrors{0},outputErrors{0},identityErrors{0},nonfinite{0},overflow{0},padding{0},missing{0};
    std::vector<float> reference,actual;
    std::size_t channels=0,rate=0,period=0,start=0,required=0,capacity=0;
    std::uint64_t generation=0,session=0,firstEpoch=0,lastEpoch=0;
    std::size_t nextRaw=0,nextOutput=0,wraps=0,seenFrames=0;
    bool rawSeen=false;
    static bool same(float left,float right)noexcept{return std::bit_cast<std::uint32_t>(left)==std::bit_cast<std::uint32_t>(right);}
    static void source(void* context,const float*const* pcm,std::size_t count,std::size_t at,
                       std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept {
        auto& x=*static_cast<Capture*>(context);if(!x.armed.load(std::memory_order_acquire))return;
        if(at>x.period||count>x.period-at){++x.identityErrors;return;}
        if(generation!=x.generation||session!=x.session)++x.identityErrors;
        if(!x.rawSeen){if(at!=x.start||epoch!=x.firstEpoch)++x.identityErrors;x.lastEpoch=epoch;x.rawSeen=true;}
        else if(x.nextRaw==x.period){if(at||epoch==x.lastEpoch)++x.identityErrors;++x.wraps;x.lastEpoch=epoch;}
        else if(at!=x.nextRaw||epoch!=x.lastEpoch)++x.identityErrors;
        const auto done=x.frames.load(std::memory_order_relaxed);
        if(done+count>x.capacity){++x.overflow;return;}
        for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<x.channels;++c){
            const auto actual=pcm[c][i],expected=x.reference[(at+i)*x.channels+c];
            x.actual[(done+i)*x.channels+c]=actual;
            if(!same(actual,expected))++x.rawErrors;if(!std::isfinite(actual))++x.nonfinite;
        }
        x.nextRaw=at+count;x.seenFrames+=count;x.frames.store(done+count,std::memory_order_release);
    }
    static void output(void* context,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept {
        auto& x=*static_cast<Capture*>(context);
        x.outputFrames.fetch_add(span.frames,std::memory_order_relaxed);
        if(!x.armed.load(std::memory_order_acquire))return;
        x.padding.fetch_add(span.failurePaddingFrames,std::memory_order_relaxed);
        x.missing.fetch_add(span.oldMissingFrames+span.newMissingFrames+span.outputAffectedFrames,std::memory_order_relaxed);
        if(!span.frames||span.oldEpoch||span.mixedFrames||span.frames!=span.newReceivedFrames||span.newEpoch!=x.lastEpoch)++x.identityErrors;
        const auto at=span.newOutputOffset;
        if(at>x.period||span.frames>x.period-at){++x.identityErrors;return;}
        if(x.nextOutput==x.period)x.nextOutput=0;
        if(at!=x.nextOutput)++x.identityErrors;
        const auto window=std::min(x.rate/200,x.period/4);
        for(std::size_t i=0;i<span.frames;++i)for(std::size_t c=0;c<x.channels;++c){
            const auto position=at+i;auto expected=x.reference[position*x.channels+c];
            const auto first=x.reference[c],last=x.reference[(x.period-1)*x.channels+c];
            if(position>=x.period-window){
                const auto j=position-(x.period-window);
                if(j+1==window)expected=last*.5f+first*.5f;
                else{const float t=float(j+1)/float(window);expected-=(last-first)*.5f*(t*t*(3.f-2.f*t));}
            }else if(x.wraps&&position<window){
                if(!position)expected=last*.5f+first*.5f;
                else{const float t=1.f-float(position)/float(window);expected+=(last-first)*.5f*(t*t*(3.f-2.f*t));}
            }
            if(!same(pcm[c][i],expected))++x.outputErrors;if(!std::isfinite(pcm[c][i]))++x.nonfinite;
        }
        x.nextOutput=at+span.frames;
    }
};

int run(int argc,char** argv) {
    fs::path out;bool owned=false;int oracleExit=-1;
    try {
        require(argc==6,"INPUT SPEED_MICROS candidate|baseline NEW_OUTPUT_DIR fixed_oracle");
        const fs::path input=fs::absolute(argv[1]),oracle=fs::absolute(argv[5]);
        const auto speed=std::uint32_t(std::stoul(argv[2]));const std::string preset=argv[3];
        require(phase59::formalSpeed(speed)&&(preset=="candidate"||preset=="baseline"),"invalid speed/preset");
        out=fs::absolute(argv[4]);require(!fs::exists(out),"fresh evidence directory required");fs::create_directories(out);owned=true;
        const auto oracleHash=fileSha(oracle);require(oracleHash==fixedSha,"fixed independent oracle SHA mismatch");
        ts::WavStreamReader wav(input);require(wav.frames()>=wav.sampleRate()/2,"whole-loop fixture must be >=500ms");
        Capture capture;capture.channels=wav.channels();capture.rate=wav.sampleRate();
        ProgressiveMacPlaybackEngine engine;ProgressiveOptions options;
        options.initialSpeed=speed==1000000?1.25:1.;options.preset=preset=="candidate"?Preset::Candidate:Preset::Baseline;
        options.allowExperimentalLoops=true;options.observerContext=&capture;
        options.observeEpochPcm=Capture::source;options.observeOutputPcm=Capture::output;
        require(engine.prepare(input,options),"native prepare rejected");state(engine,State::Ready);
        const auto initial=engine.getStateSnapshot();progressive::LoopOptions loopOptions;loopOptions.startPolicy=progressive::LoopStartPolicy::ReturnToA;
        const auto loopReceipt=engine.requestLoopRange(0,wav.frames(),{initial.inputGeneration,initial.session,initial.renderEpoch},loopOptions);
        require(loopReceipt.accepted,loopReceipt.reason);
        waitFor([&]{const auto loop=engine.getLoopSnapshot();require(loop.state!=progressive::LoopState::Failed,loop.reason);return loop.initialPositionComplete&&loop.state==progressive::LoopState::Active;},"whole loop preparation");
        require(engine.play(),"initial play rejected");state(engine,State::Playing);
        waitFor([&]{require(engine.getPlaybackState()!=State::Failed,"initial playback failed");return capture.outputFrames.load()>=2048;},"initial real output");
        require(engine.pause(),"initial Pause rejected");
        const auto frozen=engine.getCurrentPlaybackPosition();const auto before=engine.getPlaybackDiagnostics();
        const auto beforeLoop=engine.getLoopSnapshot();const auto seekCount=engine.seekHistory().size();
        const auto outputBefore=capture.outputFrames.load();
        require(frozen.inputFrame&&*frozen.inputFrame>0&&*frozen.inputFrame<wav.frames()&&frozen.sampledOutputFrame==frozen.outputFrame,"paired stopped input C missing");
        const auto receipt=engine.setSpeed(speed/1000000.);require(receipt.result==ts::prototype::Phase39RequestResult::Accepted&&receipt.id,"Paused speed request rejected/duplicate");
        StoppedSpeedOperation prepared;
        const auto hold=[&]{
            const auto state=engine.getStateSnapshot();const auto loop=engine.getLoopSnapshot();const auto position=engine.getCurrentPlaybackPosition();
            const auto diagnostic=engine.getPlaybackDiagnostics();
            require(state.state==State::Paused&&!state.resumePending,"Paused preparation auto-resumed");
            require(position.inputFrame==frozen.inputFrame&&position.inputGeneration==frozen.inputGeneration,"stopped input changed");
            require(loop.enabled&&loop.id==beforeLoop.id&&loop.startFrame==0&&loop.endFrameExclusive==wav.frames()&&loop.cycles==beforeLoop.cycles,"stopped Loop/cycle changed");
            require(capture.outputFrames.load()==outputBefore&&engine.seekHistory().size()==seekCount,"preparation emitted output or fabricated seek");
            if(diagnostic.renderEpoch==before.renderEpoch)require(diagnostic.consumedFrames==before.consumedFrames,"old FIFO was consumed while stopped");
            else require(diagnostic.consumedFrames==diagnostic.pipeline.outputStartFrame&&diagnostic.currentEpochPresentedFrame==diagnostic.pipeline.outputStartFrame,"new epoch was consumed before Resume");
        };
        waitFor([&]{const auto snapshot=engine.getStateSnapshot();require(snapshot.state!=State::Failed,snapshot.error);require(snapshot.stoppedSpeed&&snapshot.stoppedSpeed->id==receipt.id,"Paused request identity lost");
            prepared=*snapshot.stoppedSpeed;require(prepared.state!=StoppedSpeedState::Failed&&prepared.state!=StoppedSpeedState::Cancelled&&prepared.state!=StoppedSpeedState::Replaced,prepared.reason);
            if(prepared.state!=StoppedSpeedState::ReadyForResume)return false;hold();return true;},"Resume-free Ready");
        require(prepared.positionCaptured&&prepared.resumeInputFrame==*frozen.inputFrame&&prepared.loopID==beforeLoop.id&&prepared.cycle==beforeLoop.cycles&&prepared.speedMicros==speed,"Ready input/Loop/request identity mismatch");
        require(prepared.mode==progressive::SeekMode::Exact&&!prepared.outputStarted&&prepared.readyNs>=prepared.acceptedNs&&!engine.getPlaybackDiagnostics().retiringPipeline,"Ready preceded retirement or used a different mode");
        bool retired=false;for(const auto& old:engine.closedEpochs())if(old.pipeline.session==prepared.sourceSession){require(old.pipeline.finalDataAvailable,"old producer not joined");require(prepared.discardedForStoppedSpeedFrames==old.pipeline.published-old.pipeline.consumed,"dedicated stopped FIFO discard audit mismatch");retired=true;}
        require(retired,"retired source epoch audit missing");
        std::ofstream manifest(out/"EXPECTED.json");manifest<<"{\"suite\":\"phase62_paused_pcm\",\"expected\":1,\"input_sha256\":"<<quote(fileSha(input))<<",\"binary_sha256\":"<<quote(fileSha(fs::absolute(argv[0])))
            <<",\"reference_sha256\":"<<quote(oracleHash)<<",\"initial_speed\":"<<options.initialSpeed<<",\"speed_micros\":"<<speed<<",\"preset\":"<<quote(preset)<<",\"input_C\":"<<prepared.resumeInputFrame
            <<",\"input_A\":0,\"input_B\":"<<wav.frames()<<",\"resume_calls_before_ready\":0,\"comparison\":\"independent fixed Exact C-to-B plus A-to-B RAW, finite and separate period correction formula\"}\n";manifest.close();
        const auto rawPath=out/"reference.f32";
        const std::vector<std::string> command{oracle.string(),input.string(),std::to_string(speed),preset,rawPath.string(),std::to_string(prepared.resumeInputFrame),"0",std::to_string(wav.frames())};
        std::ofstream commandFile(out/"REFERENCE_COMMAND.json");commandFile<<'[';for(std::size_t i=0;i<command.size();++i)commandFile<<(i?",":"")<<quote(command[i]);commandFile<<"]\n";commandFile.close();
        oracleExit=runFrozen(command,out/"reference.log");require(!oracleExit,"independent fixed reference failed");hold();
        const auto metadata=contents(out/"reference.log");const auto mapped=positions(metadata);
        require(mapped[1]==0&&mapped[2]==number(metadata,"output_frames")&&mapped[0]==prepared.outputStartFrame&&mapped[0]<mapped[2],"independent fixed Map C/A/B differs");
        require(number(metadata,"channels")==wav.channels()&&number(metadata,"rate")==wav.sampleRate()&&number(metadata,"input_frames")==wav.frames(),"independent reference format differs");
        capture.period=mapped[2];capture.start=mapped[0];capture.required=capture.period-capture.start+capture.period;
        capture.capacity=capture.required+wav.sampleRate()/2+8192;
        require(fs::file_size(rawPath)==capture.period*capture.channels*sizeof(float)&&capture.period*capture.channels<=16*1024*1024,"reference RAW length/budget differs");
        capture.reference.resize(capture.period*capture.channels);capture.actual.resize(capture.capacity*capture.channels);
        std::ifstream raw(rawPath,std::ios::binary);raw.read(reinterpret_cast<char*>(capture.reference.data()),capture.reference.size()*sizeof(float));require(bool(raw),"reference RAW incomplete");
        for(float sample:capture.reference)require(std::isfinite(sample),"nonfinite independent fixed RAW");
        const auto rawSha=fileSha(rawPath);require(metadata.find(rawSha)!=std::string::npos,"reference RAW SHA differs from oracle final statistics");
        // Touch every host-owned capture page before allowing any callback write.
        for(auto& sample:capture.actual)sample=0.f;
        capture.generation=prepared.inputGeneration;capture.session=prepared.session;capture.firstEpoch=prepared.renderEpoch;
        capture.nextRaw=capture.nextOutput=capture.start;hold();
        require(!engine.getPlaybackDiagnostics().retiringPipeline,"retirement reappeared before Resume");
        capture.armed.store(true,std::memory_order_release);require(engine.resume(),"prepared Resume rejected");state(engine,State::Playing);
        waitFor([&]{const auto s=engine.getStateSnapshot();require(s.state!=State::Failed,s.error);require(!capture.overflow,"capture capacity exhausted");return capture.frames.load(std::memory_order_acquire)>=capture.required;},"C-to-B and A-to-B real output");
        require(engine.pause(),"final Pause rejected");capture.armed.store(false,std::memory_order_release);
        const auto finalLoop=engine.getLoopSnapshot();const auto final=engine.getPlaybackDiagnostics();
        require(finalLoop.cycles==beforeLoop.cycles+2,"initial resume counted as a cycle, or natural B-to-A count differs");
        require(!capture.rawErrors&&!capture.outputErrors&&!capture.identityErrors&&!capture.nonfinite&&!capture.overflow&&!capture.padding&&!capture.missing,"independent RAW/correction/identity/finite/missing check failed");
        require(!final.missingFrames&&!final.underrunCalls&&!final.rejectedWrites&&!final.retiringPipeline,"native supply/retirement regression");
        const auto history=engine.loopHistory();std::vector<progressive::LoopBoundaryEvent> boundaries;
        for(const auto& event:history)if(event.cycle>beforeLoop.cycles)boundaries.push_back(event);
        require(boundaries.size()==2&&boundaries[1].callbackFrame-boundaries[0].callbackFrame==capture.period,"independent full next-period/cumulative length differs");
        for(const auto& event:boundaries)require(event.loopID==beforeLoop.id&&event.inputA==0&&event.inputBExclusive==wav.frames()&&event.oldOutputEnd==capture.period&&event.newOutputStart==0&&!event.overlapFrames,"boundary Map/identity/period shortening differs");
        engine.stop();require(engine.getPlaybackDiagnostics().pipeline.finalDataAvailable,"active producer not joined at stop");
        require(fileSha(oracle)==oracleHash,"fixed oracle changed during native test");
        std::ofstream actual(out/"captured.f32",std::ios::binary);actual.write(reinterpret_cast<const char*>(capture.actual.data()),capture.required*capture.channels*sizeof(float));actual.close();require(bool(actual),"captured RAW write failed");
        std::ofstream summary(out/"SUMMARY.json");summary<<"{\"suite\":\"phase62_paused_pcm\",\"expected\":1,\"executed\":1,\"status\":\"PASS\",\"speed_micros\":"<<speed<<",\"preset\":"<<quote(preset)
            <<",\"input_C\":"<<prepared.resumeInputFrame<<",\"output_C\":"<<capture.start<<",\"output_A\":0,\"output_B\":"<<capture.period<<",\"compared_frames\":"<<capture.required
            <<",\"observed_frames\":"<<capture.frames.load()<<",\"channels\":"<<capture.channels<<",\"cycles\":2,\"loop_id\":"<<prepared.loopID<<",\"preparation_version\":"<<prepared.preparationVersion
            <<",\"ready_before_resume\":true,\"resume_calls_before_ready\":0,\"retired_before_resume\":true,\"stopped_position_and_loop_preserved\":true,\"independent_fixed_DSP_RAW\":true,\"map_bit_exact\":true,\"period_formula_bit_exact\":true,\"nonfinite\":0,\"missing\":0,\"padding\":0,\"oracle_exit\":"<<oracleExit
            <<",\"reference_sha256\":"<<quote(oracleHash)<<",\"reference_pcm_sha256\":"<<quote(rawSha)<<",\"captured_pcm_sha256\":"<<quote(fileSha(out/"captured.f32"))
            <<",\"execution\":\"native HAL real output\",\"realtime_deadline_approval\":\"NOT_RUN\",\"physical_loopback\":\"NOT_RUN\",\"final_gain_measurement\":\"NOT_RUN\"}\n";
        summary.close();std::cout<<contents(out/"SUMMARY.json");return 0;
    } catch(const std::exception& error) {
        std::cerr<<error.what()<<'\n';
        if(owned){std::ofstream summary(out/"SUMMARY.json");summary<<"{\"suite\":\"phase62_paused_pcm\",\"expected\":1,\"executed\":0,\"status\":\"FAIL\",\"oracle_exit\":"<<oracleExit<<",\"reason\":"<<quote(error.what())<<"}\n";}
        return 1;
    }
}
}
int main(int argc,char** argv){int result=1;std::thread owner([&]{result=paused_pcm::run(argc,argv);});owner.join();return result;}
