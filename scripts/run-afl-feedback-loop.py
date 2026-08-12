#!/usr/bin/env python3
"""Run the LoongForge ExtractLLM -> GroupLLM -> InstanLLM AFL feedback loop.

This is an orchestration script for long compiler-quality test runs.  It does
not add a second pipeline path: it only calls the existing GroupLLM/InstanLLM
CLI commands with per-stage logging and recovery-friendly batching.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GROUP_DIR = PROJECT_ROOT / "group-llm"
INSTAN_DIR = PROJECT_ROOT / "instan-llm"
GROUP_OUT = GROUP_DIR / "out"
INSTAN_OUT = INSTAN_DIR / "out"
GROUPS_FILE = GROUP_OUT / "feature-groups.jsonl"
FEEDBACK_MANIFEST = GROUP_OUT / "afl-feedback" / "afl-feedback-manifest.json"
EVALUATIONS_FILE = INSTAN_OUT / "evaluations.jsonl"
LOG_ROOT = PROJECT_ROOT / "logs" / "afl-feedback-loop"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iter_jsonl(path: Path) -> Iterable[dict]:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(dict(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def module_env(component: str) -> dict:
    env = os.environ.copy()
    src = PROJECT_ROOT / component / "src"
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(src) if not prior else f"{src}{os.pathsep}{prior}"
    return env


def run_logged(
    *,
    name: str,
    cwd: Path,
    env: Mapping[str, str],
    args: Sequence[str],
    log_dir: Path,
    timeout: int | None = None,
    continue_on_error: bool = False,
) -> subprocess.CompletedProcess:
    log_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    proc: subprocess.CompletedProcess | None = None
    timed_out = False
    try:
        proc = subprocess.run(
            list(args),
            cwd=str(cwd),
            env=dict(env),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        timed_out = True
        proc = subprocess.CompletedProcess(
            args=list(args),
            returncode=124,
            stdout=error.stdout or "",
            stderr=error.stderr or f"timed out after {timeout}s",
        )
    elapsed = round(time.time() - started, 3)
    stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    (log_dir / f"{stem}.stdout.log").write_text(proc.stdout or "", encoding="utf-8")
    (log_dir / f"{stem}.stderr.log").write_text(proc.stderr or "", encoding="utf-8")
    meta = {
        "args": list(args),
        "cwd": str(cwd),
        "elapsed_seconds": elapsed,
        "returncode": proc.returncode,
        "timed_out": timed_out,
    }
    write_json(log_dir / f"{stem}.meta.json", meta)
    if proc.returncode != 0 and not continue_on_error:
        raise RuntimeError(f"{name} failed with {proc.returncode}; see {log_dir / (stem + '.stderr.log')}")
    return proc


def candidate_ids_tail(count: int) -> list[str]:
    rows = list(iter_jsonl(GROUP_OUT / "group-candidates.jsonl"))
    return [str(row["candidate_id"]) for row in rows[-count:]]


def group_statuses(ids: Sequence[str]) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for gid in ids:
        path = GROUP_OUT / "groups" / f"{gid}.group.json"
        if not path.is_file():
            counts["missing"] += 1
            continue
        counts[str(read_json(path).get("synthesis_status") or "unknown")] += 1
    return counts


def ready_group_ids(ids: Sequence[str]) -> list[str]:
    ready: list[str] = []
    for row in iter_jsonl(GROUPS_FILE):
        cid = str(row.get("candidate_id") or "")
        if cid in ids:
            ready.append(cid)
    return ready


def evaluation_statuses(ids: Sequence[str]) -> collections.Counter:
    wanted = set(ids)
    counts: collections.Counter = collections.Counter()
    for row in iter_jsonl(EVALUATIONS_FILE):
        if str(row.get("candidate_id") or "") in wanted:
            counts[str(row.get("evaluation_status") or "unknown")] += 1
    return counts


def union_edges() -> int:
    if not FEEDBACK_MANIFEST.is_file():
        return 0
    counts = read_json(FEEDBACK_MANIFEST).get("counts", {})
    try:
        return int(counts.get("union_edges") or 0)
    except (TypeError, ValueError):
        return 0


def ice_candidates(ids: Sequence[str]) -> list[dict]:
    wanted = set(ids)
    groups_by_candidate = {str(row.get("candidate_id")): row for row in iter_jsonl(GROUPS_FILE)}
    result: list[dict] = []
    for row in iter_jsonl(EVALUATIONS_FILE):
        if str(row.get("candidate_id") or "") not in wanted:
            continue
        if row.get("evaluation_status") != "ice":
            continue
        stderr = ""
        compile_record = row.get("compile")
        if isinstance(compile_record, dict):
            stderr = str(compile_record.get("stderr") or "")
        signature = "\n".join(stderr.splitlines()[-20:])
        group = groups_by_candidate.get(str(row.get("candidate_id")), {})
        result.append(
            {
                "candidate_id": row.get("candidate_id"),
                "group_uid": row.get("group_uid"),
                "instantiation_id": row.get("instantiation_id"),
                "source_path": row.get("source_path"),
                "source_bug_ids": group.get("source_bug_ids", []),
                "stderr_signature_sha256": hashlib.sha256(signature.encode("utf-8")).hexdigest(),
                "stderr_tail": signature[-2000:],
                "dedupe_status": "needs_known_poc_signature_review",
            }
        )
    return result


def repeated_group_args(ids: Sequence[str]) -> list[str]:
    result: list[str] = []
    for gid in ids:
        result.extend(["--group-id", gid])
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--seed-base", type=int, default=2026081200)
    parser.add_argument("--group-api-timeout", type=int, default=180)
    parser.add_argument("--group-process-timeout", type=int, default=240)
    parser.add_argument("--group-parallel", type=int, default=4)
    parser.add_argument("--group-retries", type=int, default=2)
    parser.add_argument("--instan-workers", type=int, default=2)
    parser.add_argument("--instan-timeout", type=int, default=180)
    parser.add_argument("--instan-process-timeout", type=int, default=900)
    parser.add_argument("--evaluate-timeout-ms", type=int, default=20000)
    parser.add_argument("--optimization", default="-Ofast")
    parser.add_argument("--coverage-basis", default="ready")
    parser.add_argument("--log-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.iterations <= 0 or args.batch_size <= 0:
        raise SystemExit("iterations and batch-size must be positive")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = (args.log_dir or LOG_ROOT / run_id).resolve()
    group_env = module_env("group-llm")
    instan_env = module_env("instan-llm")
    summaries: list[dict] = []
    print(f"log_dir: {log_dir}", flush=True)

    for iteration in range(1, args.iterations + 1):
        before_edges = union_edges()
        iter_log = log_dir / f"iter-{iteration:03d}"
        seed = args.seed_base + iteration
        print(f"[iter {iteration}] prepare batch={args.batch_size} seed={seed}", flush=True)
        run_logged(
            name="01-prepare",
            cwd=GROUP_DIR,
            env=group_env,
            args=[
                sys.executable, "-m", "group_llm", "prepare",
                "--output-dir", "out",
                "--append-groups", str(args.batch_size),
                "--coverage-basis", args.coverage_basis,
                "--seed", str(seed),
            ],
            log_dir=iter_log,
        )
        ids = candidate_ids_tail(args.batch_size)

        def run_group(index_and_gid: tuple[int, str]) -> tuple[str, int]:
            index, gid = index_and_gid
            proc = run_logged(
                name=f"02-group-{index:03d}-{gid}",
                cwd=GROUP_DIR,
                env=group_env,
                args=[
                    sys.executable, "-m", "group_llm", "run",
                    "--output-dir", "out",
                    "--workers", "1",
                    "--timeout", str(args.group_api_timeout),
                    "--retries", str(args.group_retries),
                    "--group-id", gid,
                ],
                log_dir=iter_log,
                timeout=args.group_process_timeout,
                continue_on_error=True,
            )
            return gid, int(proc.returncode)

        group_jobs = list(enumerate(ids, start=1))
        print(
            f"[iter {iteration}] group synthesis {len(group_jobs)} jobs "
            f"parallel={args.group_parallel} per_process_timeout={args.group_process_timeout}s",
            flush=True,
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.group_parallel) as executor:
            futures = [executor.submit(run_group, item) for item in group_jobs]
            for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                gid, returncode = future.result()
                print(
                    f"[iter {iteration}] group done {completed}/{len(group_jobs)} {gid} rc={returncode}",
                    flush=True,
                )

        run_logged(
            name="03-build-groups",
            cwd=GROUP_DIR,
            env=group_env,
            args=[sys.executable, "-m", "group_llm", "build-groups", "--output-dir", "out"],
            log_dir=iter_log,
        )
        ready_ids = ready_group_ids(ids)

        if ready_ids:
            run_logged(
                name="04-instan-run",
                cwd=INSTAN_DIR,
                env=instan_env,
                args=[
                    sys.executable, "-m", "instan_llm", "run",
                    "--groups-file", str(GROUPS_FILE),
                    "--output-dir", "out",
                    "--workers", str(args.instan_workers),
                    "--timeout", str(args.instan_timeout),
                    *repeated_group_args(ready_ids),
                ],
                log_dir=iter_log,
                timeout=args.instan_process_timeout,
                continue_on_error=True,
            )
            run_logged(
                name="05-evaluate",
                cwd=INSTAN_DIR,
                env=instan_env,
                args=[
                    sys.executable, "-m", "instan_llm", "evaluate",
                    "--output-dir", "out",
                    f"--optimization={args.optimization}",
                    "--timeout-ms", str(args.evaluate_timeout_ms),
                    *repeated_group_args(ready_ids),
                ],
                log_dir=iter_log,
                continue_on_error=True,
            )

        run_logged(
            name="06-feedback",
            cwd=GROUP_DIR,
            env=group_env,
            args=[
                sys.executable, "-m", "group_llm", "feedback",
                "--output-dir", "out",
                "--instan-output-dir", str(INSTAN_OUT),
            ],
            log_dir=iter_log,
        )
        after_edges = union_edges()
        summary = {
            "iteration": iteration,
            "generated_at": utc_now(),
            "candidate_ids": ids,
            "ready_group_ids": ready_ids,
            "group_statuses": dict(group_statuses(ids)),
            "evaluation_statuses": dict(evaluation_statuses(ready_ids)),
            "ice_candidates": ice_candidates(ready_ids),
            "union_edges_before": before_edges,
            "union_edges_after": after_edges,
            "union_edges_delta": after_edges - before_edges,
            "optimization": args.optimization,
            "quality_scope": "compiler CI quality testing; not security testing",
        }
        write_json(iter_log / "iteration-summary.json", summary)
        summaries.append(summary)
        print(
            f"[iter {iteration}] ready={len(ready_ids)} "
            f"group={summary['group_statuses']} eval={summary['evaluation_statuses']} "
            f"edges={before_edges}->{after_edges} delta={after_edges - before_edges} "
            f"ice={len(summary['ice_candidates'])}",
            flush=True,
        )

    final = {
        "run_id": run_id,
        "generated_at": utc_now(),
        "log_dir": str(log_dir),
        "iterations": summaries,
        "final_union_edges": union_edges(),
    }
    write_json(log_dir / "run-summary.json", final)
    print(f"summary: {log_dir / 'run-summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
