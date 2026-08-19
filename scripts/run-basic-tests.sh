#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"

cd "${task_root}"

PYTHONPATH=gcc-bugzilla-loongarch/src \
  python3 -m unittest discover -s gcc-bugzilla-loongarch/tests -q

PYTHONPATH=extract-llm/src \
  python3 -m unittest discover -s extract-llm/tests -q

PYTHONPATH=group-llm/src \
  python3 -m unittest discover -s group-llm/tests -q

PYTHONPATH=instan-llm/src \
  python3 -m unittest discover -s instan-llm/tests -q

python3 -m py_compile \
  gcc-bugzilla-loongarch/src/loongarch_bug_corpus/core.py \
  gcc-bugzilla-loongarch/src/loongarch_bug_corpus/cli.py \
  extract-llm/src/extract_llm/pipeline.py \
  extract-llm/src/extract_llm/cli.py \
  group-llm/src/group_llm/pipeline.py \
  group-llm/src/group_llm/cli.py \
  instan-llm/src/instan_llm/pipeline.py \
  instan-llm/src/instan_llm/cli.py \
  scripts/gcc-source-coverage-replay.py \
  scripts/run-afl-feedback-loop.py

bash -n scripts/*.sh

printf 'basic tests: PASS\n'
