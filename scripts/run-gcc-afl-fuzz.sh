#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"
task_target="${TARGET:-loongarch64-linux-gnu}"
task_prefix="${GCC_AFL_PREFIX:-${task_root}/install-afl}"
task_afl_root="${AFL_ROOT:-/opt/homebrew/opt/afl++}"
unset AFL_ROOT

task_lang="c"
task_seconds="0"
task_timeout="5000+"
task_output=""

usage() {
  printf '%s\n' \
    'Usage: run-gcc-afl-fuzz.sh [options] CORPUS_DIR [-- GCC_OPTIONS...]' \
    '' \
    'Run AFL++ against an instrumented GCC frontend for compiler quality.' \
    '  --lang c|c++       Select cc1 or cc1plus (default: c).' \
    '  --seconds N        Stop after N seconds; 0 runs until interrupted.' \
    '  --output DIR       New AFL output directory.' \
    '  --timeout MS[+]    Per-input timeout (default: 5000+).' \
    '  -h, --help         Show this help.'
}

## run-gcc-afl-fuzz.sh [options] CORPUS_DIR [-- GCC_OPTIONS...]
##
## Run AFL++ against the instrumented GCC frontend for compiler-quality tests.
## GCC internal compiler errors exit with status 4 and are saved as crashes.
##
## Options:
##   --lang c|c++       Select cc1 or cc1plus (default: c).
##   --seconds N        Stop after N seconds; 0 means run until interrupted.
##   --output DIR       New AFL output directory.
##   --timeout MS[+]    Per-input timeout (default: 5000+).
##   -h, --help         Show this help.
##
## Example:
##   ./scripts/run-gcc-afl-fuzz.sh --seconds 60 seeds -- -O2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang)
      task_lang="${2:?missing value for --lang}"
      shift 2
      ;;
    --seconds)
      task_seconds="${2:?missing value for --seconds}"
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
      echo "error: CORPUS_DIR must appear before --" >&2
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

task_corpus="$1"
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

if [[ ! "${task_seconds}" =~ ^[0-9]+$ ]]; then
  echo "error: --seconds must be a non-negative integer" >&2
  exit 2
fi

case "${task_lang}" in
  c)
    task_driver="${task_prefix}/bin/${task_target}-gcc"
    task_frontend_name="cc1"
    ;;
  c++|cpp|cxx)
    task_driver="${task_prefix}/bin/${task_target}-g++"
    task_frontend_name="cc1plus"
    ;;
  *)
    echo "error: --lang must be c or c++" >&2
    exit 2
    ;;
esac

task_fuzzer="${task_afl_root}/bin/afl-fuzz"
test -x "${task_fuzzer}" || { echo "error: not executable: ${task_fuzzer}" >&2; exit 1; }
test -x "${task_driver}" || { echo "error: not executable: ${task_driver}" >&2; exit 1; }
test -d "${task_corpus}" || { echo "error: corpus directory not found: ${task_corpus}" >&2; exit 1; }

task_frontend="$(${task_driver} -print-prog-name="${task_frontend_name}")"
test -x "${task_frontend}" || { echo "error: not executable: ${task_frontend}" >&2; exit 1; }

if [[ -z "${task_output}" ]]; then
  task_output="${task_root}/out/fuzz-${task_lang}-$(date +%Y%m%d-%H%M%S)"
fi
if [[ -e "${task_output}" ]]; then
  echo "error: output already exists: ${task_output}" >&2
  exit 1
fi
mkdir -p "$(dirname -- "${task_output}")"

task_fuzz_args=(-m none -t "${task_timeout}" -i "${task_corpus}" -o "${task_output}")
if (( task_seconds > 0 )); then
  task_fuzz_args=(-V "${task_seconds}" "${task_fuzz_args[@]}")
fi

printf 'quality-test target: %s\n' "${task_frontend}"
printf 'ICE handling: exit code 4 is treated as a crash\n'
printf 'output: %s\n' "${task_output}"

AFL_CRASH_EXITCODE=4 AFL_NO_UI=1 AFL_SKIP_CPUFREQ=1 \
  "${task_fuzzer}" "${task_fuzz_args[@]}" -- \
  "${task_frontend}" -quiet ${task_extra[@]+"${task_extra[@]}"} @@ -o /dev/null

printf 'finished; inspect with:\n  %q %q\n' \
  "${script_dir}/afl-coverage-report.sh" "${task_output}"
