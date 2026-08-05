#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"
task_target="${TARGET:-loongarch64-linux-gnu}"
task_source="${task_root}/src/gcc-upstream"
task_build="${GCC_GCOV_BUILD:-${task_root}/build/gcc-gcov}"
task_prefix="${GCC_GCOV_PREFIX:-${task_root}/install-gcov}"
task_binutils_prefix="${PREFIX:-${task_root}/install}"
task_jobs="${JOBS:-$(sysctl -n hw.ncpu)}"
task_cc="${GCOV_CC:-$(command -v gcc-15 || command -v gcc)}"
task_cxx="${GCOV_CXX:-$(command -v g++-15 || command -v g++)}"
task_cflags="${GCOV_CFLAGS:--O0 -g --coverage -fno-inline -fno-inline-functions -fno-default-inline}"
task_cxxflags="${GCOV_CXXFLAGS:-${task_cflags}}"
task_ldflags="${GCOV_LDFLAGS:---coverage}"

export PATH="${task_binutils_prefix}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset AFL_CC AFL_CXX AFL_PREFIX AFL_ROOT

if [[ ! -x "${task_cc}" || ! -x "${task_cxx}" ]]; then
  echo "error: coverage compiler not found; set GCOV_CC and GCOV_CXX" >&2
  exit 1
fi

task_triplet="$("${task_source}/config.guess")"
mkdir -p "${task_build}"

if [[ ! -f "${task_build}/Makefile" ]]; then
  cd "${task_build}"
  CC="${task_cc}" \
  CXX="${task_cxx}" \
  CC_FOR_BUILD="${task_cc}" \
  CXX_FOR_BUILD="${task_cxx}" \
  CFLAGS="${task_cflags}" \
  CXXFLAGS="${task_cxxflags}" \
  LDFLAGS="${task_ldflags}" \
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

if ! grep -Fq "CC = ${task_cc}" "${task_build}/Makefile" ||
   ! grep -Fq "CXX = ${task_cxx}" "${task_build}/Makefile"; then
  echo "error: ${task_build} was configured with a different host compiler" >&2
  echo "move that build directory aside, recreate it, and rerun this script" >&2
  exit 1
fi

if ! grep -Fq -- "--coverage" "${task_build}/Makefile"; then
  echo "error: ${task_build} Makefile does not contain --coverage" >&2
  echo "move that build directory aside, recreate it, and rerun this script" >&2
  exit 1
fi

cd "${task_build}"
gmake -j"${task_jobs}" all-gcc
gmake install-gcc

echo "installed: ${task_prefix}/bin/${task_target}-gcc"
echo "installed: ${task_prefix}/bin/${task_target}-g++"
