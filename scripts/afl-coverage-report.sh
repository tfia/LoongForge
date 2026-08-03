#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_lang="c"
task_report=""
task_recalculate=1
task_ci=0

usage() {
  printf '%s\n' \
    'Usage: afl-coverage-report.sh [options] AFL_OUTPUT_DIR [-- GCC_OPTIONS...]' \
    '' \
    'Create a Markdown quality/coverage summary from AFL++ fuzzer_stats.' \
    '  --lang c|c++        Frontend used to recalculate queue coverage.' \
    '  --output FILE       Markdown report path (default: under run directory).' \
    '  --no-recalculate    Report saved stats only; skip queue replay.' \
    '  --ci                Exit non-zero when crashes/ICE or hangs exist.' \
    '  -h, --help          Show this help.'
}

## afl-coverage-report.sh [options] AFL_OUTPUT_DIR
##
## Create a Markdown quality/coverage summary from AFL++ fuzzer_stats.
##
## Options:
##   --lang c|c++        Frontend used to recalculate queue coverage.
##   --output FILE       Markdown report path (default: under run directory).
##   --no-recalculate    Report saved stats only; skip afl-showmap over queue.
##   -h, --help          Show this help.

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang)
      task_lang="${2:?missing value for --lang}"
      shift 2
      ;;
    --output|-o)
      task_report="${2:?missing value for --output}"
      shift 2
      ;;
    --no-recalculate)
      task_recalculate=0
      shift
      ;;
    --ci)
      task_ci=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "error: unknown option: $1" >&2
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

task_given="$1"
shift
task_extra=()
task_has_extra=0
if [[ $# -gt 0 ]]; then
  if [[ "$1" != "--" ]]; then
    echo "error: put compiler options after --" >&2
    exit 2
  fi
  shift
  task_extra=("$@")
  task_has_extra=1
fi

if [[ -f "${task_given}/fuzzer_stats" ]]; then
  task_instance="${task_given}"
  task_run="$(dirname -- "${task_given}")"
elif [[ -f "${task_given}/default/fuzzer_stats" ]]; then
  task_instance="${task_given}/default"
  task_run="${task_given}"
else
  echo "error: cannot find fuzzer_stats under ${task_given}" >&2
  exit 1
fi

task_stats="${task_instance}/fuzzer_stats"
task_queue="${task_instance}/queue"
if [[ -z "${task_report}" ]]; then
  task_report="${task_run}/coverage-report.md"
fi
mkdir -p "$(dirname -- "${task_report}")"

stat_value() {
  awk -F ' *: *' -v key="$1" '$1 == key { print $2; exit }' "${task_stats}"
}

task_queue_edges="not recalculated"
task_queue_map=""
if (( task_recalculate )); then
  task_queue_map="${task_run}/queue-coverage-${task_lang}.map"
  if (( task_has_extra )); then
    "${script_dir}/afl-corpus-coverage.sh" --lang "${task_lang}" \
      --output "${task_queue_map}" "${task_queue}" -- "${task_extra[@]}"
  else
    "${script_dir}/afl-corpus-coverage.sh" --lang "${task_lang}" \
      --output "${task_queue_map}" "${task_queue}"
  fi
  task_queue_edges="$(wc -l < "${task_queue_map}" | tr -d '[:space:]')"
fi

task_generated="$(date '+%Y-%m-%d %H:%M:%S %z')"
task_start="$(stat_value start_time)"
task_last="$(stat_value last_update)"
task_execs="$(stat_value execs_done)"
task_eps="$(stat_value execs_per_sec)"
task_corpus="$(stat_value corpus_count)"
task_found="$(stat_value corpus_found)"
task_stability="$(stat_value stability)"
task_bitmap="$(stat_value bitmap_cvg)"
task_edges="$(stat_value edges_found)"
task_total_edges="$(stat_value total_edges)"
task_crashes="$(stat_value saved_crashes)"
task_hangs="$(stat_value saved_hangs)"

{
  printf '# GCC AFL++ 质量测试覆盖报告\n\n'
  printf -- '- 生成时间：`%s`\n' "${task_generated}"
  printf -- '- AFL 实例：`%s`\n' "${task_instance}"
  printf -- '- 测试范围：自有 GCC fork 的编译器质量与 CI；不涉及网络安全测试。\n\n'
  printf '## 核心指标\n\n'
  printf '| 指标 | 数值 |\n|---|---:|\n'
  printf '| 开始时间（Unix） | %s |\n' "${task_start:-N/A}"
  printf '| 最后更新（Unix） | %s |\n' "${task_last:-N/A}"
  printf '| 总执行次数 | %s |\n' "${task_execs:-N/A}"
  printf '| 执行速度（次/秒） | %s |\n' "${task_eps:-N/A}"
  printf '| 语料总数 | %s |\n' "${task_corpus:-N/A}"
  printf '| 新发现语料 | %s |\n' "${task_found:-N/A}"
  printf '| 稳定性 | %s |\n' "${task_stability:-N/A}"
  printf '| AFL bitmap 覆盖率 | %s |\n' "${task_bitmap:-N/A}"
  printf '| 已发现边 / 可见总边 | %s / %s |\n' "${task_edges:-N/A}" "${task_total_edges:-N/A}"
  printf '| 队列累计 edge map 条目 | %s |\n' "${task_queue_edges}"
  printf '| ICE/崩溃样例 | %s |\n' "${task_crashes:-N/A}"
  printf '| 超时样例 | %s |\n' "${task_hangs:-N/A}"
  printf '\n## CI 判读\n\n'
  if [[ "${task_crashes:-0}" != "0" ]]; then
    printf -- '- **失败**：发现 ICE/崩溃样例，应最小化并回归。\n'
  else
    printf -- '- ICE/崩溃：本轮未发现。\n'
  fi
  if [[ "${task_hangs:-0}" != "0" ]]; then
    printf -- '- **失败**：发现超时样例，应确认是否为编译器性能回归。\n'
  else
    printf -- '- 超时：本轮未发现。\n'
  fi
  printf -- '- 覆盖指标用于比较同一构建、同一前端和同一参数下的趋势；它不是 gcov 源码行覆盖率。\n'
  if [[ -n "${task_queue_map}" ]]; then
    printf -- '- 累计覆盖图：`%s`\n' "${task_queue_map}"
  fi
} > "${task_report}"

cat "${task_report}"
printf '\nreport: %s\n' "${task_report}"

if (( task_ci )) && { [[ "${task_crashes:-0}" != "0" ]] || [[ "${task_hangs:-0}" != "0" ]]; }; then
  echo "error: quality gate failed because crashes/ICE or hangs were saved" >&2
  exit 4
fi
