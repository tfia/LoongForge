"""Pipeline primitives for ExtractLLM feature extraction.

The pipeline is intentionally plain Python: the surrounding corpus builder uses
only the standard library, and keeping this package dependency-free makes it
simple to run inside CI preparation jobs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_OUTPUT_DIR = Path("out")
DEFAULT_INPUTS_FILE = "extract-inputs.jsonl"
DEFAULT_MODEL_TIMEOUT = 180.0
DEFAULT_MAX_PROMPT_CHARS = 120000
DEFAULT_MAX_TOKENS = 12000
INPUT_SCHEMA_VERSION = 1
FEATURE_SCHEMA_VERSION = 1

FIX_EVIDENCE_RE = re.compile(
    r"(branch has been updated|https://gcc\.gnu\.org/g:|\bcommit\b|ChangeLog|"
    r"\bFixed\b|\bfixed\b|\bfix(?:ed|es)?\b|\bpatch\b|root cause|caused by|"
    r"cherry picked|backport|regression fix)",
    re.IGNORECASE,
)
COMMIT_HASH_RE = re.compile(r"(?:gcc\.gnu\.org/g:)?\b([0-9a-f]{12,40})\b", re.IGNORECASE)
BUG_ID_RE = re.compile(r"bug-(\d+)")
CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


class PipelineError(RuntimeError):
    """Raised when the local pipeline cannot complete a requested operation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_hash(value: Any, length: int = 16) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise PipelineError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
    return count


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise PipelineError(f"expected JSON object at {path}:{line_number}")
            yield value


def clip_text(text: str, max_chars: int) -> Tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    marker = "\n\n[... content truncated by extract-llm to fit the model context ...]\n\n"
    keep = max(0, max_chars - len(marker))
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + text[-tail:], True


def read_text_lossy(path: Path, max_chars: int = 0) -> Tuple[str, bool]:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    if max_chars:
        return clip_text(text, max_chars)
    return text, False


def report_bug_id_from_path(path: Path) -> int:
    match = BUG_ID_RE.search(str(path))
    if not match:
        return 0
    return int(match.group(1))


def sorted_report_paths(corpus_dir: Path) -> List[Path]:
    reports_dir = corpus_dir / "archive" / "reports"
    if not reports_dir.is_dir() and (corpus_dir / "reports").is_dir():
        reports_dir = corpus_dir / "reports"
    if not reports_dir.is_dir():
        raise PipelineError(
            "corpus reports directory does not exist; expected either "
            f"{corpus_dir / 'archive' / 'reports'} or {corpus_dir / 'reports'}"
        )
    paths = list(reports_dir.glob("bug-*/report.json"))
    return sorted(paths, key=report_bug_id_from_path)


def testcase_full_path(report_path: Path, testcase: Dict[str, Any]) -> Path:
    rel = testcase.get("path") or testcase.get("source_path")
    if not rel:
        raise PipelineError(f"testcase without path in {report_path}")
    rel_path = Path(str(rel))
    if rel_path.is_absolute():
        return rel_path
    if str(rel).startswith("reports/"):
        archive_root = report_path.parents[2]
        return archive_root / rel_path
    return report_path.parent / rel_path


def normalize_comment(comment: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    text, truncated = clip_text(str(comment.get("text") or ""), max_chars)
    return {
        "count": comment.get("count"),
        "time": comment.get("creation_time") or comment.get("time"),
        "attachment_id": comment.get("attachment_id"),
        "text": text,
        "truncated": truncated,
    }


def is_fix_comment(comment: Dict[str, Any]) -> bool:
    text = str(comment.get("text") or "")
    if not text:
        return False
    return bool(FIX_EVIDENCE_RE.search(text))


def attachment_is_fix_evidence(attachment: Dict[str, Any]) -> bool:
    summary = f"{attachment.get('summary') or ''} {attachment.get('file_name') or ''}"
    return bool(attachment.get("is_patch")) or bool(re.search(r"\b(patch|fix|backport)\b", summary, re.I))


def extract_commit_hashes(text: str) -> List[str]:
    seen = set()
    commits = []
    for match in COMMIT_HASH_RE.finditer(text):
        value = match.group(1).lower()
        if value not in seen:
            commits.append(value)
            seen.add(value)
    return commits


def extract_fix_history(report: Dict[str, Any], max_comment_chars: int) -> Dict[str, Any]:
    evidence: List[Dict[str, Any]] = []
    seen_comments = set()

    for comment in report.get("comments") or []:
        if not isinstance(comment, dict) or not is_fix_comment(comment):
            continue
        normalized = normalize_comment(comment, max_comment_chars)
        text = normalized["text"]
        normalized.update(
            {
                "kind": "bugzilla_comment",
                "commit_hashes": extract_commit_hashes(text),
            }
        )
        evidence.append(normalized)
        seen_comments.add(comment.get("count"))

    for attachment in report.get("attachments") or []:
        if not isinstance(attachment, dict) or not attachment_is_fix_evidence(attachment):
            continue
        entry = {
            "kind": "bugzilla_attachment",
            "attachment_id": attachment.get("id"),
            "summary": attachment.get("summary"),
            "file_name": attachment.get("file_name"),
            "is_patch": bool(attachment.get("is_patch")),
            "downloaded": bool(attachment.get("downloaded")),
            "source_url": f"https://gcc.gnu.org/bugzilla/rest.cgi/bug/attachment/{attachment.get('id')}"
            if attachment.get("id")
            else None,
        }
        evidence.append(entry)

    commit_hashes: List[str] = []
    for item in evidence:
        for commit in item.get("commit_hashes") or []:
            if commit not in commit_hashes:
                commit_hashes.append(commit)

    return {
        "available": bool(evidence),
        "evidence_count": len(evidence),
        "commit_hashes": commit_hashes,
        "evidence": evidence,
        "notes": (
            "Fix history was extracted from public Bugzilla comments and patch metadata. "
            "If no explicit fix/root-cause evidence is present, ExtractLLM must lower confidence."
        ),
    }


def testcase_record(
    report_path: Path,
    bug_id: int,
    testcase: Dict[str, Any],
    index: int,
    max_program_chars: int,
) -> Dict[str, Any]:
    path = testcase_full_path(report_path, testcase)
    if not path.is_file():
        raise PipelineError(f"missing testcase file for bug {bug_id}: {path}")
    content, truncated = read_text_lossy(path, max_program_chars)
    source_sha256 = testcase.get("sha256") or testcase.get("source_sha256")
    return {
        "program_id": f"bug-{bug_id}-poc-{index:03d}",
        "kind": testcase.get("kind"),
        "language": testcase.get("language") or "unknown",
        "path": str(path),
        "archive_relative_path": str(path.relative_to(report_path.parents[2]))
        if report_path.parents[2] in path.parents
        else str(path),
        "sha256": source_sha256,
        "bytes": testcase.get("bytes") or testcase.get("source_bytes"),
        "provenance": testcase.get("provenance") or {},
        "content": content,
        "truncated": truncated,
    }


def prepare_bug_input(
    report_path: Path,
    corpus_dir: Path,
    max_comment_chars: int,
    max_program_chars: int,
) -> Dict[str, Any]:
    report = read_json(report_path)
    metadata = report.get("metadata") or {}
    bug_id = int(metadata.get("id") or report_bug_id_from_path(report_path))
    description = str(report.get("description") or "")
    comments = [
        normalize_comment(comment, max_comment_chars)
        for comment in (report.get("comments") or [])
        if isinstance(comment, dict) and str(comment.get("text") or "").strip()
    ]
    programs = [
        testcase_record(report_path, bug_id, testcase, index, max_program_chars)
        for index, testcase in enumerate(report.get("testcases") or [], start=1)
        if isinstance(testcase, dict)
    ]
    fix_history = extract_fix_history(report, max_comment_chars)
    evidence_gaps = []
    if not programs:
        evidence_gaps.append("missing_bug_triggering_program")
    if not fix_history["available"]:
        evidence_gaps.append("missing_explicit_fix_history")

    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "input_id": f"gcc-bugzilla-loongarch-bug-{bug_id}",
        "bug_id": bug_id,
        "source_url": report.get("source_url") or f"https://gcc.gnu.org/bugzilla/show_bug.cgi?id={bug_id}",
        "prepared_at": utc_now(),
        "purpose": "Compiler quality testing for an owned LoongArch GCC fork; not security testing.",
        "metadata": {
            "summary": metadata.get("summary"),
            "component": metadata.get("component"),
            "status": metadata.get("status"),
            "resolution": metadata.get("resolution"),
            "target": metadata.get("cf_gcctarget"),
            "known_to_fail": metadata.get("cf_known_to_fail"),
            "known_to_work": metadata.get("cf_known_to_work"),
            "keywords": metadata.get("keywords") or [],
            "target_milestone": metadata.get("target_milestone"),
            "version": metadata.get("version"),
            "creation_time": metadata.get("creation_time"),
            "last_change_time": metadata.get("last_change_time"),
        },
        "relevance": report.get("relevance") or {},
        "architecture_scope": report.get("architecture_scope") or {},
        "bug_report": {
            "description": description,
            "comments": comments,
        },
        "bug_triggering_programs": programs,
        "fix_history": fix_history,
        "quality_context": {
            "not_security_research": True,
            "intended_ci_use": (
                "Extract semantic compiler-test features from historical regressions, "
                "then combine features to mutate future GCC quality tests."
            ),
        },
        "eligibility": {
            "has_bug_triggering_program": bool(programs),
            "has_explicit_fix_history": fix_history["available"],
            "evidence_gaps": evidence_gaps,
        },
        "input_sha256": stable_hash(
            {
                "bug_id": bug_id,
                "description": description,
                "comments": comments,
                "programs": programs,
                "fix_history": fix_history,
            },
            length=64,
        ),
    }


def prepare_corpus(
    corpus_dir: Path,
    output_dir: Path,
    max_comment_chars: int = 30000,
    max_program_chars: int = 120000,
) -> Dict[str, Any]:
    corpus_dir = corpus_dir.resolve()
    output_dir = output_dir.resolve()
    paths = sorted_report_paths(corpus_dir)
    records = [
        prepare_bug_input(path, corpus_dir, max_comment_chars, max_program_chars)
        for path in paths
    ]
    inputs_path = output_dir / DEFAULT_INPUTS_FILE
    write_jsonl(inputs_path, records)

    per_bug_dir = output_dir / "inputs"
    for record in records:
        write_json(per_bug_dir / f"bug-{record['bug_id']}.input.json", record)

    manifest = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "corpus_dir": str(corpus_dir),
        "output_dir": str(output_dir),
        "inputs_file": str(inputs_path),
        "counts": {
            "bug_reports": len(records),
            "with_bug_triggering_program": sum(
                1 for record in records if record["eligibility"]["has_bug_triggering_program"]
            ),
            "with_explicit_fix_history": sum(
                1 for record in records if record["eligibility"]["has_explicit_fix_history"]
            ),
            "with_program_and_fix_history": sum(
                1
                for record in records
                if record["eligibility"]["has_bug_triggering_program"]
                and record["eligibility"]["has_explicit_fix_history"]
            ),
            "without_bug_triggering_program": sum(
                1 for record in records if not record["eligibility"]["has_bug_triggering_program"]
            ),
            "without_explicit_fix_history": sum(
                1 for record in records if not record["eligibility"]["has_explicit_fix_history"]
            ),
        },
        "policy": {
            "all_archived_reports_are_prepared": True,
            "reports_without_poc_are_sent_to_extract_llm": True,
            "api_key_persisted": False,
        },
    }
    write_json(output_dir / "prepare-manifest.json", manifest)
    return manifest


def compact_text_field(value: Any, max_chars: int) -> Tuple[str, bool]:
    return clip_text(str(value or ""), max_chars)


def compact_bug_comments(
    comments: List[Dict[str, Any]],
    fix_history: Dict[str, Any],
    max_comments: int,
    max_chars: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fix_counts = {
        item.get("count")
        for item in (fix_history.get("evidence") or [])
        if isinstance(item, dict) and item.get("kind") == "bugzilla_comment"
    }
    selected_indices = set()
    for index, comment in enumerate(comments):
        if index < 3 or index >= max(0, len(comments) - 3):
            selected_indices.add(index)
        if comment.get("count") in fix_counts or comment.get("attachment_id") is not None:
            selected_indices.add(index)
    for index in range(len(comments)):
        if len(selected_indices) >= max_comments:
            break
        selected_indices.add(index)

    selected = []
    truncated_count = 0
    for index in sorted(selected_indices)[:max_comments]:
        comment = dict(comments[index])
        text, truncated = compact_text_field(comment.get("text"), max_chars)
        comment["text"] = text
        comment["truncated_for_prompt"] = truncated or bool(comment.get("truncated"))
        if comment["truncated_for_prompt"]:
            truncated_count += 1
        selected.append(comment)
    return selected, {
        "original_comment_count": len(comments),
        "prompt_comment_count": len(selected),
        "omitted_comment_count": max(0, len(comments) - len(selected)),
        "truncated_comment_count": truncated_count,
    }


def compact_fix_history(
    fix_history: Dict[str, Any],
    max_evidence: int,
    max_chars: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    compacted = dict(fix_history)
    evidence = []
    truncated_count = 0
    source = fix_history.get("evidence") or []
    for item in source[:max_evidence]:
        if not isinstance(item, dict):
            continue
        new_item = dict(item)
        if "text" in new_item:
            text, truncated = compact_text_field(new_item.get("text"), max_chars)
            new_item["text"] = text
            new_item["truncated_for_prompt"] = truncated or bool(new_item.get("truncated"))
            if new_item["truncated_for_prompt"]:
                truncated_count += 1
        evidence.append(new_item)
    compacted["evidence"] = evidence
    compacted["prompt_evidence_count"] = len(evidence)
    compacted["omitted_evidence_count"] = max(0, len(source) - len(evidence))
    return compacted, {
        "original_fix_evidence_count": len(source),
        "prompt_fix_evidence_count": len(evidence),
        "omitted_fix_evidence_count": max(0, len(source) - len(evidence)),
        "truncated_fix_evidence_count": truncated_count,
    }


def compact_programs(
    programs: List[Dict[str, Any]],
    max_programs: int,
    max_program_chars: int,
    total_program_chars: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    selected = []
    truncated_count = 0
    remaining_total = total_program_chars
    selected_programs = programs[:max_programs]
    for index, program in enumerate(selected_programs):
        new_program = dict(program)
        remaining_slots = max(1, len(selected_programs) - index)
        per_program_budget = max(1000, min(max_program_chars, remaining_total // remaining_slots))
        content, truncated = compact_text_field(new_program.get("content"), per_program_budget)
        remaining_total = max(0, remaining_total - len(content))
        new_program["content"] = content
        new_program["truncated_for_prompt"] = truncated or bool(new_program.get("truncated"))
        if new_program["truncated_for_prompt"]:
            truncated_count += 1
        selected.append(new_program)
    return selected, {
        "original_program_count": len(programs),
        "prompt_program_count": len(selected),
        "omitted_program_count": max(0, len(programs) - len(selected)),
        "truncated_program_count": truncated_count,
    }


def compact_record_once(
    input_record: Dict[str, Any],
    max_comments: int,
    max_comment_chars: int,
    max_fix_evidence: int,
    max_fix_chars: int,
    max_programs: int,
    max_program_chars: int,
    total_program_chars: int,
    max_prompt_chars: int,
) -> Dict[str, Any]:
    record = json.loads(json.dumps(input_record, ensure_ascii=False))
    comments, comment_meta = compact_bug_comments(
        record.get("bug_report", {}).get("comments") or [],
        record.get("fix_history") or {},
        max_comments=max_comments,
        max_chars=max_comment_chars,
    )
    fix_history, fix_meta = compact_fix_history(
        record.get("fix_history") or {},
        max_evidence=max_fix_evidence,
        max_chars=max_fix_chars,
    )
    programs, program_meta = compact_programs(
        record.get("bug_triggering_programs") or [],
        max_programs=max_programs,
        max_program_chars=max_program_chars,
        total_program_chars=total_program_chars,
    )
    record.setdefault("bug_report", {})["comments"] = comments
    record["fix_history"] = fix_history
    record["bug_triggering_programs"] = programs
    record["prompt_compaction"] = {
        "enabled": True,
        "max_prompt_chars": max_prompt_chars,
        **comment_meta,
        **fix_meta,
        **program_meta,
    }
    return record


def compact_record_for_prompt(
    input_record: Dict[str, Any],
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
) -> Dict[str, Any]:
    if max_prompt_chars <= 0:
        record = json.loads(json.dumps(input_record, ensure_ascii=False))
        record["prompt_compaction"] = {"enabled": False, "reason": "disabled"}
        return record

    original_size = len(json.dumps(input_record, ensure_ascii=False, sort_keys=True))
    if original_size <= max_prompt_chars:
        record = json.loads(json.dumps(input_record, ensure_ascii=False))
        record["prompt_compaction"] = {
            "enabled": False,
            "original_chars": original_size,
            "max_prompt_chars": max_prompt_chars,
        }
        return record

    configs = [
        (12, 8000, 8, 12000, 8, 50000, 100000),
        (8, 5000, 6, 8000, 6, 30000, 70000),
        (6, 2500, 5, 5000, 4, 20000, 40000),
        (4, 1500, 4, 3000, 3, 10000, 25000),
        (2, 1000, 3, 2000, 2, 6000, 12000),
    ]
    best = None
    best_size = 0
    for config in configs:
        candidate = compact_record_once(input_record, *config, max_prompt_chars=max_prompt_chars)
        size = len(json.dumps(candidate, ensure_ascii=False, sort_keys=True))
        candidate["prompt_compaction"]["original_chars"] = original_size
        candidate["prompt_compaction"]["prompt_record_chars"] = size
        best = candidate
        best_size = size
        if size <= max_prompt_chars:
            return candidate
    if best is None:
        raise PipelineError("internal error: no compaction candidate produced")
    best["prompt_compaction"]["still_over_budget"] = best_size > max_prompt_chars
    return best


def build_messages(
    input_record: Dict[str, Any],
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
) -> List[Dict[str, str]]:
    system_prompt = (
        "You are ExtractLLM, a compiler quality-testing feature extractor. "
        "Your task is not vulnerability discovery and not offensive security. "
        "Use the provided GCC Bugzilla report, bug-triggering program(s), and fix-history evidence "
        "to extract reusable compiler-test features.\n\n"
        "A Feature is a pair: (1) a natural-language description of a high-level semantic invariant, "
        "and (2) a code witness showing how that invariant is implemented. "
        "The description must be general enough to combine with other features later, while the "
        "code witness must be concrete enough to guide C/C++/Fortran/assembly testcase mutation.\n\n"
        "Return a single JSON object only. Do not include Markdown. Do not invent missing root causes. "
        "A single bug should normally be decomposed into multiple independent, reusable features. "
        "Do not collapse a bug into one root-cause feature. Split it across semantic invariants, "
        "program shapes, target/ABI/ISA conditions, pass interactions, failure oracles, and mutation knobs. "
        "Aim for at least 2 features for every compiler-quality bug, and 3 to 8 features when the report "
        "has a PoC, testcase, fix history, or enough technical discussion. Use 0 features only for reports "
        "that are truly not useful for compiler test generation, such as pure documentation edits with no "
        "testable behavior. If exact PoC code is absent, produce lower-confidence feature seeds with a "
        "small schematic witness derived from the report and mark witness_kind as synthetic_from_report."
    )
    output_contract = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "bug_id": input_record["bug_id"],
        "extraction_status": "ok | insufficient_evidence",
        "root_cause_summary": "one or two sentences grounded in fix_history; empty if unavailable",
        "evidence_gaps": ["missing or weak evidence items"],
        "features": [
            {
                "feature_id": "F1",
                "feature_type": (
                    "semantic_invariant | code_shape | target_condition | pass_interaction | "
                    "failure_oracle | mutation_knob"
                ),
                "description": "high-level semantic invariant, not tied to exact variable names",
                "code_witness": "short code snippet copied or minimized from the PoC/report",
                "witness_kind": "exact_poc | minimized_from_poc | report_snippet | synthetic_from_report",
                "evidence_strength": "strong | medium | weak",
                "language": "c | c++ | fortran | asm | unknown",
                "compiler_area": "target | vectorizer | optimizer | frontend | rtl | ira | reload | other",
                "failure_mode": "ICE | wrong-code | rejects-valid | accepts-invalid | sanitizer | build-failure | other",
                "target_options": ["compiler options or target features if relevant"],
                "mutation_knobs": ["small, local changes that can be varied when generating new PoCs"],
                "composition_tags": ["tags useful for recombining this feature with other features"],
                "root_cause_link": "how this feature connects to the fix-history root cause",
                "source_program_ids": ["bug-...-poc-001"],
                "source_comment_numbers": [0],
                "confidence": 0.0,
            }
        ],
        "notes": "brief extraction notes",
    }
    prompt_record = compact_record_for_prompt(input_record, max_prompt_chars=max_prompt_chars)
    user_prompt = (
        "Extract all useful feature objects from this archived GCC bug. Keep the quality-testing "
        "boundary explicit: we will use the features to generate compiler CI regression tests for "
        "our own GCC fork. One bug can and often should yield multiple features. Decompose the bug "
        "aggressively into reusable feature atoms for later recombination into new PoCs. Prefer multiple "
        "small features over one broad summary feature. For a normal compiler-quality report, return at "
        "least 2 features; if you return fewer than 2, explain the concrete reason in evidence_gaps.\n\n"
        "Use these decomposition axes when evidence allows:\n"
        "1. semantic_invariant: source-level behavior that must be preserved;\n"
        "2. code_shape: syntax/control/data-flow shape that helps trigger the compiler path;\n"
        "3. target_condition: LoongArch/ABI/ISA/vector/option precondition;\n"
        "4. pass_interaction: optimizer, RTL, reload, register allocation, vectorizer, or frontend interaction;\n"
        "5. failure_oracle: how CI can tell the generated test is interesting, such as ICE, wrong-code, warning, or missed optimization;\n"
        "6. mutation_knob: values, types, attributes, vector widths, immediates, loop bounds, or builtin arguments worth varying.\n\n"
        "If no exact PoC exists, still try to extract feature seeds from the report and fix history. The "
        "code_witness may be a small schematic C/C++/Fortran/asm snippet, but mark witness_kind as "
        "synthetic_from_report and set evidence_strength/confidence accordingly.\n\n"
        "Required output JSON shape:\n"
        f"{json.dumps(output_contract, ensure_ascii=False, indent=2)}\n\n"
        "Input bug record:\n"
        f"{json.dumps(prompt_record, ensure_ascii=False, indent=2, sort_keys=True)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def parse_json_content(content: str) -> Dict[str, Any]:
    content = content.strip()
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        fence = CODE_FENCE_RE.search(content)
        if fence:
            value = json.loads(fence.group(1))
        else:
            start = content.find("{")
            end = content.rfind("}")
            if start < 0 or end <= start:
                raise
            value = json.loads(content[start : end + 1])
    if not isinstance(value, dict):
        raise PipelineError("LLM returned JSON but not an object")
    return value


def call_deepseek_chat(
    api_key: str,
    messages: List[Dict[str, str]],
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_MODEL_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 0.0,
    response_format: bool = True,
) -> Dict[str, Any]:
    if not api_key:
        raise PipelineError("DeepSeek API key is empty")
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        body["response_format"] = {"type": "json_object"}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "loongarch-gcc-extract-llm/0.1 quality-testing",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body_text = error.read().decode("utf-8", errors="replace")
        raise PipelineError(f"DeepSeek HTTP {error.code}: {body_text[:800]}") from error
    except urllib.error.URLError as error:
        raise PipelineError(f"DeepSeek request failed: {error}") from error


def normalize_feature_output(
    input_record: Dict[str, Any],
    response: Dict[str, Any],
    raw_response: Dict[str, Any],
    model: str,
    base_url: str,
) -> Dict[str, Any]:
    choices = raw_response.get("choices") or []
    if not choices:
        raise PipelineError("DeepSeek response did not include choices")
    message = choices[0].get("message") or {}
    content = str(message.get("content") or "")
    if not content.strip():
        raise PipelineError("DeepSeek response content was empty")
    parsed = parse_json_content(content)
    parsed["schema_version"] = int(parsed.get("schema_version") or FEATURE_SCHEMA_VERSION)
    parsed["bug_id"] = int(parsed.get("bug_id") or input_record["bug_id"])
    if parsed["bug_id"] != int(input_record["bug_id"]):
        raise PipelineError(f"LLM returned wrong bug_id: {parsed['bug_id']} != {input_record['bug_id']}")
    parsed.setdefault("source_url", input_record.get("source_url"))
    parsed.setdefault("input_sha256", input_record.get("input_sha256"))
    parsed.setdefault("extraction_status", "ok")
    parsed.setdefault("root_cause_summary", "")
    parsed.setdefault("evidence_gaps", [])
    parsed.setdefault("features", [])
    if not isinstance(parsed["features"], list):
        raise PipelineError("LLM returned non-list features")
    if parsed["features"] and parsed.get("extraction_status") == "insufficient_evidence":
        parsed["extraction_status"] = "ok"
        parsed["notes"] = (
            str(parsed.get("notes") or "").strip()
            + "\nStatus normalized to ok because feature objects were extracted; evidence limits remain in evidence_gaps."
        ).strip()
    if not parsed["features"] and parsed.get("extraction_status") == "ok":
        parsed["extraction_status"] = "insufficient_evidence"
        gaps = parsed.get("evidence_gaps")
        if isinstance(gaps, list) and "no_features_extracted" not in gaps:
            gaps.append("no_features_extracted")
    for index, feature in enumerate(parsed["features"], start=1):
        if not isinstance(feature, dict):
            raise PipelineError(f"feature {index} is not an object")
        feature["feature_id"] = str(feature.get("feature_id") or f"F{index}")
        feature["feature_type"] = str(feature.get("feature_type") or "semantic_invariant")
        feature["description"] = str(feature.get("description") or "")
        feature["code_witness"] = str(feature.get("code_witness") or "")
        feature["witness_kind"] = str(feature.get("witness_kind") or "exact_poc")
        feature["evidence_strength"] = str(feature.get("evidence_strength") or "medium")
        if not isinstance(feature.get("mutation_knobs"), list):
            feature["mutation_knobs"] = []
        if not isinstance(feature.get("composition_tags"), list):
            feature["composition_tags"] = []
        if not isinstance(feature.get("source_program_ids"), list):
            feature["source_program_ids"] = []
        if not isinstance(feature.get("source_comment_numbers"), list):
            feature["source_comment_numbers"] = []
        feature.setdefault("confidence", 0.0)
    parsed["generated_by"] = {
        "tool": "extract-llm",
        "mode": "deepseek_chat_completions",
        "model": model,
        "base_url": base_url,
        "created_at": utc_now(),
        "usage": raw_response.get("usage") or {},
        "response_id": raw_response.get("id"),
    }
    return parsed


def feature_output_path(output_dir: Path, bug_id: int) -> Path:
    return output_dir / "features" / f"bug-{bug_id}.features.json"


def raw_response_path(output_dir: Path, bug_id: int) -> Path:
    return output_dir / "raw-responses" / f"bug-{bug_id}.deepseek-response.json"


def run_extraction(
    output_dir: Path,
    inputs_file: Optional[Path] = None,
    api_key: Optional[str] = None,
    api_key_env: str = "DEEPSEEK_API_KEY",
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    limit: int = 0,
    bug_ids: Optional[Sequence[int]] = None,
    refresh: bool = False,
    delay_seconds: float = 0.2,
    retries: int = 3,
    timeout: float = DEFAULT_MODEL_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    temperature: float = 0.0,
    keep_going: bool = False,
    response_format: bool = True,
) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    inputs_path = inputs_file.resolve() if inputs_file else output_dir / DEFAULT_INPUTS_FILE
    if not inputs_path.is_file():
        raise PipelineError(f"inputs file does not exist: {inputs_path}")
    wanted = set(int(value) for value in bug_ids) if bug_ids else None
    key = api_key if api_key is not None else os.environ.get(api_key_env, "")
    records = list(iter_jsonl(inputs_path))
    attempted = 0
    skipped_existing = 0
    api_success = 0
    api_errors = 0
    parse_errors = 0
    errors: List[Dict[str, Any]] = []

    for record in records:
        bug_id = int(record["bug_id"])
        if wanted is not None and bug_id not in wanted:
            continue
        out_path = feature_output_path(output_dir, bug_id)
        if out_path.is_file() and not refresh:
            skipped_existing += 1
            continue
        if limit and attempted >= limit:
            break
        attempted += 1

        messages = build_messages(record, max_prompt_chars=max_prompt_chars)
        raw_response: Optional[Dict[str, Any]] = None
        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                raw_response = call_deepseek_chat(
                    api_key=key,
                    messages=messages,
                    base_url=base_url,
                    model=model,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format=response_format,
                )
                break
            except Exception as error:  # noqa: BLE001 - persisted in structured run output.
                last_error = error
                if attempt < retries:
                    time.sleep(min(20.0, 1.5 * attempt * attempt))
        if raw_response is None:
            api_errors += 1
            error_record = {
                "bug_id": bug_id,
                "error": str(last_error),
                "created_at": utc_now(),
            }
            errors.append(error_record)
            if keep_going:
                write_json(
                    out_path,
                    {
                        "schema_version": FEATURE_SCHEMA_VERSION,
                        "bug_id": bug_id,
                        "source_url": record.get("source_url"),
                        "input_sha256": record.get("input_sha256"),
                        "extraction_status": "api_error",
                        "root_cause_summary": "",
                        "evidence_gaps": ["api_error"],
                        "features": [],
                        "notes": str(last_error),
                        "generated_by": {
                            "tool": "extract-llm",
                            "mode": "deepseek_chat_completions",
                            "model": model,
                            "base_url": base_url,
                            "created_at": utc_now(),
                        },
                    },
                )
                continue
            raise PipelineError(f"bug {bug_id}: {last_error}") from last_error

        write_json(raw_response_path(output_dir, bug_id), raw_response)
        try:
            normalized = normalize_feature_output(record, {}, raw_response, model, base_url)
            write_json(out_path, normalized)
            api_success += 1
        except Exception as error:  # noqa: BLE001 - persisted in structured run output.
            parse_errors += 1
            errors.append({"bug_id": bug_id, "error": str(error), "created_at": utc_now()})
            if keep_going:
                write_json(
                    out_path,
                    {
                        "schema_version": FEATURE_SCHEMA_VERSION,
                        "bug_id": bug_id,
                        "source_url": record.get("source_url"),
                        "input_sha256": record.get("input_sha256"),
                        "extraction_status": "parse_error",
                        "root_cause_summary": "",
                        "evidence_gaps": ["parse_error"],
                        "features": [],
                        "notes": str(error),
                        "generated_by": {
                            "tool": "extract-llm",
                            "mode": "deepseek_chat_completions",
                            "model": model,
                            "base_url": base_url,
                            "created_at": utc_now(),
                            "usage": raw_response.get("usage") or {},
                            "response_id": raw_response.get("id"),
                        },
                    },
                )
                continue
            raise
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    manifest = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "inputs_file": str(inputs_path),
        "output_dir": str(output_dir),
        "model": model,
        "base_url": base_url,
        "max_prompt_chars": max_prompt_chars,
        "counts": {
            "input_records": len(records),
            "attempted_this_run": attempted,
            "skipped_existing": skipped_existing,
            "api_success": api_success,
            "api_errors": api_errors,
            "parse_errors": parse_errors,
        },
        "errors": errors,
    }
    write_json(output_dir / "extract-run-manifest.json", manifest)
    return manifest


def load_feature_outputs(output_dir: Path) -> List[Dict[str, Any]]:
    features_dir = output_dir / "features"
    if not features_dir.is_dir():
        return []
    records = []
    for path in sorted(features_dir.glob("bug-*.features.json"), key=report_bug_id_from_path):
        record = read_json(path)
        record["_path"] = str(path)
        records.append(record)
    return records


def feature_pool_record(feature_output: Dict[str, Any], feature: Dict[str, Any]) -> Dict[str, Any]:
    bug_id = int(feature_output["bug_id"])
    fingerprint = stable_hash(
        {
            "bug_id": bug_id,
            "feature_id": feature.get("feature_id"),
            "description": feature.get("description"),
            "code_witness": feature.get("code_witness"),
        }
    )
    normalized_feature = dict(feature)
    normalized_feature["feature_id"] = feature.get("feature_id")
    normalized_feature["description"] = str(feature.get("description") or "")
    normalized_feature["code_witness"] = str(feature.get("code_witness") or "")
    normalized_feature["language"] = str(feature.get("language") or "unknown")
    normalized_feature["compiler_area"] = str(feature.get("compiler_area") or "other")
    normalized_feature["failure_mode"] = str(feature.get("failure_mode") or "other")
    normalized_feature["target_options"] = (
        feature.get("target_options") if isinstance(feature.get("target_options"), list) else []
    )
    normalized_feature["root_cause_link"] = str(feature.get("root_cause_link") or "")
    normalized_feature["source_program_ids"] = (
        feature.get("source_program_ids") if isinstance(feature.get("source_program_ids"), list) else []
    )
    normalized_feature["source_comment_numbers"] = (
        feature.get("source_comment_numbers") if isinstance(feature.get("source_comment_numbers"), list) else []
    )
    normalized_feature["confidence"] = feature.get("confidence")
    normalized_feature["feature_type"] = str(feature.get("feature_type") or "semantic_invariant")
    normalized_feature["witness_kind"] = str(feature.get("witness_kind") or "exact_poc")
    normalized_feature["evidence_strength"] = str(feature.get("evidence_strength") or "medium")
    normalized_feature["mutation_knobs"] = (
        feature.get("mutation_knobs") if isinstance(feature.get("mutation_knobs"), list) else []
    )
    normalized_feature["composition_tags"] = (
        feature.get("composition_tags") if isinstance(feature.get("composition_tags"), list) else []
    )
    return {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "feature_uid": f"bug-{bug_id}-{feature.get('feature_id', 'F')}-{fingerprint}",
        "bug_id": bug_id,
        "source_url": feature_output.get("source_url"),
        "input_sha256": feature_output.get("input_sha256"),
        "root_cause_summary": feature_output.get("root_cause_summary") or "",
        "feature": normalized_feature,
        "generated_by": feature_output.get("generated_by") or {},
    }


def build_feature_pool(output_dir: Path) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    outputs = load_feature_outputs(output_dir)
    pool = []
    statuses: Dict[str, int] = {}
    for output in outputs:
        status = str(output.get("extraction_status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        for feature in output.get("features") or []:
            if isinstance(feature, dict):
                pool.append(feature_pool_record(output, feature))

    pool_path = output_dir / "feature-pool.jsonl"
    write_jsonl(pool_path, pool)
    write_json(
        output_dir / "feature-pool.json",
        {
            "schema_version": FEATURE_SCHEMA_VERSION,
            "generated_at": utc_now(),
            "feature_pool_jsonl": str(pool_path),
            "counts": {
                "feature_outputs": len(outputs),
                "features": len(pool),
                "statuses": statuses,
            },
            "features": pool,
        },
    )

    by_area: Dict[str, int] = {}
    by_feature_type: Dict[str, int] = {}
    by_witness_kind: Dict[str, int] = {}
    by_evidence_strength: Dict[str, int] = {}
    by_language: Dict[str, int] = {}
    by_failure_mode: Dict[str, int] = {}
    for record in pool:
        feature = record["feature"]
        by_area[feature["compiler_area"]] = by_area.get(feature["compiler_area"], 0) + 1
        by_feature_type[feature["feature_type"]] = by_feature_type.get(feature["feature_type"], 0) + 1
        by_witness_kind[feature["witness_kind"]] = by_witness_kind.get(feature["witness_kind"], 0) + 1
        by_evidence_strength[feature["evidence_strength"]] = (
            by_evidence_strength.get(feature["evidence_strength"], 0) + 1
        )
        by_language[feature["language"]] = by_language.get(feature["language"], 0) + 1
        by_failure_mode[feature["failure_mode"]] = by_failure_mode.get(feature["failure_mode"], 0) + 1

    summary = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "counts": {
            "feature_outputs": len(outputs),
            "features": len(pool),
            "statuses": statuses,
            "by_compiler_area": by_area,
            "by_feature_type": by_feature_type,
            "by_witness_kind": by_witness_kind,
            "by_evidence_strength": by_evidence_strength,
            "by_language": by_language,
            "by_failure_mode": by_failure_mode,
        },
    }
    write_json(output_dir / "feature-pool-manifest.json", summary)
    write_feature_pool_summary(output_dir / "FEATURE_POOL_SUMMARY.md", summary)
    return summary


def write_feature_pool_summary(path: Path, summary: Dict[str, Any]) -> None:
    counts = summary["counts"]
    lines = [
        "# ExtractLLM Feature Pool Summary",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Feature output files: {counts['feature_outputs']}",
        f"- Features: {counts['features']}",
        "",
        "## Extraction Status",
        "",
    ]
    for key, value in sorted(counts["statuses"].items()):
        lines.append(f"- {key}: {value}")
    for title, field in [
        ("Compiler Area", "by_compiler_area"),
        ("Feature Type", "by_feature_type"),
        ("Witness Kind", "by_witness_kind"),
        ("Evidence Strength", "by_evidence_strength"),
        ("Language", "by_language"),
        ("Failure Mode", "by_failure_mode"),
    ]:
        lines.extend(["", f"## {title}", ""])
        for key, value in sorted(counts[field].items()):
            lines.append(f"- {key}: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_outputs(
    output_dir: Path,
    require_outputs: bool = False,
    fail_on_api_error: bool = False,
) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    inputs_path = output_dir / DEFAULT_INPUTS_FILE
    if not inputs_path.is_file():
        raise PipelineError(f"inputs file does not exist: {inputs_path}")
    inputs = list(iter_jsonl(inputs_path))
    outputs = load_feature_outputs(output_dir)
    output_by_bug = {int(record["bug_id"]): record for record in outputs}
    missing = [record["bug_id"] for record in inputs if int(record["bug_id"]) not in output_by_bug]
    statuses: Dict[str, int] = {}
    feature_count = 0
    errors = []
    for bug_id, output in sorted(output_by_bug.items()):
        status = str(output.get("extraction_status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        features = output.get("features")
        if not isinstance(features, list):
            errors.append({"bug_id": bug_id, "error": "features is not a list"})
            continue
        feature_count += len(features)
        for index, feature in enumerate(features, start=1):
            if not isinstance(feature, dict):
                errors.append({"bug_id": bug_id, "error": f"feature {index} is not an object"})
                continue
            if not str(feature.get("description") or "").strip():
                errors.append({"bug_id": bug_id, "error": f"feature {index} missing description"})
            if not str(feature.get("code_witness") or "").strip():
                errors.append({"bug_id": bug_id, "error": f"feature {index} missing code_witness"})

    pool_jsonl = output_dir / "feature-pool.jsonl"
    pool_count = sum(1 for _ in iter_jsonl(pool_jsonl)) if pool_jsonl.is_file() else 0
    if pool_jsonl.is_file() and pool_count != feature_count:
        errors.append(
            {
                "error": f"feature pool count {pool_count} does not equal extracted feature count {feature_count}"
            }
        )

    if require_outputs and missing:
        errors.append({"error": f"missing feature outputs for {len(missing)} bugs", "bug_ids": missing[:50]})
    if fail_on_api_error:
        for bad_status in ("api_error", "parse_error"):
            if statuses.get(bad_status):
                errors.append({"error": f"{bad_status} outputs present", "count": statuses[bad_status]})

    result = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "verified_at": utc_now(),
        "counts": {
            "input_records": len(inputs),
            "feature_outputs": len(outputs),
            "missing_feature_outputs": len(missing),
            "features": feature_count,
            "feature_pool_records": pool_count,
            "statuses": statuses,
        },
        "missing_bug_ids": missing,
        "errors": errors,
    }
    if errors:
        raise PipelineError(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return result
