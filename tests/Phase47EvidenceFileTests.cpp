#include "prototype/Phase47EvidenceFile.h"
#include <iostream>
void check(bool value) { if (!value) throw std::runtime_error("Evidence assertion"); }
int main() {
    auto directory=std::filesystem::temp_directory_path()/ ("phase47_evidence_"+std::to_string(getpid()));
    std::filesystem::create_directories(directory);
    for (const auto stage:{"write","flush","close"}) {
        const auto path=directory/(std::string(stage)+".csv");
        setenv("PHASE47_IO_FAILURE_STAGE",stage,1);
        bool failed=false;
        try { ts::prototype::Phase47EvidenceFile file(path);file.stream()<<"id,value\n1,2\n";file.commit(); }
        catch (const std::exception&) { failed=true; }
        check(failed && !std::filesystem::exists(path));
    }
    unsetenv("PHASE47_IO_FAILURE_STAGE");
    { ts::prototype::Phase47EvidenceFile file(directory/"good.csv");file.stream()<<"id,value\n1,2\n";file.commit(); }
    check(std::filesystem::exists(directory/"good.csv"));
    bool failed=false;
    try { ts::prototype::Phase47EvidenceFile file(directory/"missing"/"open.csv"); }
    catch (const std::exception&) { failed=true; }
    check(failed);
    std::filesystem::remove_all(directory);
    std::cout<<"Evidence open/write/flush/close failure detection PASS\n";
}
