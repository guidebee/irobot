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
find_package(OpenCV REQUIRED)
add_subdirectory(libs)

# -------------------------------------------------------------
include_directories(${CMAKE_HOME_DIRECTORY}/src ${PROJECT_BINARY_DIR}/src)

SET(COMMON_SOURCE_HEADERS
        ${CMAKE_HOME_DIRECTORY}/src/util/buffer_util.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/cbuf.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/helper.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/lock.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/log.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/queue.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/str_util.hpp
        ${CMAKE_HOME_DIRECTORY}/src/util/net.hpp
        ${CMAKE_HOME_DIRECTORY}/src/video/common.hpp)

SET(COMMON_SOURCES
        ${COMMON_SOURCE_HEADERS}
        ${CMAKE_HOME_DIRECTORY}/src/video/common.cpp
        ${CMAKE_HOME_DIRECTORY}/src/util/helper.cpp
        ${CMAKE_HOME_DIRECTORY}/src/util/str_util.cpp
        ${CMAKE_HOME_DIRECTORY}/src/util/net.cpp)


if (WIN32)
    SET(COMMON_SOURCES ${COMMON_SOURCES}
            ${CMAKE_HOME_DIRECTORY}/src/platform/windows/net.cpp)
else (WIN32)
    SET(COMMON_SOURCES ${COMMON_SOURCES}
            ${CMAKE_HOME_DIRECTORY}/src/platform/unix/net.cpp)
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

    if (WIN32)
        install(TARGETS ${name}
                RUNTIME DESTINATION ${CMAKE_BINARY_DIR})
    endif ()

endfunction(APP)

# -------------------------------------------------------------
# project sub directories
add_subdirectory(apps)
add_subdirectory(docs)
add_subdirectory(tests)











