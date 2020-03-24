cmake_minimum_required(VERSION 3.12)
project(FFmpeg)

find_path(AVCODEC_INCLUDE_DIR libavcodec/avcodec.h)
find_library(AVCODEC_LIBRARY avcodec)

find_path(AVFORMAT_INCLUDE_DIR libavformat/avformat.h)
find_library(AVFORMAT_LIBRARY avformat)

find_path(AVUTIL_INCLUDE_DIR libavutil/avutil.h)
find_library(AVUTIL_LIBRARY avutil)

find_path(AVDEVICE_INCLUDE_DIR libavdevice/avdevice.h)
find_library(AVDEVICE_LIBRARY avdevice)

find_path(SWSCALE_INCLUDE_DIR libswscale/swscale.h)
find_library(SWSCALE_LIBRARY swscale)

find_path(AVFILTER_INCLUDE_DIR libavfilter/avfilter.h)
find_library(AVFILTER_LIBRARY avfilter)

find_path(AVRESAMPLE_INCLUDE_DIR libavresample/avresample.h)
find_library(AVRESAMPLE_LIBRARY avresample)

find_path(SWRESAMPLE_INCLUDE_DIR libswresample/swresample.h)
find_library(SWRESAMPLE_LIBRARY swresample)


add_library(FFmpeg INTERFACE)

target_include_directories(FFmpeg INTERFACE
        ${AVCODEC_INCLUDE_DIR}
        ${AVFORMAT_INCLUDE_DIR}
        ${AVUTIL_INCLUDE_DIR}
        ${AVDEVICE_INCLUDE_DIR}
        ${SWSCALE_INCLUDE_DIR}
        ${AVFILTER_INCLUDE_DIR}
        ${AVRESAMPLE_INCLUDE_DIR}
        ${SWRESAMPLE_INCLUDE_DIR}
        )

target_link_libraries(FFmpeg INTERFACE
        ${AVCODEC_LIBRARY}
        ${AVFORMAT_LIBRARY}
        ${AVUTIL_LIBRARY}
        ${AVDEVICE_LIBRARY}
        ${SWSCALE_LIBRARY}
        ${AVFILTER_LIBRARY}
        ${AVRESAMPLE_LIBRARY}
        ${SWRESAMPLE_LIBRARY}
        )
