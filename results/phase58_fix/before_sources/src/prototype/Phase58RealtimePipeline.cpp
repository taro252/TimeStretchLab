#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase56PinnedWav.h"
#include "prototype/Phase45PcmDigest.h"
#include "playback/StartupDiagnostics.h"
#include <condition_variable>
#include <cerrno>
#include <mutex>
#include <pthread.h>
#include <cmath>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace ts::prototype::phase58 {
namespace {
struct Cancelled {};
// Immutable identity and FD; validation has no analysis-session side effect.
class Input {
    std::filesystem::path selected_;int fd_=-1,snapshotFd_=-1;struct stat identity_{};
    static bool same(const struct stat& a,const struct stat& b){
        auto t=[](timespec x,timespec y){return x.tv_sec==y.tv_sec&&x.tv_nsec==y.tv_nsec;};
        return a.st_dev==b.st_dev&&a.st_ino==b.st_ino&&a.st_gen==b.st_gen&&a.st_size==b.st_size&&
            t(a.st_mtimespec,b.st_mtimespec)&&t(a.st_ctimespec,b.st_ctimespec)&&t(a.st_birthtimespec,b.st_birthtimespec);
    }
public:
    std::uint32_t rate=0;std::size_t channels=0,frames=0;
    explicit Input(const std::filesystem::path& p):selected_(p){
        fd_=open(p.c_str(),O_RDONLY|O_CLOEXEC);
        try{
            if(fd_<0||fstat(fd_,&identity_)||!S_ISREG(identity_.st_mode))throw std::runtime_error("Cannot pin regular input");
            WavStreamReader r(path());rate=r.sampleRate();channels=r.channels();frames=r.frames();
            if(!frames||(rate!=44100&&rate!=48000)||(channels!=1&&channels!=2))throw std::invalid_argument("Unsupported Phase58 WAV");
            validate();
        }catch(...){if(fd_>=0)close(fd_);fd_=-1;throw;}
    }
    ~Input(){if(snapshotFd_>=0)close(snapshotFd_);if(fd_>=0)close(fd_);}
    std::filesystem::path path()const{return "/dev/fd/"+std::to_string(snapshotFd_>=0?snapshotFd_:fd_);}
    std::size_t snapshotBytes()const{return snapshotFd_>=0?std::size_t(identity_.st_size):0;}
    void validate()const{
        struct stat actual{},selected{};const int choice=open(selected_.c_str(),O_RDONLY|O_CLOEXEC);
        const bool valid=fd_>=0&&fstat(fd_,&actual)==0&&choice>=0&&fstat(choice,&selected)==0&&same(identity_,actual)&&same(identity_,selected);
        if(choice>=0)close(choice);
        if(!valid)throw std::runtime_error("Input changed/replaced/unavailable");
    }
    std::string identify(std::size_t budget){
        validate();Phase45PcmDigest hash;std::array<unsigned char,131072> b{};off_t at=0;
        if(std::uint64_t(identity_.st_size)>budget)throw std::length_error("Input snapshot budget exceeded");
        auto name=(std::filesystem::temp_directory_path()/"phase58-input-XXXXXX").string();
        snapshotFd_=mkstemp(name.data());if(snapshotFd_<0)throw std::runtime_error("Cannot allocate private source snapshot");
        if(unlink(name.c_str())!=0)throw std::runtime_error("Cannot unlink private source snapshot");
        if(fcntl(snapshotFd_,F_SETFD,FD_CLOEXEC)<0)throw std::runtime_error("Cannot protect source snapshot FD");
        while(at<identity_.st_size){const auto n=pread(fd_,b.data(),std::min<off_t>(b.size(),identity_.st_size-at),at);
            if(n<0&&errno==EINTR)continue;
            if(n<=0)throw std::runtime_error("Input identification read failed");
            std::size_t written=0;while(written<std::size_t(n)){const auto count=write(snapshotFd_,b.data()+written,std::size_t(n)-written);if(count<0&&errno==EINTR)continue;if(count<=0)throw std::runtime_error("Private input snapshot write failed");written+=count;}
            hash.update(b.data(),std::size_t(n));at+=n;}
        validate();return hash.finish();
    }
};
std::atomic<std::uint64_t> nextSession{1};
static_assert(std::atomic<std::uint64_t>::is_always_lock_free);
static_assert(std::atomic<std::size_t>::is_always_lock_free);
static_assert(std::atomic<bool>::is_always_lock_free);
struct CpuEnd {
    std::atomic<double>& destination;double start=playback::threadCpuSeconds();
    ~CpuEnd(){destination=playback::threadCpuSeconds()-start;}
};
void maximum(std::atomic<std::uint64_t>& destination,std::uint64_t value){auto old=destination.load();while(old<value&&!destination.compare_exchange_weak(old,value)){};}
}
struct RealtimePipeline::Impl {
    playback::StageClock origin;Configuration config;Input input;
    const std::uint64_t session=nextSession.fetch_add(1);const std::size_t lead;
    Phase14AudioFifo fifo;
    std::thread analysisWorker,dspWorker;
    mutable std::mutex mutex;std::condition_variable changed;
    std::shared_ptr<const phase56::AnalysisSnapshot> mailbox;
    std::uint64_t version=0;std::string inputSha,pcmSha,error;
    std::atomic<bool> started{false},cancelled{false},failure{false},analysisDone{false},dspDone{false},ready{false};
    std::atomic<bool> analysisQos{false},dspQos{false};
    std::atomic<std::uint64_t> analysisThread{0},dspThread{0},missing{0},missingCalls{0},maxMissing{0},analysisWaits{0};
    std::uint64_t consecutiveMissing=0; // Audio consumer only.
    std::atomic<std::size_t> received{0},generated{0},published{0},consumed{0},output{0},snapshotPeak{0},snapshotCopies{0};
    std::atomic<std::size_t> inputAtFirstPcm{0},inputAtReady{0},nonEosPublished{0};
    double verified=-1,identified=-1;
    std::atomic<double> analysisStart{-1},firstEvent{-1},firstMap{-1},firstGenerated{-1},firstPublished{-1},readyTime{-1},analysisEnd{-1};
    std::atomic<double> analysisCpu{0},dspCpu{0},maxDspWall{0},analysisWait{0},backpressureWait{0};
    std::atomic<double> dspWorkerCpu{0},maxDspCpu{0},maxPublicationGap{0};
    std::atomic<double> analysisWorkerCpu{0};
    std::atomic<double> maxDspValidationWall{0},maxDspValidationCpu{0};
    std::vector<WorkerRecord> profiles;std::size_t profileDropped=0;
    Impl(const std::filesystem::path& p,Configuration c):config(c),input(p),lead(c.candidate?16384:12288),fifo(input.channels,16384){
        if(c.speedMicros<400000||c.speedMicros>2000000||c.speedMicros%10000||!c.analysisChunk||c.analysisChunk>131072||!std::isfinite(c.analysisDelayMs)||c.analysisDelayMs<0||!std::isfinite(c.dspDelayMs)||c.dspDelayMs<0)throw std::invalid_argument("Invalid Phase58 configuration");
        error.reserve(256);verified=elapsed();inputSha=input.identify(config.sourceSnapshotBytes);identified=elapsed();
    }
    double elapsed()const{return origin.elapsed().wallSeconds;}
    void check(bool dsp=false){if(cancelled.load()||failure.load())throw Cancelled{};
        // DSP sees only the private immutable byte snapshot. Original-path
        // validation belongs exclusively to the analysis/identity worker.
        if(!dsp)input.validate();}
    void fail(const char* message){
        {std::lock_guard lock(mutex);if(!failure.exchange(true))error.assign(message,std::min<std::size_t>(std::char_traits<char>::length(message),256));}
        changed.notify_all();
    }
    void publish(std::shared_ptr<const phase56::AnalysisSnapshot> s){
        if(s->closedEventCount&&firstEvent.load()<0)firstEvent=elapsed();
        if(s->mapThroughNode>1&&firstMap.load()<0)firstMap=elapsed();
        {std::lock_guard lock(mutex);mailbox=std::move(s);++version;}
        changed.notify_all();
    }
    void analyze(){
        CpuEnd measured{analysisWorkerCpu};
        std::unique_ptr<phase56::ProgressiveAnalysisSession> a;
        try{
            std::uint64_t tid=0;pthread_threadid_np(nullptr,&tid);analysisThread=tid;
            analysisQos=pthread_set_qos_class_self_np(QOS_CLASS_UTILITY,0)==0;
            analysisStart=elapsed();playback::StageClock cpu;
            a=std::make_unique<phase56::ProgressiveAnalysisSession>(input.rate,input.channels,session,phase56::AnalysisLimits{},std::vector<std::uint32_t>{config.speedMicros});
            phase56::PinnedWavSource source(input.path(),session);std::size_t at=0;
            while(at<input.frames){check();if(config.analysisDelayMs)std::this_thread::sleep_for(std::chrono::duration<double,std::milli>(config.analysisDelayMs));
                check();at+=source.appendNext(*a,config.analysisChunk);check();received=at;publish(a->getSnapshot());}
            check();source.finish(*a);check();analysisEnd=elapsed();analysisDone=true;publish(a->getSnapshot());
            const auto stats=a->statistics();snapshotPeak=stats.snapshotPeakBytes;snapshotCopies=stats.snapshotCopyBytes;
            analysisCpu=cpu.elapsed().threadCpuSeconds;
            // Continue validating the selected source after analysis EOS. The
            // control/audio owner joins this worker before releasing the FD.
            while(!cancelled.load()&&!failure.load()){
                std::unique_lock lock(mutex);changed.wait_for(lock,std::chrono::milliseconds(10),[&]{return cancelled.load()||failure.load();});lock.unlock();
                if(dspDone.load()&&fifo.available()==0)break;check();
            }
        }catch(const Cancelled&){if(a)a->cancel();}
        catch(const std::exception& e){if(dspDone.load()&&fifo.available()==0&&!failure.load())return;
            if(a&&!analysisDone.load()){try{a->failInput(session,phase56::AnalysisError::InputRead);}catch(...){}}fail(e.what());}
        changed.notify_all();
    }
    void synthesize(){
        CpuEnd measured{dspWorkerCpu};
        try{
            std::uint64_t tid=0;pthread_threadid_np(nullptr,&tid);dspThread=tid;
            dspQos=pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED,0)==0;
            phase57::ProgressiveSynthesisEngine engine(input.path(),config.speedMicros,session,[this]{check(true);});
            output=std::size_t(std::llround(input.frames*(1.0/(double(config.speedMicros)/1000000.0))));
            engine.setDeclaredFinalOutputFrames(output.load());
            if(config.recordWorkerProfile){profiles.reserve(65536);engine.enableWorkProfiling();}
            Phase45PcmDigest hash;std::vector<float> interleaved(config.verifyPcm?2048*input.channels:0);
            std::uint64_t seen=0;
            bool needSnapshot=true,finalSnapshot=false;double previousPublished=-1;
            while(!cancelled.load()&&!failure.load()){
                std::shared_ptr<const phase56::AnalysisSnapshot> next;
                if(needSnapshot){
                    playback::StageClock wait;std::unique_lock lock(mutex);++analysisWaits;
                    changed.wait(lock,[&]{return cancelled.load()||failure.load()||version!=seen;});
                    analysisWait=analysisWait.load()+wait.elapsed().wallSeconds;
                    if(cancelled.load()||failure.load())break;
                    next=mailbox;seen=version;needSnapshot=false;
                }else{
                    std::lock_guard lock(mutex);if(version!=seen){next=mailbox;seen=version;}
                }
                if(next){
                    engine.supplySnapshot(next);
                    finalSnapshot=next->isFinal;
                }
                if(fifo.free()<2048||fifo.available()+2048>lead){
                    playback::StageClock wait;std::unique_lock lock(mutex);
                    // Callback only reads atomics/FIFO. A bounded 2ms worker
                    // sleep supplies backpressure without callback-side wakeups.
                    changed.wait_for(lock,std::chrono::milliseconds(2),[&]{return cancelled.load()||failure.load()||(fifo.free()>=2048&&fifo.available()+2048<=lead);});
                    backpressureWait=backpressureWait.load()+wait.elapsed().wallSeconds;continue;
                }
                check(true);playback::StageClock block;const auto began=elapsed();const auto fifoBefore=fifo.available();const auto startOutput=published.load();double atPublication=0,gap=0;
                if(config.dspDelayMs)std::this_thread::sleep_for(std::chrono::duration<double,std::milli>(config.dspDelayMs));
                phase57::SynthesisState state;
                try{state=engine.advance([&](auto generation,auto offset,const float*const* p,std::size_t n){
                    check(true);if(generation!=session||offset!=published.load())throw std::logic_error("PCM identity/offset mismatch");
                    generated=offset+n;if(firstGenerated.load()<0)firstGenerated=elapsed();
                    if(config.verifyPcm){for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<input.channels;++c)interleaved[i*input.channels+c]=p[c][i];hash.update(interleaved.data(),n*input.channels*sizeof(float));}
                    if(!fifo.write(p,n))throw std::runtime_error("FIFO rejected PCM write");
                    atPublication=elapsed();gap=previousPublished<0?0:atPublication-previousPublished;previousPublished=atPublication;maxPublicationGap=std::max(maxPublicationGap.load(),gap);
                    published=offset+n;if(firstPublished.load()<0){inputAtFirstPcm=received.load();firstPublished=atPublication;}
                    if(!analysisDone.load())nonEosPublished=offset+n;
                    if(offset+n>=lead&&!ready.load()){
                        // Publish the condition under the waiter's mutex so
                        // notify cannot fall between its predicate and park.
                        std::lock_guard lock(mutex);inputAtReady=received.load();readyTime=elapsed();ready=true;
                    }changed.notify_all();
                });}catch(...){generated=engine.frontier().generated;throw;}
                const auto t=block.elapsed();dspCpu=dspCpu.load()+t.threadCpuSeconds;maxDspWall=std::max(maxDspWall.load(),t.wallSeconds);maxDspCpu=std::max(maxDspCpu.load(),t.threadCpuSeconds);
                if(config.recordWorkerProfile&&published.load()!=startOutput){
                    if(profiles.size()<65536)profiles.push_back({startOutput,published.load(),fifoBefore,fifo.available(),received.load(),seen,finalSnapshot,began,atPublication,t.wallSeconds,t.threadCpuSeconds,gap,engine.workProfile()});else ++profileDropped;
                }
                if(state==phase57::SynthesisState::NeedsMoreAnalysis||state==phase57::SynthesisState::NeedsMoreInput){needSnapshot=true;continue;}
                if(state==phase57::SynthesisState::Finished){
                    if(engine.frontier().published!=output.load())throw std::logic_error("Final output length differs");
                    {std::lock_guard lock(mutex);if(config.verifyPcm)pcmSha=hash.finish();
                        dspDone=true;if(published.load()&&!ready.load()){inputAtReady=received.load();readyTime=elapsed();ready=true;}}
                    changed.notify_all();return;
                }
                if(state!=phase57::SynthesisState::Produced)throw std::runtime_error("Unexpected synthesis terminal state");
            }
        }catch(const Cancelled&){}
        catch(const std::exception& e){fail(e.what());}
        changed.notify_all();
    }
    void stop(){{std::lock_guard lock(mutex);cancelled=true;}changed.notify_all();if(analysisWorker.joinable())analysisWorker.join();if(dspWorker.joinable())dspWorker.join();}
};
RealtimePipeline::RealtimePipeline(const std::filesystem::path& p,Configuration c):impl_(std::make_unique<Impl>(p,c)){}
RealtimePipeline::~RealtimePipeline(){impl_->stop();}
void RealtimePipeline::start(){if(impl_->started.exchange(true))throw std::logic_error("Create a fresh playback session");
    try{impl_->analysisWorker=std::thread([this]{impl_->analyze();});impl_->dspWorker=std::thread([this]{impl_->synthesize();});}catch(...){impl_->stop();throw;}}
bool RealtimePipeline::waitUntilReady(std::chrono::milliseconds timeout){auto& x=*impl_;std::unique_lock lock(x.mutex);x.changed.wait_for(lock,timeout,[&]{return x.ready.load()||x.failure.load()||x.cancelled.load();});return x.ready.load()&&!x.failure.load()&&!x.cancelled.load();}
void RealtimePipeline::stop(){impl_->stop();}
RenderResult RealtimePipeline::pullAudio(float*const* p,std::size_t n)noexcept{
    auto& x=*impl_;RenderResult r;r.outputBefore=x.consumed.load(std::memory_order_relaxed);r.fifoBefore=x.fifo.available();
    const auto end=x.output.load(std::memory_order_acquire);r.wanted=end?(end>r.outputBefore?std::min(n,end-r.outputBefore):0):n;
    if(x.cancelled.load()||x.failure.load())r.wanted=0;
    r.received=x.fifo.read(p,r.wanted);x.consumed.fetch_add(r.received,std::memory_order_relaxed);
    for(std::size_t c=0;c<x.input.channels;++c)std::fill(p[c]+r.received,p[c]+n,0.0f);
    const auto missing=r.wanted-r.received;
    if(missing){x.missing.fetch_add(missing);x.missingCalls.fetch_add(1);x.consecutiveMissing=r.received?missing:x.consecutiveMissing+missing;maximum(x.maxMissing,x.consecutiveMissing);}else x.consecutiveMissing=0;
    return r;
}
bool RealtimePipeline::finished()const noexcept{return impl_->dspDone.load();}
bool RealtimePipeline::drained()const noexcept{return finished()&&!available();}
bool RealtimePipeline::failed()const noexcept{return impl_->failure.load();}
std::size_t RealtimePipeline::available()const noexcept{return impl_->fifo.available();}
std::uint32_t RealtimePipeline::sampleRate()const noexcept{return impl_->input.rate;}
std::size_t RealtimePipeline::channels()const noexcept{return impl_->input.channels;}
std::size_t RealtimePipeline::inputFrames()const noexcept{return impl_->input.frames;}
double RealtimePipeline::elapsedSeconds()const noexcept{return impl_->elapsed();}
Diagnostics RealtimePipeline::diagnostics()const{
    const auto& x=*impl_;Diagnostics d;std::lock_guard lock(x.mutex);
    d.session=x.session;d.analysisThread=x.analysisThread;d.dspThread=x.dspThread;d.snapshotVersion=x.version;
    d.inputFrames=x.input.frames;d.receivedInput=x.received;d.generated=x.generated;d.published=x.published;d.consumed=x.consumed;d.outputFrames=x.output;
    d.inputAtFirstPcm=x.inputAtFirstPcm;d.inputAtReady=x.inputAtReady;d.nonEosPublished=x.nonEosPublished;
    d.sourceSnapshotBytes=x.input.snapshotBytes();d.analysisWorkerCpuS=x.analysisWorkerCpu;
    d.fifoHighWater=x.fifo.highWater();d.snapshotPeakBytes=x.snapshotPeak;d.snapshotCopyBytes=x.snapshotCopies;
    d.missingFrames=x.missing;d.missingCalls=x.missingCalls;d.maxConsecutiveMissing=x.maxMissing;d.rejectedWrites=x.fifo.rejectedWrites();d.analysisWaits=x.analysisWaits;
    d.verifiedS=x.verified;d.identifiedS=x.identified;d.analysisStartS=x.analysisStart;d.firstEventS=x.firstEvent;d.firstMapS=x.firstMap;
    d.firstGeneratedS=x.firstGenerated;d.firstPublishedS=x.firstPublished;d.readyS=x.readyTime;d.analysisDoneS=x.analysisEnd;
    d.analysisCpuS=x.analysisCpu;d.dspCpuS=x.dspCpu;d.maxDspWallS=x.maxDspWall;d.analysisWaitS=x.analysisWait;d.backpressureWaitS=x.backpressureWait;
    d.dspWorkerCpuS=x.dspWorkerCpu;d.maxDspCpuS=x.maxDspCpu;d.maxPublicationGapS=x.maxPublicationGap;
    d.maxDspValidationWallS=x.maxDspValidationWall;d.maxDspValidationCpuS=x.maxDspValidationCpu;
    if(!x.dspWorker.joinable()){d.workerProfileRecords=x.profiles.size();d.workerProfileDropped=x.profileDropped;}
    d.analysisQos=x.analysisQos;d.dspQos=x.dspQos;d.analysisDone=x.analysisDone;d.dspDone=x.dspDone;d.cancelled=x.cancelled&&!x.dspDone;d.failed=x.failure;
    d.inputSha256=x.inputSha;d.pcmSha256=x.pcmSha;d.error=x.error;return d;
}
std::vector<WorkerRecord> RealtimePipeline::workerRecords()const{const auto& x=*impl_;if(x.analysisWorker.joinable()||x.dspWorker.joinable())throw std::logic_error("Stop and join before exporting worker records");return x.profiles;}
}
