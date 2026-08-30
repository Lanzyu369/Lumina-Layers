cmake_minimum_required(VERSION 3.20)

project(lumina_svg_core VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module NumPy)
find_package(pybind11 CONFIG REQUIRED)

include(cmake/Dependencies.cmake)
lumina_fetch_native_svg_dependencies()

# The extension target is added with the first recorder implementation. Keeping
# dependency resolution here makes a source distribution independently buildable.

