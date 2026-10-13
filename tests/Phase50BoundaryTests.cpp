#include "prototype/Phase50Boundary.h"
#include <iostream>
#include <stdexcept>
using namespace ts;using namespace ts::prototype;
int main() {
    std::vector<long long> nodes;for (int i=0;i<64;++i) nodes.push_back(i*2048);
    TimeMap map(1024,nodes,{});
    Phase36StreamingSpeedEngine::Frontier f;
    f.preparedOutput=5000;f.lastProcessedInput={3072,3072,3072};
    f.nextInput={4096,4096,4096};f.finalizedOla={7000,7000,7000};
    f.firstUnprocessedFirSource={2048,2048};
    const auto b=phase50Boundary(f,map,4096);
    if (b.precise!=7000 || b.legacy!=12288) throw std::runtime_error("Boundary coordinate regression");
    auto changed=nodes;for (std::size_t i=5;i<changed.size();++i) changed[i]+=128;
    if (!phase50PreservesState(f,map,TimeMap(1024,changed,{}))) throw std::runtime_error("Safe future rejected");
    changed[3]+=1;
    if (phase50PreservesState(f,map,TimeMap(1024,changed,{}))) throw std::runtime_error("Processed interpolation changed");
    changed=nodes;changed[4]=6999;
    if (phase50PreservesState(f,map,TimeMap(1024,changed,{}))) throw std::runtime_error("Finalized OLA intrusion accepted");
    f.recentFrameCount[2]=1;f.recentFrameInput[2][0]=2176;f.recentFrameOutput[2][0]=4353;
    if (phase50PreservesState(f,map,map)) throw std::runtime_error("Actual history mismatch accepted");
    std::cout<<"Dependency fence / actual frame preservation PASS; no realtime claim\n";
}
