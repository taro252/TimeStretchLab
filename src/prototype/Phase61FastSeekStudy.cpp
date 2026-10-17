// Offline experiment. No native playback, callback, checkpoint or PCM cache.
#include "prototype/Phase57ProgressiveSynthesis.h"
#include "prototype/Phase56PinnedWav.h"
#include "prototype/Phase59ProgressiveTransition.h"
#include <fstream>
#include <iostream>
#include <sstream>
#include <iomanip>
#include <sys/resource.h>
using namespace ts;using namespace ts::prototype;
namespace {
using Clock=std::chrono::steady_clock;
double seconds(Clock::time_point a){return std::chrono::duration<double>(Clock::now()-a).count();}
std::vector<std::size_t> numbers(const std::string& text){std::vector<std::size_t> v;std::istringstream s(text);std::string t;while(std::getline(s,t,','))v.push_back(std::stoull(t));if(v.empty())throw std::invalid_argument("Empty list");return v;}
void require(bool yes,const char* why){if(!yes)throw std::runtime_error(why);}
}
int main(int argc,char** argv){try{
    if(argc!=9)throw std::invalid_argument("input output_dir speeds_csv preroll_frames_csv positions_csv capture_frames repeats local|head");
    const auto speeds=numbers(argv[3]),warms=numbers(argv[4]),positions=numbers(argv[5]);
    const std::size_t capture=std::stoull(argv[6]),repeats=std::stoull(argv[7]);
    const bool local=std::string(argv[8])=="local";require(local||std::string(argv[8])=="head","mode");
    const auto out=std::filesystem::path(argv[2]);require(std::filesystem::create_directories(out),"Output exists");
    std::ifstream f(argv[1],std::ios::binary);require(bool(f),"Input open");
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(f)),{});
    const int fd=open(argv[1],O_RDONLY|O_CLOEXEC);require(fd>=0,"Input FD");
    phase56::PinnedWavSource source(fd,73);std::vector<std::uint32_t> requested(speeds.begin(),speeds.end());
    const auto a=Clock::now();phase56::ProgressiveAnalysisSession analysis(source.rate(),source.channels(),73,{},requested);
    while(source.appendNext(analysis,32768)){}source.finish(analysis);const auto snapshot=analysis.getSnapshot();
    const auto analysisS=seconds(a);const auto rate=source.rate();const auto channels=source.channels();
    std::cout<<std::setprecision(12);
    for(auto speed:speeds)for(bool candidate:{true,false})for(auto warm:warms)for(auto input:positions)for(std::size_t repeat=0;repeat<repeats;++repeat){
        require(input<=source.frames(),"Target out of range");const auto request=Clock::now();
        auto engine=std::make_unique<phase57::ProgressiveSynthesisEngine>(fd,speed,73,std::function<void()>{},16*1024*1024,bytes);
        engine->enableDynamicTransitions();const auto constructed=seconds(request);const auto p=Clock::now();
        phase59::ProgressiveTransitionPlanner planner(rate,source.frames(),73,speed,candidate);planner.update(snapshot);
        engine->supplySnapshot(snapshot);require(engine->trySupplyBorrowedDynamicMap(planner.view().get()),"Final map");
        const auto planned=seconds(p);const auto init=Clock::now();
        const auto end=planner.view()->outputFrames;
        const auto target=input==source.frames()?end:std::min(end,std::size_t(std::llround(planner.view()->map.outputPositionForInputSample(double(input)))));
        const auto start=local?engine->initializeFastLocal(input,warm):phase57::LocalSeekStart{input,target,0,0};
        require(start.requestedInput==input&&start.requestedOutput==target,"Input/output coordinate");
        const auto initialized=seconds(init);
        const auto needed=std::min(end-target,capture);const auto lead=std::min(end-target,std::size_t(candidate?16384:12288));
        const auto name=std::to_string(speed)+"_"+(candidate?"candidate":"baseline")+"_"+std::to_string(warm)+"_"+std::to_string(input)+"_"+std::to_string(repeat);
        std::ofstream raw(out/(name+".f32"),std::ios::binary);require(bool(raw),"Output open");
        std::size_t cursor=start.beginOutput,written=0;std::vector<float> packed(2048*channels);
        double ready=lead? -1:seconds(request);const auto synth=Clock::now();
        const phase57::ProgressiveSynthesisEngine::Sink sink=[&](auto generation,auto at,auto pcm,std::size_t n){
            require(generation==73&&at==cursor,"Output gap/duplication");cursor+=n;
            if(ready<0&&cursor>=target+lead)ready=seconds(request);
            for(std::size_t i=0;i<n&&written<needed;++i)if(at+i>=target){
                for(std::size_t c=0;c<channels;++c){require(std::isfinite(pcm[c][i]),"Nonfinite PCM");packed[written%2048*channels+c]=pcm[c][i];}
                ++written;
                if(written%2048==0)raw.write(reinterpret_cast<const char*>(packed.data()),2048*channels*sizeof(float));
            }
        };
        while(cursor<target+std::max(needed,lead)){
            const auto state=engine->advance(sink);
            require(state==phase57::SynthesisState::Produced||state==phase57::SynthesisState::Finished,"Synthesis state");
            if(state==phase57::SynthesisState::Finished)break;
        }
        if(written%2048)raw.write(reinterpret_cast<const char*>(packed.data()),written%2048*channels*sizeof(float));raw.close();
        require(written==needed&&ready>=0,"Output length/Ready");
        require(!local||!engine->cloneFixedCheckpoint(fd,bytes),"Local PCM contaminated Exact checkpoint");
        rusage usage{};getrusage(RUSAGE_SELF,&usage);
        std::cout<<"{\"name\":\""<<name<<"\",\"speed\":"<<speed<<",\"candidate\":"<<(candidate?"true":"false")<<",\"local\":"<<(local?"true":"false")
            <<",\"input\":"<<input<<",\"rate\":"<<rate<<",\"channels\":"<<channels<<",\"preroll_input_frames\":"<<warm<<",\"seed_input\":"<<start.seedInput<<",\"begin_output\":"<<start.beginOutput
            <<",\"output_start\":"<<target<<",\"output_end\":"<<end<<",\"captured\":"<<written<<",\"input_error_frames\":0,\"output_gaps\":0,\"output_duplicates\":0"
            <<",\"repeat\":"<<repeat<<",\"ready_s\":"<<ready<<",\"construct_s\":"<<constructed<<",\"map_s\":"<<planned<<",\"initialize_s\":"<<initialized<<",\"synthesize_and_capture_s\":"<<seconds(synth)<<",\"analysis_reused_s\":"<<analysisS<<",\"peak_rss_bytes\":"<<usage.ru_maxrss<<"}"<<std::endl;
    }
    close(fd);
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
