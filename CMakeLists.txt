cmake_minimum_required(VERSION 3.21)
project(TimeStretchLab VERSION 0.1 LANGUAGES CXX)

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
    src/dsp/TimeStretchEngine.cpp
    src/dsp/WSOLAEngine.cpp
    src/dsp/SinusoidalResidualEngine.cpp
)
target_include_directories(timestretch_core PUBLIC src)
target_link_libraries(timestretch_core PUBLIC ${ACCELERATE_FRAMEWORK})
target_compile_options(timestretch_core PRIVATE -Wall -Wextra -Wpedantic)

add_executable(timestretch src/main.cpp)
target_link_libraries(timestretch PRIVATE timestretch_core)

add_executable(wsola_stretch src/wsola_main.cpp)
target_link_libraries(wsola_stretch PRIVATE timestretch_core)

add_executable(sinusoidal_residual_stretch src/sinusoidal_residual_main.cpp)
target_link_libraries(sinusoidal_residual_stretch PRIVATE timestretch_core)

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
endif()
