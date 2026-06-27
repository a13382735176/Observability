cmake_minimum_required(VERSION 3.13)
project(image-resizer CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# cpp-httplib is single-header. Download it at configure time.
set(HTTPLIB_VERSION v0.16.0)
set(HTTPLIB_URL https://raw.githubusercontent.com/yhirose/cpp-httplib/${HTTPLIB_VERSION}/httplib.h)
set(HTTPLIB_PATH ${CMAKE_CURRENT_BINARY_DIR}/httplib.h)
if(NOT EXISTS ${HTTPLIB_PATH})
    message(STATUS "Downloading cpp-httplib ${HTTPLIB_VERSION}")
    file(DOWNLOAD ${HTTPLIB_URL} ${HTTPLIB_PATH}
         STATUS dl_status
         TLS_VERIFY ON)
    list(GET dl_status 0 dl_code)
    if(NOT dl_code EQUAL 0)
        message(FATAL_ERROR "Failed to download httplib.h: ${dl_status}")
    endif()
endif()

add_executable(app main.cpp)
target_include_directories(app PRIVATE . ${CMAKE_CURRENT_BINARY_DIR})
find_package(Threads REQUIRED)
target_link_libraries(app PRIVATE Threads::Threads)
