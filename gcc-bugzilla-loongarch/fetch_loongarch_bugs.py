#!/usr/bin/env python3
"""Convenience entry point; equivalent to `uv run loongarch-bug-corpus`."""

from loongarch_bug_corpus.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
