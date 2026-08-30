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

pybind11_add_module(
  _lumina_svg_core
  MODULE
  src/bindings.cpp
  src/geometry_kernel.cpp
  src/paint_command.cpp
  src/result.cpp
  src/stroke_expander.cpp
)
target_include_directories(
  _lumina_svg_core
  PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_link_libraries(
  _lumina_svg_core
  PRIVATE
  lunasvg::lunasvg
  Clipper2
)
target_compile_definitions(_lumina_svg_core PRIVATE PYBIND11_DETAILED_ERROR_MESSAGES=1)
set_target_properties(
  _lumina_svg_core
  PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN ON
)

install(TARGETS _lumina_svg_core LIBRARY DESTINATION . RUNTIME DESTINATION .)
