// Compile against the frozen baseline headers AND baseline static libraries.
// Full-file analysis, live Phase39 planning at the captured DSP frontiers.
#include "prototype/Phase59ReplaySupport.h"
#include <iostream>
#include <map>
using namespace ts;using namespace ts::prototype;using namespace ts::prototype::phase59;
namespace {
using Row=std::map<std::string,std::string>;
std::vector<Row> csv(const std::filesystem::path& path){
    std::ifstream input(path);if(!input)throw std::runtime_error("Missing captured CSV");std::string line;
    const auto fields=[](const std::string& line){std::istringstream stream(line);std::string field;std::vector<std::string> result;while(std::getline(stream,field,','))result.push_back(field);return result;};
    std::getline(input,line);const auto header=fields(line);std::vector<Row> rows;
    while(std::getline(input,line)){if(line.empty())continue;const auto values=fields(line);if(values.size()!=header.size())throw std::runtime_error("Malformed captured CSV");Row row;for(std::size_t i=0;i<header.size();++i)row[header[i]]=values[i];rows.push_back(std::move(row));}return rows;
}
std::uint64_t number(const Row& row,const std::string& key){return std::stoull(row.at(key));}
}
int main(int argc,char** argv){try{
    if(argc!=7)throw std::invalid_argument("input.wav initial_micros preset captured_directory output.f32 output_prefix");
    WavStreamReader reader(argv[1]);const Phase39Speed initial{std::uint32_t(std::stoul(argv[2]))};const bool candidate=std::string(argv[3])=="candidate";
    if(!candidate&&std::string(argv[3])!="baseline")throw std::invalid_argument("Preset");
    const std::filesystem::path captured=argv[4];const auto operations=csv(captured/"speeds.csv"),plans=csv(captured/"plans.csv"),frontiers=csv(captured/"plan_frontiers.csv");
    std::map<std::uint64_t,Row> operationByGeneration,frontierById;
    for(const auto& op:operations)if(std::stod(op.at("applied_s"))>=0)operationByGeneration.emplace(number(op,"generation"),op);
    for(const auto& f:frontiers)frontierById.emplace(number(f,"id"),f);
    auto config=experimental(reader,initial.micros);auto ac=config;ac.timeRatio=2;
    const auto analysis=Phase13StreamingEngine(ac).analyzeTransientEvents(argv[1]);
    Phase39TimeMap timeline(analysis,reader.sampleRate(),initial,candidate?Phase39Planning::L2:Phase39Planning::C);
    auto tail=initial;std::size_t next=0,published=0;Phase45PcmDigest digest;std::array<float,4096> interleaved{};
    std::ofstream raw(argv[5],std::ios::binary),trace(std::string(argv[6])+".plans.csv");
    if(!raw)throw std::runtime_error("Cannot write reference PCM");trace<<"generation,published,applied_frame,ramp_end,applied_output,completion_output,density_input,frontier_exact\n";
    const auto initialLength=std::size_t(std::llround(reader.frames()*initial.timeRatio()));
    Phase36StreamingSpeedEngine(config).process(argv[1],analysis,timeline.current(),initialLength,2048,
        [&](const float*const* data,std::size_t n,const std::function<void()>& poll){
            for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<reader.channels();++c)interleaved[i*reader.channels()+c]=data[c][i];
            raw.write(reinterpret_cast<const char*>(interleaved.data()),n*reader.channels()*sizeof(float));digest.update(interleaved.data(),n*reader.channels()*sizeof(float));published+=n;poll();
        },[&](const auto& f,TimeMap& map,std::size_t& length,auto& modes){
            while(next<plans.size()){
                const auto& expected=plans[next];const auto gen=number(expected,"generation");const auto& op=operationByGeneration.at(gen);const auto wanted=number(op,"published_at_plan");
                if(published<wanted)return;if(published>wanted)throw std::runtime_error("Captured planning frontier was skipped");
                const auto& actual=frontierById.at(number(op,"id"));
                const auto equal=[&](const std::string& field,std::uint64_t value){if(number(actual,field)!=value){std::ofstream bad(std::string(argv[6])+".frontier_mismatch.json");bad<<"{\"generation\":"<<gen<<",\"field\":\""<<field<<"\",\"captured\":"<<number(actual,field)<<",\"reference\":"<<value<<"}\n";throw std::runtime_error("Captured DSP frontier differs: "+field);}};
                equal("prepared",f.preparedOutput);equal("published",published);
                for(std::size_t r=0;r<3;++r){const auto suffix=std::to_string(r);equal("next_"+suffix,f.nextInput[r]);equal("last_"+suffix,f.lastProcessedInput[r]);equal("ola_"+suffix,f.finalizedOla[r]);
                    if(actual.contains("history_count_"+suffix)){
                        equal("history_count_"+suffix,f.recentFrameCount[r]);equal("weight_sample_"+suffix,f.actualWeightSample[r]);equal("weight_bits_"+suffix,std::bit_cast<std::uint32_t>(f.actualWeight[r]));
                        for(std::size_t i=0;i<f.recentFrameCount[r];++i){equal("history_input_"+suffix+"_"+std::to_string(i),f.recentFrameInput[r][i]);equal("history_output_"+suffix+"_"+std::to_string(i),f.recentFrameOutput[r][i]);}
                    }
                }
                equal("fir_0",f.firstUnprocessedFirSource[0]);equal("fir_1",f.firstUnprocessedFirSource[1]);
                const auto target=Phase39Speed::fromDouble(std::stod(expected.at("target_speed")));
                const auto change=evaluate(timeline,f,modes,tail,target,gen,number(op,"logical_presented"),published,reader.frames(),candidate);
                const auto& p=change.plan;
                if(!p.applied()||change.request.requestedInputSample!=number(expected,"requested_input")||std::uint64_t(change.request.publishedOutputSample)!=number(expected,"fence")||
                    p.appliedFrame!=number(expected,"applied_frame")||p.rampEndFrame!=number(expected,"ramp_end_frame")||std::uint64_t(p.appliedOutputSample)!=number(expected,"applied_output")||
                    std::uint64_t(p.completionOutputSample)!=number(expected,"completion_output")||change.densityInput!=number(expected,"density_frame")*1024)
                    throw std::runtime_error("Frozen full-analysis Phase39 plan differs");
                map=timeline.current();length=change.outputFrames;if(change.changesDensity)modes.emplace_back(change.densityInput,target.micros<500000);tail=target;
                trace<<gen<<','<<published<<','<<p.appliedFrame<<','<<p.rampEndFrame<<','<<p.appliedOutputSample<<','<<p.completionOutputSample<<','<<change.densityInput<<",1\n";++next;
            }
        },{}, {},nullptr,0,0,true);
    if(next!=plans.size())throw std::runtime_error("Reference EOS before captured plan");
    std::ofstream nodes(std::string(argv[6])+".nodes.bin",std::ios::binary);nodes.write(reinterpret_cast<const char*>(timeline.current().starts().data()),timeline.current().starts().size()*sizeof(long long));
    std::ofstream result(std::string(argv[6])+".json");result<<"{\"frames\":"<<published<<",\"channels\":"<<reader.channels()<<",\"pcm_sha256\":\""<<digest.finish()<<"\",\"map_sha256\":\""<<mapSha(timeline.current())<<"\",\"plans\":"<<next<<",\"frontiers_exact\":true}\n";
    std::cout<<"captured full-analysis reference frames="<<published<<" plans="<<next<<'\n';
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
