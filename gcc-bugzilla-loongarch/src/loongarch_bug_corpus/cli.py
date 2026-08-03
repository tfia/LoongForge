"""Command-line interface for the LoongArch GCC Bugzilla corpus builder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .core import (
    DEFAULT_BASE_URL,
    DEFAULT_USER_AGENT,
    CorpusError,
    rebuild_archive,
    sync_archive,
    verify_archive,
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Archive public LoongArch-related GCC Bugzilla reports and reproducible "
            "test cases for compiler quality/CI work."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser("sync", help="fetch or incrementally update the archive")
    sync.add_argument("--archive-dir", type=Path, default=project_root() / "archive")
    sync.add_argument(
        "--gcc-source",
        type=Path,
        default=project_root().parent / "src" / "gcc-upstream",
        help="optional local GCC checkout used to add PR regression tests",
    )
    sync.add_argument("--base-url", default=DEFAULT_BASE_URL)
    sync.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    sync.add_argument("--delay", type=float, default=0.4, help="minimum delay between HTTP requests")
    sync.add_argument("--timeout", type=float, default=60.0)
    sync.add_argument("--max-attachment-bytes", type=int, default=5_000_000)
    sync.add_argument("--refresh", action="store_true", help="refetch unchanged reports")
    sync.add_argument("--limit", type=int, default=0, help="development only: process first N bugs")

    verify = subparsers.add_parser("verify", help="verify scope, indexes, test cases, and checksums")
    verify.add_argument("--archive-dir", type=Path, default=project_root() / "archive")

    rebuild = subparsers.add_parser(
        "rebuild", help="reapply local quality policy and rebuild indexes without HTTP requests"
    )
    rebuild.add_argument("--archive-dir", type=Path, default=project_root() / "archive")

    stats = subparsers.add_parser("stats", help="print the current archive manifest")
    stats.add_argument("--archive-dir", type=Path, default=project_root() / "archive")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "sync":
            if args.delay < 0 or args.timeout <= 0 or args.max_attachment_bytes <= 0 or args.limit < 0:
                raise CorpusError("delay/timeout/attachment size/limit values are invalid")
            gcc_source = args.gcc_source if args.gcc_source.is_dir() else None
            manifest = sync_archive(
                archive_dir=args.archive_dir,
                gcc_source=gcc_source,
                base_url=args.base_url,
                user_agent=args.user_agent,
                delay_seconds=args.delay,
                timeout_seconds=args.timeout,
                max_attachment_bytes=args.max_attachment_bytes,
                refresh=args.refresh,
                limit=args.limit,
            )
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"manifest: {args.archive_dir.resolve() / 'manifest.json'}")
            return 0
        if args.command == "verify":
            counts = verify_archive(args.archive_dir)
            print(json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True))
            print("archive verification: PASS")
            return 0
        if args.command == "rebuild":
            manifest = rebuild_archive(args.archive_dir)
            print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2, sort_keys=True))
            print(f"manifest: {args.archive_dir.resolve() / 'manifest.json'}")
            return 0
        if args.command == "stats":
            manifest = args.archive_dir.resolve() / "manifest.json"
            if not manifest.is_file():
                raise CorpusError(f"manifest does not exist: {manifest}")
            print(manifest.read_text(encoding="utf-8"), end="")
            return 0
    except (CorpusError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 2
