"""Command-line interface for the GroupLLM feature-group pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .pipeline import (
    DEFAULT_ENV_FILE,
    DEFAULT_FEATURE_POOL,
    DEFAULT_GROUP_COUNT,
    DEFAULT_LANGUAGES,
    DEFAULT_MAX_FEATURES,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_WITNESS_CHARS,
    DEFAULT_MIN_FEATURES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SEED,
    DEFAULT_TIMEOUT,
    PipelineError,
    build_group_pool,
    build_afl_feedback,
    prepare_candidates,
    project_root,
    run_synthesis,
    verify_outputs,
)


def csv_values(value: str) -> Sequence[str]:
    result = [item.strip() for item in value.split(",") if item.strip()]
    if not result:
        raise argparse.ArgumentTypeError("expected at least one comma-separated value")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sample immutable ExtractLLM features and use GroupLLM to add coherent glue "
            "semantics for LoongArch GCC compiler-quality PoC generation."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="deterministically sample compatible candidates")
    prepare.add_argument(
        "--feature-pool",
        type=Path,
        default=(project_root() / DEFAULT_FEATURE_POOL).resolve(),
    )
    prepare.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    prepare.add_argument("--groups", type=int, default=DEFAULT_GROUP_COUNT)
    prepare.add_argument(
        "--append-groups",
        type=int,
        default=0,
        help=(
            "append this many candidates to the existing index, prioritizing features absent "
            "from the current ready pool; --groups is used only for an initial prepare"
        ),
    )
    prepare.add_argument("--min-features", type=int, default=DEFAULT_MIN_FEATURES)
    prepare.add_argument("--max-features", type=int, default=DEFAULT_MAX_FEATURES)
    prepare.add_argument("--seed", type=int, default=DEFAULT_SEED)
    prepare.add_argument("--target-profile", default="loongarch")
    prepare.add_argument("--languages", type=csv_values, default=DEFAULT_LANGUAGES)
    prepare.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    prepare.add_argument(
        "--coverage-basis",
        choices=("candidate", "ready"),
        default="candidate",
        help=(
            "candidate: first-pass breadth over features never sampled; ready: later iteration "
            "prioritizes features absent from validated ready groups"
        ),
    )
    prepare.add_argument(
        "--feedback-rewards",
        type=Path,
        default=None,
        help=(
            "optional AFL feature reward JSONL. If omitted, prepare auto-uses "
            "OUTPUT_DIR/afl-feedback/feature-afl-rewards.jsonl when it exists"
        ),
    )

    run = subparsers.add_parser("run", help="call the configured DeepSeek model for each candidate")
    run.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    run.add_argument(
        "--env-file",
        type=Path,
        default=(project_root() / DEFAULT_ENV_FILE).resolve(),
        help="dotenv file with DEEPSEEK_API_ENDPOINT, DEEPSEEK_API_KEY, and DEEPSEEK_MODEL",
    )
    run.add_argument("--candidates-file", type=Path, default=None)
    run.add_argument("--group-id", action="append", default=None)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--refresh", action="store_true")
    run.add_argument("--retries", type=int, default=3)
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    run.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    run.add_argument("--temperature", type=float, default=0.25)
    run.add_argument("--max-witness-chars", type=int, default=DEFAULT_MAX_WITNESS_CHARS)
    run.add_argument("--no-json-response-format", action="store_true")

    build = subparsers.add_parser(
        "build-groups", help="consolidate validated ready groups and write summary statistics"
    )
    build.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)

    feedback = subparsers.add_parser(
        "feedback", help="build AFL edge feedback rewards from InstanLLM evaluations"
    )
    feedback.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    feedback.add_argument(
        "--instan-output-dir",
        type=Path,
        default=(project_root().parent / "instan-llm" / "out").resolve(),
    )
    feedback.add_argument("--feedback-dir", type=Path, default=None)

    verify = subparsers.add_parser("verify", help="verify candidates, outputs, and ready-group pool")
    verify.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    verify.add_argument("--require-outputs", action="store_true")
    verify.add_argument("--fail-on-error", action="store_true")
    verify.add_argument("--min-ready-ratio", type=float, default=0.0)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            manifest = prepare_candidates(
                feature_pool_path=args.feature_pool,
                output_dir=args.output_dir,
                group_count=args.groups,
                min_features=args.min_features,
                max_features=args.max_features,
                seed=args.seed,
                target_profile=args.target_profile,
                allowed_languages=args.languages,
                min_confidence=args.min_confidence,
                append_groups=args.append_groups,
                coverage_basis=args.coverage_basis,
                feedback_rewards_path=args.feedback_rewards,
            )
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"candidates: {Path(manifest['candidates_file']).resolve()}")
            return 0
        if args.command == "run":
            manifest = run_synthesis(
                output_dir=args.output_dir,
                env_file=args.env_file,
                candidates_file=args.candidates_file,
                group_ids=args.group_id,
                limit=args.limit,
                refresh=args.refresh,
                retries=args.retries,
                workers=args.workers,
                timeout=args.timeout,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                response_format=not args.no_json_response_format,
                max_witness_chars=args.max_witness_chars,
            )
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"manifest: {args.output_dir.resolve() / 'group-run-manifest.json'}")
            return 0
        if args.command == "build-groups":
            manifest = build_group_pool(args.output_dir)
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"feature groups: {args.output_dir.resolve() / 'feature-groups.jsonl'}")
            return 0
        if args.command == "feedback":
            manifest = build_afl_feedback(
                group_output_dir=args.output_dir,
                instan_output_dir=args.instan_output_dir,
                feedback_dir=args.feedback_dir,
            )
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"feedback: {Path(manifest['feedback_dir']).resolve()}")
            return 0
        if args.command == "verify":
            result = verify_outputs(
                output_dir=args.output_dir,
                require_outputs=args.require_outputs,
                fail_on_error=args.fail_on_error,
                min_ready_ratio=args.min_ready_ratio,
            )
            print(json.dumps(result["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print("group-llm verification: PASS")
            return 0
    except (PipelineError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 2
