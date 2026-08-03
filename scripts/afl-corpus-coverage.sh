#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"
task_target="${TARGET:-loongarch64-linux-gnu}"
task_prefix="${GCC_AFL_PREFIX:-${task_root}/install-afl}"
task_afl_root="${AFL_ROOT:-/opt/homebrew/opt/afl++}"
unset AFL_ROOT

task_lang="c"
task_timeout="20000"
task_output=""
task_baseline=""
task_min_edges=""

usage() {
  printf '%s\n' \
    'Usage: afl-corpus-coverage.sh [options] CORPUS_DIR [-- GCC_OPTIONS...]' \
    '' \
    'Aggregate edge coverage for a compiler-test corpus with afl-showmap.' \
    '  --lang c|c++       Select cc1 or cc1plus (default: c).' \
    '  --output FILE      Combined edge map output path.' \
    '  --baseline FILE    Compare with an existing edge map.' \
    '  --min-edges N      Fail if the result has fewer than N entries.' \
    '  --timeout MS       Per-input timeout (default: 20000).' \
    '  -h, --help         Show this help.'
}

## afl-corpus-coverage.sh [options] CORPUS_DIR [-- GCC_OPTIONS...]
##
## Aggregate edge coverage for a compiler-test corpus with afl-showmap.
##
## Options:
##   --lang c|c++       Select cc1 or cc1plus (default: c).
##   --output FILE      Combined edge map output path.
##   --baseline FILE    Compare the result with an existing edge map.
##   --min-edges N      Exit non-zero if the result has fewer than N entries.
##   --timeout MS       Per-input timeout (default: 20000).
##   -h, --help         Show this help.
##
## AFL queue directories include only files named id:*; ordinary corpus
## directories include every regular file below the directory.

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang)
      task_lang="${2:?missing value for --lang}"
      shift 2
      ;;
    --output|-o)
      task_output="${2:?missing value for --output}"
      shift 2
      ;;
    --baseline)
      task_baseline="${2:?missing value for --baseline}"
      shift 2
      ;;
    --min-edges)
      task_min_edges="${2:?missing value for --min-edges}"
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

task_showmap="${task_afl_root}/bin/afl-showmap"
test -x "${task_showmap}" || { echo "error: not executable: ${task_showmap}" >&2; exit 1; }
test -x "${task_driver}" || { echo "error: not executable: ${task_driver}" >&2; exit 1; }
test -d "${task_corpus}" || { echo "error: corpus directory not found: ${task_corpus}" >&2; exit 1; }

task_frontend="$(${task_driver} -print-prog-name="${task_frontend_name}")"
test -x "${task_frontend}" || { echo "error: not executable: ${task_frontend}" >&2; exit 1; }

if [[ -z "${task_output}" ]]; then
  task_output="${task_root}/out/coverage/$(basename -- "${task_corpus}").${task_lang}.$(date +%Y%m%d-%H%M%S).map"
fi
mkdir -p "$(dirname -- "${task_output}")"

task_filelist="$(mktemp -t gcc-afl-corpus.XXXXXX)"
trap 'rm -f "${task_filelist}"' EXIT
if [[ "$(basename -- "${task_corpus}")" == "queue" ]]; then
  find "${task_corpus}" -type f -name 'id:*' -print | LC_ALL=C sort > "${task_filelist}"
else
  find "${task_corpus}" -type f -not -path '*/.state/*' -print | LC_ALL=C sort > "${task_filelist}"
fi

task_inputs="$(wc -l < "${task_filelist}" | tr -d '[:space:]')"
if [[ "${task_inputs}" -eq 0 ]]; then
  echo "error: no input files found in ${task_corpus}" >&2
  exit 1
fi

if [[ -n "${task_min_edges}" && ! "${task_min_edges}" =~ ^[0-9]+$ ]]; then
  echo "error: --min-edges must be a non-negative integer" >&2
  exit 2
fi

AFL_CRASH_EXITCODE=4 "${task_showmap}" -q -m none -t "${task_timeout}" -e \
  -I "${task_filelist}" -C -o "${task_output}" -- \
  "${task_frontend}" -quiet ${task_extra[@]+"${task_extra[@]}"} @@ -o /dev/null

task_edges="$(wc -l < "${task_output}" | tr -d '[:space:]')"
printf 'frontend: %s\n' "${task_frontend}"
printf 'inputs: %s\n' "${task_inputs}"
printf 'combined edge map entries: %s\n' "${task_edges}"
printf 'map: %s\n' "${task_output}"

if [[ -n "${task_baseline}" ]]; then
  test -f "${task_baseline}" || { echo "error: baseline not found: ${task_baseline}" >&2; exit 1; }
  task_added="$(comm -13 <(LC_ALL=C sort "${task_baseline}") <(LC_ALL=C sort "${task_output}") | wc -l | tr -d '[:space:]')"
  task_lost="$(comm -23 <(LC_ALL=C sort "${task_baseline}") <(LC_ALL=C sort "${task_output}") | wc -l | tr -d '[:space:]')"
  printf 'versus baseline: +%s / -%s map entries\n' "${task_added}" "${task_lost}"
fi

if [[ -n "${task_min_edges}" ]] && (( task_edges < task_min_edges )); then
  echo "error: ${task_edges} edge map entries is below required minimum ${task_min_edges}" >&2
  exit 3
fi
