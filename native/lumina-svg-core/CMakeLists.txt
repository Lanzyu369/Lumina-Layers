cmake_minimum_required(VERSION 3.20)

if(CMAKE_HOST_APPLE)
  set(
    CMAKE_OSX_DEPLOYMENT_TARGET "12.0"
    CACHE STRING "Minimum supported macOS version" FORCE
  )
endif()

project(lumina_svg_core VERSION 0.3.0 LANGUAGES C CXX)

include(CTest)

option(
  LUMINA_SVG_BUILD_RASTER_ORACLE
  "Build the local LunaSVG raster-oracle executable"
  OFF
)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module NumPy)
find_package(pybind11 CONFIG REQUIRED)
find_package(Threads REQUIRED)

include(cmake/Dependencies.cmake)
lumina_fetch_native_svg_dependencies()

pybind11_add_module(
  _lumina_svg_core
  MODULE
  src/bindings.cpp
  src/coordinate_projection.cpp
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
  Threads::Threads
)
target_compile_definitions(_lumina_svg_core PRIVATE PYBIND11_DETAILED_ERROR_MESSAGES=1)
set_target_properties(
  _lumina_svg_core
  PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN ON
)

install(
  TARGETS _lumina_svg_core
  LIBRARY DESTINATION . COMPONENT lumina_svg_core
  RUNTIME DESTINATION . COMPONENT lumina_svg_core
)

if(LUMINA_SVG_BUILD_RASTER_ORACLE)
  add_executable(
    lumina_svg_raster_oracle
    tools/lunasvg_raster_oracle.cpp
  )
  target_link_libraries(
    lumina_svg_raster_oracle
    PRIVATE
    lunasvg::lunasvg
  )
endif()
install(
  FILES LICENSE THIRD_PARTY_NOTICES.md
  DESTINATION .
  COMPONENT lumina_svg_core
)

pybind11_add_module(
  _lumina_svg_compensation
  MODULE
  src/hole_compensation.cpp
)
target_link_libraries(_lumina_svg_compensation PRIVATE Clipper2)
target_compile_options(
  _lumina_svg_compensation
  PRIVATE $<$<CXX_COMPILER_ID:MSVC>:/utf-8>
)
set_target_properties(
  _lumina_svg_compensation
  PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN ON
)
install(
  TARGETS _lumina_svg_compensation
  LIBRARY DESTINATION . COMPONENT lumina_svg_core
  RUNTIME DESTINATION . COMPONENT lumina_svg_core
)
install(
  DIRECTORY THIRD_PARTY_LICENSES
  DESTINATION .
  COMPONENT lumina_svg_core
)

if(BUILD_TESTING)
  add_executable(
    lumina_svg_canonical_predicates_regression
    tests/canonical_predicates_regression.cpp
  )
  target_include_directories(
    lumina_svg_canonical_predicates_regression
    PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(
    lumina_svg_canonical_predicates_regression
    PRIVATE
    Clipper2
  )
  add_test(
    NAME lumina_svg_canonical_predicates_regression
    COMMAND lumina_svg_canonical_predicates_regression
  )
endif()
