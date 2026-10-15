#include "prototype/Phase56ProgressiveAnalysis.h"
#include "prototype/Phase56ReferenceData.h"
#include "dsp/STFT.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <numbers>
#include <stdexcept>
namespace ts::prototype::phase56 {
namespace {
double median(std::vector<double>& v){if(v.empty())return 0;std::sort(v.begin(),v.end());const auto m=v.size()/2;return v.size()&1?v[m]:.5*(v[m-1]+v[m]);}
constexpr std::size_t hop=1024,padding=2048,fftSize=4096,ringSize=8192;
double shoulder(std::size_t distance,int length){if(distance>=std::size_t(length))return 0;return .5*(1+std::cos(std::numbers::pi*double(distance)/length));}
}
void IncrementalDetector::push(TransientFrame f,bool active){
    const auto i=frames_.size(),first=i>12?i-12:0;
    history_.clear();deviations_.clear();
    for(auto j=first;j<i;++j)history_.push_back(frames_[j].spectralFlux);
    const double baseline=median(history_);
    for(auto j=first;j<i;++j)deviations_.push_back(std::abs(frames_[j].spectralFlux-baseline));
    const double mad=median(deviations_);
    f.threshold=std::max(double(config_.minimumFlux),baseline+config_.sensitivity*mad);
    f.strength=static_cast<float>(std::clamp((f.spectralFlux-f.threshold)/f.threshold,0.0,1.0));
    f.detected=false;f.resetApplied=false;frames_.push_back(f);active_.push_back(active);
    if(i){classify(i-1);classified_=i;}
}
void IncrementalDetector::classify(std::size_t i){
    auto& f=frames_[i];
    const bool maximum=(i==0||f.spectralFlux>=frames_[i-1].spectralFlux)&&
        (i+1==frames_.size()||f.spectralFlux>frames_[i+1].spectralFlux);
    const bool cooldown=static_cast<long long>(i)-lastDetected_>config_.cooldownFrames;
    if(i>0&&active_[i]&&maximum&&cooldown&&f.logEnergy>f.previousLogEnergy*1.02&&
       f.strength>=config_.resetStrengthThreshold&&f.spectralFlux>f.threshold){
        f.detected=true;lastDetected_=static_cast<long long>(i);
        auto reset=i>1?i-1:0;if(frames_[reset].logEnergy<f.logEnergy*.05)reset=i;
        frames_[reset].resetApplied=true;++count_;
    }
}
void IncrementalDetector::finish(){if(classified_<frames_.size()){classify(frames_.size()-1);classified_=frames_.size();}}
bool IncrementalEvents::push(std::size_t i,const TransientFrame& f,const Closed& close){
    if(i!=next_++)throw std::logic_error("Non-sequential candidate frame");
    bool changed=false;
    if(i>0&&f.spectralFlux>f.threshold&&f.strength>=.25f&&f.logEnergy>f.previousLogEnergy*1.02){
        bool merge=false;
        if(open_){const auto gap=i-open_->endFrame;merge=gap<=4||(gap<=12&&f.logEnergy<peakEnergy_*.2);}
        if(!merge){if(open_)close(*open_);open_=TransientEvent{i,i,i,i,f.strength};peakFlux_=f.spectralFlux;peakEnergy_=f.logEnergy;changed=true;}
        else {open_->endFrame=i;if(f.spectralFlux>peakFlux_){open_->peakFrame=i;peakFlux_=f.spectralFlux;peakEnergy_=f.logEnergy;changed=true;}open_->strength=std::max(open_->strength,f.strength);}
    }
    if(open_&&i>=open_->endFrame+12){close(*open_);open_.reset();}
    return changed;
}
void IncrementalEvents::finish(const Closed& close){if(open_){close(*open_);open_.reset();}}
MapPrefixBuilder::MapPrefixBuilder(std::vector<std::uint32_t> requested):speedMicros_(std::move(requested)){
    if(speedMicros_.size()>maxMaps)throw std::invalid_argument("Too many requested speeds");
    for(std::size_t i=0;i<speedMicros_.size();++i){const auto micros=speedMicros_[i];
        if(micros<400000||micros>2000000||std::find(speedMicros_.begin(),speedMicros_.begin()+i,micros)!=speedMicros_.begin()+i)
            throw std::invalid_argument("Invalid or duplicate requested speed");
        ratios_[i]=1.0/(double(micros)/1000000.0);nodes[i].push_back(0);
    }
}
void MapPrefixBuilder::close(const TransientEvent& e,const TransientAnchor& a){
    if(speedMicros_.empty())return;
    const auto p=e.peakFrame;
    stretchWeights_.resize(std::max(stretchWeights_.size(),p+6),0);
    compressWeights_.resize(std::max(compressWeights_.size(),p+6),0);
    const auto left=e.onsetFrame>2?e.onsetFrame-2:0;
    for(auto i=left;i<=p+5;++i){
        const double distance=i<p?double(p-i)/3:double(i-p)/6;
        const double weight=distance<1?.5*(1+std::cos(std::numbers::pi*distance)):0;
        stretchWeights_[i]=std::max(stretchWeights_[i],weight);
    }
    for(auto i=p>3?p-3:0;i<p+6;++i){
        const double weight=i+1<p?shoulder(p-1-i,3):i>p+1?shoulder(i-(p+1),5):1.;
        compressWeights_[i]=std::max(compressWeights_[i],weight);
    }
    ++events_;segment(p,a.sampleOffset,false);
}
void MapPrefixBuilder::segment(std::size_t end,double offset,bool tail){
    const auto first=boundary_;if(end<=first)return;
    stretchWeights_.resize(std::max(stretchWeights_.size(),end),0);
    compressWeights_.resize(std::max(compressWeights_.size(),end),0);
    for(std::size_t s=0;s<speedMicros_.size();++s){
        const double ratio=ratios_[s];auto& out=nodes[s];
        const double count=end-first;
        if(ratio>=1||!events_){
            double total=0;for(auto i=first;i<end;++i)total+=stretchWeights_[i];
            const double fc=first==0?0:(ratio-1.0)*previousOffset_,lc=tail?0:(ratio-1.0)*offset;
            double segmentRatio=ratio,depth=0,baseline=ratio;
            const bool compensated=ratio>1&&!(total==0&&fc==0&&lc==0);
            if(compensated){
                segmentRatio=fc==0&&lc==0?ratio:ratio+(lc-fc)/(count*hop);
                if(total==0||segmentRatio<=1.0)baseline=segmentRatio;
                else {const double maximum=ratio*1.5;const double maxDepth=(maximum-segmentRatio)*count/(total*(maximum-1));
                    depth=std::clamp(maxDepth,0.0,1.0);total*=depth;baseline=(count*segmentRatio-total)/(count-total);}
            }
            for(auto i=first;i<end;++i){
                double local=ratio;
                if(compensated)local=(depth==0?baseline:baseline+(1-baseline)*stretchWeights_[i]*depth);
                position_[s]+=hop*local;out.push_back(std::llround(position_[s]));
            }
        }else{
            const auto ideal=[&](std::size_t f,double off){return std::llround(f*hop*ratio+(ratio-1.0)*off);};
            const double atFirst=first==0?0.0:double(ideal(first,previousOffset_));
            const double atLast=tail?double(end*hop)*ratio:double(ideal(end,offset));
            const double target=(atLast-atFirst)/hop,segmentRatio=target/count;
            if(segmentRatio<=0||!std::isfinite(segmentRatio))throw std::runtime_error("No monotonic high-speed event interval");
            double sum=0;for(auto i=first;i<end;++i)sum+=compressWeights_[i];
            double depth=0;const double minimum=std::max(.12,ratio*.5);
            if(sum>0&&sum<count-1e-8&&segmentRatio>minimum&&segmentRatio<1){const double capacity=(target-minimum*count)/(sum*(1-minimum));depth=std::clamp(capacity,0.0,1.0);}
            const double baseline=depth>0?(target-depth*sum)/(count-depth*sum):segmentRatio;
            double position=atFirst;
            if(out.back()!=std::llround(atFirst))throw std::logic_error("Committed compression endpoint changed");
            for(auto i=first;i<end;++i){const double local=baseline+(1-baseline)*depth*compressWeights_[i];position+=hop*local;out.push_back(std::llround(position));}
            out.back()=std::llround(atLast);
            for(auto i=first+1;i<=end;++i)if(out[i]-out[i-1]<=0||out[i]-out[i-1]>=4096)throw std::runtime_error("Unsafe high-speed Mid synthesis hop");
        }
    }
    intervalWork_+=end-first;boundary_=end;previousOffset_=offset;
}
void MapPrefixBuilder::finish(std::size_t features){if(speedMicros_.empty())return;if(!features){for(auto& n:nodes)n.clear();return;}segment(features-1,0,true);}
struct ProgressiveAnalysisSession::Impl {
    std::uint32_t rate;std::size_t channels;std::uint64_t generation;AnalysisLimits limits;
    std::size_t received=0,nextFeature=0,active=0,pcmCopies=0;
    bool final=false,terminalUsed=false;std::atomic<bool> cancelled{false};
    std::shared_ptr<MemoryLedger> memory;
    std::shared_ptr<AnalysisSnapshot> terminal;
    struct SnapshotSlot {
        std::shared_ptr<const AnalysisSnapshot> value;
        auto load()const{return std::atomic_load(&value);}
        void store(std::shared_ptr<const AnalysisSnapshot> next){std::atomic_store(&value,std::move(next));}
    } published;
    STFT stft{fftSize};TransientDetector raw{2049,{}};IncrementalDetector detector;IncrementalEvents grouper;MapPrefixBuilder map;
    std::vector<std::vector<float>> pcm;
    std::vector<float> frame=std::vector<float>(fftSize),combined=std::vector<float>(2049);
    std::vector<std::complex<float>> spectrum=std::vector<std::complex<float>>(2049);
    std::vector<TransientEvent> events;std::vector<TransientAnchor> anchors;
    std::optional<TransientAnchor> provisional;
    Impl(std::uint32_t r,std::size_t c,std::uint64_t g,AnalysisLimits l,std::vector<std::uint32_t> requested):rate(r),channels(c),generation(g),limits(l),memory(std::make_shared<MemoryLedger>(l.snapshotBytes)),map(std::move(requested)),pcm(c,std::vector<float>(ringSize)){
        if((r!=44100&&r!=48000)||(c!=1&&c!=2)||g==0||l.maxInputFrames>1000000000)throw std::invalid_argument("Invalid analysis configuration");
        memory->owner=memory;terminal=std::make_shared<AnalysisSnapshot>();publish();
    }
    float sample(std::size_t c,std::size_t i)const{if(i>=received||received-i>ringSize)throw std::out_of_range("PCM window evicted");return pcm[c][i%ringSize];}
    void closed(const TransientEvent& e){
        if(!provisional||provisional->frame!=e.peakFrame)throw std::logic_error("Anchor lifetime mismatch");
        events.push_back(e);anchors.push_back(*provisional);map.close(e,*provisional);
    }
    void feature(bool isActive){
        std::fill(combined.begin(),combined.end(),0.f);const auto start=nextFeature*hop;
        for(std::size_t c=0;c<channels;++c){
            for(std::size_t i=0;i<fftSize;++i){const auto padded=start+i;frame[i]=padded>=padding&&padded-padding<received?sample(c,padded-padding):0.f;}
            stft.analyze(frame.data(),spectrum.data());
            for(std::size_t k=0;k<combined.size();++k)combined[k]+=std::norm(spectrum[k]);
        }
        for(auto& v:combined)v=std::sqrt(v);
        raw.pushMagnitudes(combined.data());detector.push(raw.frames().back(),isActive);
        if(isActive){++active;const bool changed=grouper.push(nextFeature,detector.frames().back(),[&](const auto& e){closed(e);});
            if(changed){AnchorLocatorConfig cfg;cfg.minimumPeakToRunnerUp=3;cfg.requireInteriorPeak=true;
                const auto& e=*grouper.pending();provisional=TransientAnchorLocator::locate(received,channels,[&](auto c,auto i){return sample(c,i);},{e},hop,cfg).front();}}
        ++nextFeature;
    }
    void advance(){while(nextFeature*hop+padding<=received){if(cancelled.load())return;feature(true);}}
    void publish(){
        auto previous=published.load();auto s=previous?memory->make<AnalysisSnapshot>(*previous):memory->make<AnalysisSnapshot>();
        memory->copied.fetch_add(sizeof(AnalysisSnapshot));
        s->inputGeneration=generation;s->speedCount=map.speedMicros().size();
        std::copy(map.speedMicros().begin(),map.speedMicros().end(),s->speedMicros.begin());s->receivedInputFrames=received;s->featureThrough=nextFeature;
        s->detectorThrough=final?detector.frames().size():detector.stableCount();s->activeFrameCount=active;
        s->transientCount=detector.transientCount();s->closedEventCount=events.size();s->closedAnchorCount=anchors.size();s->isFinal=final;
        s->detector=s->detector.extend(detector.frames(),s->detectorThrough,memory);
        s->events=s->events.extend(events,events.size(),memory);s->anchors=s->anchors.extend(anchors,anchors.size(),memory);
        for(std::size_t i=0;i<s->speedCount;++i)s->maps[i]=s->maps[i].extend(map.nodes[i],nextFeature?map.nodes[i].size():0,memory);
        s->mapThroughNode=s->speedCount?s->maps[0].size():0;published.store(std::move(s));
    }
    void terminate(AnalysisError error,bool cancel){
        if(terminalUsed)return;terminalUsed=true;
        *terminal=*published.load();terminal->hasError=error!=AnalysisError::None;terminal->error=error;
        terminal->isFinal=false;terminal->isCancelled=cancel;published.store(terminal);
    }
    template<class F>void guarded(F&& action){
        if(terminalUsed)throw std::logic_error("Analysis is terminal");
        if(cancelled.load()){terminate(AnalysisError::None,true);return;}
        try{action();if(cancelled.load()&&!final)terminate(AnalysisError::None,true);}
        catch(const std::bad_alloc&){terminate(AnalysisError::Allocation,false);throw;}
        catch(const std::invalid_argument&){terminate(AnalysisError::InvalidInput,false);throw;}
        catch(...){terminate(AnalysisError::Processing,false);throw;}
    }
};
ProgressiveAnalysisSession::ProgressiveAnalysisSession(std::uint32_t r,std::size_t c,std::uint64_t g,AnalysisLimits l,std::vector<std::uint32_t> requested):impl_(std::make_unique<Impl>(r,c,g,l,std::move(requested))){}
ProgressiveAnalysisSession::~ProgressiveAnalysisSession()=default;
void ProgressiveAnalysisSession::appendInput(std::uint64_t g,std::size_t offset,const float*const* p,std::size_t n){auto& x=*impl_;if(x.final)throw std::logic_error("Input already finished");x.guarded([&]{
    if(x.final||g!=x.generation||offset!=x.received||n>x.limits.maxInputFrames-x.received)throw std::invalid_argument("Input generation/offset/limit mismatch");
    if(n&&(!p||!p[0]||(x.channels==2&&!p[1])))throw std::invalid_argument("Null input channel");
    for(std::size_t at=0;at<n;){const auto count=std::min(hop,n-at);
        for(std::size_t i=0;i<count;++i)for(std::size_t c=0;c<x.channels;++c){const auto v=p[c][at+i];if(!std::isfinite(v))throw std::invalid_argument("Non-finite input");x.pcm[c][(x.received+i)%ringSize]=v;}
        x.received+=count;x.pcmCopies+=count*x.channels*sizeof(float);at+=count;x.advance();if(x.cancelled.load())return;
    }x.publish();});}
void ProgressiveAnalysisSession::advanceAnalysis(){auto& x=*impl_;x.guarded([&]{if(x.final)return;x.advance();x.publish();});}
void ProgressiveAnalysisSession::finishInput(std::uint64_t g,const std::function<void()>& beforeCommit){auto& x=*impl_;if(x.final)throw std::logic_error("Input already finished");x.guarded([&]{
    if(x.final||g!=x.generation)throw std::invalid_argument("EOS generation/state mismatch");x.advance();
    const auto count=x.received?(x.received+padding+hop-1)/hop+1:0;
    while(x.nextFeature<count){if(x.cancelled.load())return;x.feature(false);}
    x.detector.finish();x.grouper.finish([&](const auto& e){x.closed(e);});x.map.finish(count);
    if(beforeCommit)beforeCommit();if(x.cancelled.load())return;
    x.final=true;x.publish();});}
void ProgressiveAnalysisSession::cancel()noexcept{if(!impl_->published.load()->isFinal)impl_->cancelled.store(true);}
void ProgressiveAnalysisSession::failInput(std::uint64_t g,AnalysisError error){auto& x=*impl_;if(g!=x.generation||error==AnalysisError::None||x.final||x.terminalUsed)throw std::logic_error("Invalid failure notification");x.terminate(error,false);}
std::shared_ptr<const AnalysisSnapshot> ProgressiveAnalysisSession::getSnapshot()const{return impl_->published.load();}
AnalysisStatistics ProgressiveAnalysisSession::statistics()const{const auto& x=*impl_;return {x.nextFeature,x.map.intervalWork(),x.pcmCopies,x.memory->copied.load(),x.memory->live.load(),x.memory->peak.load(),x.detector.frames().capacity()*sizeof(TransientFrame)+x.raw.frames().capacity()*sizeof(TransientFrame)+x.channels*ringSize*sizeof(float)+x.map.memoryBytes()+x.events.capacity()*sizeof(TransientEvent)+x.anchors.capacity()*sizeof(TransientAnchor)+(x.frame.capacity()+x.combined.capacity()+2049)*sizeof(float)+x.spectrum.capacity()*sizeof(std::complex<float>)};}
}
