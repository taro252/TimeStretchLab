#import <AppKit/AppKit.h>
#import <AVFoundation/AVFoundation.h>
#include "audio/WavWriter.h"
#include <filesystem>
#include <fstream>
#include <thread>
#include <array>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
int runLoopNative(int,char**);
int runLoopFaults(const std::filesystem::path&,const std::filesystem::path&);
static int runPhase62FixSandbox(const std::filesystem::path& input,const std::filesystem::path& out){
    std::filesystem::create_directory(out);
    for(const auto& preset:{"candidate","baseline"}){
        std::array<std::string,8> text{"phase62",input.string(),(out/preset).string(),".1","2","100",preset,"normal"};
        std::array<char*,8> argv{};for(std::size_t i=0;i<argv.size();++i)argv[i]=text[i].data();
        if(runLoopNative(int(argv.size()),argv.data()))return 1;
    }
    return runLoopFaults(input,out/"faults");
}

static NSWindow* hostWindow=nil;
static NSTextField* statusLabel=nil;
static void runSelected(NSURL* input,NSURL* directory){
    statusLabel.stringValue=@"100msループと障害処理をSandbox内で検証しています…";
    const bool inputScope=[input startAccessingSecurityScopedResource],outputScope=[directory startAccessingSecurityScopedResource];
    std::thread([input,directory,inputScope,outputScope]{@autoreleasepool {
        int code=1;std::string error;
        const std::filesystem::path out=std::filesystem::path(directory.fileSystemRepresentation)/("run_"+std::to_string(getpid()));
        try{
            std::filesystem::create_directory(out);
            NSError* problem=nil;AVAudioFile* file=[[AVAudioFile alloc]initForReading:input commonFormat:AVAudioPCMFormatFloat32 interleaved:NO error:&problem];
            if(!file)throw std::runtime_error(problem.localizedDescription.UTF8String);
            auto format=file.processingFormat;const auto capacity=AVAudioFrameCount(std::min<AVAudioFramePosition>(file.length,AVAudioFramePosition(format.sampleRate*4)));
            if(!capacity||(format.sampleRate!=44100&&format.sampleRate!=48000)||(format.channelCount!=1&&format.channelCount!=2))throw std::runtime_error("Unsupported bounded source");
            AVAudioPCMBuffer* pcm=[[AVAudioPCMBuffer alloc]initWithPCMFormat:format frameCapacity:capacity];
            if(![file readIntoBuffer:pcm frameCount:capacity error:&problem])throw std::runtime_error(problem.localizedDescription.UTF8String);
            ts::AudioBuffer decoded;decoded.sampleRate=std::uint32_t(format.sampleRate);decoded.channels.resize(format.channelCount);
            for(unsigned c=0;c<format.channelCount;++c)decoded.channels[c].assign(pcm.floatChannelData[c],pcm.floatChannelData[c]+pcm.frameLength);
            const auto wav=out/"sandbox_decoded_4s.wav";ts::WavWriter::write(wav,decoded);
            const auto denied=std::filesystem::path(directory.fileSystemRepresentation).parent_path()/"SANDBOX_DENIED.txt";
            errno=0;const int fd=open(denied.c_str(),O_RDONLY|O_CLOEXEC);const int deniedError=errno;if(fd>=0)close(fd);
            std::ofstream context(out/"SANDBOX_CONTEXT.json");
            context<<"{\"pid\":"<<getpid()<<",\"home\":\""<<NSHomeDirectory().UTF8String<<"\",\"input_scope_started\":"<<(inputScope?"true":"false")<<",\"output_scope_started\":"<<(outputScope?"true":"false")<<",\"outside_grant_open_fd\":"<<fd<<",\"outside_grant_errno\":"<<deniedError<<",\"decoded_once_before_sessions\":true,\"decoded_frames\":"<<pcm.frameLength<<",\"rate\":"<<decoded.sampleRate<<",\"channels\":"<<decoded.channels.size()<<"}\n";context.close();
            code=runPhase62FixSandbox(wav,out/"native");
        }catch(const std::exception& e){error=e.what();}
        std::ofstream status(out/"APP_RESULT.json");status<<"{\"exit\":"<<code<<",\"error_present\":"<<(!error.empty()?"true":"false")<<"}\n";status.close();
        if(!error.empty()){std::ofstream failure(out/"error.txt");failure<<error<<'\n';}
        dispatch_async(dispatch_get_main_queue(),^{if(inputScope)[input stopAccessingSecurityScopedResource];if(outputScope)[directory stopAccessingSecurityScopedResource];[NSApp terminate:nil];});
    }}).detach();
}

@interface Phase62FixDelegate : NSObject <NSApplicationDelegate>
@end
@implementation Phase62FixDelegate
- (void)applicationDidFinishLaunching:(NSNotification*)notification {
    (void)notification;
    hostWindow=[[NSWindow alloc]initWithContentRect:NSMakeRect(0,0,640,160)
        styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];
    hostWindow.title=@"Phase62Fix Sandbox";
    statusLabel=[NSTextField labelWithString:@"Select the bounded source and the Phase62Fix output folder."];
    statusLabel.frame=NSMakeRect(20,60,600,60);[hostWindow.contentView addSubview:statusLabel];
    [hostWindow center];[hostWindow makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
    NSOpenPanel* sourcePanel=[NSOpenPanel openPanel];sourcePanel.canChooseFiles=YES;sourcePanel.canChooseDirectories=NO;
    sourcePanel.message=@"Phase 62 Fix: Sandbox内で読み取る音源を選択します（先頭4秒のみを検証用WAVへ変換）。";
    [sourcePanel beginSheetModalForWindow:hostWindow completionHandler:^(NSModalResponse sourceResult){
        if(sourceResult!=NSModalResponseOK){[NSApp terminate:nil];return;}
        NSURL* input=sourcePanel.URL;
        NSOpenPanel* outputPanel=[NSOpenPanel openPanel];outputPanel.canChooseFiles=NO;outputPanel.canChooseDirectories=YES;
        outputPanel.message=@"Phase 62 Fix: TimeStretchLab/build/phase62_fix/run_01/sandbox_io を検証出力先として選択してください。";
        [outputPanel beginSheetModalForWindow:hostWindow completionHandler:^(NSModalResponse outputResult){
            if(outputResult!=NSModalResponseOK){[NSApp terminate:nil];return;}
            runSelected(input,outputPanel.URL);
        }];
    }];
}
@end
int main(){@autoreleasepool {
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    Phase62FixDelegate* delegate=[[Phase62FixDelegate alloc]init];[NSApp setDelegate:delegate];
    [NSApp run];return 0;
}}
