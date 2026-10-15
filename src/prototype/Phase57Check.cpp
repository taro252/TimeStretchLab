#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase57PinnedInput.h"
#include "prototype/Phase45PcmDigest.h"
#include "playback/StartupDiagnostics.h"
#include <bit>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <sys/resource.h>
using namespace ts;using namespace ts::prototype;using namespace ts::prototype::phase57;
namespace {
void require(bool b,const char* why){if(!b)throw std::runtime_error(why);}
struct Row{std::size_t received,detector,events,nodes,published;double wall,cpu;SynthesisFrontier frontier;};
}
int main(int argc,char** argv){try{
    if(argc<8)throw std::invalid_argument("input speed_micros preset reference.f32 output_frames pcm_sha256 chunks_csv [bench] [trace_prefix]");
    const auto speed=std::uint32_t(std::stoul(argv[2]));const std::string preset=argv[3];require(preset=="candidate"||preset=="baseline","Invalid preset");
    const auto expectedFrames=std::stoull(argv[5]);const bool rejectMode=argc>8&&std::string(argv[8])=="reject";const bool bench=rejectMode||(argc>8&&std::string(argv[8])=="bench");
    const std::string tracePrefix=argc>9?argv[9]:"-";std::stringstream chunks(argv[7]);std::string chunk;
    while(std::getline(chunks,chunk,',')){
        PinnedInput input(argv[1],57);
        const auto channels=input.channels();std::ifstream ref;if(!bench){ref.open(argv[4],std::ios::binary);require(bool(ref),"Cannot read reference PCM");}
        std::vector<float> interleaved(2048*channels),expected(2048*channels);Phase45PcmDigest digest;
        double firstEvent=-1,firstMap=-1,firstGenerated=-1,firstPublished=-1,lead=-1,analysisCpu=0,analysisWall=0,dspCpu=0,dspWall=0,maxChunkWall=0,maxChunkCpu=0,maxStall=0,lastPublish=0;
        double waitingAnalysisWall=0,waitingInputWall=0,waitStarted=-1;SynthesisState pendingWait=SynthesisState::NeedsMoreAnalysis;
        std::size_t at=0,iteration=0,frames=0,waitAnalysis=0,waitInput=0,preEos=0;std::vector<Row> rows;
        playback::StageClock total;phase56::ProgressiveAnalysisSession analysis(input.rate(),input.channels(),57,{},{speed});ProgressiveSynthesisEngine* enginePointer=nullptr;
        ProgressiveSynthesisEngine engine(input.dspPath(),speed,57,[&]{input.validate(analysis);if(enginePointer&&firstGenerated<0&&enginePointer->frontier().generated)firstGenerated=total.elapsed().wallSeconds;});enginePointer=&engine;
        const auto sink=[&](std::uint64_t generation,std::size_t offset,const float*const* p,std::size_t n){
            require(generation==57&&offset==frames,"PCM identity/order changed");if(!rejectMode)require(frames+n<=expectedFrames,"PCM past frozen output length");
            for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<channels;++c)interleaved[i*channels+c]=p[c][i];
            if(!bench){ref.read(reinterpret_cast<char*>(expected.data()),n*channels*sizeof(float));require(ref.gcount()==std::streamsize(n*channels*sizeof(float)),"Truncated reference PCM");
                for(std::size_t i=0;i<n*channels;++i){const auto actual=std::bit_cast<std::uint32_t>(interleaved[i]),wanted=std::bit_cast<std::uint32_t>(expected[i]);if(actual!=wanted){std::ostringstream message;message<<"PCM mismatch frame="<<frames+i/channels<<" channel="<<i%channels<<" actual_bits="<<std::hex<<actual<<" expected_bits="<<wanted;throw std::runtime_error(message.str());}}}
            digest.update(interleaved.data(),n*channels*sizeof(float));frames+=n;const auto now=total.elapsed().wallSeconds;
            if(firstPublished<0)firstPublished=now;if(lead<0&&frames>=(preset=="candidate"?16384u:12288u))lead=now;
            maxStall=std::max(maxStall,now-lastPublish);lastPublish=now;
        };
        const auto pump=[&]{if(waitStarted>=0){const auto gap=total.elapsed().wallSeconds-waitStarted;if(pendingWait==SynthesisState::NeedsMoreAnalysis)waitingAnalysisWall+=gap;else waitingInputWall+=gap;waitStarted=-1;}for(;;){playback::StageClock clock;const auto state=engine.advance(sink);const auto t=clock.elapsed();dspCpu+=t.threadCpuSeconds;dspWall+=t.wallSeconds;
            if(state==SynthesisState::Produced)continue;if(state==SynthesisState::NeedsMoreAnalysis||state==SynthesisState::NeedsMoreInput){if(state==SynthesisState::NeedsMoreAnalysis)++waitAnalysis;else ++waitInput;waitStarted=total.elapsed().wallSeconds;pendingWait=state;
                if(!bench){const auto before=engine.frontier();const auto again=engine.advance(sink);const auto after=engine.frontier();require(again==state&&before.nextInput==after.nextInput&&before.olaThrough==after.olaThrough&&before.firSourceThrough==after.firSourceThrough&&before.published==after.published,"Waiting mutated DSP state");}return state;}
            if(state==SynthesisState::Finished)return state;throw std::runtime_error("Unexpected synthesis error/cancel");}};
        const std::array<std::size_t,9> pattern{1,3071,17,8193,1023,131071,7,5003,65535};
        while(at<input.frames()){
            const auto requested=chunk=="irregular"?pattern[iteration%pattern.size()]:std::stoull(chunk);require(requested>0,"Zero input chunk");playback::StageClock chunkClock;
            {playback::StageClock c;const auto n=input.appendNext(analysis,requested);require(n>0,"Input did not advance");at+=n;const auto t=c.elapsed();analysisCpu+=t.threadCpuSeconds;analysisWall+=t.wallSeconds;}
            auto s=analysis.getSnapshot();const auto now=total.elapsed().wallSeconds;if(firstEvent<0&&s->closedEventCount)firstEvent=now;if(firstMap<0&&s->mapThroughNode>1)firstMap=now;
            engine.supplySnapshot(s);const auto state=pump();require(state!=SynthesisState::Finished,"Input shortage became EOS");const auto t=chunkClock.elapsed();maxChunkWall=std::max(maxChunkWall,t.wallSeconds);maxChunkCpu=std::max(maxChunkCpu,t.threadCpuSeconds);
            if(tracePrefix!="-")rows.push_back({at,s->detectorThrough,s->closedEventCount,s->mapThroughNode,frames,t.wallSeconds,t.threadCpuSeconds,engine.frontier()});++iteration;
        }
        preEos=frames;{playback::StageClock c;input.finish(analysis);const auto t=c.elapsed();analysisCpu+=t.threadCpuSeconds;analysisWall+=t.wallSeconds;}
        const auto analysisDone=total.elapsed().wallSeconds;auto final=analysis.getSnapshot();if(firstEvent<0&&final->closedEventCount)firstEvent=analysisDone;if(firstMap<0&&final->mapThroughNode>1)firstMap=analysisDone;
        engine.supplySnapshot(final);require(pump()==SynthesisState::Finished,"EOS did not finish synthesis");const auto elapsed=total.elapsed();rusage u{};getrusage(RUSAGE_SELF,&u);
        if(!rejectMode)require(frames==expectedFrames,"Final PCM frame count mismatch");const auto sha=digest.finish();if(!rejectMode)require(sha==argv[6],"Final PCM SHA mismatch");
        engine.cancel();require(engine.advance(sink)==SynthesisState::Finished,"Completed EOS changed by cancel");
        if(!bench)require(ref.peek()==EOF,"Extra frozen PCM");auto a=analysis.statistics();
        if(tracePrefix!="-"){std::ofstream out(tracePrefix+"_"+chunk+".csv");out<<"received,detector,closed_events,map_nodes,pcm_published,wall_s,cpu_s,low_next,mid_next,high_next,low_ola,mid_ola,high_ola,low_fir_source,high_fir_source\n"<<std::setprecision(17);for(const auto& r:rows)out<<r.received<<','<<r.detector<<','<<r.events<<','<<r.nodes<<','<<r.published<<','<<r.wall<<','<<r.cpu<<','<<r.frontier.nextInput[0]<<','<<r.frontier.nextInput[1]<<','<<r.frontier.nextInput[2]<<','<<r.frontier.olaThrough[0]<<','<<r.frontier.olaThrough[1]<<','<<r.frontier.olaThrough[2]<<','<<r.frontier.firSourceThrough[0]<<','<<r.frontier.firSourceThrough[1]<<'\n';}
        std::cout<<std::setprecision(17)<<"{\"PASS\":true,\"bench\":"<<bench<<",\"speed_micros\":"<<speed<<",\"preset\":\""<<preset<<"\",\"chunk\":\""<<chunk<<"\",\"input_frames\":"<<input.frames()<<",\"output_frames\":"<<frames<<",\"pcm_sha256\":\""<<sha<<"\",\"non_eos_pcm_frames\":"<<preEos<<",\"analysis_done_s\":"<<analysisDone<<",\"first_event_s\":"<<firstEvent<<",\"first_map_s\":"<<firstMap<<",\"first_generated_s\":"<<firstGenerated<<",\"first_published_s\":"<<firstPublished<<",\"lead_ready_s\":"<<lead<<",\"wall_s\":"<<elapsed.wallSeconds<<",\"cpu_s\":"<<elapsed.threadCpuSeconds<<",\"analysis_cpu_s\":"<<analysisCpu<<",\"analysis_wall_s\":"<<analysisWall<<",\"dsp_cpu_s\":"<<dspCpu<<",\"dsp_wall_s\":"<<dspWall<<",\"max_chunk_wall_s\":"<<maxChunkWall<<",\"max_chunk_cpu_s\":"<<maxChunkCpu<<",\"max_no_pcm_s\":"<<maxStall<<",\"wait_analysis_wall_s\":"<<waitingAnalysisWall<<",\"wait_input_wall_s\":"<<waitingInputWall<<",\"wait_analysis\":"<<waitAnalysis<<",\"wait_input\":"<<waitInput<<",\"snapshot_peak_bytes\":"<<a.snapshotPeakBytes<<",\"snapshot_copy_bytes\":"<<a.snapshotCopyBytes<<",\"dsp_reserved_bytes\":"<<engine.stateBytesEstimate()<<",\"peak_rss_bytes\":"<<u.ru_maxrss<<"}\n";
    }
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
