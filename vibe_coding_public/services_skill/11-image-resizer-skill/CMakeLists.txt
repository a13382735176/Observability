cmake_minimum_required(VERSION 3.20)
project(image_resizer_skill LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)
FetchContent_Declare(
  httplib
  URL https://raw.githubusercontent.com/yhirose/cpp-httplib/v0.15.3/httplib.h
  DOWNLOAD_NO_EXTRACT TRUE
)
FetchContent_MakeAvailable(httplib)

add_executable(app src/main.cpp)
target_include_directories(app PRIVATE ${httplib_SOURCE_DIR})
