"""Command-line interface for the ExtractLLM pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .pipeline import (
    DEFAULT_BASE_URL,
    DEFAULT_INPUTS_FILE,
    DEFAULT_MAX_PROMPT_CHARS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_MODEL_TIMEOUT,
    DEFAULT_OUTPUT_DIR,
    PipelineError,
    build_feature_pool,
    prepare_corpus,
    run_extraction,
    verify_outputs,
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_corpus_dir() -> Path:
    return project_root().parent / "gcc-bugzilla-loongarch"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare GCC Bugzilla LoongArch bug records for ExtractLLM and build a "
            "feature pool for compiler quality-test generation."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="normalize all archived bug reports")
    prepare.add_argument("--corpus-dir", type=Path, default=default_corpus_dir())
    prepare.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    prepare.add_argument("--max-comment-chars", type=int, default=30000)
    prepare.add_argument("--max-program-chars", type=int, default=120000)

    run = subparsers.add_parser("run", help="run ExtractLLM over prepared inputs")
    run.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    run.add_argument("--inputs-file", type=Path, default=None)
    run.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    run.add_argument("--base-url", default=DEFAULT_BASE_URL)
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--bug-id", type=int, action="append", default=None)
    run.add_argument("--refresh", action="store_true")
    run.add_argument("--delay", type=float, default=0.2)
    run.add_argument("--retries", type=int, default=3)
    run.add_argument("--timeout", type=float, default=DEFAULT_MODEL_TIMEOUT)
    run.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    run.add_argument(
        "--max-prompt-chars",
        type=int,
        default=DEFAULT_MAX_PROMPT_CHARS,
        help="compact oversized model inputs to this many JSON characters; use 0 to disable",
    )
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--keep-going", action="store_true")
    run.add_argument("--no-json-response-format", action="store_true")

    pool = subparsers.add_parser("build-pool", help="build feature-pool.jsonl from per-bug outputs")
    pool.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)

    verify = subparsers.add_parser("verify", help="validate prepared inputs and extracted features")
    verify.add_argument("--output-dir", type=Path, default=project_root() / DEFAULT_OUTPUT_DIR)
    verify.add_argument("--require-outputs", action="store_true")
    verify.add_argument("--fail-on-api-error", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            if args.max_comment_chars <= 0 or args.max_program_chars <= 0:
                raise PipelineError("max-comment-chars and max-program-chars must be positive")
            manifest = prepare_corpus(
                corpus_dir=args.corpus_dir,
                output_dir=args.output_dir,
                max_comment_chars=args.max_comment_chars,
                max_program_chars=args.max_program_chars,
            )
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"inputs: {Path(manifest['inputs_file']).resolve()}")
            return 0
        if args.command == "run":
            if args.limit < 0 or args.delay < 0 or args.retries <= 0 or args.timeout <= 0:
                raise PipelineError("limit/delay/retries/timeout values are invalid")
            manifest = run_extraction(
                output_dir=args.output_dir,
                inputs_file=args.inputs_file,
                api_key_env=args.api_key_env,
                base_url=args.base_url,
                model=args.model,
                limit=args.limit,
                bug_ids=args.bug_id,
                refresh=args.refresh,
                delay_seconds=args.delay,
                retries=args.retries,
                timeout=args.timeout,
                max_tokens=args.max_tokens,
                max_prompt_chars=args.max_prompt_chars,
                temperature=args.temperature,
                keep_going=args.keep_going,
                response_format=not args.no_json_response_format,
            )
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"manifest: {args.output_dir.resolve() / 'extract-run-manifest.json'}")
            return 0
        if args.command == "build-pool":
            summary = build_feature_pool(args.output_dir)
            print(json.dumps(summary["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"feature pool: {args.output_dir.resolve() / 'feature-pool.jsonl'}")
            return 0
        if args.command == "verify":
            result = verify_outputs(
                output_dir=args.output_dir,
                require_outputs=args.require_outputs,
                fail_on_api_error=args.fail_on_api_error,
            )
            print(json.dumps(result["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print("extract-llm verification: PASS")
            return 0
    except (PipelineError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 2
