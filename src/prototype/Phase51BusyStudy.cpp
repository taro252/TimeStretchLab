// Virtual consumption time, not a realtime scheduling or deadline test.
#include "prototype/Phase39PlaybackPipeline.h"
#include "prototype/Phase51CommandControl.h"
#include "audio/WavStream.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <thread>
#include <cmath>
using namespace ts;using namespace ts::prototype;
int main(int argc,char** argv){
    if(argc!=9)return 2;
    try{
        WavStreamReader reader(argv[1]);const auto rate=reader.sampleRate();const std::filesystem::path out=argv[2];
        std::filesystem::create_directories(out);
        if(std::filesystem::exists(out/"operations.csv"))throw std::runtime_error("Fresh output required");
        auto initial=Phase39Speed::fromDouble(std::stod(argv[3]));
        std::vector<Phase39Speed> targets;std::stringstream list(argv[4]);std::string word;
        while(std::getline(list,word,','))targets.push_back(Phase39Speed::fromDouble(std::stod(word)));
        auto interval=std::stod(argv[5]);std::string policy=argv[6];
        if(!std::isfinite(interval)||interval<=0||
            (policy!="latest"&&policy!="defer"&&policy!="strict"&&policy!="continue"))throw std::invalid_argument("Study interval/policy");
        using C=Phase51CommandControl;C commands(targets.size(),policy=="latest"?C::Policy::Latest:policy=="defer"?C::Policy::Defer:policy=="strict"?C::Policy::Strict:C::Policy::Continue);
        const auto planning=std::string(argv[7])=="L2"?Phase39Planning::L2:Phase39Planning::C;
        const std::size_t callback=std::stoull(argv[8]);
        const auto logical=[&](std::size_t frames){return 1000000000ULL+static_cast<std::uint64_t>(frames*1e9/rate);};
        for(std::size_t i=0;i<targets.size();++i)commands.operations[i].scheduled=logical(std::llround((.5+interval*i)*rate));
        Phase39PlaybackPipeline pipeline(argv[1],initial,16384,2048,16384,planning,Phase39DensityDiagnostic::SafeGuarded,false,{},0,0,{},true);
        pipeline.start();if(!pipeline.waitForPrefill(8192,std::chrono::seconds(60)))throw std::runtime_error("Prefill");
        std::vector<std::vector<float>> block(reader.channels(),std::vector<float>(callback)),audio(reader.channels());
        std::vector<float*> ptr(reader.channels());for(std::size_t c=0;c<ptr.size();++c)ptr[c]=block[c].data();
        std::size_t consumed=0,arrivals=0,active=C::none,accepted=0,completed=0;
        auto timeout=std::chrono::steady_clock::now()+std::chrono::minutes(2);
        while(!pipeline.drained()&&!commands.failed){
            if(std::chrono::steady_clock::now()>timeout)throw std::runtime_error("Virtual study timeout");
            const auto now=logical(consumed);auto snap=pipeline.snapshot();
            if(active!=C::none){auto& op=commands.operations[active];
                if(snap.generation!=op.generation)throw std::runtime_error("Old generation overwrote new");
                if(snap.state==Phase39RequestState::Rejected||snap.state==Phase39RequestState::Cancelled){op.state=snap.state==Phase39RequestState::Rejected?"Rejected":"Cancelled";active=C::none;}
                else if(pipeline.researchTransitionComplete()){op.state="Completed";if(pipeline.researchCommandReady())op.ready=now;++completed;active=C::none;}
            }
            const bool ready=active==C::none&&pipeline.researchCommandReady();
            while(arrivals<targets.size()&&now>=commands.operations[arrivals].scheduled)commands.arrive(arrivals++,now,!ready);
            auto next=commands.next(ready,now);
            if(next!=C::none){auto result=pipeline.requestSpeed(targets[next],consumed);
                if(result==Phase39RequestResult::Accepted){commands.dispatch(next,now);auto& op=commands.operations[next];op.accepted=now;op.generation=pipeline.snapshot().generation;active=next;++accepted;}
                else if(result!=Phase39RequestResult::Busy){commands.dispatch(next,now);commands.operations[next].state=result==Phase39RequestResult::Duplicate?"Duplicate":result==Phase39RequestResult::Stopped?"Stopped":"Rejected";}
            }
            auto n=std::min(callback,pipeline.available());if(!n){if(pipeline.finished())pipeline.rethrowWorkerError();std::this_thread::sleep_for(std::chrono::microseconds(100));continue;}
            if(pipeline.pullAudio(ptr.data(),n)!=n)throw std::runtime_error("Virtual FIFO short read");
            for(std::size_t c=0;c<audio.size();++c)audio[c].insert(audio[c].end(),block[c].begin(),block[c].begin()+n);consumed+=n;
        }
        auto snap=pipeline.snapshot();pipeline.rethrowWorkerError();commands.stop(logical(consumed));
        std::ofstream ops(out/"operations.csv");ops<<"operation,target,scheduled_virtual_ns,arrived_virtual_ns,sent_virtual_ns,ready_virtual_ns,generation,state,busy_virtual_ms\n";
        for(std::size_t i=0;i<targets.size();++i){auto& o=commands.operations[i];ops<<i+1<<','<<targets[i].value()<<','<<o.scheduled<<','<<o.arrived<<','<<o.sent<<','<<o.ready<<','<<o.generation<<','<<o.state<<','<<o.busyNs/1e6<<'\n';}
        std::ofstream replay(out/"replay.csv");replay<<"generation,requested_output,requested_input,from,target,fence,prepared,published,applied_frame,applied_output,completion_output,density_input,map_bytes,plan_ms,state_preserved\n";
        for(const auto& m:pipeline.planMetrics()){
            if(!m.phase50StatePreserved)throw std::runtime_error("Prepared state changed");
            replay<<m.generation<<','<<m.requestedOutput<<','<<m.requestedInput<<','<<m.from.value()<<','<<m.target.value()<<','<<m.planningFence<<','<<m.prepared<<','<<m.published<<','<<m.plan.appliedFrame<<','<<m.plan.appliedOutputSample<<','<<m.plan.completionOutputSample<<','<<m.firstDensityChangedInput<<','<<m.timeMapBytes<<','<<m.planMilliseconds<<",1\n";
        }
        WavStreamWriter writer(out/"raw.wav",rate,reader.channels(),consumed);std::vector<const float*> sources(reader.channels());
        for(std::size_t start=0;start<consumed;start+=4096){auto n=std::min<std::size_t>(4096,consumed-start);for(std::size_t c=0;c<sources.size();++c)sources[c]=audio[c].data()+start;writer.write(sources.data(),n);}writer.finish();
        std::cout<<"frames="<<consumed<<"\noutput_length="<<snap.outputLength<<"\naccepted="<<accepted<<"\ncompleted="<<completed<<"\nvirtual_only=1\n";
        if(consumed!=snap.outputLength||snap.underrunFrames||snap.rejectedWrites||commands.failed)return 1;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
