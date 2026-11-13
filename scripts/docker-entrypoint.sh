#!/bin/sh
# Container entrypoint.
#
# CUDA image (LLAMA_BACKEND=cuda) on a host without an NVIDIA GPU or driver:
# llama.cpp's CUDA library needs libcuda.so.1, which only the host driver
# provides (through the NVIDIA Container Toolkit), so llama-cpp-python would
# fail to import and local inference would be off. In that case put CUDA's
# stub libcuda on the library path: llama.cpp then loads, finds no device and
# runs on CPU. A real driver, from ldconfig or LD_LIBRARY_PATH, always wins.
# The CPU image ships no stub, so this is a no-op there.
set -e

STUB_DIR=/opt/cuda-stub

has_real_libcuda() {
    if ldconfig -p 2>/dev/null | grep -q 'libcuda\.so\.1 '; then
        return 0
    fi
    old_ifs=$IFS
    IFS=:
    for dir in ${LD_LIBRARY_PATH:-}; do
        if [ -n "$dir" ] && [ "$dir" != "$STUB_DIR" ] && [ -e "$dir/libcuda.so.1" ]; then
            IFS=$old_ifs
            return 0
        fi
    done
    IFS=$old_ifs
    return 1
}

if [ -e "$STUB_DIR/libcuda.so.1" ] && ! has_real_libcuda; then
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}$STUB_DIR"
    echo "amadeus: no NVIDIA driver found; local inference will run on CPU" >&2
fi

exec "$@"
