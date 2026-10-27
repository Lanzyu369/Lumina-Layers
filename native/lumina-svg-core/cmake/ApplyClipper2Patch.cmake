set(
  APPROVED_CLIPPER2_REVISION
  "21ebba05db8894f0c7217ad35ea518080f324946"
)

if(NOT DEFINED SOURCE_DIR OR NOT DEFINED PATCH_FILE)
  message(FATAL_ERROR "Clipper2 patch verification requires SOURCE_DIR and PATCH_FILE")
endif()

execute_process(
  COMMAND git rev-parse HEAD
  WORKING_DIRECTORY "${SOURCE_DIR}"
  RESULT_VARIABLE revision_result
  OUTPUT_VARIABLE actual_revision
  ERROR_VARIABLE revision_error
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT revision_result EQUAL 0)
  message(FATAL_ERROR "Cannot verify Clipper2 revision: ${revision_error}")
endif()
if(NOT actual_revision STREQUAL APPROVED_CLIPPER2_REVISION)
  message(FATAL_ERROR
    "Clipper2 SVG patch is pinned to ${APPROVED_CLIPPER2_REVISION}, got ${actual_revision}"
  )
endif()

execute_process(
  COMMAND git apply --check "${PATCH_FILE}"
  WORKING_DIRECTORY "${SOURCE_DIR}"
  RESULT_VARIABLE patch_check_result
  ERROR_VARIABLE patch_check_error
)
if(patch_check_result EQUAL 0)
  execute_process(
    COMMAND git apply "${PATCH_FILE}"
    WORKING_DIRECTORY "${SOURCE_DIR}"
    RESULT_VARIABLE patch_result
    ERROR_VARIABLE patch_error
  )
  if(NOT patch_result EQUAL 0)
    message(FATAL_ERROR "Failed to apply Clipper2 SVG patch: ${patch_error}")
  endif()
  message(STATUS "Applied Clipper2 SVG patch at ${actual_revision}")
  return()
endif()

execute_process(
  COMMAND git apply --reverse --check "${PATCH_FILE}"
  WORKING_DIRECTORY "${SOURCE_DIR}"
  RESULT_VARIABLE reverse_check_result
)
if(reverse_check_result EQUAL 0)
  message(STATUS "Clipper2 SVG patch already applied at ${actual_revision}")
  return()
endif()

message(FATAL_ERROR
  "Clipper2 SVG patch does not apply cleanly at ${actual_revision}: ${patch_check_error}"
)
