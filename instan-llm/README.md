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

## Verify

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 -m instan_llm verify --require-evaluations --min-covered 1
```

## Current Limits

The first evaluator supports C and C++ programs because the existing AFL wrapper targets `cc1` and `cc1plus`. InstanLLM may still record rejected or unsupported-language instantiations for Fortran, Ada, D, COBOL, asm, shell, or RTL groups. Those require future language-specific wrappers or harnesses before they can enter the covered corpus.
