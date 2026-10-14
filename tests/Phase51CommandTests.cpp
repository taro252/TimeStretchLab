#include "prototype/Phase51CommandControl.h"
#include <iostream>
using C=ts::prototype::Phase51CommandControl;
int main(){
 for(auto interval:{100,200,400,800,1500}){
  C latest(4,C::Policy::Latest);latest.arrive(0,1,false);latest.dispatch(latest.next(true,1),1);
  latest.arrive(1,1+interval,true);latest.arrive(2,1+interval*2,true);latest.arrive(3,1+interval*3,true);
  if(latest.operations[1].state!="Replaced"||latest.operations[2].state!="Replaced"||latest.next(true,10000)!=3)return 1;
  latest.dispatch(3,10000);if(latest.operations[3].busyNs!=10000-(1+interval*3))return 1;
  try{latest.arrive(3,10001,false);return 1;}catch(const std::logic_error&){}
  C strict(2,C::Policy::Strict);strict.arrive(0,1,true);if(!strict.failed||strict.operations[0].state!="BusyRejected")return 1;
  C cont(3,C::Policy::Continue);cont.arrive(0,1,true);cont.arrive(1,2,false);if(cont.failed||cont.next(true,3)!=1)return 1;
  cont.dispatch(1,3);cont.operations[1].state="Rejected";cont.arrive(2,4,false);if(cont.next(true,4)!=2)return 1;
  cont.stop(5);if(cont.operations[2].state!="Stopped")return 1;
 }
 std::cout<<"5 interval control tests PASS; actual target scenarios are in phase51_busy_study; no realtime/PCM claim\n";
}
