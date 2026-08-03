# GroupLLM Curated Snapshot

This directory contains small, reviewed GroupLLM state files tracked by the
LoongForge monorepo.

The raw runtime directory `group-llm/out/` is intentionally ignored because it
contains candidates, raw LLM responses, temporary manifests, and other generated
artifacts. When a pipeline run reaches a stable checkpoint, copy only the files
needed for handoff or CI reproducibility into this directory.

Current snapshot:

- `feature-groups.jsonl`: ready groups for the next InstanLLM stage
- `feature-group-manifest.json`: group count and composition summary
- `feature-coverage-manifest.json`: feature coverage summary
- `uncovered-features.jsonl`: candidate-only backlog
