include(FetchContent)

set(
  LUMINA_LUNASVG_REVISION
  "59690a23981489acc3f73b8db229ef57bb69c544"
  CACHE STRING
  "Exact LunaSVG fork base revision"
)
set(
  LUMINA_CLIPPER2_REVISION
  "21ebba05db8894f0c7217ad35ea518080f324946"
  CACHE STRING
  "Exact Clipper2 revision"
)

function(lumina_fetch_native_svg_dependencies)
  set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build static native dependencies" FORCE)
  set(LUNASVG_BUILD_EXAMPLES OFF CACHE BOOL "Disable LunaSVG examples" FORCE)
  set(LUNASVG_DISABLE_LOAD_SYSTEM_FONTS ON CACHE BOOL "Disable ambient fonts" FORCE)
  set(CLIPPER2_TESTS OFF CACHE BOOL "Disable Clipper2 tests" FORCE)
  set(CLIPPER2_EXAMPLES OFF CACHE BOOL "Disable Clipper2 examples" FORCE)
  set(CLIPPER2_UTILS OFF CACHE BOOL "Disable Clipper2 utilities" FORCE)
  set(CLIPPER2_USINGZ OFF CACHE STRING "Disable Clipper2 Z support" FORCE)

  FetchContent_Declare(
    lunasvg
    GIT_REPOSITORY https://github.com/Neroued/lunasvg.git
    GIT_TAG ${LUMINA_LUNASVG_REVISION}
    GIT_SHALLOW FALSE
    GIT_PROGRESS TRUE
    PATCH_COMMAND
      ${CMAKE_COMMAND}
      -DSOURCE_DIR=<SOURCE_DIR>
      -DEXPECTED_REVISION=${LUMINA_LUNASVG_REVISION}
      -DPATCH_FILE=${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../patches/lunasvg-paint-recorder.patch
      -P ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/ApplyLunaSvgPatch.cmake
  )
  FetchContent_Declare(
    clipper2
    GIT_REPOSITORY https://github.com/AngusJohnson/Clipper2.git
    GIT_TAG ${LUMINA_CLIPPER2_REVISION}
    SOURCE_SUBDIR CPP
    GIT_SHALLOW FALSE
    GIT_PROGRESS TRUE
  )

  FetchContent_MakeAvailable(lunasvg clipper2)
endfunction()
