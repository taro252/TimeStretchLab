cmake_minimum_required(VERSION 3.21)
project(TimeStretchLab VERSION 0.1 LANGUAGES CXX OBJCXX)

if(NOT APPLE)
    message(FATAL_ERROR "Phase 1 requires Apple Accelerate")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_library(ACCELERATE_FRAMEWORK Accelerate REQUIRED)
add_library(timestretch_core
    src/audio/WavReader.cpp
    src/audio/WavWriter.cpp
    src/audio/WavStream.cpp
    src/dsp/FFTAccelerate.cpp
    src/dsp/STFT.cpp
    src/dsp/OverlapAdd.cpp
    src/dsp/RingOverlapAdd.cpp
    src/dsp/PhaseVocoder.cpp
    src/dsp/PhaseLocker.cpp
    src/dsp/PartialTracker.cpp
    src/dsp/PeriodicResynchronizer.cpp
    src/dsp/TransientDetector.cpp
    src/dsp/TransientEventMap.cpp
    src/dsp/TransientAnchor.cpp
    src/dsp/StereoPhaseCoherence.cpp
    src/dsp/TimeMap.cpp
    src/dsp/MultiResolutionCrossover.cpp
    src/dsp/StreamingCrossover.cpp
    src/dsp/ChunkedTimeStretchEngine.cpp
    src/dsp/Phase13StreamingEngine.cpp
    src/dsp/Phase14PlaybackPipeline.cpp
    src/dsp/Phase18PcmCache.cpp
    src/dsp/TimeStretchEngine.cpp
    src/dsp/TimeStretchProcessor.cpp
    src/dsp/WSOLAEngine.cpp
    src/dsp/SinusoidalResidualEngine.cpp
    src/dsp/TonalResidualEngine.cpp
)
target_include_directories(timestretch_core PUBLIC src)
target_link_libraries(timestretch_core PUBLIC ${ACCELERATE_FRAMEWORK})
target_compile_options(timestretch_core PRIVATE -Wall -Wextra -Wpedantic)
file(GLOB PHASE18_DSP_SOURCES CONFIGURE_DEPENDS src/dsp/* src/audio/*)
list(SORT PHASE18_DSP_SOURCES)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${PHASE18_DSP_SOURCES})
set(PHASE18_DSP_SOURCE_DIGEST "")
foreach(PHASE18_DSP_SOURCE IN LISTS PHASE18_DSP_SOURCES)
    if(NOT IS_DIRECTORY "${PHASE18_DSP_SOURCE}")
        file(SHA256 "${PHASE18_DSP_SOURCE}" PHASE18_SOURCE_SHA)
        string(APPEND PHASE18_DSP_SOURCE_DIGEST "${PHASE18_DSP_SOURCE}:${PHASE18_SOURCE_SHA};")
    endif()
endforeach()
string(SHA256 PHASE18_DSP_FINGERPRINT "${PHASE18_DSP_SOURCE_DIGEST};${CMAKE_CXX_COMPILER_ID};${CMAKE_CXX_COMPILER_VERSION};${CMAKE_OSX_ARCHITECTURES};${CMAKE_OSX_DEPLOYMENT_TARGET};${CMAKE_BUILD_TYPE};${CMAKE_CXX_FLAGS};${CMAKE_CXX_FLAGS_RELEASE};${CMAKE_CXX_FLAGS_DEBUG};${CMAKE_SYSTEM_VERSION}")
target_compile_definitions(timestretch_core PRIVATE "TS_PHASE18_DSP_FINGERPRINT=\"${PHASE18_DSP_FINGERPRINT}\"")

add_executable(timestretch src/main.cpp)
target_link_libraries(timestretch PRIVATE timestretch_core)
add_executable(realtime_stretch src/realtime_main.cpp)
target_link_libraries(realtime_stretch PRIVATE timestretch_core)
add_executable(phase13_stream src/phase13_main.cpp)
target_link_libraries(phase13_stream PRIVATE timestretch_core)
add_executable(phase23_audio
    src/phase23_main.cpp
    src/prototype/Phase23VariableSpeedEngine.cpp
    src/prototype/Phase22VariableTimeMap.cpp)
target_link_libraries(phase23_audio PRIVATE timestretch_core)
add_executable(phase29_audio
    src/phase29_main.cpp
    src/prototype/Phase23VariableSpeedEngine.cpp
    src/prototype/Phase28ArbitraryTimeMap.cpp)
target_link_libraries(phase29_audio PRIVATE timestretch_core)
add_library(phase24_variable
    src/prototype/Phase24StreamingSpeedEngine.cpp
    src/prototype/Phase24PlaybackPipeline.cpp
    src/prototype/Phase22VariableTimeMap.cpp)
target_link_libraries(phase24_variable PUBLIC timestretch_core)
target_include_directories(phase24_variable PUBLIC src)
add_executable(phase14_sim src/phase14_main.cpp)
target_link_libraries(phase14_sim PRIVATE timestretch_core)
add_executable(phase17_seek_study src/phase17_seek_study.cpp)
target_link_libraries(phase17_seek_study PRIVATE timestretch_core)
add_executable(phase17_cache_prefill_study src/phase17_cache_prefill_study.cpp)
target_link_libraries(phase17_cache_prefill_study PRIVATE timestretch_core)
find_library(AVFOUNDATION_FRAMEWORK AVFoundation REQUIRED)
find_library(FOUNDATION_FRAMEWORK Foundation REQUIRED)
find_library(COREAUDIO_FRAMEWORK CoreAudio REQUIRED)
find_library(AUDIOTOOLBOX_FRAMEWORK AudioToolbox REQUIRED)
add_executable(phase15_play src/platform/macos/Phase15MacPlayback.mm)
target_link_libraries(phase15_play PRIVATE timestretch_core ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK})
target_compile_options(phase15_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase24_play src/platform/macos/Phase24MacPlayback.mm)
target_link_libraries(phase24_play PRIVATE phase24_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK})
target_compile_options(phase24_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase25_play src/platform/macos/Phase24MacPlayback.mm)
target_link_libraries(phase25_play PRIVATE phase24_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK})
target_compile_options(phase25_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_library(phase26_variable
    src/prototype/Phase26BidirectionalTimeMap.cpp
    src/prototype/Phase26PlaybackPipeline.cpp)
target_link_libraries(phase26_variable PUBLIC phase24_variable)
target_include_directories(phase26_variable PUBLIC src)
add_executable(phase26_play src/platform/macos/Phase26MacPlayback.mm)
target_link_libraries(phase26_play PRIVATE phase26_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK})
target_compile_options(phase26_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase27_repeated_tests tests/Phase27RepeatedTests.cpp
    src/prototype/Phase23VariableSpeedEngine.cpp)
target_link_libraries(phase27_repeated_tests PRIVATE phase26_variable)
add_executable(phase27_play src/platform/macos/Phase27MacPlayback.mm)
target_link_libraries(phase27_play PRIVATE phase26_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK})
target_compile_options(phase27_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_library(phase30_variable
    src/prototype/Phase28ArbitraryTimeMap.cpp
    src/prototype/Phase30PlaybackPipeline.cpp)
target_link_libraries(phase30_variable PUBLIC phase24_variable)
target_include_directories(phase30_variable PUBLIC src)
add_executable(phase30_playback_tests tests/Phase30PlaybackTests.cpp
    src/prototype/Phase23VariableSpeedEngine.cpp)
target_link_libraries(phase30_playback_tests PRIVATE phase30_variable)
add_executable(phase30_play src/platform/macos/Phase30MacPlayback.mm)
target_link_libraries(phase30_play PRIVATE phase30_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK})
target_compile_options(phase30_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase31_feasibility src/prototype/Phase31Feasibility.cpp)
target_link_libraries(phase31_feasibility PRIVATE timestretch_core)
target_compile_options(phase31_feasibility PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase31_render
    src/prototype/Phase31Render.cpp
    src/prototype/Phase31ResearchEngine.cpp)
target_link_libraries(phase31_render PRIVATE timestretch_core)
target_compile_options(phase31_render PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase37_render
    src/prototype/Phase37Render.cpp
    src/prototype/Phase37HighSpeedMap.cpp
    src/prototype/Phase37SynthesisEngine.cpp)
target_link_libraries(phase37_render PRIVATE timestretch_core)
target_compile_options(phase37_render PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase38_events
    src/prototype/Phase38EventDump.cpp
    src/prototype/Phase37HighSpeedMap.cpp)
target_link_libraries(phase38_events PRIVATE timestretch_core)
target_compile_options(phase38_events PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase35_render
    src/prototype/Phase35Render.cpp
    src/prototype/Phase35TimeMap.cpp
    src/prototype/Phase35PhaseVocoder.cpp
    src/prototype/Phase35StereoPhaseCoherence.cpp
    src/prototype/Phase35TransitionEngine.cpp
    src/prototype/Phase31ResearchEngine.cpp)
target_link_libraries(phase35_render PRIVATE timestretch_core)
target_compile_options(phase35_render PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase35_density_control
    src/prototype/Phase35DensityControl.cpp
    src/prototype/Phase35TimeMap.cpp
    src/prototype/Phase35PhaseVocoder.cpp
    src/prototype/Phase35StereoPhaseCoherence.cpp
    src/prototype/Phase35TransitionEngine.cpp)
target_link_libraries(phase35_density_control PRIVATE timestretch_core)
target_compile_options(phase35_density_control PRIVATE -Wall -Wextra -Wpedantic)
add_library(phase36_variable
    src/prototype/Phase35TimeMap.cpp
    src/prototype/Phase35PhaseVocoder.cpp
    src/prototype/Phase35StereoPhaseCoherence.cpp
    src/prototype/Phase36StreamingSpeedEngine.cpp
    src/prototype/Phase36PlaybackPipeline.cpp)
target_link_libraries(phase36_variable PUBLIC phase24_variable)
target_include_directories(phase36_variable PUBLIC src)
target_compile_options(phase36_variable PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase36_sim src/prototype/Phase36Sim.cpp)
target_link_libraries(phase36_sim PRIVATE phase36_variable)
target_compile_options(phase36_sim PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase39_probe src/prototype/Phase39Probe.cpp
    src/prototype/Phase39TimeMap.cpp src/prototype/Phase37HighSpeedMap.cpp
    src/prototype/Phase35TransitionEngine.cpp src/prototype/Phase37SynthesisEngine.cpp)
target_link_libraries(phase39_probe PRIVATE phase36_variable)
target_compile_options(phase39_probe PRIVATE -Wall -Wextra -Wpedantic)
add_library(phase39_variable
    src/prototype/Phase39TimeMap.cpp
    src/prototype/Phase37HighSpeedMap.cpp
    src/prototype/Phase39PlaybackPipeline.cpp
    src/prototype/Phase42DensityGuard.cpp)
target_link_libraries(phase39_variable PUBLIC phase36_variable)
target_include_directories(phase39_variable PUBLIC src)
target_compile_options(phase39_variable PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase39_sim src/prototype/Phase39Sim.cpp)
target_link_libraries(phase39_sim PRIVATE phase39_variable)
target_compile_options(phase39_sim PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase39_paced_sim src/prototype/Phase39PacedSim.cpp)
target_link_libraries(phase39_paced_sim PRIVATE phase39_variable)
target_compile_options(phase39_paced_sim PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase40_paced_sim src/prototype/Phase40PacedSim.cpp)
target_link_libraries(phase40_paced_sim PRIVATE phase39_variable)
target_compile_options(phase40_paced_sim PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase45_pcm_hash src/prototype/Phase45PcmHash.cpp)
target_link_libraries(phase45_pcm_hash PRIVATE timestretch_core)
add_executable(phase45_device_rate src/prototype/Phase45DeviceRate.cpp)
target_link_libraries(phase45_device_rate PRIVATE ${COREAUDIO_FRAMEWORK})
add_executable(phase41_map_trace src/prototype/Phase41MapTrace.cpp)
target_link_libraries(phase41_map_trace PRIVATE phase39_variable)
target_compile_options(phase41_map_trace PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase41_profile_sim src/prototype/Phase39Sim.cpp)
target_link_libraries(phase41_profile_sim PRIVATE phase39_variable)
target_compile_definitions(phase41_profile_sim PRIVATE PHASE41_ALLOC_COUNT=1)
target_compile_options(phase41_profile_sim PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase39_reference src/prototype/Phase39Reference.cpp
    src/prototype/Phase35TransitionEngine.cpp)
target_link_libraries(phase39_reference PRIVATE phase39_variable)
target_compile_options(phase39_reference PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase36_reference src/prototype/Phase36Reference.cpp
    src/prototype/Phase35TransitionEngine.cpp)
target_link_libraries(phase36_reference PRIVATE phase36_variable)
target_compile_options(phase36_reference PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase36_play src/platform/macos/Phase36MacPlayback.mm)
target_link_libraries(phase36_play PRIVATE phase36_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK})
target_compile_options(phase36_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase43_play src/platform/macos/Phase43MacPlayback.mm)
target_link_libraries(phase43_play PRIVATE phase39_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
target_compile_options(phase43_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase48_replay_blocks src/prototype/Phase48ReplayBlocks.cpp)
add_executable(phase50_play src/platform/macos/Phase43MacPlayback.mm)
add_executable(phase50_sim src/prototype/Phase39Sim.cpp)
add_executable(phase51_sim src/prototype/Phase39Sim.cpp)
add_executable(phase51_play src/platform/macos/Phase43MacPlayback.mm)
target_compile_definitions(phase51_play PRIVATE PHASE50_RESEARCH=1 PHASE51_RESEARCH=1)
target_compile_options(phase51_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
target_link_libraries(phase51_play PRIVATE phase39_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
add_executable(phase51_counterfactual src/prototype/Phase51Counterfactual.cpp src/prototype/Phase35TransitionEngine.cpp)
target_link_libraries(phase51_counterfactual PRIVATE phase39_variable)
add_executable(phase51_busy_study src/prototype/Phase51BusyStudy.cpp)
target_link_libraries(phase51_busy_study PRIVATE phase39_variable)
add_executable(phase51_replay_blocks src/prototype/Phase48ReplayBlocks.cpp)
target_compile_definitions(phase51_replay_blocks PRIVATE PHASE51_RESEARCH=1)
target_link_libraries(phase51_replay_blocks PRIVATE phase39_variable)
target_compile_definitions(phase51_sim PRIVATE PHASE50_RESEARCH=1 PHASE51_RESEARCH=1)
target_link_libraries(phase51_sim PRIVATE phase39_variable)
add_executable(phase51_reference src/prototype/Phase39Reference.cpp src/prototype/Phase35TransitionEngine.cpp)
target_compile_definitions(phase51_reference PRIVATE PHASE51_RESEARCH=1)
target_link_libraries(phase51_reference PRIVATE phase39_variable)
target_compile_definitions(phase50_sim PRIVATE PHASE50_RESEARCH=1)
target_link_libraries(phase50_sim PRIVATE phase39_variable)
add_executable(phase50_device_buffer src/prototype/Phase50DeviceBuffer.cpp)
target_link_libraries(phase50_device_buffer PRIVATE ${COREAUDIO_FRAMEWORK})
target_compile_definitions(phase50_play PRIVATE PHASE50_RESEARCH=1)
target_link_libraries(phase50_play PRIVATE phase39_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
target_compile_options(phase50_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
target_link_libraries(phase48_replay_blocks PRIVATE phase39_variable)
target_compile_options(phase48_replay_blocks PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase36_api_tests tests/Phase36ApiTests.cpp)
target_link_libraries(phase36_api_tests PRIVATE phase36_variable)
target_compile_options(phase36_api_tests PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase32_render
    src/prototype/Phase32Render.cpp
    src/prototype/Phase32ResearchEngine.cpp)
target_link_libraries(phase32_render PRIVATE timestretch_core)
target_compile_options(phase32_render PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase33_crossover src/prototype/Phase33Crossover.cpp)
target_link_libraries(phase33_crossover PRIVATE timestretch_core)
target_compile_options(phase33_crossover PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase33_trace
    src/prototype/Phase33TraceRender.cpp
    src/prototype/Phase33TraceEngine.cpp)
target_link_libraries(phase33_trace PRIVATE timestretch_core)
target_compile_options(phase33_trace PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase24_sim src/phase24_sim_main.cpp)
target_link_libraries(phase24_sim PRIVATE phase24_variable)
add_executable(phase101_offline_events src/phase101_offline_events.cpp)
target_link_libraries(phase101_offline_events PRIVATE timestretch_core)

add_executable(wsola_stretch src/wsola_main.cpp)
target_link_libraries(wsola_stretch PRIVATE timestretch_core)

add_executable(sinusoidal_residual_stretch src/sinusoidal_residual_main.cpp)
target_link_libraries(sinusoidal_residual_stretch PRIVATE timestretch_core)

add_executable(tonal_residual_stretch src/tonal_residual_main.cpp)
target_link_libraries(tonal_residual_stretch PRIVATE timestretch_core)

add_executable(wav_metrics src/wav_metrics.cpp)
target_link_libraries(wav_metrics PRIVATE timestretch_core)

add_executable(wav_compare src/wav_compare.cpp)
target_link_libraries(wav_compare PRIVATE timestretch_core)

add_executable(bass_pitch_metrics src/bass_pitch_metrics.cpp)
target_link_libraries(bass_pitch_metrics PRIVATE timestretch_core)

add_executable(stereo_spectral_metrics src/stereo_spectral_metrics.cpp)
target_link_libraries(stereo_spectral_metrics PRIVATE timestretch_core)

add_library(playback_engine src/playback/PlaybackEngine.cpp src/playback/PlaybackAnalysisCache.cpp)
target_include_directories(playback_engine PUBLIC src)
target_link_libraries(playback_engine PUBLIC phase39_variable)
target_compile_options(playback_engine PRIVATE -Wall -Wextra -Wpedantic)
add_library(macos_playback_engine src/platform/macos/MacPlaybackEngine.mm)
target_include_directories(macos_playback_engine PUBLIC src)
target_compile_options(macos_playback_engine PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
target_link_libraries(macos_playback_engine PUBLIC playback_engine PRIVATE ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
add_executable(playback_demo src/playback/PlaybackDemo.cpp)
target_link_libraries(playback_demo PRIVATE macos_playback_engine)
add_executable(playback_handoff_example EXCLUDE_FROM_ALL examples/mac_playback_handoff.cpp)
target_link_libraries(playback_handoff_example PRIVATE macos_playback_engine)
add_executable(playback_reference src/playback/PlaybackReference.cpp src/prototype/Phase35TransitionEngine.cpp)
target_compile_definitions(playback_reference PRIVATE PHASE51_RESEARCH=1)
target_link_libraries(playback_reference PRIVATE phase39_variable)
include(CTest)
if(BUILD_TESTING)
    add_executable(phase1_tests tests/Phase1Tests.cpp)
    target_link_libraries(phase1_tests PRIVATE timestretch_core)
    add_test(NAME phase1 COMMAND phase1_tests)

    add_executable(phase1_validation tests/Phase1Validation.cpp)
    target_link_libraries(phase1_validation PRIVATE timestretch_core)
    add_test(NAME phase1_validation COMMAND phase1_validation)

    add_executable(phase2_tests tests/Phase2Tests.cpp)
    target_link_libraries(phase2_tests PRIVATE timestretch_core)
    add_test(NAME phase2 COMMAND phase2_tests ${CMAKE_SOURCE_DIR}/results/phase1)

    add_executable(phase3_tests tests/Phase3Tests.cpp)
    target_link_libraries(phase3_tests PRIVATE timestretch_core)
    add_test(NAME phase3 COMMAND phase3_tests ${CMAKE_SOURCE_DIR}/results/phase2)

    add_executable(phase35_tests tests/Phase35Tests.cpp)
    target_link_libraries(phase35_tests PRIVATE timestretch_core)
    add_test(NAME phase35 COMMAND phase35_tests ${CMAKE_SOURCE_DIR}/results/phase35/artificial)

    add_executable(phase36_tests tests/Phase36Tests.cpp)
    target_link_libraries(phase36_tests PRIVATE timestretch_core)
    add_test(NAME phase36 COMMAND phase36_tests ${CMAKE_SOURCE_DIR}/results/phase36/artificial)

    add_executable(phase37_tests tests/Phase37Tests.cpp)
    target_link_libraries(phase37_tests PRIVATE timestretch_core)
    add_test(NAME phase37 COMMAND phase37_tests ${CMAKE_SOURCE_DIR}/results/phase37/artificial)

    add_executable(phase4_tests tests/Phase4Tests.cpp)
    target_link_libraries(phase4_tests PRIVATE timestretch_core)
    add_test(NAME phase4 COMMAND phase4_tests)

    add_executable(phase5_tests tests/Phase5Tests.cpp)
    target_link_libraries(phase5_tests PRIVATE timestretch_core)
    add_test(NAME phase5 COMMAND phase5_tests)

    add_executable(phase51_tests tests/Phase51Tests.cpp)
    target_link_libraries(phase51_tests PRIVATE timestretch_core)
    add_test(NAME phase51 COMMAND phase51_tests)

    add_executable(phase52_tests tests/Phase52Tests.cpp)
    target_link_libraries(phase52_tests PRIVATE timestretch_core)
    add_test(NAME phase52 COMMAND phase52_tests)

    add_executable(phase53_tests tests/Phase53Tests.cpp)
    target_link_libraries(phase53_tests PRIVATE timestretch_core)
    add_test(NAME phase53 COMMAND phase53_tests)

    add_executable(phase6_tests tests/Phase6Tests.cpp)
    target_link_libraries(phase6_tests PRIVATE timestretch_core)
    add_test(NAME phase6 COMMAND phase6_tests)

    add_executable(phase7_tests tests/Phase7Tests.cpp)
    target_link_libraries(phase7_tests PRIVATE timestretch_core)
    add_test(NAME phase7 COMMAND phase7_tests)

    add_executable(phase8a_tests tests/Phase8ATests.cpp)
    target_link_libraries(phase8a_tests PRIVATE timestretch_core)
    add_test(NAME phase8a COMMAND phase8a_tests)

    add_executable(phase9a_tests tests/Phase9ATests.cpp)
    target_link_libraries(phase9a_tests PRIVATE timestretch_core)
    add_test(NAME phase9a COMMAND phase9a_tests)

    add_executable(phase9c_tests tests/Phase9CTests.cpp)
    target_link_libraries(phase9c_tests PRIVATE timestretch_core)
    add_test(NAME phase9c COMMAND phase9c_tests)

    add_executable(phase10_tests tests/Phase10Tests.cpp)
    target_link_libraries(phase10_tests PRIVATE timestretch_core)
    add_test(NAME phase10 COMMAND phase10_tests)
    add_test(NAME phase101 COMMAND phase10_tests --phase101)
    add_test(NAME phase10_stress COMMAND phase10_tests --stress)
    add_test(NAME phase10_benchmark COMMAND phase10_tests --benchmark)

    add_executable(phase13_tests tests/Phase13Tests.cpp)
    target_link_libraries(phase13_tests PRIVATE timestretch_core)
    add_test(NAME phase13 COMMAND phase13_tests)
    add_executable(phase21_tests tests/Phase21Tests.cpp)
    target_link_libraries(phase21_tests PRIVATE timestretch_core)
    add_test(NAME phase21 COMMAND phase21_tests)

    add_executable(phase14_tests tests/Phase14Tests.cpp)
    target_link_libraries(phase14_tests PRIVATE timestretch_core)
    add_test(NAME phase14 COMMAND phase14_tests)
    add_executable(phase16_tests tests/Phase16Tests.cpp)
    target_link_libraries(phase16_tests PRIVATE timestretch_core)
    add_test(NAME phase16 COMMAND phase16_tests)
    add_executable(phase18_tests tests/Phase18Tests.cpp)
    target_link_libraries(phase18_tests PRIVATE timestretch_core)
    add_test(NAME phase18 COMMAND phase18_tests)
    add_executable(phase19_tests tests/Phase19Tests.cpp)
    target_link_libraries(phase19_tests PRIVATE timestretch_core)
    add_test(NAME phase19 COMMAND phase19_tests)
    add_executable(phase20_architecture_study tests/Phase20ArchitectureStudy.cpp)
    target_link_libraries(phase20_architecture_study PRIVATE timestretch_core)
    add_test(NAME phase20_architecture COMMAND phase20_architecture_study)
    add_executable(phase22_timemap_study
        tests/Phase22TimeMapStudy.cpp
        src/prototype/Phase22VariableTimeMap.cpp)
    target_link_libraries(phase22_timemap_study PRIVATE timestretch_core)
    add_test(NAME phase22_timemap COMMAND phase22_timemap_study)
    add_executable(phase22b_study
        tests/Phase22BStudy.cpp
        src/prototype/Phase22BResponsiveMap.cpp
        src/prototype/Phase22VariableTimeMap.cpp)
    target_link_libraries(phase22b_study PRIVATE timestretch_core)
    add_test(NAME phase22b COMMAND phase22b_study)
    add_test(NAME phase23 COMMAND python3
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/Phase23Smoke.py
        $<TARGET_FILE:phase13_stream> $<TARGET_FILE:phase23_audio>)
    add_executable(phase24_tests tests/Phase24Tests.cpp src/prototype/Phase23VariableSpeedEngine.cpp)
    target_link_libraries(phase24_tests PRIVATE phase24_variable)
    add_test(NAME phase24 COMMAND phase24_tests)
    add_executable(phase26_timemap_tests tests/Phase26TimeMapTests.cpp)
    target_link_libraries(phase26_timemap_tests PRIVATE phase26_variable)
    add_test(NAME phase26_timemap COMMAND phase26_timemap_tests)
    add_executable(phase26_playback_tests tests/Phase26PlaybackTests.cpp
        src/prototype/Phase23VariableSpeedEngine.cpp)
    target_link_libraries(phase26_playback_tests PRIVATE phase26_variable)
    add_test(NAME phase26_playback COMMAND phase26_playback_tests)
    add_test(NAME phase27_repeated COMMAND phase27_repeated_tests ${CMAKE_SOURCE_DIR})
    add_test(NAME phase27_synthetic COMMAND phase27_repeated_tests --synthetic)
    add_executable(phase28_map_study tests/Phase28MapStudy.cpp
        src/prototype/Phase28ArbitraryTimeMap.cpp
        src/prototype/Phase22VariableTimeMap.cpp)
    target_link_libraries(phase28_map_study PRIVATE timestretch_core)
    add_test(NAME phase28_map COMMAND phase28_map_study ${CMAKE_SOURCE_DIR})
    add_test(NAME phase29_audio COMMAND python3
        ${CMAKE_CURRENT_SOURCE_DIR}/tests/Phase29Smoke.py
        $<TARGET_FILE:phase13_stream> $<TARGET_FILE:phase29_audio>)
    add_test(NAME phase30_playback COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase30Smoke.py
        $<TARGET_FILE:phase30_playback_tests>)
    add_test(NAME phase31_feasibility COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase31Smoke.py
        $<TARGET_FILE:phase31_feasibility> $<TARGET_FILE:phase31_render>)
    add_test(NAME phase32_diagnostics COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase32Smoke.py
        $<TARGET_FILE:phase31_render> $<TARGET_FILE:phase32_render>)
    add_test(NAME phase33_diagnostics COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase33Smoke.py
        $<TARGET_FILE:phase31_render> $<TARGET_FILE:phase32_render>
        $<TARGET_FILE:phase33_trace> $<TARGET_FILE:phase33_crossover>)
    add_test(NAME phase35_variable_hop COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase35TransitionSmoke.py
        $<TARGET_FILE:phase35_render>)
    add_test(NAME phase36_streaming COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase36Smoke.py
        $<TARGET_FILE:phase36_sim> $<TARGET_FILE:phase36_reference>
        $<TARGET_FILE:phase36_api_tests>)
    add_test(NAME phase37_high_speed COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase37Smoke.py
        $<TARGET_FILE:phase37_render> $<TARGET_FILE:phase31_render>)
    add_test(NAME phase38_noise_diagnostic COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase38Smoke.py
        $<TARGET_FILE:phase37_render> $<TARGET_FILE:phase38_events>)
    add_test(NAME phase39_high_speed_streaming COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase39Smoke.py
        $<TARGET_FILE:phase39_sim> $<TARGET_FILE:phase39_reference> ${CMAKE_SOURCE_DIR})
    add_test(NAME phase40_high_speed_planning COMMAND python3
        ${CMAKE_SOURCE_DIR}/tests/Phase40Smoke.py
        $<TARGET_FILE:phase39_sim> $<TARGET_FILE:phase39_reference>
        ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    add_test(NAME phase42_safe_density COMMAND python3
        ${CMAKE_SOURCE_DIR}/scripts/phase42_guard_test.py)
    option(TIMESTRETCH_ENABLE_REALTIME_TESTS "Register OS-scheduled realtime validation (strict verdicts)" OFF)
    if(TIMESTRETCH_ENABLE_REALTIME_TESTS)
        add_test(NAME phase44_quality_gate COMMAND python3
            ${CMAKE_SOURCE_DIR}/scripts/phase44_quality_test.py)
        add_test(NAME phase45_deadline_integrity COMMAND python3
            ${CMAKE_SOURCE_DIR}/scripts/phase45_deadline_test.py)
        set_tests_properties(phase44_quality_gate phase45_deadline_integrity
            PROPERTIES RUN_SERIAL TRUE LABELS realtime)
    endif()
    add_executable(phase45_clock_tests tests/Phase45CallbackClockTests.cpp)
    target_link_libraries(phase45_clock_tests PRIVATE timestretch_core)
    add_test(NAME phase45_callback_clock COMMAND phase45_clock_tests)
    add_test(NAME phase45_live_validation COMMAND python3
        ${CMAKE_SOURCE_DIR}/scripts/phase45_live_test.py)
    add_test(NAME phase45_trace_parser COMMAND python3
        ${CMAKE_SOURCE_DIR}/scripts/phase45_trace_parser_test.py)
    add_executable(phase46_host_tests tests/Phase46HostClockTests.cpp)
    target_link_libraries(phase46_host_tests PRIVATE timestretch_core)
    add_test(NAME phase46_host_clock COMMAND phase46_host_tests)
    add_test(NAME phase46_measurement_validation COMMAND python3
        ${CMAKE_SOURCE_DIR}/scripts/phase46_validation_test.py)
    add_executable(phase47_evidence_tests tests/Phase47EvidenceFileTests.cpp)
    target_link_libraries(phase47_evidence_tests PRIVATE timestretch_core)
    add_test(NAME phase47_evidence_io COMMAND phase47_evidence_tests)
    add_test(NAME phase47_evidence_validation COMMAND python3
        ${CMAKE_SOURCE_DIR}/scripts/phase47_validation_test.py)
    add_test(NAME phase48_native_validation COMMAND python3
        ${CMAKE_SOURCE_DIR}/scripts/phase48_validation_test.py)
    add_test(NAME phase48_block_partition COMMAND python3
        ${CMAKE_SOURCE_DIR}/scripts/phase48_block_test.py
        $<TARGET_FILE:phase39_sim> $<TARGET_FILE:phase48_replay_blocks> $<TARGET_FILE:phase45_pcm_hash>)
    # Absolute-time normal-load integration trials must not compete with the
    # other CTest DSP workloads. Their strict timing/failure criteria stay intact.
    add_test(NAME phase49_metric_integrity COMMAND python3
        ${CMAKE_SOURCE_DIR}/scripts/phase49_metric_test.py)
    add_executable(phase49_stall_tests tests/Phase49StallTests.cpp)
    target_link_libraries(phase49_stall_tests PRIVATE phase39_variable)
    add_test(NAME phase49_stall_controls COMMAND phase49_stall_tests)
    add_test(NAME phase50_parent_verdict COMMAND python3 ${CMAKE_SOURCE_DIR}/scripts/phase50_parent_test.py)
    add_executable(phase50_boundary_tests tests/Phase50BoundaryTests.cpp)
    target_link_libraries(phase50_boundary_tests PRIVATE phase39_variable)
    add_test(NAME phase50_boundary_state COMMAND phase50_boundary_tests)
    add_test(NAME phase50_l1_pcm COMMAND python3 ${CMAKE_SOURCE_DIR}/scripts/phase50_l1_test.py)
    add_test(NAME phase51_resume_integrity COMMAND python3 ${CMAKE_SOURCE_DIR}/scripts/phase51_resume_test.py)
    add_executable(phase51_command_tests tests/Phase51CommandTests.cpp)
    target_include_directories(phase51_command_tests PRIVATE src)
    add_test(NAME phase51_busy_control COMMAND phase51_command_tests)
    add_test(NAME phase51_l2_pcm COMMAND python3 -B ${CMAKE_SOURCE_DIR}/scripts/phase51_pcm_test.py)
    add_test(NAME phase51_timeline_integrity COMMAND python3 -B ${CMAKE_SOURCE_DIR}/scripts/phase51_timing_test.py)
    add_executable(playback_api_tests tests/PlaybackEngineTests.cpp)
    target_link_libraries(playback_api_tests PRIVATE playback_engine)
    add_test(NAME phase52_playback_api COMMAND playback_api_tests)
    add_test(NAME phase52_player_verdict COMMAND python3 -B ${CMAKE_SOURCE_DIR}/scripts/phase52_verdict_test.py)
    add_test(NAME phase52_fixed_pcm COMMAND python3 -B ${CMAKE_SOURCE_DIR}/scripts/phase52_pcm_test.py)
    add_executable(phase53_callback_export_tests tests/Phase53CallbackExportTests.cpp)
    target_include_directories(phase53_callback_export_tests PRIVATE src)
    add_test(NAME phase53_callback_export COMMAND phase53_callback_export_tests)
    add_test(NAME phase53_session_integrity COMMAND python3 -B ${CMAKE_SOURCE_DIR}/scripts/phase53_verdict_test.py)
    add_test(NAME phase53_post_handoff_integrity COMMAND python3 -B ${CMAKE_SOURCE_DIR}/scripts/phase53_post_handoff_test.py)
    get_property(registered_tests DIRECTORY PROPERTY TESTS)
    foreach(test IN LISTS registered_tests)
        if(NOT test MATCHES "^(phase44_quality_gate|phase45_deadline_integrity)$")
            set_tests_properties(${test} PROPERTIES LABELS deterministic)
        endif()
    endforeach()
endif()

add_executable(phase54_startup_probe src/playback/Phase54StartupProbe.cpp)
target_link_libraries(phase54_startup_probe PRIVATE macos_playback_engine)
target_compile_definitions(phase54_startup_probe PRIVATE PHASE54_API=1)
if(BUILD_TESTING)
    add_executable(phase54_analysis_tests tests/Phase54AnalysisCacheTests.cpp)
    target_link_libraries(phase54_analysis_tests PRIVATE playback_engine)
    add_test(NAME phase54_analysis_cache COMMAND phase54_analysis_tests)
    set_tests_properties(phase54_analysis_cache PROPERTIES LABELS deterministic)
endif()
if(BUILD_TESTING)
    add_executable(phase54_seek_tests tests/Phase54SeekTests.cpp src/prototype/Phase35TransitionEngine.cpp)
    target_link_libraries(phase54_seek_tests PRIVATE playback_engine)
    add_test(NAME phase54_seek_pcm COMMAND phase54_seek_tests)
    set_tests_properties(phase54_seek_pcm PROPERTIES LABELS deterministic)
endif()
add_executable(phase54_core_probe src/playback/Phase54CoreProbe.cpp)
target_link_libraries(phase54_core_probe PRIVATE playback_engine)
add_executable(phase54_native src/playback/Phase54NativeStudy.cpp src/prototype/Phase35TransitionEngine.cpp)
target_link_libraries(phase54_native PRIVATE macos_playback_engine)
add_executable(phase54_seek_study src/playback/Phase54SeekStudy.cpp src/prototype/Phase35TransitionEngine.cpp)
target_link_libraries(phase54_seek_study PRIVATE playback_engine)
add_executable(phase54_fade_study src/playback/Phase54FadeStudy.cpp src/prototype/Phase35TransitionEngine.cpp)
target_link_libraries(phase54_fade_study PRIVATE playback_engine)

# Phase55 experiments are executables only: no new code in playback/DSP libraries.
add_executable(phase55_analysis_probe src/prototype/Phase55AnalysisProbe.cpp)
target_link_libraries(phase55_analysis_probe PRIVATE playback_engine)
target_compile_options(phase55_analysis_probe PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase55_startup_study src/prototype/Phase55StartupStudy.cpp)
target_link_libraries(phase55_startup_study PRIVATE playback_engine)
target_compile_options(phase55_startup_study PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase56_reference src/prototype/Phase56Reference.cpp)
target_link_libraries(phase56_reference PRIVATE phase39_variable)
add_library(phase56_incremental src/prototype/Phase56ProgressiveAnalysis.cpp)
target_link_libraries(phase56_incremental PUBLIC timestretch_core)
target_compile_options(phase56_incremental PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase56_check src/prototype/Phase56Check.cpp)
target_link_libraries(phase56_check PRIVATE phase56_incremental)
target_compile_options(phase56_check PRIVATE -Wall -Wextra -Wpedantic)
if(BUILD_TESTING)
    add_executable(phase56_tests tests/Phase56Tests.cpp)
    target_link_libraries(phase56_tests PRIVATE phase56_incremental)
    add_test(NAME phase56_state_safety COMMAND phase56_tests)
    add_executable(phase56_fixed_modes tests/Phase56FixedModes.cpp)
    target_link_libraries(phase56_fixed_modes PRIVATE phase39_variable phase56_incremental)
    add_test(NAME phase56_fixed_preset_maps COMMAND phase56_fixed_modes)
    add_test(NAME phase56_incremental_exact COMMAND python3 -B ${CMAKE_SOURCE_DIR}/tests/Phase56Smoke.py
        $<TARGET_FILE:phase56_check> $<TARGET_FILE:phase56_reference>)
    set_tests_properties(phase56_state_safety phase56_incremental_exact phase56_fixed_preset_maps PROPERTIES LABELS deterministic)
endif()
if(BUILD_TESTING)
    add_executable(phase55_dependency_tests tests/Phase55DependencyTests.cpp)
    target_link_libraries(phase55_dependency_tests PRIVATE timestretch_core)
    add_test(NAME phase55_dependency_counterexamples COMMAND phase55_dependency_tests)
    add_test(NAME phase55_prefix_dependencies COMMAND python3 -B
        ${CMAKE_SOURCE_DIR}/tests/Phase55Smoke.py $<TARGET_FILE:phase55_analysis_probe>)
    set_tests_properties(phase55_prefix_dependencies phase55_dependency_counterexamples PROPERTIES LABELS deterministic)
endif()

# Phase 57 independent oracle, frozen before shared DSP extraction.
add_executable(phase57_reference src/prototype/Phase57Reference.cpp)
target_link_libraries(phase57_reference PRIVATE phase39_variable)

add_library(phase57_synthesis src/prototype/Phase57ProgressiveSynthesis.cpp)
target_link_libraries(phase57_synthesis PUBLIC phase56_incremental phase36_variable)
target_compile_options(phase57_synthesis PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase57_check src/prototype/Phase57Check.cpp)
target_link_libraries(phase57_check PRIVATE phase57_synthesis)
target_compile_options(phase57_check PRIVATE -Wall -Wextra -Wpedantic)
if(BUILD_TESTING)
    add_executable(phase57_tests tests/Phase57Tests.cpp)
    target_link_libraries(phase57_tests PRIVATE phase57_synthesis)
    add_test(NAME phase57_state_safety COMMAND phase57_tests)
    set_tests_properties(phase57_state_safety PROPERTIES LABELS deterministic)
endif()
if(BUILD_TESTING)
    add_test(NAME phase57_pcm_exact COMMAND python3 -B ${CMAKE_SOURCE_DIR}/tests/Phase57Smoke.py
        $<TARGET_FILE:phase57_check> $<TARGET_FILE:phase57_reference>)
    set_tests_properties(phase57_pcm_exact PROPERTIES LABELS deterministic)
endif()

if(BUILD_TESTING)
    set_tests_properties(phase57_state_safety phase57_pcm_exact PROPERTIES TIMEOUT 600)
endif()

# Phase58 stays independent of the product playback targets.
add_library(phase59_transition src/prototype/Phase59ProgressiveTransition.cpp)
target_link_libraries(phase59_transition PUBLIC phase39_variable phase56_incremental)
target_compile_options(phase59_transition PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase59_reference src/prototype/Phase59Reference.cpp)
target_link_libraries(phase59_reference PRIVATE phase39_variable)
add_executable(phase59_captured_reference src/prototype/Phase59CapturedReference.cpp)
target_link_libraries(phase59_captured_reference PRIVATE phase39_variable)
add_executable(phase59_check src/prototype/Phase59Check.cpp)
target_link_libraries(phase59_check PRIVATE phase59_transition phase57_synthesis)
add_executable(phase59_progressive_replay src/prototype/Phase59ProgressiveReplay.cpp)
target_link_libraries(phase59_progressive_replay PRIVATE phase59_transition phase57_synthesis)
if(BUILD_TESTING)
    add_executable(phase59_tests tests/Phase59Tests.cpp)
    target_link_libraries(phase59_tests PRIVATE phase59_transition phase57_synthesis)
    add_test(NAME phase59_certified_planning COMMAND phase59_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase59_certified_planning PROPERTIES LABELS deterministic TIMEOUT 120)
    add_test(NAME phase59_dynamic_pcm COMMAND python3 -B ${CMAKE_SOURCE_DIR}/tests/Phase59PcmSmoke.py
        $<TARGET_FILE:phase59_reference> $<TARGET_FILE:phase59_check>
        $<TARGET_FILE:phase59_progressive_replay> $<TARGET_FILE:phase59_captured_reference>)
    set_tests_properties(phase59_dynamic_pcm PROPERTIES LABELS deterministic TIMEOUT 300)
endif()

add_library(phase58_realtime src/prototype/Phase58RealtimePipeline.cpp src/prototype/Phase58FixRealtimeWorker.cpp)
add_executable(phase58_product_reference src/prototype/Phase58ProductReference.cpp)
target_link_libraries(phase58_product_reference PRIVATE phase39_variable)
target_link_libraries(phase58_realtime PUBLIC phase57_synthesis phase59_transition ${AUDIOTOOLBOX_FRAMEWORK})
target_compile_options(phase58_realtime PRIVATE -Wall -Wextra -Wpedantic)

# Explicit experimental application adapter. Legacy target/dependencies stay unchanged.
execute_process(COMMAND git rev-parse HEAD WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    OUTPUT_VARIABLE PHASE60_BUILD_SHA OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
add_library(macos_progressive_playback_engine src/platform/macos/ProgressiveMacPlaybackEngine.mm)
target_include_directories(macos_progressive_playback_engine PUBLIC src)
target_compile_definitions(macos_progressive_playback_engine PRIVATE TIMESTRETCH_PHASE60_SHA="${PHASE60_BUILD_SHA}")
target_compile_options(macos_progressive_playback_engine PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
target_link_libraries(macos_progressive_playback_engine PUBLIC phase58_realtime
    PRIVATE ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
add_executable(phase60_playback_compare src/playback/Phase60PlaybackCompare.mm)
target_compile_options(phase60_playback_compare PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
set(PHASE60_APPROVED_LEGACY_HOST "${CMAKE_CURRENT_SOURCE_DIR}/build/phase60/approved_legacy/release/phase60_legacy_compare" CACHE FILEPATH "Separately built approved Phase54 comparison host")
target_compile_definitions(phase60_playback_compare PRIVATE PHASE60_APPROVED_LEGACY_HOST="${PHASE60_APPROVED_LEGACY_HOST}")
target_link_libraries(phase60_playback_compare PRIVATE macos_progressive_playback_engine macos_playback_engine)
add_executable(phase61_interactive_play src/playback/Phase61InteractivePlay.cpp)
target_link_libraries(phase61_interactive_play PRIVATE macos_progressive_playback_engine)
add_library(phase60_bridge_example OBJECT EXCLUDE_FROM_ALL examples/phase60_bridge.mm)
target_compile_options(phase60_bridge_example PRIVATE -fobjc-arc)
target_link_libraries(phase60_bridge_example PRIVATE macos_progressive_playback_engine)
if(BUILD_TESTING)
    add_executable(phase61_contract_tests tests/Phase61ContractTests.cpp)
    target_include_directories(phase61_contract_tests PRIVATE src)
    add_test(NAME phase61_contract COMMAND phase61_contract_tests)
    set_tests_properties(phase61_contract PROPERTIES LABELS deterministic TIMEOUT 30)
    add_executable(phase61_seek_check tests/Phase61SeekCheck.cpp)
    target_link_libraries(phase61_seek_check PRIVATE phase58_realtime)
    add_executable(phase61_fast_seek_study src/prototype/Phase61FastSeekStudy.cpp)
    target_link_libraries(phase61_fast_seek_study PRIVATE phase58_realtime)
    add_executable(phase61_fast_seek_tests tests/Phase61FastSeekTests.cpp)
    target_link_libraries(phase61_fast_seek_tests PRIVATE phase58_realtime)
    add_test(NAME phase61_fast_seek_state COMMAND python3 -B ${CMAKE_SOURCE_DIR}/tests/Phase61FastSeekSmoke.py $<TARGET_FILE:phase61_fast_seek_tests>)
    set_tests_properties(phase61_fast_seek_state PROPERTIES LABELS deterministic TIMEOUT 600)
    add_executable(phase61_safety_tests tests/Phase61SafetyTests.cpp)
    target_link_libraries(phase61_safety_tests PRIVATE phase58_realtime)
    add_executable(phase61_checkpoint_tests tests/Phase61CheckpointTests.cpp)
    target_link_libraries(phase61_checkpoint_tests PRIVATE phase58_realtime)
    add_test(NAME phase61_checkpoint COMMAND phase61_checkpoint_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase61_checkpoint PROPERTIES LABELS deterministic TIMEOUT 120)
    add_test(NAME phase61_safety COMMAND phase61_safety_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase61_safety PROPERTIES LABELS deterministic TIMEOUT 120)
    add_executable(phase61_seek_reference src/prototype/Phase61SeekReference.cpp)
    target_link_libraries(phase61_seek_reference PRIVATE phase39_variable)
    add_executable(paused_speed_pipeline_tests tests/PausedSpeedPipelineTests.cpp)
    target_link_libraries(paused_speed_pipeline_tests PRIVATE phase58_realtime)
    add_test(NAME paused_speed_pipeline COMMAND paused_speed_pipeline_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(paused_speed_pipeline PROPERTIES LABELS deterministic TIMEOUT 120)
    add_executable(paused_speed_loop_tests EXCLUDE_FROM_ALL tests/PausedSpeedLoopTests.cpp)
    target_link_libraries(paused_speed_loop_tests PRIVATE macos_progressive_playback_engine)
    add_executable(paused_speed_boundary_tests EXCLUDE_FROM_ALL tests/PausedSpeedBoundaryTests.cpp)
    target_link_libraries(paused_speed_boundary_tests PRIVATE macos_progressive_playback_engine)
    add_executable(paused_speed_native_tests EXCLUDE_FROM_ALL tests/PausedSpeedNativeTests.cpp)
    target_link_libraries(paused_speed_native_tests PRIVATE macos_progressive_playback_engine)
    add_executable(phase61_native_tests EXCLUDE_FROM_ALL tests/Phase61NativeTests.cpp)
    target_link_libraries(phase61_native_tests PRIVATE macos_progressive_playback_engine)
    add_executable(phase61_fast_native_tests EXCLUDE_FROM_ALL tests/Phase61FastNativeTests.cpp)
    target_link_libraries(phase61_fast_native_tests PRIVATE macos_progressive_playback_engine)
    add_executable(phase61_interactive_native_tests EXCLUDE_FROM_ALL tests/Phase61InteractiveNativeTests.cpp)
    add_library(phase61_callback_heap_probe SHARED EXCLUDE_FROM_ALL tests/Phase61CallbackMallocProbe.cpp)
    target_link_libraries(phase61_interactive_native_tests PRIVATE macos_progressive_playback_engine phase61_callback_heap_probe)
    add_executable(phase61_interactive_eof_tests EXCLUDE_FROM_ALL tests/Phase61InteractiveEofTests.cpp)
    target_link_libraries(phase61_interactive_eof_tests PRIVATE macos_progressive_playback_engine phase61_callback_heap_probe)
    add_executable(phase61_output_transition_tests tests/Phase61OutputTransitionTests.cpp)
    target_include_directories(phase61_output_transition_tests PRIVATE src)
    add_test(NAME phase61_output_transition COMMAND phase61_output_transition_tests)
    set_tests_properties(phase61_output_transition PROPERTIES LABELS deterministic TIMEOUT 30)
    add_executable(phase61_pipeline_sync_tests tests/Phase61PipelineSyncTests.cpp)
    target_link_libraries(phase61_pipeline_sync_tests PRIVATE phase58_realtime)
    add_test(NAME phase61_pipeline_sync COMMAND phase61_pipeline_sync_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase61_pipeline_sync PROPERTIES LABELS deterministic TIMEOUT 120)
    add_executable(phase61_sync_restart_native_tests EXCLUDE_FROM_ALL tests/Phase61SyncRestartNativeTests.cpp)
    target_link_libraries(phase61_sync_restart_native_tests PRIVATE macos_progressive_playback_engine phase61_callback_heap_probe)
    add_executable(phase61_device_route_tests EXCLUDE_FROM_ALL tests/Phase61DeviceRouteTests.cpp)
    target_link_libraries(phase61_device_route_tests PRIVATE macos_progressive_playback_engine)
    find_library(PHASE61_APPKIT_FRAMEWORK AppKit REQUIRED)
    add_executable(phase61_sandbox_app MACOSX_BUNDLE EXCLUDE_FROM_ALL tests/Phase61SandboxApp.mm tests/Phase61NativeTests.cpp)
    target_compile_definitions(phase61_sandbox_app PRIVATE PHASE61_SANDBOX_APP=1)
    target_compile_options(phase61_sandbox_app PRIVATE -fobjc-arc)
    target_link_libraries(phase61_sandbox_app PRIVATE macos_progressive_playback_engine ${PHASE61_APPKIT_FRAMEWORK})
    set_target_properties(phase61_sandbox_app PROPERTIES MACOSX_BUNDLE_GUI_IDENTIFIER "org.timestretchlab.phase61-sandbox" MACOSX_BUNDLE_BUNDLE_NAME "Phase61 Sandbox")
    add_executable(phase61_fast_sandbox_app MACOSX_BUNDLE EXCLUDE_FROM_ALL tests/Phase61FastSandboxApp.mm tests/Phase61FastNativeTests.cpp)
    target_compile_definitions(phase61_fast_sandbox_app PRIVATE PHASE61_FAST_SANDBOX=1)
    target_compile_options(phase61_fast_sandbox_app PRIVATE -fobjc-arc)
    target_link_libraries(phase61_fast_sandbox_app PRIVATE macos_progressive_playback_engine ${PHASE61_APPKIT_FRAMEWORK})
    set_target_properties(phase61_fast_sandbox_app PROPERTIES MACOSX_BUNDLE_GUI_IDENTIFIER "org.timestretchlab.phase61-fast-sandbox" MACOSX_BUNDLE_BUNDLE_NAME "Phase61 Fast Sandbox")
    add_test(NAME phase61_pcm_suffix COMMAND python3 -B ${CMAKE_SOURCE_DIR}/tests/Phase61SeekSmoke.py
        $<TARGET_FILE:phase61_seek_check> $<TARGET_FILE:phase61_seek_reference>)
    set_tests_properties(phase61_pcm_suffix PROPERTIES LABELS deterministic TIMEOUT 600)
    add_executable(phase60_contract_tests tests/Phase60ContractTests.cpp)
    target_include_directories(phase60_contract_tests PRIVATE src)
    add_test(NAME phase60_contract COMMAND phase60_contract_tests)
    set_tests_properties(phase60_contract PROPERTIES LABELS deterministic TIMEOUT 30)
    add_executable(phase60_adapter_tests tests/Phase60AdapterTests.cpp)
    target_link_libraries(phase60_adapter_tests PRIVATE macos_progressive_playback_engine)
    add_executable(phase60_lifecycle_tests EXCLUDE_FROM_ALL tests/Phase60LifecycleTests.cpp)
    target_link_libraries(phase60_lifecycle_tests PRIVATE macos_progressive_playback_engine)
    # Real output test is run explicitly and serially; never mixed into DSP CTest.
endif()
if(BUILD_TESTING)
    add_executable(phase59_control_tests tests/Phase59ControlTests.cpp)
    target_link_libraries(phase59_control_tests PRIVATE phase58_realtime)
    add_test(NAME phase59_request_control COMMAND phase59_control_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase59_request_control PROPERTIES LABELS deterministic TIMEOUT 120)
endif()
add_executable(phase58_check src/prototype/Phase58Check.cpp)
target_link_libraries(phase58_check PRIVATE phase58_realtime)
add_executable(phase58_native src/prototype/Phase58Native.mm)
target_link_libraries(phase58_native PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
target_compile_options(phase58_native PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase59_native src/prototype/Phase58Native.mm)
target_compile_definitions(phase59_native PRIVATE PHASE59_RESEARCH=1)
target_link_libraries(phase59_native PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
target_compile_options(phase59_native PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase59_fix_startup_probe src/prototype/Phase58Native.mm)
target_compile_definitions(phase59_fix_startup_probe PRIVATE PHASE59_RESEARCH=1 PHASE59_FIX_STARTUP=1)
target_link_libraries(phase59_fix_startup_probe PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
target_compile_options(phase59_fix_startup_probe PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase59_fix_fixed_probe src/prototype/Phase58Native.mm)
target_compile_definitions(phase59_fix_fixed_probe PRIVATE PHASE59_FIX_STARTUP=1)
target_link_libraries(phase59_fix_fixed_probe PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
target_compile_options(phase59_fix_fixed_probe PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
add_executable(phase59_fix_eos_probe tests/Phase59FixEOSProbe.cpp)
add_executable(phase59_fix2_sourcenode src/platform/macos/Phase59Fix2SourceNode.mm)
target_link_libraries(phase59_fix2_sourcenode PRIVATE timestretch_core ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK} ${AUDIOTOOLBOX_FRAMEWORK})
target_compile_options(phase59_fix2_sourcenode PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
foreach(fix2_mode IN ITEMS fixed dynamic)
    add_executable(phase59_fix2_${fix2_mode}_probe src/prototype/Phase58Native.mm)
    target_compile_definitions(phase59_fix2_${fix2_mode}_probe PRIVATE PHASE59_FIX_STARTUP=1 PHASE59_FIX2_CLOCK=1)
    if(fix2_mode STREQUAL "dynamic")
        target_compile_definitions(phase59_fix2_${fix2_mode}_probe PRIVATE PHASE59_RESEARCH=1)
    endif()
    target_link_libraries(phase59_fix2_${fix2_mode}_probe PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
    target_compile_options(phase59_fix2_${fix2_mode}_probe PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
endforeach()
target_link_libraries(phase59_fix_eos_probe PRIVATE phase58_realtime)
target_compile_options(phase59_fix_eos_probe PRIVATE -Wall -Wextra -Wpedantic)
if(BUILD_TESTING)
    add_executable(phase59_fix_vocoder_tests tests/Phase59FixVocoderTests.cpp
        tests/reference/phase59_fix/Before59FixPhaseVocoder.cpp)
    target_link_libraries(phase59_fix_vocoder_tests PRIVATE phase36_variable)
    add_executable(phase59_fix_vocoder_bench tests/Phase59FixVocoderBench.cpp
        tests/reference/phase59_fix/Before59FixPhaseVocoder.cpp)
    target_link_libraries(phase59_fix_vocoder_bench PRIVATE phase36_variable)
    add_test(NAME phase59_fix_frozen_vocoder COMMAND phase59_fix_vocoder_tests)
    set_tests_properties(phase59_fix_frozen_vocoder PROPERTIES LABELS deterministic TIMEOUT 120)
    add_executable(phase59_fix_stereo_tests tests/Phase59FixStereoTests.cpp
        tests/reference/phase59_fix/Before59FixPhaseVocoder.cpp
        tests/reference/phase59_fix/Before59FixStereoPhaseCoherence.cpp)
    target_link_libraries(phase59_fix_stereo_tests PRIVATE phase36_variable)
    add_test(NAME phase59_fix_frozen_stereo COMMAND phase59_fix_stereo_tests)
    set_tests_properties(phase59_fix_frozen_stereo PROPERTIES LABELS deterministic TIMEOUT 120)
endif()
add_executable(phase58_legacy_startup src/prototype/Phase58LegacyStartup.cpp)
target_link_libraries(phase58_legacy_startup PRIVATE macos_playback_engine)
add_executable(phase58_fix_scheduling_probe src/prototype/Phase58FixSchedulingProbe.mm)
target_link_libraries(phase58_fix_scheduling_probe PRIVATE phase57_synthesis ${FOUNDATION_FRAMEWORK} ${AUDIOTOOLBOX_FRAMEWORK})
target_compile_options(phase58_fix_scheduling_probe PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
if(BUILD_TESTING)
    add_executable(phase58_tests tests/Phase58Tests.cpp)
    target_link_libraries(phase58_tests PRIVATE phase58_realtime)
    add_test(NAME phase58_state_safety COMMAND phase58_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase58_state_safety PROPERTIES LABELS deterministic TIMEOUT 120)
    add_test(NAME phase58_fifo_pcm COMMAND python3 -B ${CMAKE_SOURCE_DIR}/tests/Phase58PcmSmoke.py
        $<TARGET_FILE:phase58_check> $<TARGET_FILE:phase58_product_reference>)
    set_tests_properties(phase58_fifo_pcm PROPERTIES LABELS deterministic TIMEOUT 300)
    add_executable(phase58_fix_tests tests/Phase58FixTests.cpp)
    target_link_libraries(phase58_fix_tests PRIVATE phase58_realtime)
    add_test(NAME phase58_fix_diagnostics COMMAND phase58_fix_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase58_fix_diagnostics PROPERTIES LABELS deterministic TIMEOUT 120)
    add_test(NAME phase58_fix_trace_analysis COMMAND python3 -B ${CMAKE_SOURCE_DIR}/tests/Phase58FixTraceTests.py)
    set_tests_properties(phase58_fix_trace_analysis PROPERTIES LABELS deterministic TIMEOUT 60)
    add_executable(phase58_fix_mailbox_tests tests/Phase58FixMailboxTests.cpp)
    target_link_libraries(phase58_fix_mailbox_tests PRIVATE phase58_realtime)
    add_test(NAME phase58_fix_mailbox COMMAND phase58_fix_mailbox_tests)
    set_tests_properties(phase58_fix_mailbox PROPERTIES LABELS deterministic TIMEOUT 120)
    add_executable(phase58_fix_worker_tests tests/Phase58FixWorkerTests.cpp)
    target_link_libraries(phase58_fix_worker_tests PRIVATE phase58_realtime)
    add_test(NAME phase58_fix_worker_lifecycle COMMAND phase58_fix_worker_tests)
    set_tests_properties(phase58_fix_worker_lifecycle PROPERTIES LABELS deterministic TIMEOUT 120)
endif()

# Phase62 research only. No Merodoa or Legacy default changes.
add_executable(phase62_loop_play src/playback/Phase62LoopPlay.cpp)
target_link_libraries(phase62_loop_play PRIVATE macos_progressive_playback_engine)
if(BUILD_TESTING)
    add_executable(phase62_loop_tests tests/Phase62LoopTests.cpp)
    target_link_libraries(phase62_loop_tests PRIVATE phase58_realtime)
    add_test(NAME phase62_loop COMMAND phase62_loop_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase62_loop PROPERTIES LABELS deterministic TIMEOUT 180)
    add_executable(phase62_native_tests EXCLUDE_FROM_ALL tests/Phase62NativeTests.cpp)
    target_link_libraries(phase62_native_tests PRIVATE macos_progressive_playback_engine phase61_callback_heap_probe)
    add_executable(phase62_render_tests tests/Phase62RenderTests.mm)
    target_compile_options(phase62_render_tests PRIVATE -fobjc-arc)
    target_link_libraries(phase62_render_tests PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
    add_test(NAME phase62_render COMMAND phase62_render_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase62_render PROPERTIES LABELS deterministic TIMEOUT 180)
endif()
if(BUILD_TESTING)
    add_executable(phase62_deadline_native EXCLUDE_FROM_ALL tests/Phase62DeadlineNative.cpp)
    target_link_libraries(phase62_deadline_native PRIVATE macos_progressive_playback_engine phase61_callback_heap_probe)
endif()

if(BUILD_TESTING)
    add_executable(phase62_fix_safety_tests tests/Phase62FixSafetyTests.mm)
    target_compile_options(phase62_fix_safety_tests PRIVATE -fobjc-arc)
    target_link_libraries(phase62_fix_safety_tests PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
    add_test(NAME phase62_fix_safety COMMAND phase62_fix_safety_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase62_fix_safety PROPERTIES LABELS deterministic TIMEOUT 180)
    if(DEFINED PHASE62_FIX_BASELINE_SOURCE)
        add_executable(phase62_fix_baseline_safety EXCLUDE_FROM_ALL tests/Phase62FixSafetyTests.mm)
        target_compile_definitions(phase62_fix_baseline_safety PRIVATE PHASE62_FIX_BASELINE_SOURCE="${PHASE62_FIX_BASELINE_SOURCE}")
        target_compile_options(phase62_fix_baseline_safety PRIVATE -fobjc-arc)
        target_link_libraries(phase62_fix_baseline_safety PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
    endif()
endif()
if(BUILD_TESTING)
    add_test(NAME phase62_evidence COMMAND python3 -B ${CMAKE_SOURCE_DIR}/tests/Phase62EvidenceTests.py)
    set_tests_properties(phase62_evidence PROPERTIES LABELS deterministic TIMEOUT 60)
endif()
if(BUILD_TESTING)
    add_executable(phase62_fix_reuse_tests tests/Phase62FixReuseTests.cpp)
    target_link_libraries(phase62_fix_reuse_tests PRIVATE phase58_realtime)
    add_test(NAME phase62_fix_reuse COMMAND phase62_fix_reuse_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase62_fix_reuse PROPERTIES LABELS deterministic TIMEOUT 300)
endif()
if(BUILD_TESTING)
    add_executable(phase62_fix_render_tests tests/Phase62FixRenderTests.mm)
    target_compile_options(phase62_fix_render_tests PRIVATE -fobjc-arc)
    target_link_libraries(phase62_fix_render_tests PRIVATE phase58_realtime ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK} ${COREAUDIO_FRAMEWORK})
    add_test(NAME phase62_fix_period COMMAND phase62_fix_render_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase62_fix_period PROPERTIES LABELS deterministic TIMEOUT 300)
endif()
if(BUILD_TESTING)
    add_executable(phase62_fix_checkpoint_tests tests/Phase62FixCheckpointTests.cpp)
    target_link_libraries(phase62_fix_checkpoint_tests PRIVATE phase57_synthesis)
    add_test(NAME phase62_fix_checkpoint COMMAND phase62_fix_checkpoint_tests ${CMAKE_SOURCE_DIR}/results/phase31/input/mix.wav)
    set_tests_properties(phase62_fix_checkpoint PROPERTIES LABELS deterministic TIMEOUT 300)
    add_executable(phase62_fix_sandbox_app MACOSX_BUNDLE EXCLUDE_FROM_ALL tests/Phase62FixSandboxApp.mm tests/Phase62NativeTests.cpp)
    target_compile_definitions(phase62_fix_sandbox_app PRIVATE PHASE62_SANDBOX_APP=1)
    target_compile_options(phase62_fix_sandbox_app PRIVATE -fobjc-arc)
    target_link_libraries(phase62_fix_sandbox_app PRIVATE macos_progressive_playback_engine phase61_callback_heap_probe ${PHASE61_APPKIT_FRAMEWORK})
    set_target_properties(phase62_fix_sandbox_app PROPERTIES MACOSX_BUNDLE_GUI_IDENTIFIER "org.timestretchlab.phase62-fix-sandbox" MACOSX_BUNDLE_BUNDLE_NAME "Phase62 Fix Sandbox")
    add_executable(phase62_fix_clock_native EXCLUDE_FROM_ALL tests/Phase62FixClockNative.cpp)
    target_link_libraries(phase62_fix_clock_native PRIVATE macos_progressive_playback_engine)
endif()
