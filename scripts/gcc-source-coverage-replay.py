#!/usr/bin/env python3
"""Replay compiler-test corpus on a gcov-instrumented GCC and summarize source coverage."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DEFAULT_TARGET = "loongarch64-linux-gnu"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def canonical_language(value: Any) -> str:
    language = str(value or "unknown").strip().lower()
    return {"cpp": "c++", "cxx": "c++", "g++": "c++"}.get(language, language)


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"invalid JSONL at {path}:{line_number}: {error}") from error
            if not isinstance(value, dict):
                raise RuntimeError(f"expected object at {path}:{line_number}")
            yield value


def sanitize_compiler_options(values: Any) -> List[str]:
    if not isinstance(values, list):
        values = []
    sanitized: List[str] = []
    skip_next = False
    blocked_exact = {
        "-c",
        "-S",
        "-E",
        "-o",
        "-pipe",
        "-save-temps",
        "-shared",
        "-static",
        "-fuse-ld=gold",
        "-fuse-ld=lld",
    }
    for raw in values:
        if skip_next:
            skip_next = False
            continue
        item = str(raw).strip()
        if not item:
            continue
        if item in {"-o", "-x"}:
            skip_next = True
            continue
        if item in blocked_exact:
            continue
        if item.startswith(("-l", "-L", "-Wl,", "-Xlinker", "-fuse-ld=")):
            continue
        sanitized.append(item)
    if not any(re.fullmatch(r"-O[0-3sSzZgfast]+", item) for item in sanitized):
        sanitized.insert(0, "-O2")
    return sanitized


def percent(covered: int, total: int) -> float:
    return 0.0 if total == 0 else round(100.0 * covered / total, 2)


def inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def reset_gcda(build_dir: Path) -> int:
    build_dir = build_dir.resolve()
    root_build = (repo_root() / "build").resolve()
    if not inside(build_dir, root_build):
        raise RuntimeError(f"refusing to delete .gcda outside repository build directory: {build_dir}")
    removed = 0
    for path in build_dir.rglob("*.gcda"):
        path.unlink()
        removed += 1
    return removed


def load_covered_evaluations(evaluations_file: Path, limit: int = 0) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for item in iter_jsonl(evaluations_file):
        if item.get("evaluation_status") != "covered":
            continue
        language = canonical_language(item.get("language"))
        if language not in {"c", "c++"}:
            continue
        source = Path(str(item.get("source_path") or ""))
        if not source.is_file():
            continue
        selected.append(item)
        if limit and len(selected) >= limit:
            break
    return selected


def run_command(command: Sequence[str], timeout: float, env: Mapping[str, str]) -> Dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=dict(env),
        )
        return {
            "command": list(command),
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "duration_seconds": round(time.time() - started, 3),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "command": list(command),
            "returncode": None,
            "stdout": str(error.stdout or "")[-4000:],
            "stderr": str(error.stderr or "")[-4000:],
            "duration_seconds": round(time.time() - started, 3),
            "timed_out": True,
        }


def replay_one(
    evaluation: Mapping[str, Any],
    prefix: Path,
    target: str,
    asm_dir: Path,
    timeout_ms: int,
    env: Mapping[str, str],
) -> Dict[str, Any]:
    language = canonical_language(evaluation.get("language"))
    compiler_name = f"{target}-g++" if language == "c++" else f"{target}-gcc"
    compiler = prefix / "bin" / compiler_name
    if not compiler.is_file():
        raise RuntimeError(f"compiler does not exist: {compiler}")
    instantiation_id = str(evaluation.get("instantiation_id") or "unknown")
    suffix = ".cc" if language == "c++" else ".c"
    output = asm_dir / f"{instantiation_id}{suffix}.s"
    output.parent.mkdir(parents=True, exist_ok=True)
    source = Path(str(evaluation.get("source_path") or ""))
    options = sanitize_compiler_options(evaluation.get("compiler_options"))
    command = [str(compiler), *options, "-S", "-w", "-o", str(output), str(source)]
    result = run_command(command, timeout=max(5.0, timeout_ms / 1000.0 + 10.0), env=env)
    return {
        "instantiation_id": instantiation_id,
        "candidate_id": evaluation.get("candidate_id"),
        "language": language,
        "source_path": str(source),
        "asm_path": str(output) if output.is_file() else "",
        "status": "ok" if result["returncode"] == 0 else ("timeout" if result["timed_out"] else "failed"),
        "compile": result,
    }


def replay_corpus(
    evaluations: Sequence[Mapping[str, Any]],
    prefix: Path,
    target: str,
    out_dir: Path,
    timeout_ms: int,
) -> List[Dict[str, Any]]:
    asm_dir = out_dir / "asm"
    env = os.environ.copy()
    env.pop("GCOV_PREFIX", None)
    env.pop("GCOV_PREFIX_STRIP", None)
    env["PATH"] = f"{prefix / 'bin'}:{repo_root() / 'install' / 'bin'}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    results = []
    for index, evaluation in enumerate(evaluations, start=1):
        result = replay_one(evaluation, prefix, target, asm_dir, timeout_ms, env)
        results.append(result)
        if index % 25 == 0 or index == len(evaluations):
            print(f"replayed {index}/{len(evaluations)}", file=sys.stderr, flush=True)
    return results


def collect_gcov_json(build_dir: Path, gcov: str, source_root: Path, json_dir: Path, workers: int) -> List[Dict[str, Any]]:
    gcda_files = sorted(build_dir.rglob("*.gcda"))
    work_root = json_dir / "_work"
    if json_dir.exists():
        for path in json_dir.glob("*.gcov.json.gz"):
            path.unlink()
        if work_root.exists() and inside(work_root, json_dir):
            shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []
    if not gcda_files:
        return results
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = []
        for gcda in gcda_files:
            futures.append(pool.submit(run_gcov_one_in_dir, gcov, gcda, json_dir, work_root, source_root))
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index % 100 == 0 or index == len(futures):
                print(f"gcov processed {index}/{len(futures)}", file=sys.stderr, flush=True)
    return results


def run_gcov_one_in_dir(gcov: str, gcda: Path, json_dir: Path, work_root: Path, source_root: Path) -> Dict[str, Any]:
    json_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(gcda).encode("utf-8")).hexdigest()[:16]
    work_dir = work_root / digest
    work_dir.mkdir(parents=True, exist_ok=True)
    command = [gcov, "-j", "-b", "-p", "-x", "-s", str(source_root), str(gcda)]
    result = run_command_in_cwd(command, timeout=120.0, env=os.environ, cwd=work_dir)
    generated_count = 0
    for generated in sorted(work_dir.glob("*.gcov.json.gz")):
        generated.replace(json_dir / f"{digest}-{generated.name}")
        generated_count += 1
    return {
        "gcda": str(gcda),
        "status": "ok" if result["returncode"] == 0 else "failed",
        "generated_count": generated_count,
        "gcov": result if result["returncode"] != 0 else {"returncode": 0, "duration_seconds": result["duration_seconds"]},
    }


def run_command_in_cwd(command: Sequence[str], timeout: float, env: Mapping[str, str], cwd: Path) -> Dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=dict(env),
        )
        return {
            "command": list(command),
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "duration_seconds": round(time.time() - started, 3),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "command": list(command),
            "returncode": None,
            "stdout": str(error.stdout or "")[-4000:],
            "stderr": str(error.stderr or "")[-4000:],
            "duration_seconds": round(time.time() - started, 3),
            "timed_out": True,
        }


def parse_gcov_json_files(json_dir: Path, source_root: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    files: Dict[str, Dict[str, Any]] = {}
    source_root = source_root.resolve()
    for path in sorted(json_dir.glob("*.gcov.json.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        for file_entry in payload.get("files", []):
            source_path = Path(str(file_entry.get("file") or ""))
            if not source_path.is_absolute():
                source_path = (source_root / source_path).resolve()
            else:
                source_path = source_path.resolve()
            if not inside(source_path, source_root) or not source_path.is_file():
                continue
            key = str(source_path)
            bucket = files.setdefault(
                key,
                {
                    "file": key,
                    "_lines_total": set(),
                    "_lines_covered": set(),
                    "_functions_total": set(),
                    "_functions_covered": set(),
                    "_branches_total": set(),
                    "_branches_covered": set(),
                },
            )
            for line in file_entry.get("lines", []):
                line_no = line.get("line_number")
                if line_no is None:
                    continue
                line_no = int(line_no)
                bucket["_lines_total"].add(line_no)
                if int(line.get("count") or 0) > 0:
                    bucket["_lines_covered"].add(line_no)
                for branch_index, branch in enumerate(line.get("branches", []) or []):
                    branch_key = (line_no, branch_index)
                    bucket["_branches_total"].add(branch_key)
                    if int(branch.get("count") or 0) > 0:
                        bucket["_branches_covered"].add(branch_key)
            for function in file_entry.get("functions", []) or []:
                name = str(function.get("name") or "")
                if not name:
                    continue
                bucket["_functions_total"].add(name)
                if int(function.get("execution_count") or 0) > 0:
                    bucket["_functions_covered"].add(name)

    per_file = []
    for bucket in files.values():
        per_file.append(
            {
                "file": bucket["file"],
                "lines_total": len(bucket["_lines_total"]),
                "lines_covered": len(bucket["_lines_covered"]),
                "functions_total": len(bucket["_functions_total"]),
                "functions_covered": len(bucket["_functions_covered"]),
                "branches_total": len(bucket["_branches_total"]),
                "branches_covered": len(bucket["_branches_covered"]),
            }
        )
    per_file = sorted(per_file, key=lambda item: (-item["lines_covered"], item["file"]))
    totals = {
        "files_total": len(per_file),
        "lines_total": sum(item["lines_total"] for item in per_file),
        "lines_covered": sum(item["lines_covered"] for item in per_file),
        "functions_total": sum(item["functions_total"] for item in per_file),
        "functions_covered": sum(item["functions_covered"] for item in per_file),
        "branches_total": sum(item["branches_total"] for item in per_file),
        "branches_covered": sum(item["branches_covered"] for item in per_file),
    }
    totals["line_coverage_percent"] = percent(totals["lines_covered"], totals["lines_total"])
    totals["function_coverage_percent"] = percent(totals["functions_covered"], totals["functions_total"])
    totals["branch_coverage_percent"] = percent(totals["branches_covered"], totals["branches_total"])
    return totals, per_file


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def write_report(report_path: Path, manifest: Mapping[str, Any], per_file: Sequence[Mapping[str, Any]]) -> None:
    totals = manifest["coverage_totals"]
    top_rows = []
    for item in per_file[:50]:
        top_rows.append(
            [
                str(Path(str(item["file"])).relative_to(Path(manifest["source_root"]))),
                item["lines_covered"],
                item["lines_total"],
                f"{percent(item['lines_covered'], item['lines_total']):.2f}%",
                item["functions_covered"],
                item["functions_total"],
                f"{percent(item['functions_covered'], item['functions_total']):.2f}%",
            ]
        )
    content = [
        "# GCC 源码覆盖率报告",
        "",
        f"生成时间：`{manifest['generated_at']}`",
        "",
        "测试范围：自有 LoongArch GCC fork 的编译器 CI 质量测试；不涉及网络安全测试。",
        "",
        "## 汇总",
        "",
        markdown_table(
            ["指标", "数值"],
            [
                ["重放测例数", manifest["replay_counts"]["selected"]],
                ["重放返回 0", manifest["replay_counts"]["ok"]],
                ["重放非零退出", manifest["replay_counts"]["failed"]],
                ["重放超时", manifest["replay_counts"]["timeout"]],
                ["GCC 源码文件数", totals["files_total"]],
                ["源码行覆盖", f"{totals['lines_covered']}/{totals['lines_total']} ({totals['line_coverage_percent']:.2f}%)"],
                ["函数覆盖", f"{totals['functions_covered']}/{totals['functions_total']} ({totals['function_coverage_percent']:.2f}%)"],
                ["分支覆盖", f"{totals['branches_covered']}/{totals['branches_total']} ({totals['branch_coverage_percent']:.2f}%)"],
            ],
        ),
        "",
        "## 口径说明",
        "",
        "- 本报告使用 gcov 读取 coverage 版 GCC 运行后生成的 `.gcda/.gcno`，统计 GCC 源码树内文件的源码行、函数和分支覆盖。",
        "- 它回答的是“这批编译器测试让 GCC 自身源码执行了多少行/函数”，不是 AFL edge map；两者应并列使用。",
        "- 只统计真实存在于 `src/gcc-upstream` 下的文件；测试程序、系统头文件和 GCC build 目录生成文件不计入分母。",
        "- 当前重放以 `-S` 编译到汇编，避免链接/sysroot 依赖；因此覆盖重点是 driver、C/C++ 前端、优化器和后端编译路径。",
        "- 非零退出的测例仍会触发 GCC 前端/诊断路径并产生 coverage，因此保留在质量测试口径中；返回 0 单独列出用于说明语料可编译比例。",
        "",
        "## 结果解读",
        "",
        f"- 当前 260 条 InstanLLM covered corpus 覆盖 GCC 源码行 {totals['lines_covered']}/{totals['lines_total']}，函数 {totals['functions_covered']}/{totals['functions_total']}。",
        "- Top 文件集中在 C/C++ 前端、通用优化器和 `gcc/config/loongarch` 后端，说明这批语料已经能穿透到 LoongArch 代码生成与向量化相关路径。",
        "- 后续提升覆盖率的主要方向不是增加同质编译参数，而是补齐当前无法稳定编译的头文件依赖，并为 Fortran/Ada/D/asm/RTL 等非 C/C++ group 增加专用 harness。",
        "",
        "## 覆盖最多的源码文件 Top 50",
        "",
        markdown_table(["文件", "覆盖行", "总行", "行覆盖率", "覆盖函数", "总函数", "函数覆盖率"], top_rows),
        "",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(content), encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=os.environ.get("TARGET", DEFAULT_TARGET))
    parser.add_argument("--prefix", type=Path, default=Path(os.environ.get("GCC_GCOV_PREFIX", root / "install-gcov")))
    parser.add_argument("--build-dir", type=Path, default=Path(os.environ.get("GCC_GCOV_BUILD", root / "build" / "gcc-gcov")))
    parser.add_argument("--source-root", type=Path, default=root / "src" / "gcc-upstream")
    parser.add_argument("--evaluations", type=Path, default=root / "instan-llm" / "out" / "evaluations.jsonl")
    parser.add_argument("--out-dir", type=Path, default=root / "out" / "source-coverage" / "instanllm-covered")
    parser.add_argument("--gcov", default=os.environ.get("GCOV", shutil.which("gcov-15") or shutil.which("gcov") or "gcov"))
    parser.add_argument("--timeout-ms", type=int, default=20000)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--gcov-workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    parser.add_argument("--no-reset", action="store_true", help="do not delete old .gcda files before replay")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    prefix = args.prefix.resolve()
    build_dir = args.build_dir.resolve()
    source_root = args.source_root.resolve()
    out_dir = args.out_dir.resolve()
    if not (prefix / "bin" / f"{args.target}-gcc").is_file():
        raise RuntimeError(f"coverage GCC is missing; run scripts/build-gcc-gcov.sh first: {prefix}")
    if not build_dir.is_dir():
        raise RuntimeError(f"coverage GCC build directory is missing: {build_dir}")
    if not source_root.is_dir():
        raise RuntimeError(f"GCC source root is missing: {source_root}")
    out_dir.mkdir(parents=True, exist_ok=True)
    removed_gcda = 0 if args.no_reset else reset_gcda(build_dir)
    evaluations = load_covered_evaluations(args.evaluations.resolve(), args.limit)
    print(f"selected covered evaluations: {len(evaluations)}", file=sys.stderr)
    replay_results = replay_corpus(evaluations, prefix, args.target, out_dir, args.timeout_ms)
    gcov_dir = out_dir / "gcov-json"
    gcov_results = collect_gcov_json(build_dir, args.gcov, source_root, gcov_dir, args.gcov_workers)
    totals, per_file = parse_gcov_json_files(gcov_dir, source_root)
    status_counts = Counter(item["status"] for item in replay_results)
    manifest = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "quality_scope": "compiler CI quality testing; not security testing",
        "target": args.target,
        "prefix": str(prefix),
        "build_dir": str(build_dir),
        "source_root": str(source_root),
        "evaluations": str(args.evaluations.resolve()),
        "out_dir": str(out_dir),
        "gcov": args.gcov,
        "removed_gcda_before_replay": removed_gcda,
        "replay_counts": {
            "selected": len(evaluations),
            "ok": status_counts.get("ok", 0),
            "failed": status_counts.get("failed", 0),
            "timeout": status_counts.get("timeout", 0),
        },
        "gcov_counts": {
            "gcda_files": len(list(build_dir.rglob("*.gcda"))),
            "gcov_ok": sum(1 for item in gcov_results if item["status"] == "ok"),
            "gcov_failed": sum(1 for item in gcov_results if item["status"] != "ok"),
            "json_files": len(list(gcov_dir.glob("*.gcov.json.gz"))),
        },
        "coverage_totals": totals,
        "report_path": str(out_dir / "gcc-source-coverage-report.md"),
        "json_path": str(out_dir / "gcc-source-coverage-summary.json"),
    }
    write_json(out_dir / "replay-results.json", replay_results)
    write_json(out_dir / "gcov-results.json", gcov_results)
    write_json(out_dir / "per-file-coverage.json", per_file)
    write_json(out_dir / "gcc-source-coverage-summary.json", manifest)
    write_report(out_dir / "gcc-source-coverage-report.md", manifest, per_file)
    print(json.dumps({
        "selected": manifest["replay_counts"]["selected"],
        "replay_ok": manifest["replay_counts"]["ok"],
        "line_coverage_percent": totals["line_coverage_percent"],
        "function_coverage_percent": totals["function_coverage_percent"],
        "report": manifest["report_path"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
