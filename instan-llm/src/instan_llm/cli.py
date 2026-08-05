"""Command-line interface for InstanLLM test instantiation and coverage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .pipeline import (
    DEFAULT_ENV_FILE,
    DEFAULT_GROUPS_FILE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TIMEOUT,
    PipelineError,
    build_corpus,
    evaluate_instantiations,
    generate_coverage_report,
    project_root,
    run_synthesis,
    verify_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Instantiate GroupLLM feature groups into complete compiler-quality tests, "
            "then compile them with the AFL++ wrapped LoongArch GCC to record coverage."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="call the configured model to generate test programs")
    run.add_argument(
        "--groups-file",
        type=Path,
        default=(project_root() / DEFAULT_GROUPS_FILE).resolve(),
    )
    run.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    run.add_argument(
        "--env-file",
        type=Path,
        default=(project_root() / DEFAULT_ENV_FILE).resolve(),
        help="dotenv file with DEEPSEEK_API_ENDPOINT, DEEPSEEK_API_KEY, and DEEPSEEK_MODEL",
    )
    run.add_argument("--group-id", action="append", default=None)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--refresh", action="store_true")
    run.add_argument("--retries", type=int, default=3)
    run.add_argument("--workers", type=int, default=2)
    run.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    run.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    run.add_argument("--temperature", type=float, default=0.2)
    run.add_argument("--no-json-response-format", action="store_true")

    evaluate = subparsers.add_parser(
        "evaluate", help="compile generated programs and collect AFL++ edge coverage"
    )
    evaluate.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    evaluate.add_argument("--instantiations-file", type=Path, default=None)
    evaluate.add_argument("--group-id", action="append", default=None)
    evaluate.add_argument("--limit", type=int, default=0)
    evaluate.add_argument("--refresh", action="store_true")
    evaluate.add_argument("--timeout-ms", type=int, default=20000)
    evaluate.add_argument("--min-edges", type=int, default=1)

    build = subparsers.add_parser(
        "build-corpus", help="copy covered C/C++ programs into a corpus directory"
    )
    build.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    build.add_argument("--corpus-dir", type=Path, default=None)

    report = subparsers.add_parser("report", help="write a Markdown InstanLLM coverage report")
    report.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    report.add_argument(
        "--groups-file",
        type=Path,
        default=(project_root() / DEFAULT_GROUPS_FILE).resolve(),
    )
    report.add_argument("--report-path", type=Path, default=None)

    verify = subparsers.add_parser("verify", help="verify instantiation and coverage outputs")
    verify.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    verify.add_argument("--require-evaluations", action="store_true")
    verify.add_argument("--min-covered", type=int, default=0)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            manifest = run_synthesis(
                groups_file=args.groups_file,
                output_dir=args.output_dir,
                env_file=args.env_file,
                group_ids=args.group_id,
                limit=args.limit,
                refresh=args.refresh,
                retries=args.retries,
                workers=args.workers,
                timeout=args.timeout,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                response_format=not args.no_json_response_format,
            )
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"manifest: {args.output_dir.resolve() / 'instan-run-manifest.json'}")
            return 0
        if args.command == "evaluate":
            manifest = evaluate_instantiations(
                output_dir=args.output_dir,
                instantiations_file=args.instantiations_file,
                group_ids=args.group_id,
                limit=args.limit,
                refresh=args.refresh,
                timeout_ms=args.timeout_ms,
                min_edges=args.min_edges,
            )
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"manifest: {args.output_dir.resolve() / 'evaluation-manifest.json'}")
            return 0
        if args.command == "build-corpus":
            manifest = build_corpus(args.output_dir, args.corpus_dir)
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"corpus: {manifest['corpus_dir']}")
            return 0
        if args.command == "report":
            manifest = generate_coverage_report(args.output_dir, args.groups_file, args.report_path)
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"report: {manifest['report_path']}")
            return 0
        if args.command == "verify":
            result = verify_outputs(
                output_dir=args.output_dir,
                require_evaluations=args.require_evaluations,
                min_covered=args.min_covered,
            )
            print(json.dumps(result["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print("instan-llm verification: PASS")
            return 0
    except (PipelineError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 2
