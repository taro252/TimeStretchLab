#include "platform/macos/MacPlaybackEngine.h"
#include <stdexcept>
#include <iostream>
using namespace ts::playback;
int main(){
 for(int i=0;i<1000;++i){
  if(detail::callbackHistoryReadable(PlaybackState::Draining,false,0))throw std::runtime_error("Draining export permitted");
  if(detail::callbackHistoryReadable(PlaybackState::Playing,true,0))throw std::runtime_error("active export permitted");
  if(detail::callbackHistoryReadable(PlaybackState::Failed,false,1))throw std::runtime_error("in-flight export permitted");
  for(auto state:{PlaybackState::Ended,PlaybackState::Stopped,PlaybackState::Paused,PlaybackState::Failed})
   if(!detail::callbackHistoryReadable(state,false,0))throw std::runtime_error("quiescent export refused");
 }
 std::cout<<"Read-only callback export policy: Draining/active/in-flight denied, quiescent terminal/pause allowed\n";
}
