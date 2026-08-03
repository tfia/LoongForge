#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"
task_target="${TARGET:-loongarch64-linux-gnu}"
task_prefix="${GCC_AFL_PREFIX:-${task_root}/install-afl}"
task_afl_root="${AFL_ROOT:-/opt/homebrew/opt/afl++}"
task_gcc="${task_prefix}/bin/${task_target}-gcc"
task_cc1="$(${task_gcc} -print-prog-name=cc1)"
task_run_id="$(date +%Y%m%d-%H%M%S)"
task_verify_dir="${task_root}/out/verify-${task_run_id}"
task_fuzz_seconds="${FUZZ_SECONDS:-${AFL_FUZZ_SECONDS:-10}}"

# AFL++ warns about unknown AFL_* variables inherited by its child tools.
unset AFL_ROOT AFL_FUZZ_SECONDS

mkdir -p "${task_verify_dir}"

echo "gcc: ${task_gcc}"
echo "cc1: ${task_cc1}"
"${task_gcc}" --version | head -n 1

nm "${task_cc1}" > "${task_verify_dir}/cc1.symbols"
if ! grep -q '___afl_area_ptr' "${task_verify_dir}/cc1.symbols"; then
  echo "error: cc1 does not contain AFL++ runtime symbols" >&2
  exit 1
fi

AFL_CRASH_EXITCODE=4 \
"${task_afl_root}/bin/afl-showmap" -q -m none -t 20000 -e \
  -o "${task_verify_dir}/minimal.map" -- \
  "${task_cc1}" -quiet "${task_root}/seeds/minimal.c" -o /dev/null

AFL_CRASH_EXITCODE=4 \
"${task_afl_root}/bin/afl-showmap" -q -m none -t 20000 -e \
  -o "${task_verify_dir}/branches.map" -- \
  "${task_cc1}" -quiet "${task_root}/seeds/branches.c" -o /dev/null

task_minimal_edges="$(wc -l < "${task_verify_dir}/minimal.map" | tr -d '[:space:]')"
task_branches_edges="$(wc -l < "${task_verify_dir}/branches.map" | tr -d '[:space:]')"
echo "showmap edges: minimal=${task_minimal_edges}, branches=${task_branches_edges}"

if [[ "${task_minimal_edges}" -eq 0 || "${task_branches_edges}" -eq 0 ]]; then
  echo "error: AFL++ returned an empty coverage map" >&2
  exit 1
fi

if cmp -s "${task_verify_dir}/minimal.map" "${task_verify_dir}/branches.map"; then
  echo "error: distinct compiler inputs produced identical coverage maps" >&2
  exit 1
fi

AFL_CRASH_EXITCODE=4 AFL_NO_UI=1 AFL_SKIP_CPUFREQ=1 \
"${task_afl_root}/bin/afl-fuzz" \
  -V "${task_fuzz_seconds}" \
  -m none \
  -t 5000+ \
  -i "${task_root}/seeds" \
  -o "${task_verify_dir}/fuzz" \
  -- "${task_cc1}" -quiet @@ -o /dev/null

task_stats="${task_verify_dir}/fuzz/default/fuzzer_stats"
test -s "${task_stats}"
grep -E '^(execs_done|execs_per_sec|corpus_count|corpus_found|stability|bitmap_cvg|edges_found|total_edges|saved_crashes|saved_hangs)' "${task_stats}" || true
echo "verification artifacts: ${task_verify_dir}"
