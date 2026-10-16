#include "prototype/Phase59Control.h"
#include "prototype/Phase58FixSnapshotMailbox.h"
#include <iostream>
using namespace ts::prototype;using namespace ts::prototype::phase59;
int main(){std::cout<<"{\"speed_operation_bytes\":"<<sizeof(SpeedOperation)<<",\"planning_frontier_bytes\":"<<sizeof(PlanningFrontier)<<",\"frontier_mailbox_bytes\":"<<sizeof(ValueMailbox<PlanningFrontier>)<<",\"request_bytes\":"<<sizeof(Phase39Request)<<",\"plan_bytes\":"<<sizeof(Phase39Plan)<<",\"density_mode_bytes\":"<<sizeof(std::pair<std::size_t,bool>)<<",\"audit_payload_bound_bytes\":"<<4096*sizeof(SpeedOperation)<<",\"history_payload_bound_bytes\":"<<maximumChanges*(sizeof(Phase39Request)+sizeof(Phase39Plan)+sizeof(std::pair<std::size_t,bool>))<<"}\n";}
