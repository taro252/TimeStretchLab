#include "prototype/Phase59ReplaySupport.h"
#include <iostream>
using namespace ts;using namespace ts::prototype;using namespace ts::prototype::phase59;
int main(int argc,char** argv){try{
    if(argc!=7)throw std::invalid_argument("input.wav initial_micros candidate|baseline requests.csv output.f32 output_prefix");
    WavStreamReader reader(argv[1]);const Phase39Speed initial{std::uint32_t(std::stoul(argv[2]))};
    const bool candidate=std::string(argv[3])=="candidate";
    if(!candidate&&std::string(argv[3])!="baseline")throw std::invalid_argument("Preset");
    const auto config=experimental(reader,initial.micros);auto analysisConfig=config;analysisConfig.timeRatio=2;
    const auto analysis=Phase13StreamingEngine(analysisConfig).analyzeTransientEvents(argv[1]);
    Phase39TimeMap timeline(analysis,reader.sampleRate(),initial,candidate?Phase39Planning::L2:Phase39Planning::C);
    LogicalControl control(readOperations(argv[4]),initial);
    std::vector<std::pair<std::size_t,bool>> modes;std::size_t published=0;
    std::ofstream raw(argv[5],std::ios::binary);if(!raw)throw std::runtime_error("Cannot write PCM");
    Phase45PcmDigest pcmHash;std::array<float,4096> interleaved{};
    const auto initialLength=std::size_t(std::llround(reader.frames()*initial.timeRatio()));
    Phase36StreamingSpeedEngine(config).process(argv[1],analysis,timeline.current(),initialLength,2048,
        [&](const float*const* p,std::size_t n,const std::function<void()>& poll){
            for(std::size_t i=0;i<n;++i)for(std::size_t c=0;c<reader.channels();++c)interleaved[i*reader.channels()+c]=p[c][i];
            raw.write(reinterpret_cast<const char*>(interleaved.data()),n*reader.channels()*sizeof(float));
            pcmHash.update(interleaved.data(),n*reader.channels()*sizeof(float));published+=n;poll();
        },[&](const auto& f,TimeMap& map,std::size_t& length,auto& liveModes){
            control.poll(published,f,liveModes,[&](const auto& op,const auto& frontier,auto from){
                auto result=evaluate(timeline,frontier,liveModes,from,{op.target},op.generation,op.at,published,reader.frames(),candidate);
                if(result.plan.applied()){map=timeline.current();length=result.outputFrames;if(result.changesDensity)liveModes.emplace_back(result.densityInput,op.target<500000);}
                return result;
            });modes=liveModes;
        },{}, {},nullptr,0,0,true);
    control.finish();writeOperations(std::string(argv[6])+".operations.csv",control.operations);
    std::ofstream summary(std::string(argv[6])+".json");summary<<"{\"frames\":"<<published<<",\"channels\":"<<reader.channels()<<",\"pcm_sha256\":\""<<pcmHash.finish()<<"\",\"map_sha256\":\""<<mapSha(timeline.current())<<"\",\"modes\":"<<modes.size()<<"}\n";
    std::ofstream nodes(std::string(argv[6])+".nodes.bin",std::ios::binary);nodes.write(reinterpret_cast<const char*>(timeline.current().starts().data()),timeline.current().starts().size()*sizeof(long long));
    std::cout<<"reference frames="<<published<<'\n';
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
