include(FetchContent)

set(
  LUMINA_LUNASVG_REVISION
  "59690a23981489acc3f73b8db229ef57bb69c544"
)
set(
  LUMINA_CLIPPER2_REVISION
  "21ebba05db8894f0c7217ad35ea518080f324946"
)

function(lumina_reject_dependency_source_override dependency_name)
  string(TOUPPER "${dependency_name}" dependency_upper)
  set(override_name "FETCHCONTENT_SOURCE_DIR_${dependency_upper}")
  if(DEFINED ${override_name} AND NOT "${${override_name}}" STREQUAL "")
    message(FATAL_ERROR
      "${override_name} is not supported for release builds; native SVG dependencies are immutable"
    )
  endif()
endfunction()

function(lumina_verify_git_head source_dir expected_revision dependency_name)
  execute_process(
    COMMAND git rev-parse HEAD
    WORKING_DIRECTORY "${source_dir}"
    RESULT_VARIABLE revision_result
    OUTPUT_VARIABLE actual_revision
    ERROR_VARIABLE revision_error
    OUTPUT_STRIP_TRAILING_WHITESPACE
  )
  if(NOT revision_result EQUAL 0 OR NOT actual_revision STREQUAL expected_revision)
    message(FATAL_ERROR
      "${dependency_name} source revision mismatch: expected ${expected_revision}, got ${actual_revision}; ${revision_error}"
    )
  endif()
endfunction()

function(lumina_verify_dependency_sources lunasvg_dir clipper2_dir)
  lumina_verify_git_head(
    "${lunasvg_dir}" "${LUMINA_LUNASVG_REVISION}" "LunaSVG"
  )
  lumina_verify_git_head(
    "${clipper2_dir}" "${LUMINA_CLIPPER2_REVISION}" "Clipper2"
  )

  execute_process(
    COMMAND git diff --no-ext-diff --binary
    WORKING_DIRECTORY "${lunasvg_dir}"
    RESULT_VARIABLE lunasvg_diff_result
    OUTPUT_VARIABLE actual_lunasvg_patch
    ERROR_VARIABLE lunasvg_diff_error
  )
  file(READ
    "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../patches/lunasvg-paint-recorder.patch"
    expected_lunasvg_patch
  )
  if(NOT lunasvg_diff_result EQUAL 0
      OR NOT actual_lunasvg_patch STREQUAL expected_lunasvg_patch)
    message(FATAL_ERROR
      "LunaSVG source does not exactly match the approved recorder patch: ${lunasvg_diff_error}"
    )
  endif()

  execute_process(
    COMMAND git diff --no-ext-diff --binary
    WORKING_DIRECTORY "${clipper2_dir}"
    RESULT_VARIABLE clipper2_diff_result
    OUTPUT_VARIABLE actual_clipper2_patch
    ERROR_VARIABLE clipper2_diff_error
  )
  file(READ
    "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../patches/clipper2-svg-miter-fallback.patch"
    expected_clipper2_patch
  )
  if(NOT clipper2_diff_result EQUAL 0
      OR NOT actual_clipper2_patch STREQUAL expected_clipper2_patch)
    message(FATAL_ERROR
      "Clipper2 source does not exactly match the approved SVG miter patch: ${clipper2_diff_error}"
    )
  endif()

  execute_process(
    COMMAND git ls-files --others --exclude-standard
    WORKING_DIRECTORY "${lunasvg_dir}"
    OUTPUT_VARIABLE lunasvg_untracked
    OUTPUT_STRIP_TRAILING_WHITESPACE
  )
  execute_process(
    COMMAND git ls-files --others --exclude-standard
    WORKING_DIRECTORY "${clipper2_dir}"
    OUTPUT_VARIABLE clipper2_untracked
    OUTPUT_STRIP_TRAILING_WHITESPACE
  )
  if(NOT lunasvg_untracked STREQUAL "")
    message(FATAL_ERROR "LunaSVG source contains unapproved untracked files")
  endif()
  if(NOT clipper2_untracked STREQUAL "")
    message(FATAL_ERROR "Clipper2 source contains unapproved untracked files")
  endif()
endfunction()

function(lumina_fetch_native_svg_dependencies)
  lumina_reject_dependency_source_override(lunasvg)
  lumina_reject_dependency_source_override(clipper2)
  set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build static native dependencies" FORCE)
  set(LUNASVG_BUILD_EXAMPLES OFF CACHE BOOL "Disable LunaSVG examples" FORCE)
  set(LUNASVG_DISABLE_LOAD_SYSTEM_FONTS ON CACHE BOOL "Disable ambient fonts" FORCE)
  set(USE_SYSTEM_PLUTOVG OFF CACHE BOOL "Use pinned PlutoVG submodule" FORCE)
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
    PATCH_COMMAND
      ${CMAKE_COMMAND}
      -DSOURCE_DIR=<SOURCE_DIR>
      -DPATCH_FILE=${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../patches/clipper2-svg-miter-fallback.patch
      -P ${CMAKE_CURRENT_FUNCTION_LIST_DIR}/ApplyClipper2Patch.cmake
  )

  FetchContent_MakeAvailable(lunasvg clipper2)
  lumina_verify_dependency_sources(
    "${lunasvg_SOURCE_DIR}" "${clipper2_SOURCE_DIR}"
  )
endfunction()
