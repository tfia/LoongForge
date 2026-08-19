#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"
task_target="${TARGET:-loongarch64-linux-gnu}"
task_source="${BINUTILS_SOURCE:-${task_root}/src/binutils-gdb}"
task_build="${BINUTILS_BUILD:-${task_root}/build/binutils}"
task_prefix="${PREFIX:-${task_root}/install}"
task_jobs="${JOBS:-$(sysctl -n hw.ncpu)}"

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

test -x "${task_source}/configure" || {
  echo "error: binutils source not found; run scripts/bootstrap-sources.sh first" >&2
  exit 1
}

mkdir -p "${task_build}" "${task_prefix}/${task_target}/sysroot"

if [[ ! -f "${task_build}/Makefile" ]]; then
  cd "${task_build}"
  "${task_source}/configure" \
    --target="${task_target}" \
    --prefix="${task_prefix}" \
    --disable-gdb \
    --disable-gdbserver \
    --disable-sim \
    --disable-nls \
    --disable-werror \
    --with-sysroot="${task_prefix}/${task_target}/sysroot"
fi

cd "${task_build}"
gmake -j"${task_jobs}"
gmake install

echo "installed: ${task_prefix}/bin/${task_target}-as"
echo "installed: ${task_prefix}/bin/${task_target}-ld"
