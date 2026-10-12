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
add_executable(phase36_reference src/prototype/Phase36Reference.cpp
    src/prototype/Phase35TransitionEngine.cpp)
target_link_libraries(phase36_reference PRIVATE phase36_variable)
target_compile_options(phase36_reference PRIVATE -Wall -Wextra -Wpedantic)
add_executable(phase36_play src/platform/macos/Phase36MacPlayback.mm)
target_link_libraries(phase36_play PRIVATE phase36_variable ${AVFOUNDATION_FRAMEWORK} ${FOUNDATION_FRAMEWORK})
target_compile_options(phase36_play PRIVATE -fobjc-arc -Wall -Wextra -Wpedantic)
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
endif()
