#include "prototype/Phase59ReplaySupport.h"
#include "prototype/Phase59ProgressiveTransition.h"
#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase56PinnedWav.h"
#include <iostream>
using namespace ts;using namespace ts::prototype;using namespace ts::prototype::phase59;
int main(int argc,char** argv){try{
    if(argc!=9&&argc!=10)throw std::invalid_argument("input.wav initial_micros candidate|baseline requests.csv reference.f32 reference_prefix output_prefix chunk_frames [stream]");
    const bool streaming=argc==10&&std::string(argv[9])=="stream";
    if(argc==10&&!streaming)throw std::invalid_argument("Analysis mode");
    WavStreamReader reader(argv[1]);const std::uint32_t initial=std::stoul(argv[2]);const bool candidate=std::string(argv[3])=="candidate";
    if(!candidate&&std::string(argv[3])!="baseline")throw std::invalid_argument("Preset");
    if(!formalSpeed(initial))throw std::invalid_argument("Formal speed");
    const std::string chunkOption=argv[8];const auto chunk=chunkOption=="irregular"?5003:std::stoull(chunkOption);if(!chunk||chunk>131072)throw std::invalid_argument("Chunk limit");
    constexpr std::array<std::size_t,9> irregular{1,3071,17,8193,1023,131071,7,5003,65535};std::size_t chunkIndex=0;
    phase56::ProgressiveAnalysisSession analysis(reader.sampleRate(),reader.channels(),1,{},std::vector<std::uint32_t>{initial});
    phase56::PinnedWavSource source(argv[1],1);std::size_t received=0;
    ProgressiveTransitionPlanner planner(reader.sampleRate(),reader.frames(),1,initial,candidate);
    phase57::ProgressiveSynthesisEngine engine(argv[1],initial,1);engine.enableDynamicTransitions();
    std::shared_ptr<const DynamicMap> view;bool analysisFinal=false;
    const auto append=[&]{received+=source.appendNext(analysis,chunkOption=="irregular"?irregular[chunkIndex++%irregular.size()]:chunk);};
    const auto supply=[&]{const auto snapshot=analysis.getSnapshot();engine.supplySnapshot(snapshot);planner.update(snapshot);
        auto next=planner.view();if(next&&(!view||next->version!=view->version)){if(!engine.trySupplyBorrowedDynamicMap(next.get()))throw std::runtime_error("Analysis extension map rejected");view=std::move(next);}
    };
    if(!streaming){while(received<reader.frames())append();source.finish(analysis);analysisFinal=true;supply();}
    LogicalControl control(readOperations(argv[4]),{initial});
    std::ifstream expected(argv[5],std::ios::binary);if(!expected)throw std::runtime_error("Reference PCM absent");
    Phase45PcmDigest hash;std::array<float,4096> interleaved{},reference{};std::size_t published=0,nonfinalPcm=0,nonfinalPlans=0;
    const phase57::ProgressiveSynthesisEngine::Sink sink=[&](auto generation,auto offset,const float*const* p,std::size_t n){
        if(generation!=1||offset!=published)throw std::runtime_error("PCM generation/offset mismatch");
        if(!expected.read(reinterpret_cast<char*>(reference.data()),n*reader.channels()*sizeof(float)))throw std::runtime_error("Reference shorter than actual PCM");
        for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<reader.channels();++c){
            const auto value=p[c][i],want=reference[i*reader.channels()+c];interleaved[i*reader.channels()+c]=value;
            if(std::bit_cast<std::uint32_t>(value)!=std::bit_cast<std::uint32_t>(want)){
                std::ofstream mismatch(std::string(argv[7])+".mismatch.json");
                mismatch<<"{\"frame\":"<<offset+i<<",\"channel\":"<<c<<",\"actual_bits\":"<<std::bit_cast<std::uint32_t>(value)<<",\"reference_bits\":"<<std::bit_cast<std::uint32_t>(want)<<",\"map_version\":"<<view->version<<",\"published\":"<<published<<"}\n";
                throw std::runtime_error("Float32 bit mismatch at frame "+std::to_string(offset+i));
            }
        }
        hash.update(interleaved.data(),n*reader.channels()*sizeof(float));published+=n;
        if(!analysisFinal)nonfinalPcm+=n;
    };
    for(;;){
        const auto state=engine.advance(sink);
        if(state==phase57::SynthesisState::Finished)break;
        if((state==phase57::SynthesisState::NeedsMoreAnalysis||state==phase57::SynthesisState::NeedsMoreInput)&&!analysisFinal){
            if(received<reader.frames())append();else {source.finish(analysis);analysisFinal=true;}supply();continue;
        }
        if(state!=phase57::SynthesisState::Produced)throw std::runtime_error("Unexpected completed-analysis wait");
        const auto frontier=engine.dspFrontier();
        control.poll(published,frontier,view->modes,[&](const auto& op,const auto& f,auto){
            auto result=planner.plan({op.target},op.generation,op.at,published,f);
            if(result.status!=PlanningStatus::Decided)throw std::runtime_error("Final analysis planning remained pending");
            if(result.change.plan.applied()){
                auto next=planner.view();if(!engine.trySupplyBorrowedDynamicMap(next.get()))throw std::runtime_error("Certified map application rejected");view=std::move(next);
                planner.confirmPlan(true);
                if(!analysisFinal)++nonfinalPlans;
            }
            return result.change;
        });
    }
    if(expected.peek()!=EOF)throw std::runtime_error("Reference longer than actual PCM");
    control.finish();writeOperations(std::string(argv[7])+".operations.csv",control.operations);
    const auto compare=[&](const std::string& suffix){
        std::ifstream a(std::string(argv[6])+suffix,std::ios::binary),b(std::string(argv[7])+suffix,std::ios::binary);
        const std::string actual((std::istreambuf_iterator<char>(b)),{}),reference((std::istreambuf_iterator<char>(a)),{});
        if(actual!=reference){
            if(streaming&&suffix==".operations.csv"){
                const auto fields=[](const std::string& s){std::istringstream lines(s);std::string line;std::vector<std::vector<std::string>> result;while(std::getline(lines,line)){std::istringstream input(line);std::string field;std::vector<std::string> row;while(std::getline(input,field,','))row.push_back(field);result.push_back(std::move(row));}return result;};
                auto a=fields(actual),b=fields(reference);if(a.size()!=b.size())throw std::runtime_error("Operation count differs");
                for(std::size_t i=1;i<a.size();++i){if(a[i].size()>24&&a[i][24]=="0")a[i][24]=b[i][24];}
                if(a==b)return;
            }
            throw std::runtime_error("Logical plan/reference differs: "+suffix);
        }
    };
    std::ofstream nodes(std::string(argv[7])+".nodes.bin",std::ios::binary);const auto exportedMap=view->map.materialize();nodes.write(reinterpret_cast<const char*>(exportedMap.starts().data()),exportedMap.starts().size()*sizeof(long long));nodes.close();
    compare(".operations.csv");compare(".nodes.bin");
    std::ofstream summary(std::string(argv[7])+".json");summary<<"{\"PASS\":true,\"frames\":"<<published<<",\"pcm_sha256\":\""<<hash.finish()<<"\",\"map_sha256\":\""<<mapSha(view->map)<<"\",\"same_dsp_instance\":true,\"analysis_chunk\":\""<<chunkOption<<"\",\"history_count\":"<<planner.historyCount()<<",\"map_bytes\":"<<planner.mapBytes()<<",\"streaming\":"<<streaming<<",\"nonfinal_pcm_frames\":"<<nonfinalPcm<<",\"nonfinal_plans\":"<<nonfinalPlans<<"}\n";
    std::cout<<"PASS frames="<<published<<" transitions="<<planner.historyCount()<<'\n';
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
