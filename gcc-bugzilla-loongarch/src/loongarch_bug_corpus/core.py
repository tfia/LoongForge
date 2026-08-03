"""Fetch, normalize, archive, and verify LoongArch GCC Bugzilla reports."""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = 3
DEFAULT_BASE_URL = "https://gcc.gnu.org/bugzilla/rest.cgi"
DEFAULT_WEB_URL = "https://gcc.gnu.org/bugzilla/show_bug.cgi?id={bug_id}"
DEFAULT_USER_AGENT = (
    "loongarch-gcc-quality-corpus/0.1 "
    "(public compiler quality and CI corpus builder)"
)

ARCH_RE = re.compile(r"(?<![A-Za-z0-9_])loongarch(?:64|32)?(?![A-Za-z0-9_])", re.I)
OTHER_ARCH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:x86_64|i[3-6]86|aarch64|arm(?:64)?|mips|"
    r"powerpc|ppc(?:64)?|riscv|s390x?|sparc|alpha|ia64|hppa|m68k|"
    r"nvptx|amdgcn|bpf|sh[0-9]?)(?![A-Za-z0-9_])",
    re.I,
)

SEARCH_FIELDS = [
    "id",
    "summary",
    "status",
    "resolution",
    "severity",
    "priority",
    "component",
    "product",
    "version",
    "target_milestone",
    "creation_time",
    "last_change_time",
    "cf_gcctarget",
    "cf_gcchost",
    "cf_gccbuild",
    "cf_known_to_fail",
    "cf_known_to_work",
    "keywords",
    "blocks",
    "depends_on",
    "dupe_of",
    "see_also",
    "creator",
    "assigned_to",
    "whiteboard",
    "url",
]

SOURCE_SUFFIXES = {
    ".c": "c",
    ".i": "c-preprocessed",
    ".h": "c-header",
    ".cc": "c++",
    ".cp": "c++",
    ".cpp": "c++",
    ".cxx": "c++",
    ".c++": "c++",
    ".ii": "c++-preprocessed",
    ".f": "fortran",
    ".f90": "fortran",
    ".f95": "fortran",
    ".f03": "fortran",
    ".f08": "fortran",
    ".s": "assembly",
    ".asm": "assembly",
    ".rs": "rust",
    ".m": "objective-c",
    ".mm": "objective-c++",
}

CODE_MIME_LANGUAGES = {
    "text/x-csrc": "c",
    "text/x-c++src": "c++",
    "text/x-c++": "c++",
    "text/x-fortran": "fortran",
    "text/x-asm": "assembly",
}

REPRO_WORD_RE = re.compile(
    r"\b(?:test[ -]?case|reproducer|reduced|preprocessed source|compile with|"
    r"command line|causes? (?:an )?ice|internal compiler error)\b",
    re.I,
)
FENCED_RE = re.compile(r"```\s*([A-Za-z0-9_+.-]*)\s*\n(.*?)```", re.S)
LOONGARCH64_EVIDENCE_RE = re.compile(
    r"loongarch64|longarch64|elf64-loongarch|(?:^|[^A-Za-z0-9_])la64(?:[^A-Za-z0-9_]|$)|"
    r"(?:^|[^A-Za-z0-9_])la(?:464|664)(?:[^A-Za-z0-9_]|$)|"
    r"(?:^|[^A-Za-z0-9_])lp64[dfs]?(?:[^A-Za-z0-9_]|$)|"
    r"-m(?:lsx|lasx)|(?:^|[^A-Za-z0-9_])(?:lsx|lasx)(?:[^A-Za-z0-9_]|$)",
    re.I | re.M,
)
LOONGARCH32_EVIDENCE_RE = re.compile(
    r"loongarch32|(?:^|[^A-Za-z0-9_])la32(?:[^A-Za-z0-9_]|$)|"
    r"(?:^|[^A-Za-z0-9_])ilp32[dfs]?(?:[^A-Za-z0-9_]|$)",
    re.I | re.M,
)
NON_BUG_RESOLUTIONS = {"INVALID", "MOVED"}
FAILURE_CONTEXT_RE = re.compile(
    r"\b(?:ice|internal compiler error|wrong code|miscompil(?:e|ation)|fails?|failure|"
    r"hang|crash|segfault|unrecognizable|missed optimization|reproducer|timeout|abort)\b",
    re.I,
)
VALIDATION_CONTEXT_RE = re.compile(
    r"\b(?:bootstrapped|regtested|tested|test results?|passes? on|verified)\b",
    re.I,
)
ARCH_VALIDATION_RE = re.compile(
    r"(?:bootstrapped(?:\s+and)?|regression\s+tested|regtested|tested|verified)"
    r"[^.\n]{0,240}(?:loongarch(?:64)?|(?:-m)?(?:lsx|lasx))|"
    r"(?:loongarch(?:64)?|(?:-m)?(?:lsx|lasx))[^.\n]{0,160}"
    r"(?:bootstrapped|regression\s+tested|regtested|tested|verified)",
    re.I,
)
VECTOR_EXTENSION_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:-m)?(?:lsx|lasx)(?![A-Za-z0-9_])|__(?:lsx|lasx)_",
    re.I,
)
LSX_RE = re.compile(r"(?<![A-Za-z0-9_])(?:-m)?lsx(?![A-Za-z0-9_])|__lsx_", re.I)
LASX_RE = re.compile(r"(?<![A-Za-z0-9_])(?:-m)?lasx(?![A-Za-z0-9_])|__lasx_", re.I)
BROAD_VECTOR_RE = re.compile(
    r"\b(?:vectoriz(?:e|ed|es|ing|ation)?|vector|simd)\b|"
    r"(?:^|[/_.-])vect(?:[/_.-]|$)|\bvec_",
    re.I | re.M,
)
COMMENT_FAILURE_CONTEXT_RADIUS = 320


class CorpusError(RuntimeError):
    """Raised for a corpus build or verification failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def write_text_atomic(path: Path, text: str) -> None:
    write_bytes_atomic(path, text.encode("utf-8"))


def write_json_atomic(path: Path, value: Any) -> None:
    write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def safe_filename(name: str, fallback: str = "artifact") -> str:
    cleaned = name.replace("\\", "_").replace("/", "_").replace("\x00", "_")
    cleaned = re.sub(r"[^A-Za-z0-9._+-]+", "_", cleaned).strip("._")
    return cleaned[:160] or fallback


def language_for(name: str, content_type: str = "", hint: str = "") -> str:
    if Path(name).suffix == ".C":
        return "c++"
    suffix = Path(name.lower()).suffix
    if suffix in SOURCE_SUFFIXES:
        return SOURCE_SUFFIXES[suffix]
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in CODE_MIME_LANGUAGES:
        return CODE_MIME_LANGUAGES[mime]
    normalized_hint = hint.strip().lower()
    if normalized_hint in {"c", "cpp", "c++", "cc", "fortran", "asm", "assembly", "rust"}:
        return {"cpp": "c++", "cc": "c++", "asm": "assembly"}.get(normalized_hint, normalized_hint)
    return "unknown"


def extension_for_language(language: str) -> str:
    return {
        "c": ".c",
        "c-preprocessed": ".i",
        "c++": ".cc",
        "c++-preprocessed": ".ii",
        "fortran": ".f90",
        "assembly": ".s",
        "rust": ".rs",
        "objective-c": ".m",
        "objective-c++": ".mm",
    }.get(language, ".txt")


def language_for_content(content: str) -> str:
    lowered = content.lower()
    if re.search(r"\b(?:g\+\+|cc1plus)\b", content) or re.search(
        r"\b(?:std::|template\s*<|namespace\s+[A-Za-z_]|class\s+[A-Za-z_])", content
    ):
        return "c++"
    if re.search(r"\b(?:program|subroutine|integer\s*::|real\s*::)\b", lowered):
        return "fortran"
    if re.search(r"\b(?:gcc|cc1)\b", content) or re.search(
        r"(?:#\s*include|\b(?:int|void|struct|enum)\s+[A-Za-z_]|__attribute__)", content
    ):
        return "c"
    if re.search(r"\b(?:\.text|\.globl|addi\.d|ld\.d|st\.d)\b", lowered):
        return "assembly"
    return "unknown"


def classify_relevance(summary: str, target: str) -> Dict[str, Any]:
    summary_hits = [match.group(0) for match in ARCH_RE.finditer(summary or "")]
    target_hits = [match.group(0) for match in ARCH_RE.finditer(target or "")]
    other_target_arches = sorted({match.group(0).lower() for match in OTHER_ARCH_RE.finditer(target or "")})

    if summary_hits:
        tier = "architecture_specific"
        reason = "summary_mentions_loongarch"
    elif target_hits and not other_target_arches:
        tier = "architecture_specific"
        reason = "gcc_target_is_loongarch"
    elif target_hits:
        tier = "multi_arch_shared"
        reason = "gcc_target_includes_loongarch_and_other_architectures"
    else:
        tier = "not_loongarch"
        reason = "no_summary_or_target_evidence"

    return {
        "tier": tier,
        "reason": reason,
        "summary_matches": summary_hits,
        "target_matches": target_hits,
        "other_target_architectures": other_target_arches,
    }


def classify_full_relevance(
    metadata: Dict[str, Any],
    comments: Sequence[Dict[str, Any]],
    local_tests: Sequence[Path],
    discovery_sources: Sequence[str],
) -> Dict[str, Any]:
    relevance = classify_relevance(
        str(metadata.get("summary") or ""), str(metadata.get("cf_gcctarget") or "")
    )
    relevance["discovery_sources"] = sorted(set(discovery_sources))
    if relevance["tier"] != "not_loongarch":
        return relevance

    if local_tests:
        relevance.update(
            {
                "tier": "loongarch_testsuite_linked",
                "reason": "gcc_loongarch_testsuite_links_pr",
                "testsuite_paths": [str(path) for path in local_tests],
            }
        )
        return relevance

    architecture_comments = []
    failure_comments = []
    validation_comments = []
    for comment in comments:
        text = str(comment.get("text") or "")
        architecture_matches = list(ARCH_RE.finditer(text)) + list(VECTOR_EXTENSION_RE.finditer(text))
        if not architecture_matches:
            continue
        count = int(comment.get("count") or 0)
        architecture_comments.append(count)
        # A bug comment can contain a failure for one target and mention LoongArch
        # only in a target list or a later "regression tested on" footer.  Require
        # the failure vocabulary to occur near the architecture evidence instead
        # of combining unrelated parts of a long comment.
        validation_spans = [match.span() for match in ARCH_VALIDATION_RE.finditer(text)]
        failure_architecture_matches = [
            match
            for match in architecture_matches
            if not any(start <= match.start() < end for start, end in validation_spans)
        ]
        reports_arch_failure = any(
            FAILURE_CONTEXT_RE.search(
                text[
                    max(0, match.start() - COMMENT_FAILURE_CONTEXT_RADIUS) :
                    min(len(text), match.end() + COMMENT_FAILURE_CONTEXT_RADIUS)
                ]
            )
            for match in failure_architecture_matches
        )
        if reports_arch_failure:
            failure_comments.append(count)
        elif VALIDATION_CONTEXT_RE.search(text):
            validation_comments.append(count)

    if failure_comments:
        relevance.update(
            {
                "tier": "loongarch_observed",
                "reason": "public_comment_reports_loongarch_failure_or_reproducer",
                "evidence_comment_numbers": sorted(set(failure_comments)),
            }
        )
    elif architecture_comments:
        relevance.update(
            {
                "tier": "loongarch_validation_only",
                "reason": "loongarch_only_appears_in_validation_or_discussion",
                "evidence_comment_numbers": sorted(set(architecture_comments)),
                "validation_comment_numbers": sorted(set(validation_comments)),
            }
        )
    return relevance


def classify_architecture_scope(report: Dict[str, Any]) -> Dict[str, Any]:
    metadata = report.get("metadata") or {}
    text_parts = [
        str(metadata.get("summary") or ""),
        str(metadata.get("cf_gcctarget") or ""),
        str(report.get("description") or ""),
    ]
    text_parts.extend(str(comment.get("text") or "") for comment in report.get("comments") or [])
    for testcase in report.get("testcases") or []:
        text_parts.append(json.dumps(testcase.get("provenance") or {}, ensure_ascii=False))
        text_parts.append(str(testcase.get("path") or ""))
    technical_text = "\n".join(text_parts)
    evidence64 = sorted(
        {match.group(0).strip().lower() for match in LOONGARCH64_EVIDENCE_RE.finditer(technical_text)}
    )
    evidence32 = sorted(
        {match.group(0).strip().lower() for match in LOONGARCH32_EVIDENCE_RE.finditer(technical_text)}
    )
    if evidence64 and evidence32:
        scope = "mixed_loongarch32_loongarch64"
    elif evidence64:
        scope = "loongarch64"
    elif evidence32:
        scope = "loongarch32"
    else:
        scope = "loongarch_family_unspecified"
    return {
        "scope": scope,
        "loongarch64_evidence": evidence64,
        "loongarch32_evidence": evidence32,
    }


def finalize_report_quality_fields(report: Dict[str, Any]) -> Dict[str, Any]:
    metadata = report.get("metadata") or {}
    description = str(report.get("description") or "")
    testcases = report.get("testcases") or []
    architecture_scope = classify_architecture_scope(report)
    resolution = str(metadata.get("resolution") or "").upper()
    disposition = {
        "eligible_as_gcc_bug_report": resolution not in NON_BUG_RESOLUTIONS,
        "excluded_resolution": resolution if resolution in NON_BUG_RESOLUTIONS else None,
    }
    exclusion_reasons: List[str] = []
    if (report.get("relevance") or {}).get("tier") != "architecture_specific":
        exclusion_reasons.append("not_architecture_specific")
    if architecture_scope["scope"] != "loongarch64":
        exclusion_reasons.append("no_explicit_loongarch64_evidence")
    if not description.strip():
        exclusion_reasons.append("missing_bug_description")
    if not testcases:
        exclusion_reasons.append("missing_testcase")
    if not disposition["eligible_as_gcc_bug_report"]:
        exclusion_reasons.append(f"resolution_{resolution.lower()}")

    report["schema_version"] = SCHEMA_VERSION
    report["architecture_scope"] = architecture_scope
    report["disposition"] = disposition
    report["has_description"] = bool(description.strip())
    report["has_testcase"] = bool(testcases)
    report["llm_ready_exclusion_reasons"] = exclusion_reasons
    report["llm_ready"] = not exclusion_reasons

    expanded_exclusions: List[str] = []
    expanded_tiers = {
        "architecture_specific",
        "multi_arch_shared",
        "loongarch_testsuite_linked",
        "loongarch_observed",
    }
    if (report.get("relevance") or {}).get("tier") not in expanded_tiers:
        expanded_exclusions.append("no_loongarch_failure_or_testsuite_evidence")
    if architecture_scope["scope"] != "loongarch64":
        expanded_exclusions.append("no_explicit_loongarch64_evidence")
    if not description.strip():
        expanded_exclusions.append("missing_bug_description")
    if not testcases:
        expanded_exclusions.append("missing_testcase")
    if not disposition["eligible_as_gcc_bug_report"]:
        expanded_exclusions.append(f"resolution_{resolution.lower()}")
    report["expanded_llm_ready_exclusion_reasons"] = expanded_exclusions
    report["expanded_llm_ready"] = not expanded_exclusions
    return report


def is_source_attachment(metadata: Dict[str, Any]) -> bool:
    if metadata.get("is_patch"):
        return False
    file_name = str(metadata.get("file_name") or "")
    content_type = str(metadata.get("content_type") or "").split(";", 1)[0].lower()
    summary = str(metadata.get("summary") or "")
    if Path(file_name.lower()).suffix in SOURCE_SUFFIXES:
        return True
    if content_type in CODE_MIME_LANGUAGES:
        return True
    return content_type.startswith("text/") and bool(REPRO_WORD_RE.search(summary))


def extract_comment_testcases(comments: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    extracted: List[Dict[str, Any]] = []
    for comment in comments:
        text = str(comment.get("text") or "").replace("\r\n", "\n")
        count = int(comment.get("count") or 0)
        fenced = list(FENCED_RE.finditer(text))
        for block_number, match in enumerate(fenced, start=1):
            code = match.group(2).strip() + "\n"
            if len(code) < 20:
                continue
            lang = language_for("", hint=match.group(1))
            if lang == "unknown":
                lang = language_for_content(code)
            extracted.append(
                {
                    "kind": "comment_code_block",
                    "comment_number": count,
                    "block_number": block_number,
                    "language": lang,
                    "content": code,
                }
            )

        if fenced or not REPRO_WORD_RE.search(text):
            continue
        has_code = (
            text.count(";") >= 2
            or bool(re.search(r"\b(?:gcc|g\+\+|cc1|cc1plus)\b[^\n]*\s-[A-Za-z0-9]", text))
            or bool(re.search(r"\b(?:int|void|struct|class|enum|template)\s+[A-Za-z_]", text))
        )
        if has_code and len(text) >= 40:
            extracted.append(
                {
                    "kind": "comment_reproducer",
                    "comment_number": count,
                    "block_number": 1,
                    "language": "unknown",
                    "content": text.strip() + "\n",
                }
            )
            extracted[-1]["language"] = language_for_content(text)
    return extracted


def indent_text(text: str) -> str:
    if not text:
        return "    (empty)"
    return "\n".join("    " + line for line in text.replace("\r\n", "\n").split("\n"))


@dataclass
class BugzillaClient:
    base_url: str = DEFAULT_BASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    delay_seconds: float = 0.4
    timeout_seconds: float = 60.0
    retries: int = 4

    def __post_init__(self) -> None:
        self._last_request = 0.0

    def get_json(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = urllib.parse.urlencode(params or {}, doseq=True)
        url = self.base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        if query:
            url += "?" + query

        last_error: Optional[BaseException] = None
        for attempt in range(self.retries):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.delay_seconds:
                time.sleep(self.delay_seconds - elapsed)
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": self.user_agent},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = response.read()
                self._last_request = time.monotonic()
                decoded = json.loads(payload.decode("utf-8"))
                if "error" in decoded:
                    raise CorpusError(f"Bugzilla error for {url}: {decoded.get('message', decoded['error'])}")
                return decoded
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                self._last_request = time.monotonic()
                last_error = error
                retryable = not isinstance(error, urllib.error.HTTPError) or error.code in {
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                if not retryable or attempt + 1 == self.retries:
                    break
                time.sleep(min(8.0, 2.0**attempt))
        raise CorpusError(f"failed to fetch {url}: {last_error}")


def bug_comments(payload: Dict[str, Any], bug_id: int) -> List[Dict[str, Any]]:
    bugs = payload.get("bugs") or {}
    return list((bugs.get(str(bug_id)) or {}).get("comments") or [])


def bug_attachments(payload: Dict[str, Any], bug_id: int) -> List[Dict[str, Any]]:
    bugs = payload.get("bugs") or {}
    return list(bugs.get(str(bug_id)) or [])


def attachment_object(payload: Dict[str, Any], attachment_id: int) -> Dict[str, Any]:
    attachments = payload.get("attachments") or {}
    value = attachments.get(str(attachment_id))
    if not isinstance(value, dict):
        raise CorpusError(f"attachment {attachment_id} missing from Bugzilla response")
    return value


def discover_local_regression_tests(
    gcc_source: Optional[Path], bug_ids: Iterable[int]
) -> Dict[int, List[Path]]:
    wanted = set(bug_ids)
    result: Dict[int, List[Path]] = {bug_id: [] for bug_id in wanted}
    if not gcc_source or not gcc_source.is_dir():
        return result
    roots = [gcc_source / "gcc" / "testsuite", gcc_source / "libstdc++-v3" / "testsuite"]
    pattern = re.compile(r"(?:^|[^0-9])pr([0-9]{4,})(?:[^0-9]|$)", re.I)
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            for match in pattern.finditer(path.name):
                bug_id = int(match.group(1))
                if bug_id in wanted:
                    result[bug_id].append(path)
    return result


def discover_loongarch_target_regression_tests(
    gcc_source: Optional[Path],
) -> Dict[int, List[Path]]:
    result: Dict[int, List[Path]] = {}
    if not gcc_source or not gcc_source.is_dir():
        return result
    roots = [
        gcc_source / "gcc" / "testsuite" / "gcc.target" / "loongarch",
        gcc_source / "gcc" / "testsuite" / "g++.target" / "loongarch",
    ]
    filename_pattern = re.compile(r"(?:^|[^0-9])pr([0-9]{4,})(?:[^0-9]|$)", re.I)
    content_pattern = re.compile(r"\bPR\s+[a-z0-9_+.-]+/([0-9]{4,})", re.I)
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            bug_ids = {int(match.group(1)) for match in filename_pattern.finditer(path.name)}
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            bug_ids.update(int(match.group(1)) for match in content_pattern.finditer(text))
            for bug_id in bug_ids:
                result.setdefault(bug_id, []).append(path)
    return result


def git_revision(gcc_source: Optional[Path]) -> Optional[str]:
    if not gcc_source or not (gcc_source / ".git").exists():
        return None
    process = subprocess.run(
        ["git", "-C", str(gcc_source), "rev-parse", "HEAD"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return process.stdout.strip() or None


def copy_testcase(
    report_dir: Path,
    name: str,
    data: bytes,
    kind: str,
    language: str,
    provenance: Dict[str, Any],
) -> Dict[str, Any]:
    destination = report_dir / "testcases" / safe_filename(name)
    write_bytes_atomic(destination, data)
    return {
        "kind": kind,
        "language": language,
        "path": destination.relative_to(report_dir).as_posix(),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "provenance": provenance,
    }


def render_report_markdown(report: Dict[str, Any]) -> str:
    metadata = report["metadata"]
    lines = [
        f"# GCC Bug {metadata['id']}: {metadata.get('summary', '')}",
        "",
        "> 用途：LoongArch GCC 编译器质量测试语料准备；不属于网络安全测试。",
        "",
        "## Metadata",
        "",
        f"- Bugzilla: {report['source_url']}",
        f"- Status: `{metadata.get('status', '')}` / `{metadata.get('resolution', '')}`",
        f"- Component: `{metadata.get('component', '')}`",
        f"- GCC target: `{metadata.get('cf_gcctarget', '')}`",
        f"- Created: `{metadata.get('creation_time', '')}`",
        f"- Last changed: `{metadata.get('last_change_time', '')}`",
        f"- Relevance tier: `{report['relevance']['tier']}`",
        f"- Relevance reason: `{report['relevance']['reason']}`",
        f"- Architecture scope: `{report['architecture_scope']['scope']}`",
        f"- LLM ready: `{str(report['llm_ready']).lower()}`",
        f"- LLM-ready exclusions: `{', '.join(report['llm_ready_exclusion_reasons']) or 'none'}`",
        f"- Expanded LLM ready: `{str(report['expanded_llm_ready']).lower()}`",
        f"- Expanded exclusions: `{', '.join(report['expanded_llm_ready_exclusion_reasons']) or 'none'}`",
        "",
        "## Original bug description",
        "",
        indent_text(report.get("description", "")),
        "",
        "## Reproduction/test artifacts",
        "",
    ]
    if report["testcases"]:
        for artifact in report["testcases"]:
            lines.append(
                f"- `{artifact['path']}` — {artifact['kind']}, "
                f"language `{artifact['language']}`, SHA-256 `{artifact['sha256']}`"
            )
    else:
        lines.append("- No extractable public test case was found; this report is not in `llm-ready.jsonl`.")

    lines.extend(["", "## Public comments", ""])
    for comment in report.get("comments", []):
        lines.extend(
            [
                f"### Comment {comment.get('count', '?')}",
                "",
                f"- Creator: `{comment.get('creator', '')}`",
                f"- Time: `{comment.get('creation_time', '')}`",
                "",
                indent_text(str(comment.get("text") or "")),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_report(
    client: BugzillaClient,
    metadata: Dict[str, Any],
    archive_dir: Path,
    local_tests: Sequence[Path],
    gcc_source: Optional[Path],
    max_attachment_bytes: int,
    discovery_sources: Sequence[str],
) -> Optional[Dict[str, Any]]:
    bug_id = int(metadata["id"])
    report_dir = archive_dir / "reports" / f"bug-{bug_id}"
    comments_payload = client.get_json(f"bug/{bug_id}/comment")
    comments = bug_comments(comments_payload, bug_id)
    relevance = classify_full_relevance(metadata, comments, local_tests, discovery_sources)
    if relevance["tier"] == "not_loongarch":
        return None

    raw_dir = report_dir / "raw"
    attachment_dir = report_dir / "attachments"
    raw_dir.mkdir(parents=True, exist_ok=True)
    attachment_dir.mkdir(parents=True, exist_ok=True)
    attachments_payload = client.get_json(
        f"bug/{bug_id}/attachment", {"exclude_fields": "data"}
    )
    attachment_metadata = bug_attachments(attachments_payload, bug_id)

    write_json_atomic(raw_dir / "bug.json", {"bugs": [metadata], "faults": []})
    write_json_atomic(raw_dir / "comments.json", comments_payload)
    write_json_atomic(raw_dir / "attachments.json", attachments_payload)

    testcases: List[Dict[str, Any]] = []
    archived_attachments: List[Dict[str, Any]] = []
    for attachment in attachment_metadata:
        attachment_id = int(attachment["id"])
        normalized = {key: value for key, value in attachment.items() if key != "data"}
        normalized["downloaded"] = False
        normalized["testcase_candidate"] = is_source_attachment(attachment)
        if not normalized["testcase_candidate"]:
            archived_attachments.append(normalized)
            continue
        try:
            payload = client.get_json(f"bug/attachment/{attachment_id}")
            detailed = attachment_object(payload, attachment_id)
            data = base64.b64decode(detailed.get("data") or "", validate=True)
            if len(data) > max_attachment_bytes:
                normalized["skip_reason"] = (
                    f"decoded attachment exceeds {max_attachment_bytes} bytes"
                )
                archived_attachments.append(normalized)
                continue
            file_name = safe_filename(
                str(detailed.get("file_name") or attachment.get("file_name") or "attachment")
            )
            archived_path = attachment_dir / f"attachment-{attachment_id}-{file_name}"
            write_bytes_atomic(archived_path, data)
            normalized.update(
                {
                    "downloaded": True,
                    "path": archived_path.relative_to(report_dir).as_posix(),
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                }
            )
            language = language_for(
                file_name,
                str(detailed.get("content_type") or attachment.get("content_type") or ""),
            )
            testcase_name = f"bug-{bug_id}-attachment-{attachment_id}-{file_name}"
            if Path(testcase_name.lower()).suffix not in SOURCE_SUFFIXES and language != "unknown":
                testcase_name += extension_for_language(language)
            testcases.append(
                copy_testcase(
                    report_dir,
                    testcase_name,
                    data,
                    "bugzilla_attachment",
                    language,
                    {
                        "bug_id": bug_id,
                        "attachment_id": attachment_id,
                        "source_url": f"{DEFAULT_BASE_URL}/bug/attachment/{attachment_id}",
                        "original_file_name": file_name,
                    },
                )
            )
        except (CorpusError, ValueError, binascii.Error) as error:
            normalized["skip_reason"] = str(error)
        archived_attachments.append(normalized)

    for candidate in extract_comment_testcases(comments):
        language = candidate["language"]
        name = (
            f"bug-{bug_id}-comment-{candidate['comment_number']}-"
            f"block-{candidate['block_number']}{extension_for_language(language)}"
        )
        testcases.append(
            copy_testcase(
                report_dir,
                name,
                candidate["content"].encode("utf-8"),
                candidate["kind"],
                language,
                {
                    "bug_id": bug_id,
                    "comment_number": candidate["comment_number"],
                    "source_url": f"{DEFAULT_WEB_URL.format(bug_id=bug_id)}#c{candidate['comment_number']}",
                },
            )
        )

    for source_path in local_tests:
        data = source_path.read_bytes()
        try:
            relative_source = source_path.relative_to(gcc_source).as_posix() if gcc_source else source_path.name
        except ValueError:
            relative_source = source_path.name
        testcases.append(
            copy_testcase(
                report_dir,
                f"gcc-testsuite-{safe_filename(relative_source.replace('/', '__'))}",
                data,
                "gcc_testsuite_regression",
                language_for(source_path.name),
                {
                    "bug_id": bug_id,
                    "gcc_source_relative_path": relative_source,
                    "gcc_git_revision": git_revision(gcc_source),
                },
            )
        )

    description = str(comments[0].get("text") or "") if comments else ""
    report = {
        "schema_version": SCHEMA_VERSION,
        "archived_at": utc_now(),
        "source": "GCC Bugzilla public REST API",
        "source_url": DEFAULT_WEB_URL.format(bug_id=bug_id),
        "discovery_sources": sorted(set(discovery_sources)),
        "metadata": metadata,
        "relevance": relevance,
        "description": description,
        "comments": comments,
        "attachments": archived_attachments,
        "testcases": testcases,
    }
    finalize_report_quality_fields(report)
    write_json_atomic(report_dir / "report.json", report)
    write_text_atomic(report_dir / "report.md", render_report_markdown(report))
    return report


def report_index_record(report: Dict[str, Any]) -> Dict[str, Any]:
    metadata = report["metadata"]
    return {
        "bug_id": metadata["id"],
        "summary": metadata.get("summary", ""),
        "status": metadata.get("status", ""),
        "resolution": metadata.get("resolution", ""),
        "component": metadata.get("component", ""),
        "gcc_target": metadata.get("cf_gcctarget", ""),
        "creation_time": metadata.get("creation_time", ""),
        "last_change_time": metadata.get("last_change_time", ""),
        "relevance_tier": report["relevance"]["tier"],
        "relevance_reason": report["relevance"]["reason"],
        "architecture_scope": report["architecture_scope"]["scope"],
        "has_description": report["has_description"],
        "has_testcase": report["has_testcase"],
        "testcase_count": len(report["testcases"]),
        "llm_ready": report["llm_ready"],
        "llm_ready_exclusion_reasons": ";".join(report["llm_ready_exclusion_reasons"]),
        "expanded_llm_ready": report["expanded_llm_ready"],
        "expanded_llm_ready_exclusion_reasons": ";".join(
            report["expanded_llm_ready_exclusion_reasons"]
        ),
        "source_url": report["source_url"],
        "report_path": f"reports/bug-{metadata['id']}/report.json",
    }


def llm_dataset_record(archive_dir: Path, report: Dict[str, Any]) -> Dict[str, Any]:
    metadata = report["metadata"]
    bug_id = int(metadata["id"])
    report_dir = archive_dir / "reports" / f"bug-{bug_id}"
    seen_hashes = set()
    testcases = []
    for testcase in report.get("testcases") or []:
        digest = testcase["sha256"]
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        source_path = report_dir / testcase["path"]
        data = source_path.read_bytes()
        content = data.decode("utf-8", errors="replace")
        testcases.append(
            {
                "kind": testcase["kind"],
                "language": testcase["language"],
                "content": content,
                "source_path": source_path.relative_to(archive_dir).as_posix(),
                "source_sha256": digest,
                "source_bytes": len(data),
                "utf8_replacement_used": "\ufffd" in content,
                "provenance": testcase.get("provenance") or {},
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "LoongArch64 GCC compiler quality test generation",
        "bug_id": bug_id,
        "source_url": report["source_url"],
        "summary": metadata.get("summary", ""),
        "component": metadata.get("component", ""),
        "status": metadata.get("status", ""),
        "resolution": metadata.get("resolution", ""),
        "gcc_target": metadata.get("cf_gcctarget", ""),
        "known_to_fail": metadata.get("cf_known_to_fail", ""),
        "known_to_work": metadata.get("cf_known_to_work", ""),
        "architecture_scope": report["architecture_scope"],
        "description": report["description"],
        "technical_comments": [
            {
                "count": comment.get("count"),
                "creation_time": comment.get("creation_time"),
                "text": comment.get("text", ""),
            }
            for comment in report.get("comments") or []
        ],
        "testcases": testcases,
    }


def write_indexes(archive_dir: Path, reports: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    records = sorted((report_index_record(report) for report in reports), key=lambda item: item["bug_id"])
    jsonl = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    write_text_atomic(archive_dir / "index.jsonl", jsonl)
    llm_ready = [record for record in records if record["llm_ready"]]
    write_text_atomic(
        archive_dir / "llm-ready.jsonl",
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in llm_ready),
    )
    ready_reports = [report for report in reports if report["llm_ready"]]
    llm_dataset = [llm_dataset_record(archive_dir, report) for report in ready_reports]
    write_text_atomic(
        archive_dir / "llm-dataset.jsonl",
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in llm_dataset),
    )
    expanded_ready = [record for record in records if record["expanded_llm_ready"]]
    write_text_atomic(
        archive_dir / "llm-expanded-ready.jsonl",
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in expanded_ready),
    )
    expanded_reports = [report for report in reports if report["expanded_llm_ready"]]
    expanded_dataset = [llm_dataset_record(archive_dir, report) for report in expanded_reports]
    write_text_atomic(
        archive_dir / "llm-expanded-dataset.jsonl",
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in expanded_dataset
        ),
    )

    csv_path = archive_dir / "index.csv"
    temporary = csv_path.with_name(csv_path.name + ".tmp")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8", newline="") as output:
        fieldnames = list(records[0].keys()) if records else ["bug_id"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    os.replace(temporary, csv_path)

    vector_sets = {
        scope: {"lsx": set(), "lasx": set(), "vector": set()}
        for scope in ("all", "core", "expanded")
    }
    direct_extension_reports = set()
    for report in reports:
        metadata = report.get("metadata") or {}
        bug_id = int(metadata["id"])
        report_dir = archive_dir / "reports" / f"bug-{bug_id}"
        text_parts = [json.dumps(report, ensure_ascii=False)]
        testcase_paths = []
        for testcase in report.get("testcases") or []:
            relative_path = str(testcase.get("path") or "")
            testcase_paths.append(relative_path)
            testcase_path = report_dir / relative_path
            if testcase_path.is_file():
                text_parts.append(testcase_path.read_text(encoding="utf-8", errors="replace"))
        search_text = "\n".join(text_parts)
        scopes = ["all"]
        if report.get("llm_ready"):
            scopes.append("core")
        if report.get("expanded_llm_ready"):
            scopes.append("expanded")
        has_lsx = bool(LSX_RE.search(search_text))
        has_lasx = bool(LASX_RE.search(search_text))
        has_vector = bool(BROAD_VECTOR_RE.search(search_text) or has_lsx or has_lasx)
        for scope in scopes:
            if has_lsx:
                vector_sets[scope]["lsx"].add(bug_id)
            if has_lasx:
                vector_sets[scope]["lasx"].add(bug_id)
            if has_vector:
                vector_sets[scope]["vector"].add(bug_id)
        direct_text = "\n".join([str(metadata.get("summary") or ""), *testcase_paths])
        if VECTOR_EXTENSION_RE.search(direct_text):
            direct_extension_reports.add(bug_id)

    counts = {
        "candidate_reports": len(records),
        "architecture_specific_reports": sum(
            record["relevance_tier"] == "architecture_specific" for record in records
        ),
        "multi_arch_shared_reports": sum(
            record["relevance_tier"] == "multi_arch_shared" for record in records
        ),
        "loongarch64_reports": sum(
            record["architecture_scope"] == "loongarch64" for record in records
        ),
        "reports_with_testcases": sum(record["has_testcase"] for record in records),
        "llm_ready_reports": len(llm_ready),
        "llm_dataset_records": len(llm_dataset),
        "expanded_llm_ready_reports": len(expanded_ready),
        "expanded_llm_dataset_records": len(expanded_dataset),
        "testcase_artifacts": sum(record["testcase_count"] for record in records),
        "loongarch_observed_reports": sum(
            record["relevance_tier"] == "loongarch_observed" for record in records
        ),
        "loongarch_testsuite_linked_reports": sum(
            record["relevance_tier"] == "loongarch_testsuite_linked" for record in records
        ),
        "loongarch_validation_only_reports": sum(
            record["relevance_tier"] == "loongarch_validation_only" for record in records
        ),
        "lsx_reports": len(vector_sets["all"]["lsx"]),
        "lasx_reports": len(vector_sets["all"]["lasx"]),
        "lsx_or_lasx_reports": len(
            vector_sets["all"]["lsx"] | vector_sets["all"]["lasx"]
        ),
        "strict_llm_lsx_or_lasx_reports": len(
            vector_sets["core"]["lsx"] | vector_sets["core"]["lasx"]
        ),
        "expanded_llm_lsx_or_lasx_reports": len(
            vector_sets["expanded"]["lsx"] | vector_sets["expanded"]["lasx"]
        ),
        "vector_related_reports": len(vector_sets["all"]["vector"]),
        "strict_llm_vector_related_reports": len(vector_sets["core"]["vector"]),
        "expanded_llm_vector_related_reports": len(vector_sets["expanded"]["vector"]),
        "direct_title_or_testcase_lsx_or_lasx_reports": len(direct_extension_reports),
    }
    summary = f"""# LoongArch GCC Bugzilla archive summary

Generated: `{utc_now()}`

Purpose: LoongArch64 GCC compiler quality and CI data preparation; this is not network security testing.

| Metric | Count |
|---|---:|
| Candidate reports retained for audit | {counts['candidate_reports']} |
| Architecture-specific reports | {counts['architecture_specific_reports']} |
| Reports with explicit LoongArch64 evidence | {counts['loongarch64_reports']} |
| Multi-architecture shared reports | {counts['multi_arch_shared_reports']} |
| Reports with test material | {counts['reports_with_testcases']} |
| Strict LLM-ready reports | {counts['llm_ready_reports']} |
| Direct LLM dataset records | {counts['llm_dataset_records']} |
| Expanded LLM-ready reports | {counts['expanded_llm_ready_reports']} |
| Expanded LLM dataset records | {counts['expanded_llm_dataset_records']} |
| LoongArch failures observed in comments | {counts['loongarch_observed_reports']} |
| LoongArch testsuite-linked reports | {counts['loongarch_testsuite_linked_reports']} |
| LoongArch validation-only reports | {counts['loongarch_validation_only_reports']} |
| Reports mentioning LSX | {counts['lsx_reports']} |
| Reports mentioning LASX | {counts['lasx_reports']} |
| Reports mentioning LSX or LASX | {counts['lsx_or_lasx_reports']} |
| Strict LLM-ready reports mentioning LSX or LASX | {counts['strict_llm_lsx_or_lasx_reports']} |
| Expanded LLM-ready reports mentioning LSX or LASX | {counts['expanded_llm_lsx_or_lasx_reports']} |
| Broad vectorization/SIMD-related reports | {counts['vector_related_reports']} |
| Expanded LLM-ready vectorization/SIMD reports | {counts['expanded_llm_vector_related_reports']} |
| Testcase artifacts | {counts['testcase_artifacts']} |

Use `llm-dataset.jsonl` for the high-precision core. Use `llm-expanded-dataset.jsonl` when generic GCC bugs reproduced on LoongArch64 or linked by LoongArch tests are also desired. The corresponding compact indexes are `llm-ready.jsonl` and `llm-expanded-ready.jsonl`.
"""
    write_text_atomic(archive_dir / "SUMMARY.md", summary)
    return counts


def load_cached_report(archive_dir: Path, metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    path = archive_dir / "reports" / f"bug-{metadata['id']}" / "report.json"
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if report.get("schema_version") != SCHEMA_VERSION:
        return None
    old_metadata = report.get("metadata") or {}
    if old_metadata.get("last_change_time") != metadata.get("last_change_time"):
        return None
    return report


def rebuild_archive(archive_dir: Path) -> Dict[str, Any]:
    archive_dir = archive_dir.resolve()
    manifest_path = archive_dir / "manifest.json"
    if not manifest_path.is_file():
        raise CorpusError(f"manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reports: List[Dict[str, Any]] = []
    for report_path in sorted((archive_dir / "reports").glob("bug-*/report.json")):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_dir = report_path.parent
        old_relevance = report.get("relevance") or {}
        report["relevance"] = classify_full_relevance(
            report.get("metadata") or {},
            report.get("comments") or [],
            [Path(path) for path in old_relevance.get("testsuite_paths") or []],
            old_relevance.get("discovery_sources") or [],
        )
        for testcase in report.get("testcases") or []:
            testcase_path = report_dir / testcase["path"]
            if testcase_path.is_file():
                testcase["language"] = language_for(testcase_path.name)
                if testcase["language"] == "unknown":
                    testcase["language"] = language_for_content(
                        testcase_path.read_text(encoding="utf-8", errors="replace")
                    )
        finalize_report_quality_fields(report)
        write_json_atomic(report_path, report)
        write_text_atomic(report_dir / "report.md", render_report_markdown(report))
        reports.append(report)
    counts = write_indexes(archive_dir, reports)
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["generated_at"] = utc_now()
    manifest["counts"] = counts
    write_json_atomic(manifest_path, manifest)
    return manifest


def sync_archive(
    archive_dir: Path,
    gcc_source: Optional[Path] = None,
    base_url: str = DEFAULT_BASE_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    delay_seconds: float = 0.4,
    timeout_seconds: float = 60.0,
    max_attachment_bytes: int = 5_000_000,
    refresh: bool = False,
    limit: int = 0,
) -> Dict[str, Any]:
    archive_dir = archive_dir.resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = archive_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    client = BugzillaClient(
        base_url=base_url,
        user_agent=user_agent,
        delay_seconds=delay_seconds,
        timeout_seconds=timeout_seconds,
    )

    version_payload = client.get_json("version")
    common = {"limit": 0, "include_fields": ",".join(SEARCH_FIELDS)}
    summary_payload = client.get_json("bug", {**common, "summary": "loongarch"})
    target_payload = client.get_json(
        "bug",
        {
            **common,
            "f1": "cf_gcctarget",
            "o1": "substring",
            "v1": "loongarch",
        },
    )
    comments_payload = client.get_json(
        "bug",
        {
            **common,
            "f1": "longdesc",
            "o1": "substring",
            "v1": "loongarch",
        },
    )
    write_json_atomic(raw_dir / "version.json", version_payload)
    write_json_atomic(raw_dir / "search-summary-loongarch.json", summary_payload)
    write_json_atomic(raw_dir / "search-target-loongarch.json", target_payload)
    write_json_atomic(raw_dir / "search-comments-loongarch.json", comments_payload)

    candidates: Dict[int, Dict[str, Any]] = {}
    discovery_sources: Dict[int, List[str]] = {}
    for source_name, payload in (
        ("summary_contains_loongarch", summary_payload),
        ("gcc_target_contains_loongarch", target_payload),
        ("public_comment_contains_loongarch", comments_payload),
    ):
        for bug in payload.get("bugs") or []:
            bug_id = int(bug["id"])
            candidates[bug_id] = bug
            discovery_sources.setdefault(bug_id, []).append(source_name)

    loongarch_target_tests = discover_loongarch_target_regression_tests(gcc_source)
    missing_test_ids = sorted(set(loongarch_target_tests) - set(candidates))
    testsuite_payload: Dict[str, Any] = {"bugs": [], "faults": []}
    if missing_test_ids:
        testsuite_payload = client.get_json(
            "bug",
            {"id": missing_test_ids, "include_fields": ",".join(SEARCH_FIELDS)},
        )
        for bug in testsuite_payload.get("bugs") or []:
            bug_id = int(bug["id"])
            candidates[bug_id] = bug
            discovery_sources.setdefault(bug_id, []).append("gcc_loongarch_testsuite_pr")
    write_json_atomic(raw_dir / "search-testsuite-pr-ids.json", testsuite_payload)

    ordered = [candidates[bug_id] for bug_id in sorted(candidates)]
    if limit > 0:
        ordered = ordered[:limit]

    local_tests = discover_local_regression_tests(
        gcc_source, (int(bug["id"]) for bug in ordered)
    )
    reports: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    discarded: List[int] = []
    total = len(ordered)
    for position, metadata in enumerate(ordered, start=1):
        bug_id = int(metadata["id"])
        cached = None if refresh else load_cached_report(archive_dir, metadata)
        if cached is not None:
            reports.append(cached)
            print(f"[{position}/{total}] bug {bug_id}: unchanged, using archive", flush=True)
            continue
        print(f"[{position}/{total}] bug {bug_id}: fetching", flush=True)
        try:
            report = build_report(
                client,
                metadata,
                archive_dir,
                local_tests.get(bug_id, []),
                gcc_source,
                max_attachment_bytes,
                discovery_sources.get(bug_id, []),
            )
            if report is None:
                discarded.append(bug_id)
                print("  discarded: no direct LoongArch evidence in full report", flush=True)
            else:
                reports.append(report)
        except Exception as error:  # continue to preserve a useful partial archive
            errors.append({"bug_id": bug_id, "error": str(error)})
            print(f"  error: {error}", file=sys.stderr, flush=True)

    counts = write_indexes(archive_dir, reports)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "purpose": "LoongArch GCC compiler quality and CI test corpus; not network security testing",
        "source": "GCC Bugzilla public REST API",
        "base_url": base_url,
        "bugzilla_version": version_payload.get("version"),
        "queries": [
            {"summary": "loongarch"},
            {"field": "cf_gcctarget", "operator": "substring", "value": "loongarch"},
            {"field": "public_comments", "operator": "substring", "value": "loongarch"},
            {"source": "local GCC LoongArch testsuite", "key": "PR bug id"},
        ],
        "gcc_source": str(gcc_source.resolve()) if gcc_source else None,
        "gcc_git_revision": git_revision(gcc_source),
        "max_attachment_bytes": max_attachment_bytes,
        "limited_run": limit if limit > 0 else None,
        "counts": counts,
        "discovered_candidates": len(ordered),
        "discarded_after_fulltext_review": discarded,
        "errors": errors,
    }
    write_json_atomic(archive_dir / "manifest.json", manifest)
    if errors:
        raise CorpusError(
            f"archive completed with {len(errors)} failed reports; see {archive_dir / 'manifest.json'}"
        )
    return manifest


def verify_archive(archive_dir: Path) -> Dict[str, int]:
    archive_dir = archive_dir.resolve()
    manifest_path = archive_dir / "manifest.json"
    index_path = archive_dir / "index.jsonl"
    llm_path = archive_dir / "llm-ready.jsonl"
    llm_dataset_path = archive_dir / "llm-dataset.jsonl"
    expanded_path = archive_dir / "llm-expanded-ready.jsonl"
    expanded_dataset_path = archive_dir / "llm-expanded-dataset.jsonl"
    for required in (
        manifest_path,
        index_path,
        llm_path,
        llm_dataset_path,
        expanded_path,
        expanded_dataset_path,
        archive_dir / "index.csv",
        archive_dir / "SUMMARY.md",
    ):
        if not required.is_file():
            raise CorpusError(f"required archive file is missing: {required}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("errors"):
        raise CorpusError("manifest contains fetch errors")
    if manifest.get("base_url") != DEFAULT_BASE_URL:
        raise CorpusError("manifest source is not the official GCC Bugzilla REST endpoint")
    for raw_search in (
        archive_dir / "raw" / "version.json",
        archive_dir / "raw" / "search-summary-loongarch.json",
        archive_dir / "raw" / "search-target-loongarch.json",
        archive_dir / "raw" / "search-comments-loongarch.json",
        archive_dir / "raw" / "search-testsuite-pr-ids.json",
    ):
        if not raw_search.is_file():
            raise CorpusError(f"missing raw Bugzilla discovery response: {raw_search}")
    records = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    ready_records = [json.loads(line) for line in llm_path.read_text(encoding="utf-8").splitlines() if line]
    dataset_records = [
        json.loads(line) for line in llm_dataset_path.read_text(encoding="utf-8").splitlines() if line
    ]
    expanded_records = [
        json.loads(line) for line in expanded_path.read_text(encoding="utf-8").splitlines() if line
    ]
    expanded_dataset_records = [
        json.loads(line)
        for line in expanded_dataset_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if {record["bug_id"] for record in ready_records} != {
        record["bug_id"] for record in records if record["llm_ready"]
    }:
        raise CorpusError("llm-ready.jsonl does not match index.jsonl")
    if {record["bug_id"] for record in dataset_records} != {
        record["bug_id"] for record in ready_records
    }:
        raise CorpusError("llm-dataset.jsonl does not match llm-ready.jsonl")
    if {record["bug_id"] for record in expanded_records} != {
        record["bug_id"] for record in records if record["expanded_llm_ready"]
    }:
        raise CorpusError("llm-expanded-ready.jsonl does not match index.jsonl")
    if {record["bug_id"] for record in expanded_dataset_records} != {
        record["bug_id"] for record in expanded_records
    }:
        raise CorpusError("llm-expanded-dataset.jsonl does not match expanded index")

    testcase_count = 0
    reports_by_id: Dict[int, Dict[str, Any]] = {}
    for record in records:
        report_path = archive_dir / record["report_path"]
        if not report_path.is_file():
            raise CorpusError(f"missing normalized report: {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        reports_by_id[int(record["bug_id"])] = report
        if not (report_path.parent / "report.md").is_file():
            raise CorpusError(f"missing readable Markdown report: {report_path.parent / 'report.md'}")
        for raw_name in ("bug.json", "comments.json", "attachments.json"):
            raw_path = report_path.parent / "raw" / raw_name
            if not raw_path.is_file():
                raise CorpusError(f"missing per-report raw Bugzilla response: {raw_path}")
        if int(report["metadata"]["id"]) != int(record["bug_id"]):
            raise CorpusError(f"bug id mismatch in {report_path}")
        expected_source_url = DEFAULT_WEB_URL.format(bug_id=record["bug_id"])
        if report.get("source_url") != expected_source_url:
            raise CorpusError(f"report does not point to official GCC Bugzilla: {report_path}")
        comments = report.get("comments") or []
        expected_description = str(comments[0].get("text") or "") if comments else ""
        if str(report.get("description") or "") != expected_description:
            raise CorpusError(f"description is not the original first public comment: {report_path}")
        if report["relevance"]["tier"] == "not_loongarch":
            raise CorpusError(f"non-LoongArch report leaked into archive: {report_path}")
        if report["llm_ready"]:
            if report["relevance"]["tier"] != "architecture_specific":
                raise CorpusError(f"shared multi-arch report marked LLM-ready: {report_path}")
            if (report.get("architecture_scope") or {}).get("scope") != "loongarch64":
                raise CorpusError(f"LLM-ready report lacks LoongArch64 evidence: {report_path}")
            if not (report.get("disposition") or {}).get("eligible_as_gcc_bug_report"):
                raise CorpusError(f"invalid/moved report marked LLM-ready: {report_path}")
            if not str(report.get("description") or "").strip():
                raise CorpusError(f"LLM-ready report lacks description: {report_path}")
            if not report.get("testcases"):
                raise CorpusError(f"LLM-ready report lacks test case: {report_path}")
        if report.get("expanded_llm_ready"):
            if report["relevance"]["tier"] not in {
                "architecture_specific",
                "multi_arch_shared",
                "loongarch_testsuite_linked",
                "loongarch_observed",
            }:
                raise CorpusError(f"expanded dataset contains validation-only report: {report_path}")
            if (report.get("architecture_scope") or {}).get("scope") != "loongarch64":
                raise CorpusError(f"expanded-ready report lacks LoongArch64 evidence: {report_path}")
            if not (report.get("disposition") or {}).get("eligible_as_gcc_bug_report"):
                raise CorpusError(f"invalid/moved report marked expanded-ready: {report_path}")
            if not report.get("testcases") or not str(report.get("description") or "").strip():
                raise CorpusError(f"expanded-ready report lacks description/testcase: {report_path}")
        report_dir = report_path.parent
        for testcase in report.get("testcases") or []:
            testcase_path = report_dir / testcase["path"]
            if not testcase_path.is_file():
                raise CorpusError(f"missing test case: {testcase_path}")
            data = testcase_path.read_bytes()
            if sha256_bytes(data) != testcase["sha256"]:
                raise CorpusError(f"test case checksum mismatch: {testcase_path}")
            provenance = testcase.get("provenance") or {}
            kind = testcase.get("kind")
            if kind in {"bugzilla_attachment", "comment_code_block", "comment_reproducer"}:
                if not str(provenance.get("source_url") or "").startswith(
                    "https://gcc.gnu.org/bugzilla/"
                ):
                    raise CorpusError(f"Bugzilla test case lacks official provenance: {testcase_path}")
            if kind == "gcc_testsuite_regression" and not provenance.get("gcc_git_revision"):
                raise CorpusError(f"GCC testsuite case lacks a git revision: {testcase_path}")
            testcase_count += 1

    for dataset in dataset_records:
        bug_id = int(dataset["bug_id"])
        report = reports_by_id[bug_id]
        if dataset.get("description") != report.get("description"):
            raise CorpusError(f"LLM dataset description mismatch for bug {bug_id}")
        if (dataset.get("architecture_scope") or {}).get("scope") != "loongarch64":
            raise CorpusError(f"LLM dataset contains non-LoongArch64 bug {bug_id}")
        dataset_testcases = dataset.get("testcases") or []
        if not dataset_testcases:
            raise CorpusError(f"LLM dataset lacks testcase content for bug {bug_id}")
        digests = [testcase["source_sha256"] for testcase in dataset_testcases]
        if len(digests) != len(set(digests)):
            raise CorpusError(f"LLM dataset contains duplicate testcase content for bug {bug_id}")
        for testcase in dataset_testcases:
            source_path = archive_dir / testcase["source_path"]
            if not source_path.is_file():
                raise CorpusError(f"LLM dataset source path is missing: {source_path}")
            if sha256_bytes(source_path.read_bytes()) != testcase["source_sha256"]:
                raise CorpusError(f"LLM dataset source checksum mismatch: {source_path}")

    for dataset in expanded_dataset_records:
        bug_id = int(dataset["bug_id"])
        report = reports_by_id[bug_id]
        if not report.get("expanded_llm_ready"):
            raise CorpusError(f"expanded LLM dataset includes ineligible bug {bug_id}")
        if dataset.get("description") != report.get("description"):
            raise CorpusError(f"expanded LLM dataset description mismatch for bug {bug_id}")
        if (dataset.get("architecture_scope") or {}).get("scope") != "loongarch64":
            raise CorpusError(f"expanded LLM dataset contains non-LoongArch64 bug {bug_id}")
        dataset_testcases = dataset.get("testcases") or []
        if not dataset_testcases:
            raise CorpusError(f"expanded LLM dataset lacks testcase content for bug {bug_id}")
        digests = [testcase["source_sha256"] for testcase in dataset_testcases]
        if len(digests) != len(set(digests)):
            raise CorpusError(
                f"expanded LLM dataset contains duplicate testcase content for bug {bug_id}"
            )
        for testcase in dataset_testcases:
            source_path = archive_dir / testcase["source_path"]
            if not source_path.is_file():
                raise CorpusError(f"expanded LLM dataset source path is missing: {source_path}")
            if sha256_bytes(source_path.read_bytes()) != testcase["source_sha256"]:
                raise CorpusError(f"expanded LLM dataset source checksum mismatch: {source_path}")

    counts = {
        "reports": len(records),
        "llm_ready_reports": len(ready_records),
        "llm_dataset_records": len(dataset_records),
        "expanded_llm_ready_reports": len(expanded_records),
        "expanded_llm_dataset_records": len(expanded_dataset_records),
        "testcase_artifacts": testcase_count,
    }
    expected = manifest.get("counts") or {}
    if expected.get("candidate_reports") != counts["reports"]:
        raise CorpusError("manifest report count does not match index")
    if expected.get("llm_ready_reports") != counts["llm_ready_reports"]:
        raise CorpusError("manifest LLM-ready count does not match index")
    if expected.get("llm_dataset_records") != counts["llm_dataset_records"]:
        raise CorpusError("manifest LLM dataset count does not match archive")
    if expected.get("expanded_llm_ready_reports") != counts["expanded_llm_ready_reports"]:
        raise CorpusError("manifest expanded-ready count does not match archive")
    if expected.get("expanded_llm_dataset_records") != counts["expanded_llm_dataset_records"]:
        raise CorpusError("manifest expanded dataset count does not match archive")
    if expected.get("testcase_artifacts") != counts["testcase_artifacts"]:
        raise CorpusError("manifest test case count does not match archive")
    return counts
