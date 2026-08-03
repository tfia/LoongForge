#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"
task_target="${TARGET:-loongarch64-linux-gnu}"
task_prefix="${GCC_AFL_PREFIX:-${task_root}/install-afl}"
task_afl_root="${AFL_ROOT:-/opt/homebrew/opt/afl++}"
unset AFL_ROOT

task_lang="c"
task_mode="frontend"
task_timeout="20000"
task_output=""

usage() {
  printf '%s\n' \
    'Usage: afl-showmap-gcc.sh [options] INPUT [-- GCC_OPTIONS...]' \
    '' \
    'Show AFL++ edge coverage for one C/C++ compiler input.' \
    '  --lang c|c++             Select cc1 or cc1plus (default: c).' \
    '  --mode frontend|driver   Direct frontend is recommended (default: frontend).' \
    '  --output FILE            Coverage map output path.' \
    '  --timeout MS             Per-input timeout (default: 20000).' \
    '  -h, --help               Show this help.'
}

## afl-showmap-gcc.sh [options] INPUT [-- GCC_OPTIONS...]
##
## Show AFL++ edge coverage for one C/C++ compiler input.
##
## Options:
##   --lang c|c++             Select cc1 or cc1plus (default: c).
##   --mode frontend|driver   Direct frontend is recommended (default: frontend).
##   --output FILE            Coverage map output path.
##   --timeout MS             Per-input timeout (default: 20000).
##   -h, --help               Show this help.
##
## Examples:
##   ./scripts/afl-showmap-gcc.sh seeds/minimal.c
##   ./scripts/afl-showmap-gcc.sh --lang c++ test.cc -- -O2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang)
      task_lang="${2:?missing value for --lang}"
      shift 2
      ;;
    --mode)
      task_mode="${2:?missing value for --mode}"
      shift 2
      ;;
    --output|-o)
      task_output="${2:?missing value for --output}"
      shift 2
      ;;
    --timeout|-t)
      task_timeout="${2:?missing value for --timeout}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      echo "error: INPUT must appear before --" >&2
      exit 2
      ;;
    -*)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

task_input="$1"
shift
task_extra=()
if [[ $# -gt 0 ]]; then
  if [[ "$1" != "--" ]]; then
    echo "error: put compiler options after --" >&2
    exit 2
  fi
  shift
  task_extra=("$@")
fi

case "${task_lang}" in
  c)
    task_driver="${task_prefix}/bin/${task_target}-gcc"
    task_frontend_name="cc1"
    task_driver_lang="c"
    ;;
  c++|cpp|cxx)
    task_driver="${task_prefix}/bin/${task_target}-g++"
    task_frontend_name="cc1plus"
    task_driver_lang="c++"
    ;;
  *)
    echo "error: --lang must be c or c++" >&2
    exit 2
    ;;
esac

task_showmap="${task_afl_root}/bin/afl-showmap"
test -x "${task_showmap}" || { echo "error: not executable: ${task_showmap}" >&2; exit 1; }
test -x "${task_driver}" || { echo "error: not executable: ${task_driver}" >&2; exit 1; }
test -f "${task_input}" || { echo "error: input not found: ${task_input}" >&2; exit 1; }

task_frontend="$(${task_driver} -print-prog-name="${task_frontend_name}")"
test -x "${task_frontend}" || { echo "error: not executable: ${task_frontend}" >&2; exit 1; }

if [[ -z "${task_output}" ]]; then
  task_stem="$(basename -- "${task_input}")"
  task_stem="${task_stem//[^[:alnum:]._-]/_}"
  task_output="${task_root}/out/showmap/${task_stem}.${task_lang}.$(date +%Y%m%d-%H%M%S).map"
fi
mkdir -p "$(dirname -- "${task_output}")"

case "${task_mode}" in
  frontend)
    task_command=("${task_frontend}" -quiet ${task_extra[@]+"${task_extra[@]}"} "${task_input}" -o /dev/null)
    ;;
  driver)
    task_command=("${task_driver}" -S -x "${task_driver_lang}" ${task_extra[@]+"${task_extra[@]}"} "${task_input}" -o /dev/null)
    ;;
  *)
    echo "error: --mode must be frontend or driver" >&2
    exit 2
    ;;
esac

AFL_CRASH_EXITCODE=4 "${task_showmap}" -q -m none -t "${task_timeout}" -e \
  -o "${task_output}" -- "${task_command[@]}"

task_edges="$(wc -l < "${task_output}" | tr -d '[:space:]')"
printf 'target: %s\n' "${task_command[0]}"
printf 'input: %s\n' "${task_input}"
printf 'edge map entries: %s\n' "${task_edges}"
printf 'map: %s\n' "${task_output}"
