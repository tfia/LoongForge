# InstanLLM

InstanLLM is the third LLM stage in LoongForge:

```text
ExtractLLM bug reports -> semantic features
GroupLLM features -> connected feature groups
InstanLLM feature groups -> complete compiler test programs
AFL++ wrapped GCC -> compile coverage and CI-quality signals
```

This module is for compiler CI quality testing of the team's own LoongArch GCC fork. It does not generate network tests, exploits, payloads, or third-party security tests.

## Data Contract

Input:

- `../group-llm/out/feature-groups.jsonl`
- Only `synthesis_status=ready` GroupLLM records are consumed.

InstanLLM output:

- `out/instantiations/*.instantiation.json`
- `out/instantiations.jsonl`
- `out/programs/*.{c,cc}`
- `out/instan-run-manifest.json`

Evaluation output:

- `out/evaluations/*.evaluation.json`
- `out/evaluations.jsonl`
- `out/coverage/*.map`
- `out/evaluation-manifest.json`
- `out/corpus/covered/`

An instantiation is only admitted into the covered corpus after `evaluate` compiles it through the AFL++ wrapped GCC frontend and records a non-empty edge map.

## Generate Programs

Run one group first:

```bash
cd /Users/mac/work/loong-gcc-afl/instan-llm
PYTHONPATH=src python3 -m instan_llm run \
  --env-file ../.env \
  --groups-file ../group-llm/out/feature-groups.jsonl \
  --limit 1 \
  --workers 1
```

Generate specific groups by `group_uid` or `candidate_id`:

```bash
PYTHONPATH=src python3 -m instan_llm run \
  --env-file ../.env \
  --group-id group-0001-0c4805f873ab \
  --workers 1
```

Use `--refresh` to regenerate existing instantiations.

## Evaluate Coverage

Evaluate generated C/C++ programs:

```bash
PYTHONPATH=src python3 -m instan_llm evaluate --limit 1
```

The evaluator calls:

```text
../scripts/afl-showmap-gcc.sh --lang c|c++ --output <map> <source> -- <compiler options>
```

It records compiler output, return code, edge-map path, edge count, and SHA-256. Linker-only options such as `-lffi`, `-L...`, `-Wl,...`, and `-shared` are removed before frontend coverage replay because `afl-showmap-gcc.sh` compiles through `cc1`/`cc1plus`.

## Build Covered Corpus

```bash
PYTHONPATH=src python3 -m instan_llm build-corpus
```

This copies only `evaluation_status=covered` programs into `out/corpus/covered/`.

## Coverage Report

```bash
PYTHONPATH=src python3 -m instan_llm report \
  --groups-file ../group-llm/out/feature-groups.jsonl \
  --report-path ../docs/InstanLLM_阶段覆盖率报告.md
```

The report separates four different numbers:

- GroupLLM ready groups available as InstanLLM input
- ready groups selected for the current InstanLLM batch
- generated programs that passed InstanLLM structural validation
- generated programs that compiled through the AFL++ wrapped GCC frontend and produced non-empty edge coverage

Current stage result on 2026-08-05: all 272 C/C++ GroupLLM ready groups were sent through InstanLLM. The run produced 260 ready instantiations, 10 model rejections, and 2 persistent API/parser error records. All 260 ready programs compiled through the AFL++ wrapped GCC frontend and produced non-empty edge maps; the batch union edge count was 261,917.

## Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 -m instan_llm verify --require-evaluations --min-covered 1
```

## Current Limits

The first evaluator supports C and C++ programs because the existing AFL wrapper targets `cc1` and `cc1plus`. InstanLLM may still record rejected or unsupported-language instantiations for Fortran, Ada, D, COBOL, asm, shell, or RTL groups. Those require future language-specific wrappers or harnesses before they can enter the covered corpus. AFL edge maps are compiler execution-path coverage signals, not GCC source line/function coverage; source coverage requires a separate gcov/llvm-cov-style GCC build and replay of the same corpus.

This means the non-C/C++ groups are not considered invalid. They are waiting for a matching evaluator:

- Fortran: call the Fortran frontend or driver with equivalent coverage replay.
- asm: assemble/scan generated assembly or compile C that emits the target assembly condition.
- RTL/diagnostic: run compiler-internal dump or diagnostic oracles instead of treating the test as a normal C translation unit.
- Ada/D/COBOL/shell: add language-specific frontend or multi-file harness support before admitting outputs into the covered corpus.
