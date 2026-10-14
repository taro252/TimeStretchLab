// Reconstruct an independently-owned engine up to the recorded frontier.
// Never attached to the live worker, no rollback or publication replacement.
#include "prototype/Phase39TimeMap.h"
#include "prototype/Phase36StreamingSpeedEngine.h"
#include "prototype/Phase35TransitionEngine.h"
#include "prototype/Phase50Boundary.h"
#include "prototype/Phase42DensityGuard.h"
#include "audio/WavStream.h"
#include <fstream>
#include <sstream>
#include <map>
#include <iostream>
#include <numbers>
using namespace ts;using namespace ts::prototype;
using Row=std::map<std::string,std::string>;
std::vector<Row> readCsv(const std::filesystem::path& p) {
    std::ifstream f(p);if (!f) throw std::runtime_error("Missing saved replay");
    std::string line,field;std::getline(f,line);std::vector<std::string> keys;
    std::istringstream header(line);while(std::getline(header,field,','))keys.push_back(field);
    std::vector<Row> rows;
    while(std::getline(f,line)) {std::istringstream values(line);Row row;std::size_t i=0;
        while(std::getline(values,field,',')) {if(i>=keys.size())throw std::runtime_error("CSV width");row[keys[i++]]=field;}
        rows.push_back(row);}
    return rows;
}
std::size_t num(const Row& r,const std::string& k){return std::stoull(r.at(k));}
struct Captured{};
int main(int argc,char**argv) {
    if(argc!=4)return 2;
    try {
        const std::filesystem::path input=argv[1],output=argv[3];
        std::filesystem::create_directories(output);
        if(std::filesystem::exists(output/"summary.csv"))throw std::runtime_error("Fresh destination required");
        const auto rows=readCsv(argv[2]);if(rows.size()<3)throw std::runtime_error("Need third operation");
        const auto& row=rows[2];WavStreamReader reader(input);
        StretchConfig config;config.sampleRate=reader.sampleRate();config.channels=reader.channels();config.timeRatio=2.5;
        config.enableMultiResolution=true;config.qualityMode=QualityMode::Experimental;
        config.enablePhaseLocking=config.enableTransientHandling=config.enableAdaptiveTimeMapping=true;
        config.enablePreciseTransientAnchoring=config.enableStereoCoherence=true;
        auto ac=config;ac.timeRatio=2;
        const auto analysis=Phase13StreamingEngine(ac).analyzeTransientEvents(input);
        Phase39TimeMap timeline(analysis,reader.sampleRate(),Phase39Speed::fromDouble(.4),Phase39Planning::C);
        std::vector<std::pair<std::size_t,bool>> modes;
        for(std::size_t i=0;i<2;++i) {
            const auto& r=rows[i];const auto target=Phase39Speed::fromDouble(std::stod(r.at("target")));
            const auto p=timeline.submit({num(r,"generation"),target,num(r,"requested_input"),static_cast<long long>(num(r,"fence")),50});
            if(!p.applied()||p.appliedFrame!=num(r,"applied_frame")||p.completionOutputSample!=static_cast<long long>(num(r,"completion_output")))throw std::runtime_error("Prior history mismatch");
            if((std::stod(r.at("from"))<.5)!=(target.value()<.5))modes.emplace_back(num(r,"density_input"),target.value()<.5);
        }
        const auto before=timeline.current();const auto frames=std::size_t(std::llround(before.outputPositionForInputSample(reader.frames())));
        const auto prepared=num(row,"prepared"),published=num(row,"published");
        Phase36StreamingSpeedEngine::Frontier frontier;bool captured=false;
        WavStreamWriter prefix(output/"prepared_prefix.wav",reader.sampleRate(),reader.channels(),prepared);
        try {
            Phase36StreamingSpeedEngine(config).process(input,analysis,before,frames,2048,
                [&](const float*const* data,std::size_t count,const std::function<void()>&poll){prefix.write(data,count);poll();},
                [&](const auto& f,TimeMap&,std::size_t&,auto&){if(f.preparedOutput==prepared){frontier=f;captured=true;throw Captured{};}},
                modes,{},nullptr,0,0,true);
        }catch(const Captured&){}
        prefix.finish();if(!captured)throw std::runtime_error("Frontier was not captured");
        const std::array<std::string,3> band{"low","mid","high"};
        for(std::size_t r=0;r<3;++r)
            if(frontier.nextInput[r]!=num(row,"next_"+band[r]+"_input")||frontier.lastProcessedInput[r]!=num(row,"last_"+band[r]+"_input")||frontier.finalizedOla[r]!=num(row,"ola_"+band[r]))
                throw std::runtime_error("Recorded actual frontier differs from reconstruction");
        if(frontier.firstUnprocessedFirSource[0]+4096!=num(row,"fir250_fence")||frontier.firstUnprocessedFirSource[1]+4096!=num(row,"fir3500_fence"))throw std::runtime_error("FIR frontier mismatch");
        const auto boundary=phase50Boundary(frontier,before,published);
        if(boundary.legacy!=num(row,"phase50_legacy_fence")||boundary.precise!=num(row,"phase50_precise_fence"))throw std::runtime_error("Boundary audit mismatch");
        std::ofstream summary(output/"summary.csv");summary<<"candidate,frontier_match,fence,applied,complete,ramp_ms,from_request_ms,complete_from_request_ms,density_input,safe,weight_low,weight_mid,weight_high\n";
        for(int option=0;option<4;++option) {
            const std::string label=option==0?"C":option==1?"L1":option==2?"L2":"L1_L2";
            auto candidate=timeline.researchWithPlanning(option>=2?Phase39Planning::L2:Phase39Planning::C);
            const auto fence=option==1||option==3?boundary.precise:boundary.legacy;
            const auto target=Phase39Speed::fromDouble(std::stod(row.at("target")));
            const auto plan=candidate.submit({num(row,"generation"),target,num(row,"requested_input"),static_cast<long long>(fence),50});
            if(!plan.applied()||!phase50PreservesState(frontier,before,candidate.current()))throw std::runtime_error("Candidate changes processed state");
            const auto guard=chooseSafeDensitySwitch(candidate.current(),plan,frontier,modes,true,false,fence,reader.frames(),true);
            summary<<label<<",1,"<<fence<<','<<plan.appliedOutputSample<<','<<plan.completionOutputSample<<','
                <<(plan.completionOutputSample-plan.appliedOutputSample)*1000.0/reader.sampleRate()<<','
                <<(plan.appliedOutputSample-num(row,"requested_output"))*1000.0/reader.sampleRate()<<','
                <<(plan.completionOutputSample-num(row,"requested_output"))*1000.0/reader.sampleRate()<<','<<guard.inputSample<<','<<guard.safe;
            for(auto w:guard.minimumWeight)summary<<','<<w;summary<<'\n';
            std::ofstream trace(output/(label+"_ramp.csv"));trace<<"input,output,old_hop,target_hop,actual_hop,protected,progress_samples,local_speed\n";
            const auto fixed=candidate.fixed(target);long long progress=0;
            for(auto i=plan.appliedFrame;i<=plan.rampEndFrame;++i){auto old=before.starts()[i+1]-before.starts()[i],goal=fixed->starts()[i+1]-fixed->starts()[i],actual=candidate.current().starts()[i+1]-candidate.current().starts()[i];
                const bool held=!candidate.diagnosticSafeRun(i);
                trace<<i*1024<<','<<candidate.current().starts()[i]<<','<<old<<','<<goal<<','<<actual<<','<<held<<','<<progress<<','<<1024.0/actual<<'\n';
                if(!held)progress+=option>=2?actual:std::max(1LL,std::min(old,goal)-1);
            }
            if(!guard.safe)continue;auto nextModes=modes;nextModes.emplace_back(guard.inputSample,false);
            auto length=std::size_t(std::llround(candidate.current().outputPositionForInputSample(reader.frames())));
            Phase35TransitionEngine(config).processWav(input,output/(label+".wav"),candidate.current(),nextModes,length);
            for(auto block:{1024,2048}) {
                WavStreamWriter writer(output/(label+"_"+std::to_string(block)+".wav"),reader.sampleRate(),reader.channels(),length);
                Phase36StreamingSpeedEngine(config).process(input,analysis,candidate.current(),length,block,
                    [&](const float*const* samples,std::size_t n,const auto&){writer.write(samples,n);},{},nextModes);
                writer.finish();
            }
        }
        std::cout<<"same_actual_frontier=1\nprepared="<<prepared<<"\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
