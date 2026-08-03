# LoongForge

LoongForge is a monorepo for compiler quality testing of the team's LoongArch GCC fork. It combines GCC Bugzilla mining, LLM-based feature extraction/grouping, AFL++ instrumentation, coverage feedback, and CI-oriented quality checks.

This repository is for compiler quality testing only. The target is our own GCC fork and local compiler toolchains. It does not perform network scanning, protocol attacks, penetration testing, or vulnerability exploitation.

## Repository Layout

```text
docs/                      Project notes, handoff docs, and CI usage docs
scripts/                   GCC/AFL++ build, fuzzing, showmap, and report helpers
gcc-bugzilla-loongarch/    Bugzilla collection and archive tooling
extract-llm/               Bug report to feature extraction pipeline
group-llm/                 Feature grouping pipeline for later PoC generation
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

The current GroupLLM state is documented in `group-llm/WORKING_CONTEXT.md`. Curated machine-readable snapshots are kept under `data/curated/group-llm/`; raw responses and run outputs remain under ignored `group-llm/out/`.

## Local Environment

Copy `.env.example` to `.env` and fill in local API credentials when running LLM extraction/grouping. Do not commit `.env`.

On a new macOS machine, AFL++ may require SysV shared memory tuning before `afl-showmap` works:

```bash
sudo /opt/homebrew/opt/afl++/bin/afl-system-config
```

See `docs/AFL_GCC_CI_使用说明.md` for the full quality testing and coverage workflow.
