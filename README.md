# LoongForge

LoongForge is a monorepo for compiler quality testing of the team's LoongArch GCC fork. It combines GCC Bugzilla mining, LLM-based feature extraction/grouping, AFL++ instrumentation, coverage feedback, and CI-oriented quality checks.

This repository is for compiler quality testing only. The target is our own GCC fork and local compiler toolchains. It does not perform network scanning, protocol attacks, penetration testing, or vulnerability exploitation.

## Repository Layout

```text
docs/                      Reproduction guide, delivery notes, reports, and CI usage docs
scripts/                   GCC/AFL++ build, fuzzing, showmap, and report helpers
gcc-bugzilla-loongarch/    Bugzilla collection and archive tooling
extract-llm/               Bug report to feature extraction pipeline
group-llm/                 Feature grouping pipeline for later PoC generation
instan-llm/                Feature-group instantiation and AFL++ coverage evaluation
data/curated/              Small, reviewed, reproducible pipeline state snapshots
seeds/                     Small C seed corpus
seeds-cxx/                 Small C++ seed corpus
src/gcc-upstream/          GCC source submodule, pinned by Git
src/binutils-gdb/          binutils-gdb source submodule, pinned by Git
```

The project directory intentionally remains `/Users/mac/work/loong-gcc-afl` to avoid breaking existing local scripts and reports. `LoongForge` is the repository/project name.

## What Git Tracks

Git tracks source code for the local tools, documentation, small seed corpora, lightweight manifests, and curated pipeline state. It does not track local secrets, compiler build directories, installed toolchains, raw AFL++ runs, virtual environments, or large generated archives.

The two upstream source trees under `src/` are tracked as submodules rather than committed into this repository:

- `src/gcc-upstream`
- `src/binutils-gdb`

Their exact revisions are recorded by the submodule gitlinks and summarized in `third_party/SOURCES.lock`.

## Current Pipeline State

Curated machine-readable GroupLLM snapshots are kept under `data/curated/group-llm/`; raw responses and run outputs remain under ignored `group-llm/out/`.

`instan-llm/` is the next stage. It reads ready GroupLLM records, asks InstanLLM to generate complete test programs, then evaluates C/C++ programs with the AFL++ wrapped GCC frontend and records edge coverage before admitting a program into the covered corpus.

## Reproduce in a New Environment

Start here:

- `docs/项目交付说明.md`: what is included in the delivery package and what is intentionally excluded.
- `docs/复现指南.md`: end-to-end environment setup, source checkout, build, test, and pipeline replay.
- `docs/阶段结果摘要.md`: stable stage results suitable for project reporting.

Basic local validation:

```bash
./scripts/run-basic-tests.sh
```

## Local Environment

Copy `.env.example` to `.env` and fill in local API credentials when running LLM extraction/grouping. Do not commit `.env`.

On a new macOS machine, AFL++ may require SysV shared memory tuning before `afl-showmap` works:

```bash
sudo /opt/homebrew/opt/afl++/bin/afl-system-config
```

See `docs/AFL_GCC_CI_使用说明.md` for the full quality testing and coverage workflow.
