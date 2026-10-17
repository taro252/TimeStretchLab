#import <Foundation/Foundation.h>
#include "platform/macos/ProgressiveMacPlaybackEngine.h"

// Compile-checked example only. Merodoa's repository/SwiftUI is not modified.
// Every method, including close/deallocation, runs on the same serial work queue.
@interface TSLProgressiveExample : NSObject
- (BOOL)preparePath:(NSString*)path error:(NSError**)error;
- (BOOL)playWithError:(NSError**)error;
- (NSDictionary*)readingWithError:(NSError**)error;
- (void)close;
@end
@implementation TSLProgressiveExample {
    std::unique_ptr<ts::playback::ProgressiveMacPlaybackEngine> _engine;
}
- (BOOL)preparePath:(NSString*)path error:(NSError**)error {
    try {
        if([NSThread isMainThread])throw std::logic_error("専用制御キューを使用してください");
        if(!_engine)_engine=std::make_unique<ts::playback::ProgressiveMacPlaybackEngine>();
        ts::playback::ProgressiveOptions options;options.initialSpeed=1.0;
        return _engine->prepare(path.fileSystemRepresentation,options); // Accepted, not Ready
    } catch(const std::exception& e){if(error)*error=[NSError errorWithDomain:@"TSLExperimental" code:1 userInfo:@{NSLocalizedDescriptionKey:@(e.what())}];return NO;}
}
- (BOOL)playWithError:(NSError**)error {
    try {return _engine&&_engine->play();}
    catch(const std::exception& e){if(error)*error=[NSError errorWithDomain:@"TSLExperimental" code:2 userInfo:@{NSLocalizedDescriptionKey:@(e.what())}];return NO;}
}
- (NSDictionary*)readingWithError:(NSError**)error {
    try {
        if(!_engine)return @{};
        const auto s=_engine->getStateSnapshot();const auto d=_engine->getPlaybackDiagnostics();
        return @{@"state":@(ts::playback::progressive::name(s.state)),@"preparation":@(s.preparation),@"session":@(s.session),@"inputGeneration":@(s.inputGeneration),@"requestedSpeed":@(s.requestedSpeed),@"appliedTargetSpeed":@(s.appliedTargetSpeed),@"missingFrames":@(d.missingFrames),@"underrunCalls":@(d.underrunCalls),@"seekSupported":@NO};
    }catch(const std::exception& e){if(error)*error=[NSError errorWithDomain:@"TSLExperimental" code:3 userInfo:@{NSLocalizedDescriptionKey:@(e.what())}];return nil;}
}
- (void)close {if(_engine){_engine->stop();_engine.reset();}}
@end
