# Import the staged HRX packages at the top level, so the directory-scoped imported targets are visible
# everywhere. llama.cpp's HRX test targets link hrx::hrx from tests/, a sibling of ggml/src/ggml-hrx where
# find_package(hrx) runs, and an imported target does not leave that directory's scope.
if(NOT hrx_DIR OR NOT loomc_DIR)
  message(FATAL_ERROR "hrx_DIR and loomc_DIR must name the staged HRX install to import its packages")
endif()
find_package(hrx CONFIG REQUIRED)
find_package(loomc CONFIG REQUIRED)
