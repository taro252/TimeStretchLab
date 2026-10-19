#include "prototype/Phase58RealtimePipeline.h"
#include "prototype/Phase56PinnedWav.h"
#include "prototype/Phase45PcmDigest.h"
#include "prototype/Phase58FixAllocationProbe.h"
#include "prototype/Phase58FixSnapshotMailbox.h"
#include "prototype/Phase61SeekEnvelope.h"
#include "playback/StartupDiagnostics.h"
#include <condition_variable>
#include <cerrno>
#include <mutex>
#include <pthread.h>
#include <cmath>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <unistd.h>
#include <mach/mach.h>

namespace ts::prototype::phase58 {
namespace {
struct Cancelled {};
// Immutable identity and FD; validation has no analysis-session side effect.
class Input {
    std::filesystem::path selected_;int fd_=-1,snapshotFd_=-1;struct stat identity_{};
    unsigned char* resident_=nullptr;std::size_t residentSize_=0;
    std::size_t hashes_=0,snapshots_=0,locks_=0;
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
            WavStreamReader r(fd_);rate=r.sampleRate();channels=r.channels();frames=r.frames();
            if(!frames||(rate!=44100&&rate!=48000)||(channels!=1&&channels!=2))throw std::invalid_argument("Unsupported Phase58 WAV");
            validate();
        }catch(...){if(fd_>=0)close(fd_);fd_=-1;throw;}
    }
    ~Input(){if(resident_){munlock(resident_,residentSize_);munmap(resident_,residentSize_);}if(snapshotFd_>=0)close(snapshotFd_);if(fd_>=0)close(fd_);}
    int snapshotDescriptor()const{return snapshotFd_;}
    std::size_t snapshotBytes()const{return snapshotFd_>=0?std::size_t(identity_.st_size):0;}
    std::span<const unsigned char> residentBytes()const{return {resident_,residentSize_};}
    std::size_t hashes()const{return hashes_;}std::size_t snapshots()const{return snapshots_;}std::size_t locks()const{return locks_;}
    void makeResident(){
        if(snapshotFd_<0||resident_)throw std::logic_error("Resident source preparation order");
        const auto bytes=snapshotBytes();void* memory=mmap(nullptr,bytes,PROT_READ,MAP_PRIVATE,snapshotFd_,0);
        if(memory==MAP_FAILED)throw std::runtime_error("Cannot map private encoded input");
        ++locks_;if(mlock(memory,bytes)!=0){munmap(memory,bytes);throw std::runtime_error("Cannot lock private encoded input in memory");}
        resident_=static_cast<unsigned char*>(memory);residentSize_=bytes;
        WavStreamReader validated(std::filesystem::path{},residentBytes());validated.validateEncodedSamples();
    }
    void validate()const{
        struct stat actual{},selected{};const int choice=open(selected_.c_str(),O_RDONLY|O_CLOEXEC);
        const bool valid=fd_>=0&&fstat(fd_,&actual)==0&&choice>=0&&fstat(choice,&selected)==0&&same(identity_,actual)&&same(identity_,selected);
        if(choice>=0)close(choice);
        if(!valid)throw std::runtime_error("Input changed/replaced/unavailable");
    }
    std::string identify(std::size_t budget){
        ++hashes_;
        validate();Phase45PcmDigest hash;std::array<unsigned char,131072> b{};off_t at=0;
        if(std::uint64_t(identity_.st_size)>budget)throw std::length_error("Input snapshot budget exceeded");
        auto name=(std::filesystem::temp_directory_path()/"phase58-input-XXXXXX").string();
        ++snapshots_;snapshotFd_=mkstemp(name.data());if(snapshotFd_<0)throw std::runtime_error("Cannot allocate private source snapshot");
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
// One source preparation, independently retained by at most two render epochs.
// No mutable analysis/DSP state is shared between their workers.
struct InputLease {
    Input input;
    std::uint64_t generation=0;
    std::string sha;
    std::shared_ptr<const phase56::AnalysisSnapshot> finalAnalysis;
    std::atomic<bool> analysisFailed{false};
    struct Checkpoint {std::uint32_t speed;std::size_t output;std::shared_ptr<const phase57::ProgressiveSynthesisEngine> state;};
    std::mutex checkpointMutex;std::vector<Checkpoint> checkpoints;
    std::size_t checkpointBuilds=0;
    explicit InputLease(const std::filesystem::path& p):input(p){}
};
std::atomic<std::uint64_t> nextSession{1};
static_assert(std::atomic<std::uint64_t>::is_always_lock_free);
static_assert(std::atomic<std::size_t>::is_always_lock_free);
static_assert(std::atomic<bool>::is_always_lock_free);
static_assert(std::atomic<double>::is_always_lock_free);
struct CpuEnd {
    std::atomic<double>& destination;double start=playback::threadCpuSeconds();
    ~CpuEnd(){destination=playback::threadCpuSeconds()-start;}
};
void maximum(std::atomic<std::uint64_t>& destination,std::uint64_t value){auto old=destination.load();while(old<value&&!destination.compare_exchange_weak(old,value)){};}
template<class T>void prepareDiagnosticStorage(std::vector<T>& buffer,std::size_t capacity){
    // reserve alone leaves demand-zero pages untouched. Construct and touch
    // every page on this normal thread before any realtime promotion.
    buffer.resize(capacity);
    const auto bytes=buffer.size()*sizeof(T);
    if(bytes){
        auto* memory=reinterpret_cast<volatile unsigned char*>(buffer.data());
        const auto page=std::size_t(std::max<long>(1,sysconf(_SC_PAGESIZE)));
        for(std::size_t at=0;at<bytes;at+=page)memory[at]=memory[at];
        memory[bytes-1]=memory[bytes-1];
    }
    buffer.clear();
}
}
struct RealtimePipeline::Impl {
    playback::StageClock origin;Configuration config;
    std::shared_ptr<InputLease> inputLease;Input& input;
    bool seeking=false;std::size_t seekInput=0;
    std::atomic<std::size_t> outputStart{0},discarded{0};
    std::atomic<bool> seekMapReady{false};
    std::atomic<std::size_t> loopOutputEnd{0};
    std::shared_ptr<const TimeMap> fixedSeekMap; // release published, immutable
    std::array<std::array<float,2048>,2> seekPcm{};
    std::size_t seekPcmOffset=0,seekPcmCount=0;
    bool seekDspFinished=false;
    Phase45PcmDigest seekHash;std::array<float,4096> seekInterleaved{};
    phase57::ProgressiveSynthesisEngine* activeSynthesis=nullptr;
    std::atomic<std::size_t> checkpointStart{0};
    std::size_t lastCheckpointOutput=0;bool savedCheckpoint=false;
    bool localInitialized=false;
    std::atomic<std::size_t> localSeed{0},localBegin{0};std::atomic<double> localInitializeS{0};
    phase61::PublicationEnvelope envelope;
    const std::uint64_t session=nextSession.fetch_add(1);const std::size_t lead;
    Phase14AudioFifo fifo;
    std::thread analysisWorker,dspWorker,sampler;
    // Only the serialized lifecycle owner touches the std::thread objects.
    // Observers acquire Finalized; no worker or post-join writer remains then.
    std::atomic<LifecycleState> lifecycle{LifecycleState::Unstarted};
    mutable std::mutex mutex;std::condition_variable changed;
    std::shared_ptr<const phase56::AnalysisSnapshot> mailbox;
    BorrowedSnapshotMailbox<phase56::AnalysisSnapshot> borrowedMailbox;
    BorrowedSnapshotMailbox<phase59::DynamicMap> dynamicMailbox;
    phase59::ValueMailbox<phase59::PlanningFrontier> frontierMailbox;
    mutable phase59::ValueMailbox<PositionSample> positionMailbox;
    std::unique_ptr<phase59::ProgressiveTransitionPlanner> transitionPlanner;
    mutable std::mutex operationMutex;
    std::vector<phase59::SpeedOperation> operations;
    static constexpr std::size_t noOperation=std::size_t(-1);
    std::size_t pendingOperation=noOperation,activeOperation=noOperation,mapOperation=noOperation;
    std::uint64_t requestGeneration=0,pendingMapTag=0,lastPlannerReceived=0;
    bool plannerSawFinal=false,mapOffered=false;
    std::shared_ptr<const phase59::DynamicMap> pendingMap;
    std::atomic<std::uint64_t> mapAckTag{0};std::atomic<bool> mapAckAccepted{false};
    std::atomic<std::uint64_t> announcedRequest{0},observedRequest{0};
    std::atomic<double> observedRequestS{-1};
    std::atomic<double> mapAckS{-1};
    std::atomic<std::size_t> mapAckConsumed{0},transitionAttempts{0},transitionStale{0},transitionDeferrals{0},transitionMapPeak{0},transitionHistory{0};
    std::atomic<double> transitionCpu{0},transitionWall{0};
    std::size_t waitingAnalysisNodes=std::size_t(-1);bool waitingAnalysisFinal=false;
    std::unique_ptr<RealtimeWorkerSupport> realtime;
    std::uint64_t version=0;std::string inputSha,pcmSha,error;
    std::atomic<bool> started{false},cancelled{false},failure{false},analysisDone{false},dspDone{false},ready{false};
    std::atomic<bool> renderingRequested{false};
    std::atomic<bool> analysisQos{false},dspQos{false};
    std::atomic<std::uint64_t> analysisThread{0},dspThread{0},missing{0},missingCalls{0},maxMissing{0},analysisWaits{0};
    std::uint64_t consecutiveMissing=0; // Audio consumer only.
    std::atomic<std::size_t> received{0},generated{0},published{0},consumed{0},output{0},snapshotPeak{0},snapshotCopies{0};
    std::atomic<std::size_t> inputAtFirstPcm{0},inputAtReady{0},nonEosPublished{0};
    double verified=-1,identified=-1;
    double residentReady=-1;
    std::atomic<double> analysisStart{-1},firstEvent{-1},firstMap{-1},firstGenerated{-1},firstPublished{-1},readyTime{-1},analysisEnd{-1};
    std::atomic<double> analysisCpu{0},dspCpu{0},maxDspWall{0},analysisWait{0},backpressureWait{0};
    std::atomic<double> dspWorkerCpu{0},maxDspCpu{0},maxPublicationGap{0};
    std::atomic<double> analysisWorkerCpu{0};
    std::atomic<double> maxDspValidationWall{0},maxDspValidationCpu{0};
    std::vector<WorkerRecord> profiles;std::size_t profileDropped=0;
    std::vector<DetailEvent> details;std::size_t detailDropped=0;
    std::atomic<unsigned> analysisQosClass{0},dspQosClass{0};
    std::atomic<int> analysisQosRelative{0},dspQosRelative{0};
    std::atomic<bool> analysisQosQueried{false},dspQosQueried{false};
    std::atomic<std::uint64_t> dspNewCalls{0};std::atomic<bool> dspAllocationsMeasured{false};
    std::atomic<std::uint64_t> realtimeNewCalls{0};std::atomic<bool> realtimeAllocationsMeasured{false};
    std::atomic<std::uint64_t> currentStage{UINT64_MAX};
    std::array<std::uint64_t,32> stageStack{};std::size_t stageDepth=0;
    std::vector<ThreadSample> samples;std::size_t sampleDropped=0,sampleErrors=0;
    std::atomic<double> samplerCpu{0};
    Impl(const std::filesystem::path& p,Configuration c):Impl(std::make_shared<InputLease>(p),c,false,0){}
    Impl(std::shared_ptr<InputLease> lease,Configuration c,bool seek,std::size_t at)
        :config(c),inputLease(std::move(lease)),input(inputLease->input),seeking(seek),seekInput(at),
         envelope(input.rate,input.channels),lead(c.candidate?16384:12288),fifo(input.channels,16384){
        if(c.speedMicros<400000||c.speedMicros>2000000||c.speedMicros%10000||!c.analysisChunk||c.analysisChunk>131072||!std::isfinite(c.analysisDelayMs)||c.analysisDelayMs<0||!std::isfinite(c.dspDelayMs)||c.dspDelayMs<0)throw std::invalid_argument("Invalid Phase58 configuration");
        if(c.diagnosticEventLimit>262144)throw std::invalid_argument("Unbounded detail diagnostics");
        if(c.scheduling==WorkerScheduling::AudioWorkgroup&&(!c.residentInput||c.dspDelayMs))throw std::invalid_argument("Audio workgroup requires resident input and no synthetic DSP sleep");
        if(c.dynamicTransitions&&c.scheduling!=WorkerScheduling::AudioWorkgroup)throw std::invalid_argument("Phase59 requires the resident Audio Workgroup path");
        if(c.transitionFailureForTest>2||(!c.dynamicTransitions&&c.transitionFailureForTest))throw std::invalid_argument("Invalid transition fault control");
        if(c.promotionFailureOnAttemptForTest>2)throw std::invalid_argument("Invalid promotion fault control");
        if(c.phaseProbeWindowCount>c.phaseProbeWindows.size())throw std::invalid_argument("Too many phase probe windows");
        if(c.lifecycleTestHooks.failStartBeforeWorker>3)throw std::invalid_argument("Invalid worker creation fault");
        for(std::size_t w=0;w<c.phaseProbeWindowCount;++w)if(c.phaseProbeWindows[w].first>=c.phaseProbeWindows[w].second)throw std::invalid_argument("Invalid phase probe window");
        if(seeking&&seekInput>input.frames)throw std::out_of_range("Seek input frame out of range");
        if(config.fastLocalSeek&&(!seeking||!config.residentInput||!config.localPrerollInputFrames||config.localPrerollInputFrames>input.rate*2ULL))throw std::invalid_argument("Invalid local seek configuration");
        error.reserve(256);input.validate();verified=elapsed();
        if(!seeking){
            inputLease->generation=session;
            inputLease->sha=input.identify(config.sourceSnapshotBytes);
            if(config.residentInput){input.makeResident();residentReady=elapsed();}
        }else if(config.residentInput&&input.residentBytes().empty())throw std::logic_error("Seek requires prepared resident input");
        inputSha=inputLease->sha;identified=elapsed();
        realtime=std::make_unique<RealtimeWorkerSupport>(config.scheduling==WorkerScheduling::AudioWorkgroup,input.rate);
        if(config.dynamicTransitions){operations.reserve(4096);transitionPlanner=std::make_unique<phase59::ProgressiveTransitionPlanner>(input.rate,input.frames,inputLease->generation,c.speedMicros,c.candidate);}
    }
    double elapsed()const{return origin.elapsed().wallSeconds;}
    std::shared_ptr<const phase56::AnalysisSnapshot> seekAnalysis(){
        std::shared_ptr<const phase56::AnalysisSnapshot> base;
        while(!(base=std::atomic_load(&inputLease->finalAnalysis))){
            check();if(inputLease->analysisFailed.load())throw std::runtime_error("Source analysis failed");
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        check();auto s=std::make_shared<phase56::AnalysisSnapshot>(*base);
        if(s->speedCount!=1||s->speedMicros[0]!=config.speedMicros){
            phase56::MapPrefixBuilder builder({config.speedMicros});
            for(std::size_t i=0;i<s->closedEventCount;++i)builder.close(s->events.at(i),s->anchors.at(i));
            builder.finish(s->featureThrough);
            auto ledger=std::make_shared<phase56::MemoryLedger>(64*1024*1024);ledger->owner=ledger;
            s->maps={};s->speedCount=1;s->speedMicros={};s->speedMicros[0]=config.speedMicros;
            s->maps[0]=s->maps[0].extend(builder.nodes[0],builder.nodes[0].size(),ledger);
            s->mapThroughNode=s->maps[0].size();
        }
        std::vector<long long> nodes;nodes.reserve(s->mapThroughNode);
        for(std::size_t i=0;i<s->mapThroughNode;++i)nodes.push_back(s->maps[0].at(i));
        const auto length=std::size_t(std::llround(input.frames*(1.0/(double(config.speedMicros)/1000000.0))));
        const TimeMap map(1024,std::move(nodes),{});
        const auto start=seekInput==input.frames?length:std::min(length,std::size_t(std::max(0LL,std::llround(map.outputPositionForInputSample(double(seekInput))))));
        if(config.loopEndInputFrame){
            const auto end=config.loopEndInputFrame==input.frames?length:std::min(length,std::size_t(std::max(0LL,std::llround(map.outputPositionForInputSample(double(config.loopEndInputFrame))))));
            if(end<=start)throw std::invalid_argument("ループ出力範囲が空です");
            loopOutputEnd=end;
            std::atomic_store(&fixedSeekMap,std::make_shared<const TimeMap>(map));
        }
        output=length;outputStart=start;published=start;consumed=start;seekMapReady=true;
        return s;
    }
    void stageSeekPcm(std::uint64_t generation,std::size_t offset,const float*const* p,std::size_t n){
        if(generation!=inputLease->generation||offset!=generated.load()||seekPcmCount)throw std::logic_error("Seek PCM identity/order");
        generated=offset+n;
        const auto skip=std::min(n,outputStart.load()>offset?outputStart.load()-offset:0);
        discarded.fetch_add(skip);seekPcmCount=n-skip;
        if(const auto end=loopOutputEnd.load())seekPcmCount=std::min(seekPcmCount,end>offset+skip?end-offset-skip:0);seekPcmOffset=0;
        for(std::size_t c=0;c<input.channels;++c)std::copy_n(p[c]+skip,seekPcmCount,seekPcm[c].data());
    }
    void flushSeekPcm(){
        const auto room=std::min(fifo.free(),lead-std::min(lead,fifo.available()));
        const auto n=std::min(room,seekPcmCount);if(!n)return;
        std::array<const float*,2> p{};for(std::size_t c=0;c<input.channels;++c)p[c]=seekPcm[c].data()+seekPcmOffset;
        const auto* delivered=envelope.apply(p.data(),published.load(),n,config.fastLocalSeek&&config.localPublicationFade,outputStart.load());
        if(!fifo.write(delivered,n))throw std::logic_error("Seek FIFO rejected PCM");
        if(config.verifyPcm){for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<input.channels;++c)seekInterleaved[i*input.channels+c]=delivered[c][i];seekHash.update(seekInterleaved.data(),n*input.channels*sizeof(float));}
        seekPcmOffset+=n;seekPcmCount-=n;published.fetch_add(n);
        if(firstPublished.load()<0)firstPublished=elapsed();
        if(published.load()-outputStart.load()>=std::min(lead,loopOutputEnd.load()?loopOutputEnd.load()-outputStart.load():lead)&&!ready.load()){
            rememberCheckpoint(true);
            {std::lock_guard lock(mutex);inputAtReady=received.load();readyTime=elapsed();ready=true;}
            changed.notify_all();
        }
    }
    void finishSeek(){
        std::lock_guard lock(mutex);dspDone=true;
        if(config.verifyPcm)pcmSha=seekHash.finish();
        if(!ready.load()){inputAtReady=received.load();readyTime=elapsed();ready=true;}
        changed.notify_all();
    }
    std::unique_ptr<phase57::ProgressiveSynthesisEngine> makeSynthesis(std::function<void()> validate){
        if(seeking){while(!seekMapReady.load()){check(true);std::this_thread::sleep_for(std::chrono::milliseconds(1));}
            if(!config.fastLocalSeek&&!config.loopEndInputFrame&&config.seekCheckpoints&&!config.recordWorkerProfile&&!config.detailedDiagnostics&&seekInput!=input.frames){
                std::shared_ptr<const phase57::ProgressiveSynthesisEngine> saved;std::size_t point=0;
                {std::lock_guard lock(inputLease->checkpointMutex);
                    for(const auto& cp:inputLease->checkpoints)if(cp.speed==config.speedMicros&&cp.output<=outputStart.load()&&cp.output>=point){saved=cp.state;point=cp.output;}}
                if(saved){auto engine=saved->cloneFixedCheckpoint(input.snapshotDescriptor(),input.residentBytes(),validate);
                    if(!engine)throw std::logic_error("Resident checkpoint identity changed");
                    engine->prepareCheckpointForEpoch();checkpointStart=point;lastCheckpointOutput=point;generated=point;return engine;}
            }
        }
        return std::make_unique<phase57::ProgressiveSynthesisEngine>(input.snapshotDescriptor(),config.speedMicros,inputLease->generation,std::move(validate),16*1024*1024,input.residentBytes());
    }
    void rememberCheckpoint(bool atReady=false){
        if(!seeking||config.fastLocalSeek||config.loopEndInputFrame||!config.seekCheckpoints||!activeSynthesis||ready.load()||realtime->active()||config.recordWorkerProfile||config.detailedDiagnostics)return;
        const auto point=activeSynthesis->frontier().published;
        if((savedCheckpoint&&point==lastCheckpointOutput)||(!atReady&&point-lastCheckpointOutput<input.rate*30ULL))return;
        auto copy=activeSynthesis->cloneFixedCheckpoint(input.snapshotDescriptor(),input.residentBytes());if(!copy)return;
        std::shared_ptr<const phase57::ProgressiveSynthesisEngine> immutable(std::move(copy));
        {std::lock_guard lock(inputLease->checkpointMutex);auto& saved=inputLease->checkpoints;
            if(!saved.empty()&&saved.back().speed==config.speedMicros&&point>=saved.back().output&&point-saved.back().output<input.rate*5ULL)saved.pop_back();
            if(saved.size()==2)saved.erase(saved.begin());saved.push_back({config.speedMicros,point,std::move(immutable)});++inputLease->checkpointBuilds;}
        lastCheckpointOutput=point;savedCheckpoint=true;
    }
    void initializeLocalIfNeeded(phase57::ProgressiveSynthesisEngine& engine){
        if(!config.fastLocalSeek||localInitialized)return;
        playback::StageClock timer;
        const auto start=engine.initializeFastLocal(seekInput,config.localPrerollInputFrames);
        if(start.requestedOutput!=outputStart.load())throw std::logic_error("Local seek map coordinate differs");
        generated=start.beginOutput;localSeed=start.seedInput;localBegin=start.beginOutput;
        localInitialized=true;localInitializeS=timer.elapsed().wallSeconds;
    }
    static void detailObserver(void* context,std::size_t stage,std::size_t scope,bool begin,std::uint64_t ns,double cpu)noexcept{
        auto& x=*static_cast<Impl*>(context);
        if(begin){if(x.stageDepth<x.stageStack.size())x.stageStack[x.stageDepth++]=x.currentStage.load();x.currentStage=(stage<<16)|scope;}
        else{x.currentStage=x.stageDepth?x.stageStack[--x.stageDepth]:UINT64_MAX;}
        if(x.details.size()>=x.config.diagnosticEventLimit){++x.detailDropped;return;}
        const auto base=std::chrono::duration_cast<std::chrono::nanoseconds>(x.origin.wall.time_since_epoch()).count();
        x.details.push_back({stage,scope,begin,double(std::int64_t(ns)-base)*1e-9,cpu,dspAllocations});
    }
    void detail(std::size_t stage,bool begin){if(config.detailedDiagnostics)detailObserver(this,stage,3,begin,
        std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(),playback::threadCpuSeconds());}
    struct DetailScope {
        Impl& x;std::size_t stage;
        DetailScope(Impl& owner,std::size_t s):x(owner),stage(s){x.detail(stage,true);}
        ~DetailScope(){x.detail(stage,false);}
    };
    struct AllocationScope {
        Impl& x;
        explicit AllocationScope(Impl& owner):x(owner){dspAllocations=0;countDspAllocations=x.config.detailedDiagnostics||x.config.scheduling==WorkerScheduling::AudioWorkgroup;}
        ~AllocationScope(){x.dspNewCalls=dspAllocations;x.dspAllocationsMeasured=countDspAllocations&&dspAllocationProbeAvailable;countDspAllocations=false;}
    };
    void sampleThread(){
        CpuEnd measured{samplerCpu};
        try{
            pthread_setname_np("Phase58 DSP sampler");pthread_set_qos_class_self_np(QOS_CLASS_UTILITY,0);
            samples.reserve(65536);
            const auto thread=pthread_mach_thread_np(dspWorker.native_handle());
            const auto retained=mach_port_mod_refs(mach_task_self(),thread,MACH_PORT_RIGHT_SEND,1);
            if(retained!=KERN_SUCCESS){++sampleErrors;return;}
            while(!cancelled.load()&&!failure.load()&&!dspDone.load()){
                ThreadSample r;thread_extended_info_data_t info{};mach_msg_type_number_t count=THREAD_EXTENDED_INFO_COUNT;
                r.beforeS=elapsed();r.stageBefore=currentStage.load();
                r.result=thread_info(thread,THREAD_EXTENDED_INFO,reinterpret_cast<thread_info_t>(&info),&count);
                r.stageAfter=currentStage.load();r.afterS=elapsed();
                if(r.result==KERN_SUCCESS){r.userNs=info.pth_user_time;r.systemNs=info.pth_system_time;r.state=info.pth_run_state;r.policy=info.pth_policy;r.currentPriority=info.pth_curpri;r.basePriority=info.pth_priority;r.maxPriority=info.pth_maxpriority;}
                else ++sampleErrors;
                if(samples.size()<65536)samples.push_back(r);else ++sampleDropped;
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            mach_port_deallocate(mach_task_self(),thread);
        }catch(const std::exception& e){fail(e.what());}
    }
    void check(bool dsp=false){if(cancelled.load()||failure.load())throw Cancelled{};
        // DSP sees only the private immutable byte snapshot. Original-path
        // validation belongs exclusively to the analysis/identity worker.
        if(!dsp)input.validate();}
    void fail(const char* message){
        // Failure can originate on the sampler or the demoted DSP thread.
        // Only records are shared here; analysis-owned queue indices and map
        // transactions are settled by their owner or after both workers join.
        {std::lock_guard lock(mutex);
            const auto publishFailure=[&]{if(!failure.exchange(true))error.assign(message,std::min<std::size_t>(std::char_traits<char>::length(message),256));};
            if(config.dynamicTransitions){std::lock_guard operationLock(operationMutex);
                for(auto& op:operations)if(op.state==phase59::OperationState::Pending||op.state==phase59::OperationState::Submitted||op.state==phase59::OperationState::Applied){op.state=phase59::OperationState::Cancelled;op.workerState=Phase39RequestState::Cancelled;}
                publishFailure();
            }else publishFailure();
        }
        changed.notify_all();
        realtime->signal();
    }
    void publish(std::shared_ptr<const phase56::AnalysisSnapshot> s){
        if(config.scheduling==WorkerScheduling::AudioWorkgroup){
            const auto* view=s.get();
            while(!borrowedMailbox.tryPublish(s)){
                if(cancelled.load()||failure.load())throw Cancelled{};
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            if(view->closedEventCount&&firstEvent.load()<0)firstEvent=elapsed();
            if(view->mapThroughNode>1&&firstMap.load()<0)firstMap=elapsed();
            {std::lock_guard lock(mutex);++version;}
            realtime->signal();return;
        }
        if(s->closedEventCount&&firstEvent.load()<0)firstEvent=elapsed();
        if(s->mapThroughNode>1&&firstMap.load()<0)firstMap=elapsed();
        {std::lock_guard lock(mutex);mailbox=std::move(s);++version;}
        changed.notify_all();
    }
    void cancelOperations(){
        std::lock_guard lock(operationMutex);
        for(auto& op:operations){
            if(op.generation&&op.generation==observedRequest.load()&&op.workerSeenS<0)op.workerSeenS=observedRequestS;
            if(op.state==phase59::OperationState::Pending||op.state==phase59::OperationState::Submitted||op.state==phase59::OperationState::Applied){
            op.state=phase59::OperationState::Cancelled;op.workerState=Phase39RequestState::Cancelled;
            }
        }
        pendingOperation=activeOperation=noOperation;
    }
    void finalizeTransition(){ // Both workers joined, normal owner only.
        if(pendingMap&&mapOperation!=noOperation){
            const bool accepted=mapOffered&&mapAckTag.load()==pendingMapTag&&mapAckAccepted.load();
            transitionPlanner->confirmPlan(accepted);
            if(accepted){std::lock_guard lock(operationMutex);auto& op=operations[mapOperation];if(op.state!=phase59::OperationState::Cancelled){op.state=phase59::OperationState::Applied;op.workerState=Phase39RequestState::Applied;}op.appliedS=mapAckS;op.consumedAtApply=mapAckConsumed;}
        }
        pendingMap.reset();mapOperation=noOperation;mapOffered=false;
        if(transitionPlanner)transitionHistory=transitionPlanner->historyCount();
    }
    // Runs on the normal analysis/control worker. Planning, all shared ownership
    // and destruction stay here. DSP only borrows the resulting immutable map.
    void transitionStep(const std::shared_ptr<const phase56::AnalysisSnapshot>& snapshot){
        if(!config.dynamicTransitions||!snapshot||cancelled.load()||failure.load())return;
        auto& planner=*transitionPlanner;
        // Diagnostic only, normal planning owner. A proposal changes only the
        // unpublished future; the consumed prefix is immutable even before ack.
        if(auto view=planner.view();view&&view->map.starts().size()>=2){
            const auto at=consumed.load();
            if(at<=std::size_t(view->map.starts().back()))
                positionMailbox.publish({session,view->version,at,std::min(input.frames,phase59::inverseInput(view->map,at)),elapsed()});
        }
        if(pendingMap){
            if(!mapOffered){auto lease=pendingMap;if(dynamicMailbox.tryPublish(lease)){pendingMapTag=dynamicMailbox.publishedTag();mapOffered=true;realtime->signal();}return;}
            if(mapAckTag.load()!=pendingMapTag)return;
            const bool accepted=mapAckAccepted.load();
            if(mapOperation!=noOperation){
                planner.confirmPlan(accepted);
                std::lock_guard lock(operationMutex);auto& op=operations[mapOperation];
                if(accepted){const bool terminal=cancelled.load()||failure.load();op.state=terminal?phase59::OperationState::Cancelled:phase59::OperationState::Applied;op.workerState=terminal?Phase39RequestState::Cancelled:Phase39RequestState::Applied;op.appliedS=mapAckS;op.consumedAtApply=mapAckConsumed;}
                else {++op.staleReplans;++transitionStale;op.planningDecided=false;op.workerState=(cancelled.load()||failure.load())?Phase39RequestState::Cancelled:Phase39RequestState::Requested;waitingAnalysisNodes=std::size_t(-1);}
            }else if(!accepted){mapOffered=false;return;}
            pendingMap.reset();mapOffered=false;mapOperation=noOperation;
        }
        if(cancelled.load()||failure.load())return;
        if(snapshot->receivedInputFrames!=lastPlannerReceived||snapshot->isFinal!=plannerSawFinal){
            planner.update(snapshot);lastPlannerReceived=snapshot->receivedInputFrames;plannerSawFinal=snapshot->isFinal;
            transitionMapPeak=std::max(transitionMapPeak.load(),planner.mapBytes());
            if(auto view=planner.view();view&&view->version!=(frontierMailbox.read().value_or(phase59::PlanningFrontier{}).mapVersion)){
                pendingMap=std::move(view);return;
            }
        }
        auto latest=frontierMailbox.read();if(!latest||!planner.view()||latest->mapVersion!=planner.view()->version)return;
        const auto& f=latest->dsp;const auto& modes=planner.view()->modes;
        const bool densityReady=modes.empty()||std::all_of(f.nextInput.begin(),f.nextInput.end(),[&](auto p){return p>modes.back().first;});
        {
            std::lock_guard lock(operationMutex);
            if(activeOperation!=noOperation){auto& op=operations[activeOperation];
                if(op.workerState==Phase39RequestState::Applied&&consumed.load()>=std::size_t(op.change.plan.completionOutputSample)&&densityReady){op.state=phase59::OperationState::Completed;op.completedS=elapsed();activeOperation=noOperation;}
            }
            if(dspDone.load()){for(auto& op:operations)if(op.state==phase59::OperationState::Pending||op.state==phase59::OperationState::Submitted){op.state=phase59::OperationState::Cancelled;op.workerState=Phase39RequestState::Cancelled;}return;}
            if(!renderingRequested.load())return;
            if(activeOperation==noOperation&&pendingOperation!=noOperation&&densityReady){
                auto& op=operations[pendingOperation];
                if(op.target==planner.tail().micros){op.state=phase59::OperationState::Duplicate;op.acceptance=Phase39RequestResult::Duplicate;pendingOperation=noOperation;return;}
                activeOperation=pendingOperation;pendingOperation=noOperation;op.state=phase59::OperationState::Submitted;op.workerState=Phase39RequestState::Requested;
                op.generation=++requestGeneration;op.plannerSeenS=elapsed();waitingAnalysisNodes=std::size_t(-1);
                announcedRequest=op.generation;realtime->signal();
            }
            if(activeOperation==noOperation||operations[activeOperation].workerState!=Phase39RequestState::Requested)return;
            auto& op=operations[activeOperation];if(observedRequest.load()!=op.generation)return;
            if(op.workerSeenS<0)op.workerSeenS=observedRequestS;
        }
        if(waitingAnalysisNodes==snapshot->mapThroughNode&&waitingAnalysisFinal==snapshot->isFinal)return;
        phase59::SpeedOperation op;
        {std::lock_guard lock(operationMutex);op=operations[activeOperation];}
        playback::StageClock timing;const auto began=elapsed();
        {std::lock_guard lock(operationMutex);auto& record=operations[activeOperation];record.planStartedS=began;record.planningDecided=false;
            record.frontier=f;record.publishedAtPlan=latest->published;record.analysisNodesAtPlan=snapshot->mapThroughNode;record.receivedInputAtPlan=snapshot->receivedInputFrames;record.finalAnalysisAtPlan=snapshot->isFinal;}
        phase59::PlanningResult result;
        try{
            if(config.transitionFailureForTest==1)throw std::runtime_error("Injected normal transition planner failure");
            if(config.transitionFailureForTest==2)throw std::bad_alloc();
            result=planner.plan({op.target},op.generation,op.logicalPresented,latest->published,f);
        }catch(...){const auto cost=timing.elapsed();transitionCpu=transitionCpu.load()+cost.threadCpuSeconds;transitionWall=transitionWall.load()+cost.wallSeconds;++transitionAttempts;
            std::lock_guard lock(operationMutex);auto& record=operations[activeOperation];record.planFinishedS=elapsed();record.planCpuS+=cost.threadCpuSeconds;record.planWallS+=cost.wallSeconds;++record.attempts;throw;}
        const auto cost=timing.elapsed();transitionCpu=transitionCpu.load()+cost.threadCpuSeconds;transitionWall=transitionWall.load()+cost.wallSeconds;++transitionAttempts;
        if(cancelled.load()||failure.load()){if(result.change.plan.applied())planner.confirmPlan(false);transitionHistory=planner.historyCount();return;}
        transitionMapPeak=std::max(transitionMapPeak.load(),planner.mapBytes());transitionHistory=planner.historyCount();
        {
            std::lock_guard lock(operationMutex);auto& record=operations[activeOperation];
            record.planStartedS=began;record.planFinishedS=elapsed();record.planCpuS+=cost.threadCpuSeconds;record.planWallS+=cost.wallSeconds;++record.attempts;
            record.frontier=f;record.publishedAtPlan=latest->published;
            record.analysisNodesAtPlan=snapshot->mapThroughNode;record.receivedInputAtPlan=snapshot->receivedInputFrames;record.finalAnalysisAtPlan=snapshot->isFinal;
            record.planningDecided=result.status==phase59::PlanningStatus::Decided;
            if(result.status==phase59::PlanningStatus::PendingAnalysis){++record.analysisDeferrals;++transitionDeferrals;waitingAnalysisNodes=snapshot->mapThroughNode;waitingAnalysisFinal=snapshot->isFinal;return;}
            record.change=result.change;
            if(result.limitReached)record.acceptance=Phase39RequestResult::LimitReached;
            if(!result.change.plan.applied()){record.state=phase59::OperationState::Rejected;record.workerState=Phase39RequestState::Rejected;activeOperation=noOperation;return;}
        }
        pendingMap=planner.view();mapOperation=activeOperation;
    }
    void analyze(){
        CpuEnd measured{analysisWorkerCpu};
        std::unique_ptr<phase56::ProgressiveAnalysisSession> a;
        try{
            std::uint64_t tid=0;pthread_threadid_np(nullptr,&tid);analysisThread=tid;
            analysisQos=pthread_set_qos_class_self_np(QOS_CLASS_UTILITY,0)==0;
            int relative=0;qos_class_t actual=QOS_CLASS_UNSPECIFIED;
            analysisQosQueried=pthread_get_qos_class_np(pthread_self(),&actual,&relative)==0;
            if(analysisQosQueried){analysisQosClass=actual;analysisQosRelative=relative;}
            pthread_setname_np("Phase58 analysis");
            analysisStart=elapsed();playback::StageClock cpu;
            std::shared_ptr<const phase56::AnalysisSnapshot> completed;
            if(seeking){completed=seekAnalysis();received=input.frames;}
            else{
                a=std::make_unique<phase56::ProgressiveAnalysisSession>(input.rate,input.channels,session,phase56::AnalysisLimits{},std::vector<std::uint32_t>{config.speedMicros});
                phase56::PinnedWavSource source(input.snapshotDescriptor(),session);std::size_t at=0;
                while(at<input.frames){check();if(config.analysisDelayMs)std::this_thread::sleep_for(std::chrono::duration<double,std::milli>(config.analysisDelayMs));
                    check();at+=source.appendNext(*a,config.analysisChunk);check();received=at;publish(a->getSnapshot());transitionStep(a->getSnapshot());}
                check();source.finish(*a);check();completed=a->getSnapshot();std::atomic_store(&inputLease->finalAnalysis,completed);
                const auto stats=a->statistics();snapshotPeak=stats.snapshotPeakBytes;snapshotCopies=stats.snapshotCopyBytes;
            }
            analysisEnd=elapsed();analysisDone=true;publish(completed);transitionStep(completed);
            analysisCpu=cpu.elapsed().threadCpuSeconds;
            // Continue validating the selected source after analysis EOS. The
            // control/audio owner joins this worker before releasing the FD.
            while(!cancelled.load()&&!failure.load()){
                transitionStep(completed);
                std::unique_lock lock(mutex);changed.wait_for(lock,std::chrono::milliseconds(config.dynamicTransitions?1:10),[&]{return cancelled.load()||failure.load();});lock.unlock();
                // An EOF seek can remain Ready/Paused with an empty FIFO.
                // Retain its source-identity watcher until the owner stops it.
                if(!seeking&&dspDone.load()&&fifo.available()==0)break;check();
            }
            if(config.dynamicTransitions)transitionStep(completed);
        }catch(const Cancelled&){if(a)a->cancel();}
        catch(const std::exception& e){if(!seeking&&dspDone.load()&&fifo.available()==0&&!failure.load())return;
            if(!analysisDone.load())inputLease->analysisFailed=true;
            if(a&&!analysisDone.load()){try{a->failInput(session,phase56::AnalysisError::InputRead);}catch(...){}}fail(e.what());}
        changed.notify_all();
    }
    void synthesizeRealtime(){
        CpuEnd measured{dspWorkerCpu};AllocationScope allocations{*this};
        std::uint64_t activeAllocationBase=0;
        const auto demote=[&]()noexcept{
            if(realtime->active()){
                realtimeNewCalls=realtimeNewCalls.load()+dspAllocations-activeAllocationBase;
                realtimeAllocationsMeasured=countDspAllocations&&dspAllocationProbeAvailable;
            }
            return realtime->demote();
        };
        try{
            std::uint64_t tid=0;pthread_threadid_np(nullptr,&tid);dspThread=tid;
            pthread_setname_np("Phase58 realtime DSP");dspQos=pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED,0)==0;
            int relative=0;qos_class_t actual=QOS_CLASS_UNSPECIFIED;
            dspQosQueried=pthread_get_qos_class_np(pthread_self(),&actual,&relative)==0;
            if(dspQosQueried){dspQosClass=actual;dspQosRelative=relative;}
            if(config.detailedDiagnostics)prepareDiagnosticStorage(details,config.diagnosticEventLimit);
            phase57::ProgressiveSynthesisEngine* activeEngine=nullptr;
            auto ownedEngine=makeSynthesis([&]{
                if(activeEngine){if(cancelled.load()||failure.load())activeEngine->cancel();}
                else check(true);
            });auto& engine=*ownedEngine;activeSynthesis=&engine;
            activeEngine=&engine;
            output=config.dynamicTransitions?0:std::size_t(std::llround(input.frames*(1.0/(double(config.speedMicros)/1000000.0))));
            if(!checkpointStart.load()){if(config.dynamicTransitions)engine.enableDynamicTransitions();else engine.setDeclaredFinalOutputFrames(output.load());}
            if(config.recordWorkerProfile){prepareDiagnosticStorage(profiles,65536);engine.enableWorkProfiling();}
            if(config.detailedDiagnostics)engine.setWorkObserver(detailObserver,this);
            Phase45PcmDigest hash;std::vector<float> interleaved(config.verifyPcm?2048*input.channels:0);
            std::uint64_t seenTag=decltype(borrowedMailbox)::initialTag,seen=0;
            std::uint64_t seenMapTag=decltype(dynamicMailbox)::initialTag,currentMapVersion=0;
            const auto publishFrontier=[&]{if(config.dynamicTransitions)frontierMailbox.publish({engine.dspFrontier(),currentMapVersion,published.load(),consumed.load(),elapsed()});};
            bool needSnapshot=true,finalSnapshot=false;double previousPublished=-1,atPublication=0,gap=0;
            unsigned promotionAttempts=0;
            // Construct this owning function once before promotion. No per-block
            // std::function allocation, snapshot ownership, mutex or notification.
            const phase57::ProgressiveSynthesisEngine::Sink sink=[&](auto generation,auto offset,const float*const* p,std::size_t n){
                if(cancelled.load()||failure.load()){engine.cancel();return;}
                if(seeking){stageSeekPcm(generation,offset,p,n);return;}
                if(generation!=inputLease->generation||offset!=published.load())throw std::logic_error("PCM identity/offset mismatch");
                generated=offset+n;if(firstGenerated.load()<0)firstGenerated=elapsed();
                p=envelope.apply(p,offset,n,false,0);
                if(config.verifyPcm){DetailScope region{*this,15};for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<input.channels;++c)interleaved[i*input.channels+c]=p[c][i];hash.update(interleaved.data(),n*input.channels*sizeof(float));}
                {DetailScope region{*this,16};if(!fifo.write(p,n))throw std::runtime_error("FIFO rejected PCM write");}
                atPublication=elapsed();gap=previousPublished<0?0:atPublication-previousPublished;previousPublished=atPublication;maxPublicationGap=std::max(maxPublicationGap.load(),gap);
                published=offset+n;if(firstPublished.load()<0){inputAtFirstPcm=received.load();firstPublished=atPublication;}
                if(!analysisDone.load())nonEosPublished=offset+n;
                if(offset+n>=lead&&!ready.load()){
                    // Promotion is armed by the normal owner only AFTER Ready.
                    {std::lock_guard lock(mutex);inputAtReady=received.load();readyTime=elapsed();ready=true;}
                    changed.notify_all();
                }
            };
            // Keep the engine/buffers alive until the worker has left its group
            // and restored normal scheduling, including exception/cancel paths.
            try{
                while(!cancelled.load()&&!failure.load()){
                    if(renderingRequested.load()&&ready.load()&&!realtime->active()){
                        activeAllocationBase=dspAllocations;
                        if(++promotionAttempts==config.promotionFailureOnAttemptForTest)throw std::runtime_error("Injected pre-promotion failure");
                        if(!realtime->promote())throw std::runtime_error("DSP realtime promotion failed");
                    }else if(!renderingRequested.load()&&realtime->active()){
                        if(!demote())throw std::runtime_error("DSP normal-policy restore failed");
                    }
                    if(seeking){
                        flushSeekPcm();
                        if((loopOutputEnd.load()&&published.load()>=loopOutputEnd.load())||(seekDspFinished&&!seekPcmCount)||(seekMapReady.load()&&output.load()&&outputStart.load()==output.load())){demote();finishSeek();return;}
                        // Honour promotion/demotion even when a partial block
                        // is waiting behind a full Ready FIFO.
                        if(seekPcmCount){realtime->waitForSignal();continue;}
                    }
                    if(auto lease=borrowedMailbox.acquire(seenTag)){
                        DetailScope region{*this,12};
                        const auto* view=lease->get();engine.supplyBorrowedSnapshot(view);
                        finalSnapshot=view->isFinal;seenTag=lease->tag();seen=seenTag>>2;lease->commit();needSnapshot=false;
                    }
                    if(config.dynamicTransitions){
                        if(auto lease=dynamicMailbox.acquire(seenMapTag)){
                            const auto* view=lease->get();const auto tag=lease->tag();
                            const bool accepted=engine.trySupplyBorrowedDynamicMap(view);
                            if(accepted){currentMapVersion=view->version;if(view->final)output=view->outputFrames;lease->commit();needSnapshot=false;}
                            seenMapTag=tag;publishFrontier();mapAckAccepted=accepted;mapAckS=elapsed();mapAckConsumed=consumed.load();mapAckTag=tag;
                        }
                        const auto request=announcedRequest.load();
                        if(request&&request!=observedRequest.load()){
                            const auto recognized=elapsed();publishFrontier();observedRequestS=recognized;observedRequest=request;
                        }
                    }
                    if(needSnapshot){
                        DetailScope region{*this,10};playback::StageClock wait;++analysisWaits;
                        realtime->waitForSignal();analysisWait=analysisWait.load()+wait.elapsed().wallSeconds;continue;
                    }
                    if(!config.dynamicTransitions||currentMapVersion)initializeLocalIfNeeded(engine);
                    if(seeking?fifo.available()>=lead:(fifo.free()<2048||fifo.available()+2048>lead)){
                        DetailScope region{*this,13};playback::StageClock wait;
                        realtime->waitForSignal();backpressureWait=backpressureWait.load()+wait.elapsed().wallSeconds;continue;
                    }
                    playback::StageClock block;const auto began=elapsed();const auto fifoBefore=fifo.available();const auto startOutput=published.load();atPublication=0;gap=0;
                    if(config.detailedDiagnostics){
                        bool observe=config.phaseProbeWindowCount==0;
                        for(std::size_t w=0;w<config.phaseProbeWindowCount;++w)
                            observe|=startOutput>=config.phaseProbeWindows[w].first&&startOutput<config.phaseProbeWindows[w].second;
                        engine.setWorkObserverActive(observe);
                    }
                    if(!realtime->beginInterval())throw std::runtime_error("DSP work interval start failed");
                    phase57::SynthesisState state;
                    try{DetailScope region{*this,14};state=engine.advance(sink);}
                    catch(...){realtime->finishInterval();demote();generated=engine.frontier().generated;throw;}
                    if(!realtime->finishInterval())throw std::runtime_error("DSP work interval finish failed");
                    if(seeking)rememberCheckpoint();
                    publishFrontier();
                    const auto t=block.elapsed();dspCpu=dspCpu.load()+t.threadCpuSeconds;maxDspWall=std::max(maxDspWall.load(),t.wallSeconds);maxDspCpu=std::max(maxDspCpu.load(),t.threadCpuSeconds);
                    if(config.recordWorkerProfile){
                        if(profiles.size()<65536)profiles.push_back({startOutput,published.load(),fifoBefore,fifo.available(),received.load(),seen,finalSnapshot,began,atPublication,t.wallSeconds,t.threadCpuSeconds,gap,engine.workProfile(),realtime->active(),currentMapVersion,realtime->active()?realtime->lastInterval():RealtimeIntervalTiming{}});else ++profileDropped;
                    }
                    if(cancelled.load()||failure.load())break;
                    if(state==phase57::SynthesisState::NeedsMoreAnalysis||state==phase57::SynthesisState::NeedsMoreInput){needSnapshot=true;continue;}
                    if(state==phase57::SynthesisState::Finished){
                        if(seeking){seekDspFinished=true;continue;}
                        if(!demote())throw std::runtime_error("DSP final normal-policy restore failed");
                        if(engine.frontier().published!=output.load())throw std::logic_error("Final output length differs");
                        {std::lock_guard lock(mutex);if(config.verifyPcm)pcmSha=hash.finish();
                            dspDone=true;if(published.load()&&!ready.load()){inputAtReady=received.load();readyTime=elapsed();ready=true;}}
                        changed.notify_all();return;
                    }
                    if(state!=phase57::SynthesisState::Produced)throw std::runtime_error("Unexpected realtime synthesis state");
                }
                if(!demote())throw std::runtime_error("DSP cancelled normal-policy restore failed");
            }catch(...){demote();throw;}
        }catch(const Cancelled&){}
        catch(const std::exception& e){demote();fail(e.what());}
        changed.notify_all();
    }
    void synthesize(){
        if(config.scheduling==WorkerScheduling::AudioWorkgroup){synthesizeRealtime();return;}
        CpuEnd measured{dspWorkerCpu};
        AllocationScope allocations{*this};
        try{
            std::uint64_t tid=0;pthread_threadid_np(nullptr,&tid);dspThread=tid;
            dspQos=pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED,0)==0;
            int relative=0;qos_class_t actual=QOS_CLASS_UNSPECIFIED;
            dspQosQueried=pthread_get_qos_class_np(pthread_self(),&actual,&relative)==0;
            if(dspQosQueried){dspQosClass=actual;dspQosRelative=relative;}
            pthread_setname_np("Phase58 DSP");
            if(config.detailedDiagnostics)details.reserve(config.diagnosticEventLimit);
            auto ownedEngine=makeSynthesis([this]{check(true);});auto& engine=*ownedEngine;activeSynthesis=&engine;
            output=std::size_t(std::llround(input.frames*(1.0/(double(config.speedMicros)/1000000.0))));
            if(!checkpointStart.load())engine.setDeclaredFinalOutputFrames(output.load());
            if(config.recordWorkerProfile){profiles.reserve(65536);engine.enableWorkProfiling();}
            if(config.detailedDiagnostics)engine.setWorkObserver(detailObserver,this);
            Phase45PcmDigest hash;std::vector<float> interleaved(config.verifyPcm?2048*input.channels:0);
            std::uint64_t seen=0;
            bool needSnapshot=true,finalSnapshot=false;double previousPublished=-1;
            while(!cancelled.load()&&!failure.load()){
                if(seeking){
                    flushSeekPcm();
                    if((loopOutputEnd.load()&&published.load()>=loopOutputEnd.load())||(seekDspFinished&&!seekPcmCount)||(seekMapReady.load()&&output.load()&&outputStart.load()==output.load())){finishSeek();return;}
                    if(seekPcmCount){std::this_thread::sleep_for(std::chrono::milliseconds(1));continue;}
                }
                std::shared_ptr<const phase56::AnalysisSnapshot> next;
                if(needSnapshot){
                    DetailScope region{*this,10};
                    playback::StageClock wait;std::unique_lock lock(mutex);++analysisWaits;
                    changed.wait(lock,[&]{return cancelled.load()||failure.load()||version!=seen;});
                    analysisWait=analysisWait.load()+wait.elapsed().wallSeconds;
                    if(cancelled.load()||failure.load())break;
                    next=mailbox;seen=version;needSnapshot=false;
                }else{
                    DetailScope region{*this,11};
                    std::lock_guard lock(mutex);if(version!=seen){next=mailbox;seen=version;}
                }
                if(next){
                    DetailScope region{*this,12};
                    engine.supplySnapshot(next);
                    finalSnapshot=next->isFinal;
                }
                initializeLocalIfNeeded(engine);
                if(seeking?fifo.available()>=lead:(fifo.free()<2048||fifo.available()+2048>lead)){
                    DetailScope region{*this,13};
                    playback::StageClock wait;std::unique_lock lock(mutex);
                    // Callback only reads atomics/FIFO. A bounded 2ms worker
                    // sleep supplies backpressure without callback-side wakeups.
                    changed.wait_for(lock,std::chrono::milliseconds(2),[&]{return cancelled.load()||failure.load()||(fifo.free()>=2048&&fifo.available()+2048<=lead);});
                    backpressureWait=backpressureWait.load()+wait.elapsed().wallSeconds;continue;
                }
                check(true);playback::StageClock block;const auto began=elapsed();const auto fifoBefore=fifo.available();const auto startOutput=published.load();double atPublication=0,gap=0;
                if(config.dspDelayMs)std::this_thread::sleep_for(std::chrono::duration<double,std::milli>(config.dspDelayMs));
                phase57::SynthesisState state;
                try{DetailScope region{*this,14};state=engine.advance([&](auto generation,auto offset,const float*const* p,std::size_t n){
                    if(seeking){check(true);stageSeekPcm(generation,offset,p,n);return;}
                    check(true);if(generation!=inputLease->generation||offset!=published.load())throw std::logic_error("PCM identity/offset mismatch");
                    generated=offset+n;if(firstGenerated.load()<0)firstGenerated=elapsed();
                    p=envelope.apply(p,offset,n,false,0);
                    if(config.verifyPcm){DetailScope digestRegion{*this,15};for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<input.channels;++c)interleaved[i*input.channels+c]=p[c][i];hash.update(interleaved.data(),n*input.channels*sizeof(float));}
                    {DetailScope fifoRegion{*this,16};if(!fifo.write(p,n))throw std::runtime_error("FIFO rejected PCM write");}
                    atPublication=elapsed();gap=previousPublished<0?0:atPublication-previousPublished;previousPublished=atPublication;maxPublicationGap=std::max(maxPublicationGap.load(),gap);
                    published=offset+n;if(firstPublished.load()<0){inputAtFirstPcm=received.load();firstPublished=atPublication;}
                    if(!analysisDone.load())nonEosPublished=offset+n;
                    if(offset+n>=lead&&!ready.load()){
                        // Publish the condition under the waiter's mutex so
                        // notify cannot fall between its predicate and park.
                        std::lock_guard lock(mutex);inputAtReady=received.load();readyTime=elapsed();ready=true;
                    }changed.notify_all();
                });}catch(...){generated=engine.frontier().generated;throw;}
                if(seeking)rememberCheckpoint();
                const auto t=block.elapsed();dspCpu=dspCpu.load()+t.threadCpuSeconds;maxDspWall=std::max(maxDspWall.load(),t.wallSeconds);maxDspCpu=std::max(maxDspCpu.load(),t.threadCpuSeconds);
                if(config.recordWorkerProfile&&published.load()!=startOutput){
                    if(profiles.size()<65536)profiles.push_back({startOutput,published.load(),fifoBefore,fifo.available(),received.load(),seen,finalSnapshot,began,atPublication,t.wallSeconds,t.threadCpuSeconds,gap,engine.workProfile()});else ++profileDropped;
                }
                if(state==phase57::SynthesisState::NeedsMoreAnalysis||state==phase57::SynthesisState::NeedsMoreInput){needSnapshot=true;continue;}
                if(state==phase57::SynthesisState::Finished){
                    if(seeking){seekDspFinished=true;continue;}
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
    void lifecycleEvent(LifecycleTestPoint point)noexcept{
        if(config.lifecycleTestHooks.event)config.lifecycleTestHooks.event(config.lifecycleTestHooks.context,point,session);
    }
    void stop(){
        if(lifecycle.load(std::memory_order_acquire)==LifecycleState::Finalized)return;
        lifecycle.store(LifecycleState::Stopping,std::memory_order_release);
        {std::lock_guard lock(mutex);cancelled=true;}
        renderingRequested=false;realtime->signal();changed.notify_all();
        // No data/operation mutex held while joining. The sampler's native_handle
        // borrow ends before the owner joins/modifies dspWorker.
        lifecycleEvent(LifecycleTestPoint::BeforeJoin);
        lifecycleEvent(LifecycleTestPoint::Joining);
        if(sampler.joinable())sampler.join();
        if(analysisWorker.joinable())analysisWorker.join();
        if(dspWorker.joinable())dspWorker.join();
        lifecycleEvent(LifecycleTestPoint::JoinedBeforeFinalize);
        if(config.dynamicTransitions){finalizeTransition();cancelOperations();}
        lifecycleEvent(LifecycleTestPoint::BeforeFinalPublish);
        lifecycle.store(LifecycleState::Finalized,std::memory_order_release);
    }
};
RealtimePipeline::RealtimePipeline(const std::filesystem::path& p,Configuration c):impl_(std::make_unique<Impl>(p,c)){}
RealtimePipeline::RealtimePipeline(std::unique_ptr<Impl> p):impl_(std::move(p)){}
RealtimePipeline::~RealtimePipeline(){impl_->stop();}
void RealtimePipeline::start(){auto& x=*impl_;
    if(x.lifecycle.load(std::memory_order_acquire)!=LifecycleState::Unstarted||x.started.exchange(true))throw std::logic_error("Create a fresh playback session");
    x.lifecycle.store(LifecycleState::Starting,std::memory_order_release);
    const auto fault=[&](unsigned worker){if(x.config.lifecycleTestHooks.failStartBeforeWorker==worker)throw std::runtime_error("Injected worker creation failure");};
    try{
        fault(1);x.analysisWorker=std::thread([&x]{x.analyze();x.lifecycleEvent(LifecycleTestPoint::WorkerExit);});
        fault(2);x.dspWorker=std::thread([&x]{x.synthesize();x.lifecycleEvent(LifecycleTestPoint::WorkerExit);});
        if(x.config.sampleDspThread){fault(3);x.sampler=std::thread([&x]{x.sampleThread();x.lifecycleEvent(LifecycleTestPoint::WorkerExit);});}
        x.lifecycle.store(LifecycleState::Running,std::memory_order_release);
    }catch(...){x.stop();throw;}}
bool RealtimePipeline::waitUntilReady(std::chrono::milliseconds timeout){auto& x=*impl_;std::unique_lock lock(x.mutex);x.changed.wait_for(lock,timeout,[&]{return x.ready.load()||x.failure.load()||x.cancelled.load();});return x.ready.load()&&!x.failure.load()&&!x.cancelled.load();}
bool RealtimePipeline::setRealtimeRendering(bool active,std::chrono::milliseconds timeout){
    auto& x=*impl_;if(x.config.scheduling!=WorkerScheduling::AudioWorkgroup)return true;
    if(active&&(!x.started.load()||!x.ready.load()||x.failure.load()||x.cancelled.load()))return false;
    x.renderingRequested=active;x.realtime->signal();const auto end=std::chrono::steady_clock::now()+timeout;
    while(std::chrono::steady_clock::now()<end){
        if(x.failure.load()||x.cancelled.load())return false;
        if(active?(x.realtime->active()||x.dspDone.load()):!x.realtime->active())return true;
        std::this_thread::sleep_for(std::chrono::microseconds(100));
    }return false;
}
void RealtimePipeline::stop(){impl_->stop();}
RenderResult RealtimePipeline::pullAudio(float*const* p,std::size_t n)noexcept{
    auto& x=*impl_;RenderResult r;r.outputBefore=x.consumed.load(std::memory_order_relaxed);r.fifoBefore=x.fifo.available();
    const auto end=x.loopOutputEnd.load()?x.loopOutputEnd.load():x.output.load(std::memory_order_acquire);r.wanted=end?(end>r.outputBefore?std::min(n,end-r.outputBefore):0):n;
    if(x.cancelled.load()||x.failure.load())r.wanted=0;
    r.received=x.fifo.read(p,r.wanted);x.consumed.fetch_add(r.received,std::memory_order_relaxed);
    for(std::size_t c=0;c<x.input.channels;++c)std::fill(p[c]+r.received,p[c]+n,0.0f);
    const auto missing=r.wanted-r.received;
    if(missing){x.missing.fetch_add(missing);x.missingCalls.fetch_add(1);x.consecutiveMissing=r.received?missing:x.consecutiveMissing+missing;maximum(x.maxMissing,x.consecutiveMissing);}else x.consecutiveMissing=0;
    return r;
}
bool RealtimePipeline::finished()const noexcept{return impl_->dspDone.load();}
FifoCursors RealtimePipeline::diagnosticFifoCursors()const noexcept{return {impl_->fifo.readPosition(),impl_->fifo.writePosition()};}
std::optional<PositionSample> RealtimePipeline::positionSample()const noexcept{
    if(auto map=std::atomic_load(&impl_->fixedSeekMap)){const auto at=impl_->consumed.load();return PositionSample{impl_->session,0,at,std::min(impl_->input.frames,phase59::inverseInput(*map,at)),impl_->elapsed()};}
    return impl_->positionMailbox.read();
}
bool RealtimePipeline::drained()const noexcept{return finished()&&!available();}
bool RealtimePipeline::failed()const noexcept{return impl_->failure.load();}
phase59::RequestReceipt RealtimePipeline::requestSpeed(std::uint32_t speed,std::size_t position,std::uint64_t expectedSession,std::uint64_t expectedGeneration){
    auto& x=*impl_;std::lock_guard lock(x.operationMutex);
    const bool invalid=!x.config.dynamicTransitions||!phase59::formalSpeed(speed);
    const bool stopped=!x.started.load()||x.cancelled.load()||x.failure.load()||x.dspDone.load()||(expectedSession&&expectedSession!=x.session)||(expectedGeneration&&expectedGeneration!=x.inputLease->generation);
    if(x.operations.size()>=4096)return {0,invalid?Phase39RequestResult::Invalid:stopped?Phase39RequestResult::Stopped:Phase39RequestResult::LimitReached};
    phase59::SpeedOperation op;op.id=x.operations.size()+1;op.session=x.session;op.inputGeneration=x.inputLease->generation;op.target=speed;op.logicalPresented=position;op.acceptedS=x.elapsed();
    if(invalid){op.acceptance=Phase39RequestResult::Invalid;op.change.plan.outcome=Phase39Outcome::Invalid;op.state=phase59::OperationState::Rejected;}
    else if(stopped){
        op.acceptance=Phase39RequestResult::Stopped;op.state=phase59::OperationState::Rejected;
    }else{
        if(x.pendingOperation!=Impl::noOperation)x.operations[x.pendingOperation].state=phase59::OperationState::Replaced;
        x.pendingOperation=x.operations.size();
    }
    x.operations.push_back(op);return {op.id,op.acceptance};
}
std::vector<phase59::SpeedOperation> RealtimePipeline::speedOperations()const{std::lock_guard lock(impl_->operationMutex);return impl_->operations;}
TimeMap RealtimePipeline::dynamicTimeMap()const{const auto& x=*impl_;if(x.lifecycle.load(std::memory_order_acquire)==LifecycleState::Finalized)if(auto map=std::atomic_load(&x.fixedSeekMap))return *map;if(x.lifecycle.load(std::memory_order_acquire)!=LifecycleState::Finalized||!x.transitionPlanner||!x.transitionPlanner->view())throw std::logic_error("Joined dynamic session required");return x.transitionPlanner->view()->map;}
std::size_t RealtimePipeline::available()const noexcept{return impl_->fifo.available();}
std::uint32_t RealtimePipeline::sampleRate()const noexcept{return impl_->input.rate;}
std::size_t RealtimePipeline::channels()const noexcept{return impl_->input.channels;}
std::size_t RealtimePipeline::inputFrames()const noexcept{return impl_->input.frames;}
std::size_t RealtimePipeline::outputStartFrame()const noexcept{return impl_->outputStart.load();}
std::uint64_t RealtimePipeline::inputGeneration()const noexcept{return impl_->inputLease->generation;}
std::unique_ptr<RealtimePipeline> RealtimePipeline::createSeek(std::size_t frame,std::uint32_t speed)const{
    auto& x=*impl_;if(x.failure.load()||x.cancelled.load())throw std::logic_error("Seek from a failed/stopped epoch");
    auto c=x.config;if(c.loopEndInputFrame&&c.scheduling==WorkerScheduling::AudioWorkgroup)c.dynamicTransitions=true;c.loopEndInputFrame=0;c.speedMicros=speed;c.fastLocalSeek=false;c.localPrerollInputFrames=0;
    return std::unique_ptr<RealtimePipeline>(new RealtimePipeline(std::make_unique<Impl>(x.inputLease,c,true,frame)));
}
std::unique_ptr<RealtimePipeline> RealtimePipeline::createFastLocalSeek(std::size_t frame,std::uint32_t speed,std::size_t preroll)const{
    auto& x=*impl_;if(x.failure.load()||x.cancelled.load())throw std::logic_error("Seek from a failed/stopped epoch");
    auto c=x.config;c.speedMicros=speed;c.fastLocalSeek=true;c.localPrerollInputFrames=preroll?preroll:x.input.rate/2;
    return std::unique_ptr<RealtimePipeline>(new RealtimePipeline(std::make_unique<Impl>(x.inputLease,c,true,frame)));
}
std::unique_ptr<RealtimePipeline> RealtimePipeline::createLoopSeek(std::size_t start,std::size_t end,std::uint32_t speed)const{
    if(start>=end||end>inputFrames())throw std::invalid_argument("ループは入力半開区間[A,B)です");
    auto result=createSeek(start,speed);auto& c=result->impl_->config;
    c.dynamicTransitions=false;c.loopEndInputFrame=end;
    result->impl_->transitionPlanner.reset();return result;
}
std::size_t RealtimePipeline::loopOutputEndFrame()const noexcept{return impl_->loopOutputEnd.load();}
std::size_t RealtimePipeline::fixedOutputFrameForInput(std::size_t frame)const{
    const auto& x=*impl_;if(frame>x.input.frames)throw std::out_of_range("入力フレーム");
    for(const auto& op:speedOperations())if(op.acceptance==Phase39RequestResult::Accepted)throw std::logic_error("動的速度計画のある区間はA復帰でループを有効化してください");
    auto snapshot=std::atomic_load(&x.inputLease->finalAnalysis);if(!snapshot)throw std::logic_error("確定解析が必要です");
    phase56::MapPrefixBuilder builder({x.config.speedMicros});
    for(std::size_t i=0;i<snapshot->closedEventCount;++i)builder.close(snapshot->events.at(i),snapshot->anchors.at(i));
    builder.finish(snapshot->featureThrough);TimeMap map(1024,std::move(builder.nodes[0]),{});
    const auto length=std::size_t(std::llround(x.input.frames/(x.config.speedMicros/1000000.)));
    return frame==x.input.frames?length:std::min(length,std::size_t(std::max(0LL,std::llround(map.outputPositionForInputSample(double(frame))))));
}
void RealtimePipeline::requestRetireFade(bool fade){impl_->envelope.retireRequested=fade;}
std::unique_ptr<RealtimePipeline> RealtimePipeline::createInteractiveSeek(std::size_t frame,std::uint32_t speed,std::size_t preroll)const{
    auto result=createFastLocalSeek(frame,speed,preroll);result->impl_->config.localPublicationFade=false;return result;
}
bool RealtimePipeline::finalAnalysisAvailable()const noexcept{return bool(std::atomic_load(&impl_->inputLease->finalAnalysis));}
bool RealtimePipeline::retireFadeDrained()const noexcept{const auto& x=*impl_;const auto end=x.envelope.retireEnd.load();return (end&&x.consumed.load()>=end)||drained();}
double RealtimePipeline::elapsedSeconds()const noexcept{return impl_->elapsed();}
Diagnostics RealtimePipeline::diagnostics()const{
    const auto& x=*impl_;Diagnostics d;std::lock_guard lock(x.mutex);
    d.lifecycle=x.lifecycle.load(std::memory_order_acquire);d.finalDataAvailable=d.lifecycle==LifecycleState::Finalized;
    d.session=x.session;d.analysisThread=x.analysisThread;d.dspThread=x.dspThread;d.snapshotVersion=x.version;
    d.inputGeneration=x.inputLease->generation;d.outputStartFrame=x.outputStart;d.discardedFrames=x.discarded;d.reusedInput=d.reusedAnalysis=x.seeking;
    d.sourceHashPasses=x.input.hashes();d.sourceSnapshotCreations=x.input.snapshots();d.residentLockCalls=x.input.locks();
    d.checkpointUsed=x.checkpointStart.load()!=0;d.checkpointStartFrame=x.checkpointStart;
    d.fastLocalSeek=x.config.fastLocalSeek;d.localSeedInput=x.localSeed;d.localBeginOutput=x.localBegin;
    d.localPrerollInputFrames=x.config.localPrerollInputFrames;d.localInitializeS=x.localInitializeS;
    {std::lock_guard checkpointLock(x.inputLease->checkpointMutex);d.checkpointResidentStates=x.inputLease->checkpoints.size();d.checkpointBuilds=x.inputLease->checkpointBuilds;}
    d.inputFrames=x.input.frames;d.receivedInput=x.received;d.generated=x.generated;d.published=x.published;d.consumed=x.consumed;d.outputFrames=x.output;
    d.inputAtFirstPcm=x.inputAtFirstPcm;d.inputAtReady=x.inputAtReady;d.nonEosPublished=x.nonEosPublished;
    d.sourceSnapshotBytes=x.input.snapshotBytes();d.analysisWorkerCpuS=x.analysisWorkerCpu;
    d.residentInputBytes=x.input.residentBytes().size();d.residentReadyS=x.residentReady;d.renderingRequested=x.renderingRequested;
    d.inputSamplesPrevalidated=!x.input.residentBytes().empty();
    d.dynamicTransitions=x.config.dynamicTransitions;d.transitionHistory=x.transitionHistory;d.transitionMapPeakBytes=x.transitionMapPeak;
    d.transitionPlanAttempts=x.transitionAttempts;d.transitionStaleReplans=x.transitionStale;d.transitionAnalysisDeferrals=x.transitionDeferrals;d.transitionPlanCpuS=x.transitionCpu;d.transitionPlanWallS=x.transitionWall;
    {std::lock_guard operationLock(x.operationMutex);d.transitionOperations=x.operations.size();}
    if(d.finalDataAvailable)d.transitionMapOwners=x.dynamicMailbox.ownerCount();
    d.scheduling=x.realtime->metrics();d.realtimeNewCalls=x.realtimeNewCalls;d.realtimeAllocationsMeasured=x.realtimeAllocationsMeasured;
    if(d.finalDataAvailable)d.borrowedSnapshotOwners=x.borrowedMailbox.ownerCount();
    d.fifoHighWater=x.fifo.highWater();d.snapshotPeakBytes=x.snapshotPeak;d.snapshotCopyBytes=x.snapshotCopies;
    d.missingFrames=x.missing;d.missingCalls=x.missingCalls;d.maxConsecutiveMissing=x.maxMissing;d.rejectedWrites=x.fifo.rejectedWrites();d.analysisWaits=x.analysisWaits;
    d.verifiedS=x.verified;d.identifiedS=x.identified;d.analysisStartS=x.analysisStart;d.firstEventS=x.firstEvent;d.firstMapS=x.firstMap;
    d.firstGeneratedS=x.firstGenerated;d.firstPublishedS=x.firstPublished;d.readyS=x.readyTime;d.analysisDoneS=x.analysisEnd;
    d.analysisCpuS=x.analysisCpu;d.dspCpuS=x.dspCpu;d.maxDspWallS=x.maxDspWall;d.analysisWaitS=x.analysisWait;d.backpressureWaitS=x.backpressureWait;
    d.dspWorkerCpuS=x.dspWorkerCpu;d.maxDspCpuS=x.maxDspCpu;d.maxPublicationGapS=x.maxPublicationGap;
    d.maxDspValidationWallS=x.maxDspValidationWall;d.maxDspValidationCpuS=x.maxDspValidationCpu;
    if(d.finalDataAvailable){d.workerProfileRecords=x.profiles.size();d.workerProfileDropped=x.profileDropped;d.detailRecords=x.details.size();d.detailDropped=x.detailDropped;}
    d.dspNewCalls=x.dspNewCalls;d.dspAllocationsMeasured=x.dspAllocationsMeasured;
    d.analysisQosClass=x.analysisQosClass;d.dspQosClass=x.dspQosClass;d.analysisQosRelativePriority=x.analysisQosRelative;d.dspQosRelativePriority=x.dspQosRelative;
    d.analysisQosQueried=x.analysisQosQueried;d.dspQosQueried=x.dspQosQueried;d.threadSamplingRequested=x.config.sampleDspThread;d.samplerCpuS=x.samplerCpu;
    if(d.finalDataAvailable){d.threadSamples=x.samples.size();d.threadSamplesDropped=x.sampleDropped;d.threadSampleErrors=x.sampleErrors;}
    d.analysisQos=x.analysisQos;d.dspQos=x.dspQos;d.analysisDone=x.analysisDone;d.dspDone=x.dspDone;d.cancelled=x.cancelled&&!x.dspDone;d.failed=x.failure;
    d.inputSha256=x.inputSha;d.pcmSha256=x.pcmSha;d.error=x.error;return d;
}
std::vector<WorkerRecord> RealtimePipeline::workerRecords()const{const auto& x=*impl_;if(x.lifecycle.load(std::memory_order_acquire)!=LifecycleState::Finalized)throw std::logic_error("Stop and join before exporting worker records");return x.profiles;}
std::vector<DetailEvent> RealtimePipeline::detailEvents()const{const auto& x=*impl_;if(x.lifecycle.load(std::memory_order_acquire)!=LifecycleState::Finalized)throw std::logic_error("Stop and join before exporting detail records");return x.details;}
std::vector<ThreadSample> RealtimePipeline::threadSamples()const{const auto& x=*impl_;if(x.lifecycle.load(std::memory_order_acquire)!=LifecycleState::Finalized)throw std::logic_error("Stop and join before exporting samples");return x.samples;}
}
