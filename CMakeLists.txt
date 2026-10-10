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
endif()
