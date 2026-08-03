#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"
task_target="${TARGET:-loongarch64-linux-gnu}"
task_source="${task_root}/src/gcc-upstream"
task_build="${task_root}/build/gcc-afl"
task_prefix="${GCC_AFL_PREFIX:-${task_root}/install-afl}"
task_binutils_prefix="${PREFIX:-${task_root}/install}"
task_afl_root="${AFL_ROOT:-/opt/homebrew/opt/afl++}"
task_llvm_root="${LLVM_ROOT:-/opt/homebrew/opt/llvm}"
task_jobs="${JOBS:-$(sysctl -n hw.ncpu)}"

export PATH="${task_binutils_prefix}/bin:${task_afl_root}/bin:${task_llvm_root}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset AFL_CC AFL_CXX AFL_PREFIX AFL_ROOT CFLAGS CXXFLAGS CPPFLAGS LDFLAGS

task_triplet="$(${task_source}/config.guess)"
mkdir -p "${task_build}"

if [[ ! -f "${task_build}/Makefile" ]]; then
  cd "${task_build}"
  CC="${task_afl_root}/bin/afl-clang-fast" \
  CXX="${task_afl_root}/bin/afl-clang-fast++" \
  CC_FOR_BUILD="${task_llvm_root}/bin/clang" \
  CXX_FOR_BUILD="${task_llvm_root}/bin/clang++" \
  "${task_source}/configure" \
    --build="${task_triplet}" \
    --host="${task_triplet}" \
    --target="${task_target}" \
    --prefix="${task_prefix}" \
    --disable-bootstrap \
    --disable-multilib \
    --disable-nls \
    --enable-languages=c,c++ \
    --without-headers \
    --disable-shared \
    --disable-threads \
    --disable-libatomic \
    --disable-libgomp \
    --disable-libquadmath \
    --disable-libssp \
    --disable-libsanitizer \
    --with-newlib \
    --enable-checking=yes
fi

if ! grep -Fq "CC = ${task_afl_root}/bin/afl-clang-fast" "${task_build}/Makefile" ||
   ! grep -Fq "CXX = ${task_afl_root}/bin/afl-clang-fast++" "${task_build}/Makefile"; then
  echo "error: ${task_build} was not configured with AFL++ wrappers" >&2
  echo "move that build directory aside, recreate it, and rerun this script" >&2
  exit 1
fi

cd "${task_build}"
AFL_QUIET=1 gmake -j"${task_jobs}" all-gcc
AFL_QUIET=1 gmake install-gcc

echo "installed: ${task_prefix}/bin/${task_target}-gcc"
