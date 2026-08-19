#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"

task_gcc_repo="${GCC_REPO_URL:-https://gcc.gnu.org/git/gcc.git}"
task_binutils_repo="${BINUTILS_REPO_URL:-ssh://sourceware.org/git/binutils-gdb.git}"
task_gcc_commit="${GCC_COMMIT:-913ff90691dbd1a94bb5b205415955dd053279dd}"
task_binutils_commit="${BINUTILS_COMMIT:-ca8bf5f5dd69eba877e74ca8bc0796388070401f}"

clone_or_update() {
  local repo_url="$1"
  local commit="$2"
  local path="$3"
  if [[ -d "${path}/.git" ]]; then
    git -C "${path}" fetch --tags origin
  else
    mkdir -p "$(dirname -- "${path}")"
    git clone "${repo_url}" "${path}"
  fi
  git -C "${path}" checkout --detach "${commit}"
}

clone_or_update "${task_gcc_repo}" "${task_gcc_commit}" "${task_root}/src/gcc-upstream"
clone_or_update "${task_binutils_repo}" "${task_binutils_commit}" "${task_root}/src/binutils-gdb"

printf 'sources ready:\n'
printf '  %s @ %s\n' "${task_root}/src/gcc-upstream" "${task_gcc_commit}"
printf '  %s @ %s\n' "${task_root}/src/binutils-gdb" "${task_binutils_commit}"
