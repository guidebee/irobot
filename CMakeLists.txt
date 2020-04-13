cmake_minimum_required(VERSION 3.12)

if (DEFINED ENV{VCPKG_ROOT} AND NOT DEFINED CMAKE_TOOLCHAIN_FILE)
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
            CACHE STRING "")
endif ()
set(VCPKG_TARGET_TRIPLET $ENV{VCPKG_DEFAULT_TRIPLET} CACHE INTERNAL "" FORCE)

project(Android_iRobot VERSION 1.0.0 DESCRIPTION "Android iRobot Agent"
        LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS "-D__STDC_CONSTANT_MACROS")
# -------------------------------------------------------------
# library dependencies
find_package(SDL2 CONFIG REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(OpenCV CONFIG REQUIRED)
add_subdirectory(libs)

# -------------------------------------------------------------
include_directories(${CMAKE_HOME_DIRECTORY}/src ${PROJECT_BINARY_DIR}/src)

SET(COMMON_SOURCE_HEADERS
        ${CMAKE_HOME_DIRECTORY}/src/agent/agent_manager.hpp
        ${CMAKE_HOME_DIRECTORY}/src/agent/agent_controller.hpp
        ${CMAKE_HOME_DIRECTORY}/src/agent/agent_stream.hpp
        ${CMAKE_HOME_DIRECTORY}/src/ai/brain.hpp
        ${CMAKE_HOME_DIRECTORY}/src/android/input.hpp
        ${CMAKE_HOME_DIRECTORY}/src/android/keycodes.hpp
        ${CMAKE_HOME_DIRECTORY}/src/android/file_handler.hpp
        ${CMAKE_HOME_DIRECTORY}/src/android/receiver.hpp
        ${CMAKE_HOME_DIRECTORY}/src/message/device_msg.hpp
        ${CMAKE_HOME_DIRECTORY}/src/message/control_msg.hpp
        ${CMAKE_HOME_DIRECTORY}/src/message/blob_msg.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/cbuf.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/lock.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/log.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/queue.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/str_util.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/buffer_util.hpp
        ${CMAKE_HOME_DIRECTORY}/src/video/fps_counter.hpp
        ${CMAKE_HOME_DIRECTORY}/src/video/recorder.hpp
        ${CMAKE_HOME_DIRECTORY}/src/video/video_buffer.hpp
        ${CMAKE_HOME_DIRECTORY}/src/video/decoder.hpp
        ${CMAKE_HOME_DIRECTORY}/src/video/stream.hpp
        ${CMAKE_HOME_DIRECTORY}/src/ui/events.hpp
        ${CMAKE_HOME_DIRECTORY}/src/ui/input_manager.hpp
        ${CMAKE_HOME_DIRECTORY}/src/ui/event_converter.hpp
        ${CMAKE_HOME_DIRECTORY}/src/core/actor.hpp
        ${CMAKE_HOME_DIRECTORY}/src/core/common.hpp
        ${CMAKE_HOME_DIRECTORY}/src/core/controller.hpp
        ${CMAKE_HOME_DIRECTORY}/src/core/device_server.hpp
        ${CMAKE_HOME_DIRECTORY}/src/core/irobot_core.hpp
        ${CMAKE_HOME_DIRECTORY}/src/platform/command.hpp
        ${CMAKE_HOME_DIRECTORY}/src/platform/net.hpp
        )

SET(COMMON_SOURCES
        ${COMMON_SOURCE_HEADERS}
        ${CMAKE_HOME_DIRECTORY}/src/agent/agent_manager.cpp
        ${CMAKE_HOME_DIRECTORY}/src/agent/agent_controller.cpp
        ${CMAKE_HOME_DIRECTORY}/src/agent/agent_stream.cpp
        ${CMAKE_HOME_DIRECTORY}/src/ai/brain.cpp
        ${CMAKE_HOME_DIRECTORY}/src/android/file_handler.cpp
        ${CMAKE_HOME_DIRECTORY}/src/android/receiver.cpp
        ${CMAKE_HOME_DIRECTORY}/src/message/device_msg.cpp
        ${CMAKE_HOME_DIRECTORY}/src/message/control_msg.cpp
        ${CMAKE_HOME_DIRECTORY}/src/message/blob_msg.cpp
        ${CMAKE_HOME_DIRECTORY}/src/ui/event_converter.cpp
        ${CMAKE_HOME_DIRECTORY}/src/ui/screen.cpp
        ${CMAKE_HOME_DIRECTORY}/src/ui/input_manager.cpp
        ${CMAKE_HOME_DIRECTORY}/src/util/str_util.cpp
        ${CMAKE_HOME_DIRECTORY}/src/video/fps_counter.cpp
        ${CMAKE_HOME_DIRECTORY}/src/video/recorder.cpp
        ${CMAKE_HOME_DIRECTORY}/src/video/video_buffer.cpp
        ${CMAKE_HOME_DIRECTORY}/src/video/decoder.cpp
        ${CMAKE_HOME_DIRECTORY}/src/video/stream.cpp
        ${CMAKE_HOME_DIRECTORY}/src/core/actor.cpp
        ${CMAKE_HOME_DIRECTORY}/src/core/controller.cpp
        ${CMAKE_HOME_DIRECTORY}/src/core/device_server.cpp
        ${CMAKE_HOME_DIRECTORY}/src/core/irobot_core.cpp
        ${CMAKE_HOME_DIRECTORY}/src/platform/command.cpp
        ${CMAKE_HOME_DIRECTORY}/src/platform/net.cpp
        )


if (WIN32)
    SET(COMMON_SOURCES ${COMMON_SOURCES}
            ${CMAKE_HOME_DIRECTORY}/src/platform/windows/net.cpp
            ${CMAKE_HOME_DIRECTORY}/src/platform/windows/command.cpp)
else (WIN32)
    SET(COMMON_SOURCES ${COMMON_SOURCES}
            ${CMAKE_HOME_DIRECTORY}/src/platform/unix/net.cpp
            ${CMAKE_HOME_DIRECTORY}/src/platform/unix/command.cpp)
endif (WIN32)

configure_file(
        "${PROJECT_SOURCE_DIR}/config.in"
        "${PROJECT_BINARY_DIR}/src/config.hpp"
)

# -------------------------------------------------------------
# utility functions
function(APP name)
    set(APP_TARGET ${name})
    add_executable(${APP_TARGET} ${COMMON_SOURCES}
            ${CMAKE_HOME_DIRECTORY}/src/${APP_TARGET}.cpp)
    target_link_libraries(${APP_TARGET} PRIVATE FFmpeg)
    target_link_libraries(${APP_TARGET} PRIVATE SDL2::SDL2 SDL2::SDL2main)
    target_link_libraries(${APP_TARGET} PRIVATE ${OpenCV_LIBS})
    target_link_libraries(${APP_TARGET} PRIVATE nlohmann_json nlohmann_json::nlohmann_json)

    if (WIN32)
        target_link_libraries(${APP_TARGET} PRIVATE wsock32 ws2_32)
    endif ()

    install(DIRECTORY ${CMAKE_HOME_DIRECTORY}/server
            DESTINATION ${CMAKE_CURRENT_BINARY_DIR})


endfunction(APP)

# -------------------------------------------------------------
# project sub directories
add_subdirectory(apps)
add_subdirectory(docs)
add_subdirectory(tests)











