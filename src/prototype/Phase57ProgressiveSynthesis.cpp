#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase36SynthesisCore.h"
#include "prototype/Phase59ProgressiveTransition.h"
#include <unistd.h>
namespace ts::prototype::phase57 {
using namespace synthesis_detail;
struct ProgressiveSynthesisEngine::Impl final:ProgressiveAccess {
    std::uint32_t speed;std::uint64_t generation;std::size_t length,channels,output,generated=0,published=0;
    StretchConfig config;std::function<void()> validate;
    std::shared_ptr<const phase56::AnalysisSnapshot> snapshotOwner;
    const phase56::AnalysisSnapshot* snapshot=nullptr;bool borrowedSnapshots=false;
    std::optional<std::size_t> declaredFinalOutput;
    bool dynamicEnabled=false;
    const phase59::DynamicMap* dynamicMap=nullptr;
    std::shared_ptr<const phase59::DynamicMap> checkpointMapOwner;
    bool checkpointContext=false;
    const phase56::AnalysisSnapshot* fixedLoopOrigin=nullptr;
    const phase59::DynamicMap* fixedLoopMapOrigin=nullptr;
    bool localInitialized=false;
    std::span<const unsigned char> residentIdentity;
    Phase36StreamingSpeedEngine::WorkProfile profile{};bool profileEnabled=false;
    Phase36StreamingSpeedEngine::WorkProfile::Observer preparedObserver=nullptr;
    mutable std::array<std::pair<double,double>,16> positionCache{};
    mutable std::size_t positionCacheCount=0,positionCacheNext=0;
    bool waiting=false;std::size_t waitedNodes=0,waitedInput=0;
    SynthesisState waitedState=SynthesisState::NeedsMoreAnalysis;
    Detection detection;Phase13StageDigests digests{};std::vector<std::pair<std::size_t,bool>> modes;
    std::array<std::unique_ptr<ResolutionStream>,3> resolution;
    std::vector<std::unique_ptr<LiveStreamingFIR>> low,high;
    std::array<std::vector<float>,2> pcm;std::array<const float*,2> pointers{};
    std::atomic<bool> cancelled{false},finished{false};bool failed=false,injected=false,finalLength=false;
    SynthesisState state=SynthesisState::NeedsMoreAnalysis;
    Impl(const std::filesystem::path& path,std::uint32_t s,std::uint64_t g,std::function<void()> v,std::size_t budget,std::span<const unsigned char> pinnedBytes,int pinnedFd=-1):speed(s),generation(g),validate(std::move(v)),residentIdentity(pinnedBytes){
        if(s<400000||s>2000000||s%10000||!g)throw std::invalid_argument("Invalid Phase57 speed/generation");
        if(validate)validate();
        WavStreamReader reader=pinnedFd>=0&&pinnedBytes.empty()
            ? WavStreamReader(pinnedFd) : WavStreamReader(path,pinnedBytes);
        length=reader.frames();channels=reader.channels();
        if((reader.sampleRate()!=44100&&reader.sampleRate()!=48000)||(channels!=1&&channels!=2))throw std::invalid_argument("Unsupported input format");
        config.sampleRate=reader.sampleRate();config.channels=int(channels);config.timeRatio=1.0/(double(s)/1000000.0);
        config.qualityMode=QualityMode::Experimental;config.enableMultiResolution=true;config.enablePhaseLocking=true;config.enableTransientHandling=true;config.enableAdaptiveTimeMapping=true;config.enablePreciseTransientAnchoring=true;config.enableStereoCoherence=true;
        Phase36StreamingSpeedEngine validated(config);detection.progressive=this;
        output=std::size_t(std::ceil(length*2.5))+2;
        // Constant workspace reservation is deliberately conservative and is
        // independent of track length. The legacy FFT implementations own memory.
        if(budget<stateBytesEstimate())throw std::bad_alloc();
        for(auto* d:{&digests.fft,&digests.phase,&digests.ifft,&digests.ola})d->fill(hashSeed);digests.lowFir=digests.highFir=digests.fir=hashSeed;
        constexpr std::array<int,3> fft{8192,4096,1024},hop{2048,1024,256};
        for(std::size_t r=0;r<3;++r)resolution[r]=std::make_unique<ResolutionStream>(path,config,fft[r],hop[r],detection,r==1,output,modes,digests,r,nullptr,0,nullptr,false,pinnedBytes,pinnedFd);
        MultiResolutionCrossover filters(config.sampleRate,config.lowCrossoverHz,config.highCrossoverHz);
        for(std::size_t c=0;c<channels;++c){low.push_back(std::make_unique<LiveStreamingFIR>(filters.lowFilter(),output,nullptr));high.push_back(std::make_unique<LiveStreamingFIR>(filters.highFilter(),output,nullptr));pcm[c].resize(2048);pointers[c]=pcm[c].data();}
    }
    std::size_t stateBytesEstimate()const{return 8*1024*1024;} // reservation, not process RSS
    void acceptSnapshot(const phase56::AnalysisSnapshot* s){
        if(!s||s->inputGeneration!=generation||s->receivedInputFrames>length||(s->isFinal&&(s->receivedInputFrames!=length||s->hasError||s->isCancelled))||(s->hasError&&s->isCancelled)||s->closedEventCount!=s->closedAnchorCount||s->detector.size()!=s->detectorThrough||s->events.size()!=s->closedEventCount||s->anchors.size()!=s->closedAnchorCount)throw std::invalid_argument("Invalid snapshot identity/bounds");
        if(s->mapForSpeed(speed).size()!=s->mapThroughNode)throw std::invalid_argument("Requested map bounds differ");
        if(snapshot&&(s->receivedInputFrames<snapshot->receivedInputFrames||s->detectorThrough<snapshot->detectorThrough||s->closedEventCount<snapshot->closedEventCount||s->mapThroughNode<snapshot->mapThroughNode||snapshot->isFinal))throw std::invalid_argument("Snapshot regressed/after EOS");
        snapshot=s;
        if(snapshot->hasError){failed=true;state=SynthesisState::Failed;}
        else if(snapshot->isCancelled){cancelled.store(true);state=SynthesisState::Cancelled;}
    }
    const auto& map()const{if(!snapshot)throw std::logic_error("No snapshot");return snapshot->mapForSpeed(speed);}
    std::size_t mapSize()const{return dynamicEnabled?(dynamicMap?dynamicMap->certifiedNodes:0):map().size();}
    long long node(std::size_t i)const{return dynamicEnabled?dynamicMap->map.starts().at(i):map().at(i);}
    double position(double input)const override{
        for(std::size_t i=0;i<positionCacheCount;++i)if(positionCache[i].first==input)return positionCache[i].second;
        const auto size=mapSize();if(size<2)throw std::logic_error("No map interval");
        const double fractional=input/1024;const auto left=std::min(std::size_t(fractional),size-2);
        const double local=fractional-left;const double value=node(left)+local*double(node(left+1)-node(left));
        positionCache[positionCacheNext]={input,value};positionCacheNext=(positionCacheNext+1)%positionCache.size();positionCacheCount=std::min(positionCacheCount+1,positionCache.size());return value;
    }
    std::size_t eventCount()const override{return snapshot?snapshot->closedEventCount:0;}
    const TransientEvent& event(std::size_t i)const override{return snapshot->events.at(i);}
    Availability frameAvailable(std::size_t pos,std::size_t padding,std::size_t midpoint,bool processing)const override{
        if(!snapshot)return Availability::NeedsMoreAnalysis;
        if(!snapshot->isFinal){
            if(pos/1024+1>=mapSize())return Availability::NeedsMoreAnalysis;
            if(processing&&pos+padding>snapshot->receivedInputFrames)return Availability::NeedsMoreInput;
            if(processing&&midpoint>(mapSize()-1)*1024)return Availability::NeedsMoreAnalysis;
        }
        if(dynamicEnabled&&(!dynamicMap||(!dynamicMap->final&&
            (pos/1024+1>=mapSize()||(processing&&midpoint>(mapSize()-1)*1024)))))return Availability::NeedsMoreAnalysis;
        return Availability::Ready;
    }
    SynthesisState advance(const Sink& sink){
        if(profileEnabled){profile.stages={};profile.phaseFrames={};}
        if(finished.load())return state=SynthesisState::Finished;
        if(failed)return state=SynthesisState::Failed;
        if(cancelled.load())return state=SynthesisState::Cancelled;
        if(!snapshot)return state=SynthesisState::NeedsMoreAnalysis;
        if(dynamicEnabled&&(!dynamicMap||mapSize()<2))return state=SynthesisState::NeedsMoreAnalysis;
        if(snapshot->hasError){failed=true;return state=SynthesisState::Failed;}
        if(snapshot->isCancelled){cancelled.store(true);return state=SynthesisState::Cancelled;}
        if(!sink)throw std::invalid_argument("Missing PCM sink");
        if(waiting&&!snapshot->isFinal&&mapSize()==waitedNodes&&(waitedState==SynthesisState::NeedsMoreAnalysis||snapshot->receivedInputFrames==waitedInput))return state=waitedState;
        waiting=false;
        const auto wait=[&](SynthesisState s){waiting=true;waitedNodes=mapSize();waitedInput=snapshot->receivedInputFrames;waitedState=s;return state=s;};
        if(snapshot->isFinal&&(!dynamicEnabled||dynamicMap->final)&&!finalLength){
            output=declaredFinalOutput.value_or(length?std::size_t(std::llround(position(double(length)))):0);
            for(auto& r:resolution)r->setOutputLength(output);for(auto& f:low)f->setOutputLength(output);for(auto& f:high)f->setOutputLength(output);finalLength=true;
        }
        if(published==output){finished.store(true);return state=SynthesisState::Finished;}
        const auto count=std::min(std::size_t(2048),output-published),last=published+count-1;
        const auto lowThrough=low[0]->requiredSourceThrough(last),highThrough=high[0]->requiredSourceThrough(last);
        const std::array<std::size_t,3> through{std::max(last+1,lowThrough),std::max({last+1,lowThrough,highThrough}),std::max(last+1,highThrough)};
        if((!snapshot->isFinal||(dynamicEnabled&&!dynamicMap->final))&&(mapSize()<2||*std::max_element(through.begin(),through.end())>std::min(std::size_t(node(mapSize()-1)),declaredFinalOutput.value_or(std::numeric_limits<std::size_t>::max()))))return wait(SynthesisState::NeedsMoreAnalysis);
        for(std::size_t r=0;r<3;++r){const auto a=resolution[r]->readyThrough(through[r]-1);if(a!=Availability::Ready)return wait(a==Availability::NeedsMoreInput?SynthesisState::NeedsMoreInput:SynthesisState::NeedsMoreAnalysis);}
        if(validate)validate();if(injected)throw std::runtime_error("Injected DSP failure");
        for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<channels;++c){
            const auto at=published+i;const auto hi=resolution[2]->get(c,at);
            const auto lf=low[c]->next(at,[&](std::size_t n){return resolution[0]->get(c,n)-resolution[1]->get(c,n);});
            const auto hf=high[c]->next(at,[&](std::size_t n){return resolution[1]->get(c,n)-resolution[2]->get(c,n);});
            hashFloat(digests.lowFir,lf);hashFloat(digests.highFir,hf);
            float value=hi;value+=lf;value+=hf;pcm[c][i]=value;hashFloat(digests.fir,value);
        }
        generated=published+count;
        if(validate)validate();if(cancelled.load())return state=SynthesisState::Cancelled;
        sink(generation,published,pointers.data(),count);published+=count;
        if(finalLength&&published==output){finished.store(true);state=SynthesisState::Finished;}else state=SynthesisState::Produced;
        return state;
    }
};
ProgressiveSynthesisEngine::ProgressiveSynthesisEngine(const std::filesystem::path& p,std::uint32_t s,std::uint64_t g,std::function<void()> v,std::size_t b,std::span<const unsigned char> bytes):impl_(std::make_unique<Impl>(p,s,g,std::move(v),b,bytes)){}
ProgressiveSynthesisEngine::ProgressiveSynthesisEngine(int fd,std::uint32_t s,std::uint64_t g,std::function<void()> v,std::size_t b,std::span<const unsigned char> bytes){
    if(fd<0)throw std::invalid_argument("Invalid pinned input descriptor");
    impl_=std::make_unique<Impl>(std::filesystem::path{},s,g,std::move(v),b,bytes,fd);
}
ProgressiveSynthesisEngine::~ProgressiveSynthesisEngine()=default;
void ProgressiveSynthesisEngine::setDeclaredFinalOutputFrames(std::size_t frames){auto& x=*impl_;
    if(x.snapshot||x.generated||x.finished.load()||x.failed||x.cancelled.load())throw std::logic_error("Set output contract before input");
    const auto legacy=std::size_t(std::llround(x.length*x.config.timeRatio));
    if(!frames||frames!=legacy)throw std::invalid_argument("Declared length must match the fixed PlaybackEngine contract");
    x.declaredFinalOutput=frames;
}
void ProgressiveSynthesisEngine::enableWorkProfiling(){auto& x=*impl_;if(x.snapshot||x.generated)throw std::logic_error("Enable profiling before input");
    x.profileEnabled=true;for(auto& r:x.resolution)r->setWorkProfile(&x.profile);for(auto& f:x.low)f->setWorkProfile(&x.profile);for(auto& f:x.high)f->setWorkProfile(&x.profile);
}
Phase36StreamingSpeedEngine::WorkProfile ProgressiveSynthesisEngine::workProfile()const{return impl_->profile;}
void ProgressiveSynthesisEngine::setWorkObserver(Phase36StreamingSpeedEngine::WorkProfile::Observer observer,void* context){
    auto& x=*impl_;if(x.snapshot||x.generated)throw std::logic_error("Set observer before input");
    enableWorkProfiling();x.preparedObserver=observer;x.profile.observer=observer;x.profile.observerContext=context;
}
void ProgressiveSynthesisEngine::setWorkObserverActive(bool active)noexcept{auto& x=*impl_;x.profile.observer=active?x.preparedObserver:nullptr;}
void ProgressiveSynthesisEngine::supplySnapshot(std::shared_ptr<const phase56::AnalysisSnapshot> s){auto& x=*impl_;if(x.finished.load()||x.failed||x.cancelled.load())throw std::logic_error("Synthesis already terminal");try{
    if(x.borrowedSnapshots)throw std::logic_error("Cannot mix borrowed and owned snapshots");
    x.acceptSnapshot(s.get());x.snapshotOwner=std::move(s);
}catch(...){x.failed=true;x.state=SynthesisState::Failed;throw;}}
void ProgressiveSynthesisEngine::supplyBorrowedSnapshot(const phase56::AnalysisSnapshot* s){auto& x=*impl_;if(x.finished.load()||x.failed||x.cancelled.load())throw std::logic_error("Synthesis already terminal");try{
    if(x.snapshotOwner)throw std::logic_error("Cannot mix owned and borrowed snapshots");
    x.borrowedSnapshots=true;x.acceptSnapshot(s);
}catch(...){x.failed=true;x.state=SynthesisState::Failed;throw;}}
void ProgressiveSynthesisEngine::enableDynamicTransitions(){auto& x=*impl_;
    if(x.snapshot||x.generated||x.declaredFinalOutput)throw std::logic_error("Enable dynamic transitions before input");
    x.dynamicEnabled=true;
    // The realtime reader will resize within this capacity. Reserve alone does
    // not commit demand-zero pages; touch them now, while still a normal owner.
    x.modes.resize(phase59::maximumChanges);
    auto* memory=reinterpret_cast<volatile unsigned char*>(x.modes.data());
    const auto bytes=x.modes.size()*sizeof(x.modes[0]);
    const auto page=std::size_t(std::max<long>(1,sysconf(_SC_PAGESIZE)));
    for(std::size_t at=0;at<bytes;at+=page)memory[at]=memory[at];
    if(bytes)memory[bytes-1]=memory[bytes-1];x.modes.clear();
    for(auto& r:x.resolution)r->enableFrameHistory();
}
Phase36StreamingSpeedEngine::Frontier ProgressiveSynthesisEngine::dspFrontier()const {
    const auto& x=*impl_;Phase36StreamingSpeedEngine::Frontier f;f.preparedOutput=x.generated;
    for(std::size_t r=0;r<3;++r){
        const auto& s=x.resolution[r];f.nextInput[r]=s->firstUnprocessedInputSample();f.lastProcessedInput[r]=s->lastProcessedInputSample();f.finalizedOla[r]=s->finalizedOlaSample();
        s->copyFrameHistory(f.recentFrameInput[r],f.recentFrameOutput[r],f.recentFrameCount[r]);
        f.actualWeightSample[r]=f.finalizedOla[r];f.actualWeight[r]=s->diagnosticOlaWeight();
    }
    f.firstUnprocessedFirSource={x.low[0]->firstUnprocessedSourceSample(),x.high[0]->firstUnprocessedSourceSample()};return f;
}
bool ProgressiveSynthesisEngine::trySupplyBorrowedDynamicMap(const phase59::DynamicMap* view) noexcept {
    auto& x=*impl_;
    if(!x.dynamicEnabled||!x.snapshot||!view||view->inputGeneration!=x.generation||
        view->certifiedNodes<2||view->certifiedNodes!=view->map.starts().size()||view->certifiedNodes>x.snapshot->mapThroughNode||
        view->modes.size()>phase59::maximumChanges||view->receivedInput>x.snapshot->receivedInputFrames||
        (view->final&&!x.snapshot->isFinal)||x.finished.load()||x.failed||x.cancelled.load())return false;
    const auto f=dspFrontier();
    if(x.checkpointContext){
        // A saved fixed state may have advanced DSP. Rebinding is legal only
        // when the entire immutable final map is identical, with no speed or
        // density history. Subsequent changes use the original Phase59 guards.
        if(!view->final||view->hasTransitions||!x.dynamicMap||!x.dynamicMap->final||
            !view->modes.empty()||view->map.starts()!=x.dynamicMap->map.starts()||view->outputFrames!=x.output)return false;
        x.dynamicMap=view;x.checkpointMapOwner.reset();x.checkpointContext=false;x.waiting=false;return true;
    }
    if(x.dynamicMap){
        const auto& old=*x.dynamicMap;
        if(view->baseVersion!=old.version||view->version<=old.version||view->certifiedNodes<old.certifiedNodes||
            view->firstChangedNode>old.certifiedNodes||view->modes.size()<x.modes.size())return false;
        for(std::size_t i=0;i<x.modes.size();++i)if(x.modes[i]!=view->modes[i])return false;
        if(view->firstChangedNode<old.certifiedNodes){
            if(view->firstChangedNode==0)return false;
            for(std::size_t r=0;r<3;++r){
                if((f.lastProcessedInput[r]+1023)/1024>=view->firstChangedNode)return false;
                for(std::size_t i=0;i<f.recentFrameCount[r];++i)
                    if(std::llround(view->map.outputPositionForInputSample(double(f.recentFrameInput[r][i])))!=f.recentFrameOutput[r][i])return false;
            }
            const auto first=view->firstChangedNode-1;
            const auto mutableAt=std::size_t(std::min(old.map.starts()[first],view->map.starts()[first]));
            if(phase50Boundary(f,old.map,x.published).precise>mutableAt)return false;
        }
        for(std::size_t i=x.modes.size();i<view->modes.size();++i)
            if(view->modes[i].first<=*std::max_element(f.lastProcessedInput.begin(),f.lastProcessedInput.end()))return false;
    }else if(x.generated||view->baseVersion!=0)return false;
    if(view->final){
        if(!view->outputFrames||view->outputFrames<x.generated||
            view->outputFrames<std::max(f.firstUnprocessedFirSource[0],f.firstUnprocessedFirSource[1]))return false;
        x.output=view->outputFrames;for(auto& r:x.resolution)r->setOutputLength(x.output);
        for(auto& f:x.low)f->setOutputLength(x.output);for(auto& f:x.high)f->setOutputLength(x.output);x.finalLength=true;
    }
    // Before the first accepted change, preserve Phase58's known fixed-output
    // ceiling even while the analysis is incomplete. A genuine dynamic history
    // has no fixed-speed total, so only its certified prefix bounds synthesis.
    if(view->hasTransitions)x.declaredFinalOutput.reset();
    else x.declaredFinalOutput=std::size_t(std::llround(x.length*x.config.timeRatio));
    x.modes.resize(view->modes.size());std::copy(view->modes.begin(),view->modes.end(),x.modes.begin());
    x.dynamicMap=view;x.positionCacheCount=x.positionCacheNext=0;x.waiting=false;return true;
}
SynthesisState ProgressiveSynthesisEngine::advance(const Sink& s){try{return impl_->advance(s);}catch(...){impl_->failed=true;impl_->state=SynthesisState::Failed;throw;}}
void ProgressiveSynthesisEngine::cancel()noexcept{if(!impl_->finished.load())impl_->cancelled.store(true);}
void ProgressiveSynthesisEngine::fail(){if(!impl_->finished.load()&&!impl_->cancelled.load()&&!impl_->failed){impl_->failed=true;impl_->state=SynthesisState::Failed;}}
SynthesisFrontier ProgressiveSynthesisEngine::frontier()const{const auto& x=*impl_;SynthesisFrontier f;f.generation=x.generation;f.state=x.finished.load()?SynthesisState::Finished:x.failed?SynthesisState::Failed:x.cancelled.load()?SynthesisState::Cancelled:x.state;f.generated=x.generated;f.published=x.published;f.outputFrames=x.finalLength?x.output:0;
    if(x.snapshot){f.receivedInput=x.snapshot->receivedInputFrames;f.detectorThrough=x.snapshot->detectorThrough;f.closedEvents=x.snapshot->closedEventCount;f.mapThroughNode=x.snapshot->mapThroughNode;}
    for(std::size_t r=0;r<3;++r){f.nextInput[r]=x.resolution[r]->firstUnprocessedInputSample();f.lastInput[r]=x.resolution[r]->lastProcessedInputSample();f.olaThrough[r]=x.resolution[r]->finalizedOlaSample();}
    constexpr std::array<std::size_t,3> padding{4096,2048,512},normalHop{2048,1024,256};
    if(x.snapshot)for(std::size_t r=0;r<3;++r){const auto step=normalHop[r]/(x.config.timeRatio>2?2:1);
        if(x.snapshot->isFinal)f.readableInputThrough[r]=((x.length+padding[r]+step-1)/step)*step+1;
        else if(f.mapThroughNode>1&&f.receivedInput>=padding[r]){const auto boundary=(f.mapThroughNode-1)*1024;f.readableInputThrough[r]=std::min({boundary,boundary-step/2+1,f.receivedInput-padding[r]+1});}
    }
    f.firThrough={x.low[0]->finalizedOutputSample(),x.high[0]->finalizedOutputSample()};f.firSourceThrough={x.low[0]->firstUnprocessedSourceSample(),x.high[0]->firstUnprocessedSourceSample()};return f;}
std::size_t ProgressiveSynthesisEngine::stateBytesEstimate()const{return impl_->stateBytesEstimate();}
std::unique_ptr<ProgressiveSynthesisEngine> ProgressiveSynthesisEngine::cloneFixedCheckpoint(int fd,std::span<const unsigned char> bytes,std::function<void()> validate)const{
    const auto& old=*impl_;
    if(bytes.empty()||bytes.data()!=old.residentIdentity.data()||bytes.size()!=old.residentIdentity.size()||
        old.localInitialized||!old.snapshot||!old.snapshot->isFinal||old.failed||old.cancelled.load()||old.finished.load()||old.generated!=old.published||
        old.profileEnabled||old.preparedObserver||!old.modes.empty()||(old.dynamicEnabled&&(!old.dynamicMap||!old.dynamicMap->final||old.dynamicMap->hasTransitions)))return {};
    auto copy=std::make_unique<ProgressiveSynthesisEngine>(fd,old.speed,old.generation,std::move(validate),16*1024*1024,bytes);
    if(old.dynamicEnabled)copy->enableDynamicTransitions();
    auto& x=*copy->impl_;x.output=old.output;x.generated=old.generated;x.published=old.published;x.declaredFinalOutput=old.declaredFinalOutput;
    x.snapshotOwner=std::make_shared<const phase56::AnalysisSnapshot>(*old.snapshot);x.snapshot=x.snapshotOwner.get();
    x.fixedLoopOrigin=old.snapshot;
    x.fixedLoopMapOrigin=old.dynamicMap;
    if(old.dynamicMap){x.checkpointMapOwner=std::make_shared<const phase59::DynamicMap>(*old.dynamicMap);x.dynamicMap=x.checkpointMapOwner.get();}
    x.positionCache=old.positionCache;x.positionCacheCount=old.positionCacheCount;x.positionCacheNext=old.positionCacheNext;
    x.waiting=old.waiting;x.waitedNodes=old.waitedNodes;x.waitedInput=old.waitedInput;x.waitedState=old.waitedState;
    x.detection=old.detection;x.detection.progressive=&x;x.digests=old.digests;x.modes=old.modes;
    for(std::size_t r=0;r<3;++r)x.resolution[r]->copyRuntimeStateFrom(*old.resolution[r]);
    for(std::size_t c=0;c<x.channels;++c){x.low[c]->copyRuntimeStateFrom(*old.low[c]);x.high[c]->copyRuntimeStateFrom(*old.high[c]);x.pcm[c]=old.pcm[c];x.pointers[c]=x.pcm[c].data();}
    x.finalLength=old.finalLength;x.state=old.state;return copy;
}
void ProgressiveSynthesisEngine::prepareCheckpointForEpoch(){auto& x=*impl_;
    if(!x.snapshotOwner||!x.snapshotOwner->isFinal||x.generated!=x.published||x.cancelled.load()||x.finished.load())throw std::logic_error("Invalid checkpoint epoch");
    x.snapshot=nullptr;x.snapshotOwner.reset();x.borrowedSnapshots=false;x.waiting=false;x.checkpointContext=x.dynamicEnabled;
}
bool ProgressiveSynthesisEngine::restoreFixedLoopCheckpoint(const ProgressiveSynthesisEngine& saved){
    auto& x=*impl_;const auto& old=*saved.impl_;
    if(!x.snapshot||!x.snapshot->isFinal||old.fixedLoopOrigin!=x.snapshot||
       x.speed!=old.speed||x.generation!=old.generation||x.length!=old.length||x.channels!=old.channels||
       x.residentIdentity.empty()||x.residentIdentity.data()!=old.residentIdentity.data()||x.residentIdentity.size()!=old.residentIdentity.size()||
       x.dynamicEnabled!=old.dynamicEnabled||x.localInitialized||old.localInitialized||
       (x.dynamicEnabled&&(!x.dynamicMap||!old.dynamicMap||old.fixedLoopMapOrigin!=x.dynamicMap||x.dynamicMap->hasTransitions||old.dynamicMap->hasTransitions))||
       x.cancelled.load()||x.failed||old.cancelled.load()||old.failed||old.finished.load()||
       old.generated!=old.published||x.profileEnabled||old.profileEnabled||x.preparedObserver||old.preparedObserver||
       !x.modes.empty()||!old.modes.empty())return false;
    // Keep this owner's immutable snapshot and Detection references pinned.
    // All runtime vectors have their original fixed dimensions and capacity;
    // the copy operations reuse their existing storage and FFT plans.
    x.output=old.output;x.generated=old.generated;x.published=old.published;x.declaredFinalOutput=old.declaredFinalOutput;
    x.positionCache=old.positionCache;x.positionCacheCount=old.positionCacheCount;x.positionCacheNext=old.positionCacheNext;
    x.waiting=old.waiting;x.waitedNodes=old.waitedNodes;x.waitedInput=old.waitedInput;x.waitedState=old.waitedState;
    x.digests=old.digests;
    for(std::size_t r=0;r<3;++r)x.resolution[r]->copyRuntimeStateFrom(*old.resolution[r]);
    for(std::size_t c=0;c<x.channels;++c){
        x.low[c]->copyRuntimeStateFrom(*old.low[c]);x.high[c]->copyRuntimeStateFrom(*old.high[c]);
        std::copy(old.pcm[c].begin(),old.pcm[c].end(),x.pcm[c].begin());
    }
    x.finalLength=old.finalLength;x.state=old.state;x.finished=false;return true;
}
bool ProgressiveSynthesisEngine::captureFixedLoopCheckpoint(ProgressiveSynthesisEngine& slot)const{
    const auto& old=*impl_;auto& x=*slot.impl_;
    if(!old.snapshot||!old.snapshot->isFinal||x.fixedLoopOrigin!=old.snapshot||
       x.speed!=old.speed||x.generation!=old.generation||x.length!=old.length||x.channels!=old.channels||
       x.residentIdentity.empty()||x.residentIdentity.data()!=old.residentIdentity.data()||x.residentIdentity.size()!=old.residentIdentity.size()||
       x.dynamicEnabled!=old.dynamicEnabled||x.localInitialized||old.localInitialized||
       (old.dynamicEnabled&&(!x.dynamicMap||!old.dynamicMap||x.fixedLoopMapOrigin!=old.dynamicMap||x.dynamicMap->hasTransitions||old.dynamicMap->hasTransitions))||
       x.cancelled.load()||old.cancelled.load()||x.failed||old.failed||old.finished.load()||old.generated!=old.published||
       x.profileEnabled||old.profileEnabled||x.preparedObserver||old.preparedObserver||!x.modes.empty()||!old.modes.empty())return false;
    // The preallocated A slot may become a B continuation slot only after the
    // bounded PCM cache is complete. Publish it once, then keep it immutable.
    x.output=old.output;x.generated=old.generated;x.published=old.published;x.declaredFinalOutput=old.declaredFinalOutput;
    x.positionCache=old.positionCache;x.positionCacheCount=old.positionCacheCount;x.positionCacheNext=old.positionCacheNext;
    x.waiting=old.waiting;x.waitedNodes=old.waitedNodes;x.waitedInput=old.waitedInput;x.waitedState=old.waitedState;x.digests=old.digests;
    for(std::size_t r=0;r<3;++r)x.resolution[r]->copyRuntimeStateFrom(*old.resolution[r]);
    for(std::size_t c=0;c<x.channels;++c){x.low[c]->copyRuntimeStateFrom(*old.low[c]);x.high[c]->copyRuntimeStateFrom(*old.high[c]);std::copy(old.pcm[c].begin(),old.pcm[c].end(),x.pcm[c].begin());}
    x.finalLength=old.finalLength;x.state=old.state;x.finished=false;return true;
}
LocalSeekStart ProgressiveSynthesisEngine::initializeFastLocal(std::size_t input,std::size_t preroll){
    auto& x=*impl_;
    if(x.localInitialized||x.generated||x.published||!x.snapshot||!x.snapshot->isFinal||
       x.failed||x.cancelled.load()||x.finished.load()||input>x.length||!preroll||
       (x.dynamicEnabled&&(!x.dynamicMap||!x.dynamicMap->final||x.dynamicMap->hasTransitions)))
        throw std::invalid_argument("Local seek requires an untouched final fixed map");
    const auto output=x.dynamicEnabled?x.dynamicMap->outputFrames:
        x.declaredFinalOutput.value_or(std::size_t(std::llround(x.position(double(x.length)))));
    const auto target=input==x.length?output:std::min(output,std::size_t(std::llround(x.position(double(input)))));
    const auto warm=input>preroll?input-preroll:0;
    // LCM(4096-2049+1,4096-513+1) = LCM(2048,3584).
    constexpr std::size_t commonFirBlock=14336;
    const auto begin=std::min(target,std::size_t(std::llround(x.position(double(warm)))))/commonFirBlock*commonFirBlock;
    const std::size_t step=x.config.timeRatio>2?1024:2048;
    std::size_t lo=0,hi=x.length/step+1;
    while(lo<hi){const auto mid=lo+(hi-lo)/2;
        if(std::llround(x.position(double(mid*step)))<=static_cast<long long>(begin))lo=mid+1;else hi=mid;}
    const auto seed=(lo?lo-1:0)*step;
    for(auto& r:x.resolution)r->initializeLocalAt(seed,begin);
    for(auto& f:x.low)f->initializeLocalAt(begin);
    for(auto& f:x.high)f->initializeLocalAt(begin);
    x.localInitialized=true;x.generated=x.published=begin;
    return {input,target,seed,begin};
}
void ProgressiveSynthesisEngine::injectFailureForTest(){impl_->injected=true;}
}
