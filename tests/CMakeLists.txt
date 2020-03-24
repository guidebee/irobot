cmake_minimum_required(VERSION 3.12)
project(tests)

find_package(Catch2 CONFIG REQUIRED)

SET(TEST_SOURCE all_tests.cpp ${COMMON_SOURCES})
add_executable(all_tests ${TEST_SOURCE})

target_link_libraries(all_tests PRIVATE Catch2::Catch2 FFmpeg)
target_link_libraries(all_tests PRIVATE SDL2::SDL2 SDL2::SDL2main)