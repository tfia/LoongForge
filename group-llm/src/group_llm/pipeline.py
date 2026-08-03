"""GroupLLM primitives for synthesizing coherent compiler-test feature groups.

The module intentionally uses only the Python standard library so it can run in
CI preparation jobs without adding a runtime dependency.  Source features are
treated as immutable: GroupLLM may add glue features and dependency plans, but
the original feature objects in every output are copied from the candidate
record rather than trusted from model output.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple


SCHEMA_VERSION = 1
DEFAULT_OUTPUT_DIR = Path("out")
DEFAULT_FEATURE_POOL = Path("../extract-llm/out/feature-pool.jsonl")
DEFAULT_ENV_FILE = Path("../.env")
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_GROUP_COUNT = 64
DEFAULT_MIN_FEATURES = 3
DEFAULT_MAX_FEATURES = 5
DEFAULT_SEED = 20260730
DEFAULT_TIMEOUT = 240.0
# The configured reasoning model counts internal reasoning against max_tokens.
# Eight thousand tokens was insufficient for a small number of groups and
# yielded empty/truncated JSON, so leave enough headroom for a complete object.
DEFAULT_MAX_TOKENS = 16000
DEFAULT_MAX_WITNESS_CHARS = 5000
DEFAULT_MIN_CONFIDENCE = 0.0
DEFAULT_LANGUAGES = (
    "c",
    "c++",
    "fortran",
    "asm",
    "ada",
    "d",
    "cobol",
    "c-header",
    "shell",
    "rtl",
    "other",
    "unknown",
)

CORE_FEATURE_TYPES = {"semantic_invariant", "code_shape", "pass_interaction", "target_condition"}
SUPPORT_FEATURE_TYPES = {"failure_oracle", "mutation_knob"}
VALID_STATUSES = {"ready", "rejected"}
VALID_TEST_MODES = {
    "compile_only",
    "execute_differential",
    "diagnostic",
    "assembly_scan",
    "link_test",
}
VALID_LANGUAGES = set(DEFAULT_LANGUAGES)

TOKEN_RE = re.compile(r"[a-z0-9_+.-]+", re.IGNORECASE)
CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL | re.IGNORECASE)
SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
GENERIC_AFFINITY_TOKENS = {
    "-o0",
    "-o1",
    "-o2",
    "-o3",
    "-os",
    "-march",
    "-mtune",
    "compiler",
    "gcc",
    "ice",
    "loongarch",
    "loongarch64",
    "la64",
    "lsx",
    "lasx",
    "optimization",
    "optimizer",
    "other",
    "target",
    "wrong-code",
}
DESCRIPTION_STOPWORDS = {
    "about", "after", "also", "and", "are", "before", "being", "between", "both",
    "can", "code", "compile", "compiled", "compiler", "could", "does", "during", "each",
    "e.g.", "for", "from", "gcc", "has", "have", "into", "its", "may", "must", "not",
    "only", "other", "same", "should", "such", "than", "that", "the", "their", "then",
    "this", "through", "under", "used", "using", "when", "where", "which", "while", "with",
}
PROFILE_TERMS = {
    "loongarch": {"loongarch", "loongarch64", "loong64", "la64", "lsx", "lasx"},
}
ARCH_TERMS = {
    "loongarch": {"loongarch", "loongarch64", "loong64", "la64", "lsx", "lasx"},
    "x86": {"x86", "i386", "i686", "x86_64", "avx", "sse"},
    "arm": {"arm", "aarch64", "neon", "sve"},
    "mips": {"mips", "mips64"},
    "riscv": {"riscv", "risc-v", "rv64", "rv32"},
    "powerpc": {"powerpc", "ppc", "ppc64", "altivec", "vsx"},
}


class PipelineError(RuntimeError):
    """Raised when a GroupLLM operation cannot be completed safely."""


class ModelParseError(PipelineError):
    """Raised when an API response is not parseable as the requested JSON."""


class GroupValidationError(PipelineError):
    """Raised when a synthesized group violates structural invariants."""


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


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(dict(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise PipelineError(f"invalid JSON at {path}:{line_number}: {error}") from error
            if not isinstance(value, dict):
                raise PipelineError(f"expected JSON object at {path}:{line_number}")
            yield value


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dict(record), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
    return count


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def redact_secrets(value: str) -> str:
    return SECRET_RE.sub("<redacted-api-key>", value)


def load_env_file(path: Path) -> Dict[str, str]:
    """Parse a simple dotenv file without logging or persisting any values."""

    if not path.is_file():
        raise PipelineError(f"environment file does not exist: {path}")
    values: Dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise PipelineError(f"invalid dotenv assignment at {path}:{line_number}")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key] = value
    return values


def feature_object(record: Mapping[str, Any]) -> Dict[str, Any]:
    feature = record.get("feature")
    if not isinstance(feature, dict):
        raise PipelineError("feature-pool record is missing a feature object")
    return feature


def feature_uid(record: Mapping[str, Any]) -> str:
    value = str(record.get("feature_uid") or "").strip()
    if not value:
        raise PipelineError("feature-pool record is missing feature_uid")
    return value


def feature_bug_id(record: Mapping[str, Any]) -> int:
    try:
        return int(record.get("bug_id"))
    except (TypeError, ValueError) as error:
        raise PipelineError(f"feature {record.get('feature_uid')} has invalid bug_id") from error


def canonical_language(value: Any) -> str:
    language = str(value or "unknown").strip().lower()
    aliases = {
        "cpp": "c++",
        "cxx": "c++",
        "g++": "c++",
        "f90": "fortran",
        "f95": "fortran",
        "assembly": "asm",
    }
    return aliases.get(language, language)


def record_language(record: Mapping[str, Any]) -> str:
    return canonical_language(feature_object(record).get("language"))


def string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def token_set(value: Any) -> Set[str]:
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value or "")
    return {token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1}


def composition_tokens(record: Mapping[str, Any]) -> Set[str]:
    feature = feature_object(record)
    tokens = token_set(feature.get("composition_tags"))
    description_tokens = token_set(feature.get("description")) - DESCRIPTION_STOPWORDS
    tokens.update(description_tokens)
    tokens.update(token_set(feature.get("mutation_knobs")))
    return tokens - GENERIC_AFFINITY_TOKENS


def architecture_set(record: Mapping[str, Any]) -> Set[str]:
    feature = feature_object(record)
    text = " ".join(
        [
            str(feature.get("description") or ""),
            " ".join(string_list(feature.get("composition_tags"))),
            " ".join(string_list(feature.get("target_options"))),
        ]
    ).lower()
    words = token_set(text)
    result = set()
    for architecture, terms in ARCH_TERMS.items():
        if words.intersection(terms):
            result.add(architecture)
    return result


def matches_profile(record: Mapping[str, Any], target_profile: str) -> bool:
    profile = target_profile.strip().lower()
    if not profile or profile == "any":
        return True
    terms = PROFILE_TERMS.get(profile, {profile})
    feature = feature_object(record)
    searchable = " ".join(
        [
            str(feature.get("description") or ""),
            str(feature.get("code_witness") or ""),
            " ".join(string_list(feature.get("composition_tags"))),
            " ".join(string_list(feature.get("target_options"))),
            str(record.get("root_cause_summary") or ""),
        ]
    )
    return bool(token_set(searchable).intersection(terms))


def feature_quality(record: Mapping[str, Any]) -> float:
    feature = feature_object(record)
    confidence = feature.get("confidence", 0.5)
    try:
        confidence_value = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence_value = 0.5
    strength = str(feature.get("evidence_strength") or "").lower()
    strength_value = {"strong": 1.0, "medium": 0.7, "weak": 0.35}.get(strength, 0.5)
    witness = 1.0 if str(feature.get("code_witness") or "").strip() else 0.0
    return 0.55 * confidence_value + 0.3 * strength_value + 0.15 * witness


def languages_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    a = record_language(left)
    b = record_language(right)
    return a == b or a == "unknown" or b == "unknown"


def architectures_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    a = architecture_set(left)
    b = architecture_set(right)
    return not a or not b or bool(a.intersection(b))


def option_constraints(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract mutually exclusive invocation constraints used before LLM calls."""

    feature = feature_object(record)
    text = " ".join(string_list(feature.get("target_options"))).lower()
    abis = set(re.findall(r"(?:-mabi=|\b)(lp64[dfs]|ilp32[dfs]?)\b", text))
    optimization_levels = set(
        match.lower()
        for match in re.findall(r"(?<![A-Za-z0-9])-(O0|O1|O2|O3|Os|Og|Ofast)(?![A-Za-z0-9])", text)
    )
    soft_float = any(term in text for term in ("-msoft-float", "-mfpu=none", "-mabi=lp64s"))
    hard_float = any(
        term in text
        for term in ("-mhard-float", "-mfpu=64", "-mabi=lp64d", "-mlsx", "-mlasx", "-msimd=lsx", "-msimd=lasx")
    )
    return {
        "abis": abis,
        "optimization_levels": optimization_levels,
        "soft_float": soft_float,
        "hard_float": hard_float,
        "requires_lsx": any(term in text for term in ("-mlsx", "-mlasx", "-msimd=lsx", "-msimd=lasx")),
        "requires_lasx": any(term in text for term in ("-mlasx", "-msimd=lasx")),
        "forbids_lsx": "-mno-lsx" in text,
        "forbids_lasx": "-mno-lasx" in text,
    }


def options_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    a = option_constraints(left)
    b = option_constraints(right)
    if a["abis"] and b["abis"] and not a["abis"].intersection(b["abis"]):
        return False
    if (a["soft_float"] and b["hard_float"]) or (b["soft_float"] and a["hard_float"]):
        return False
    if (a["forbids_lsx"] and b["requires_lsx"]) or (b["forbids_lsx"] and a["requires_lsx"]):
        return False
    if (a["forbids_lasx"] and b["requires_lasx"]) or (b["forbids_lasx"] and a["requires_lasx"]):
        return False
    a_levels = a["optimization_levels"]
    b_levels = b["optimization_levels"]
    if len(a_levels) == 1 and len(b_levels) == 1 and a_levels != b_levels:
        return False
    return True


def pair_affinity(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, Any]:
    compatible_language = languages_compatible(left, right)
    compatible_architecture = architectures_compatible(left, right)
    compatible_options = options_compatible(left, right)
    left_feature = feature_object(left)
    right_feature = feature_object(right)
    left_tags = composition_tokens(left)
    right_tags = composition_tokens(right)
    shared_tags = sorted(left_tags.intersection(right_tags))
    union = left_tags.union(right_tags)
    tag_jaccard = len(shared_tags) / len(union) if union else 0.0
    same_area = (
        bool(left_feature.get("compiler_area"))
        and left_feature.get("compiler_area") == right_feature.get("compiler_area")
    )
    same_failure = (
        bool(left_feature.get("failure_mode"))
        and left_feature.get("failure_mode") == right_feature.get("failure_mode")
    )
    different_type = left_feature.get("feature_type") != right_feature.get("feature_type")
    same_profile = bool(architecture_set(left).intersection(architecture_set(right)))
    score = (
        5.0 * tag_jaccard
        + min(2.0, 0.45 * len(shared_tags))
        + (1.4 if same_area else 0.0)
        + (0.7 if same_failure else 0.0)
        + (0.8 if different_type else 0.0)
        + (1.0 if same_profile else 0.0)
        + 0.6 * (feature_quality(left) + feature_quality(right))
    )
    if not compatible_language or not compatible_architecture or not compatible_options:
        score = -1000.0
    return {
        "left": feature_uid(left),
        "right": feature_uid(right),
        "score": round(score, 4),
        "language_compatible": compatible_language,
        "architecture_compatible": compatible_architecture,
        "options_compatible": compatible_options,
        "shared_tags": shared_tags,
        "same_compiler_area": same_area,
        "same_failure_mode": same_failure,
        "complementary_feature_types": different_type,
    }


def load_feature_pool(
    feature_pool_path: Path,
    allowed_languages: Sequence[str] = DEFAULT_LANGUAGES,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> List[Dict[str, Any]]:
    if not feature_pool_path.is_file():
        raise PipelineError(f"feature pool does not exist: {feature_pool_path}")
    allowed = {canonical_language(language) for language in allowed_languages}
    records: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for record in iter_jsonl(feature_pool_path):
        uid = feature_uid(record)
        if uid in seen:
            raise PipelineError(f"duplicate feature_uid in pool: {uid}")
        seen.add(uid)
        feature_bug_id(record)
        feature = feature_object(record)
        if record_language(record) not in allowed:
            continue
        if not str(feature.get("description") or "").strip():
            continue
        confidence = feature.get("confidence", 0.5)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.5
        if confidence_value < min_confidence:
            continue
        records.append(record)
    if not records:
        raise PipelineError("no eligible features remained after filtering")
    return records


def compact_source_feature(record: Mapping[str, Any], max_witness_chars: int) -> Dict[str, Any]:
    feature = json.loads(json.dumps(feature_object(record), ensure_ascii=False))
    witness = str(feature.get("code_witness") or "")
    if max_witness_chars > 0 and len(witness) > max_witness_chars:
        feature["code_witness"] = witness[:max_witness_chars] + "\n/* witness truncated for GroupLLM prompt */"
        feature["witness_truncated_for_prompt"] = True
    return {
        "feature_uid": feature_uid(record),
        "bug_id": feature_bug_id(record),
        "source_url": record.get("source_url"),
        "root_cause_summary": record.get("root_cause_summary"),
        "feature": feature,
    }


def source_snapshot(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "feature_uid": feature_uid(record),
        "bug_id": feature_bug_id(record),
        "source_url": record.get("source_url"),
        "root_cause_summary": record.get("root_cause_summary"),
        "feature": json.loads(json.dumps(feature_object(record), ensure_ascii=False)),
    }


def choose_primary_language(records: Sequence[Mapping[str, Any]]) -> str:
    languages = [record_language(record) for record in records if record_language(record) != "unknown"]
    if not languages:
        return "unknown"
    return Counter(languages).most_common(1)[0][0]


def candidate_selection_score(
    candidate: Mapping[str, Any],
    selected: Sequence[Mapping[str, Any]],
    planned_coverage: Counter,
    sampling_usage: Counter,
    type_counts: Counter,
    profile_match: bool,
) -> float:
    affinities = [pair_affinity(candidate, existing)["score"] for existing in selected]
    if not affinities or min(affinities) <= -999:
        return -1000.0
    # A group may contain one exploratory bridge, but each new feature must have
    # a meaningful semantic relationship with at least one feature already in
    # the group.  Target profile and generic optimization flags are scored
    # separately and cannot satisfy this threshold by themselves.
    if max(affinities) < 3.2:
        return -1000.0
    feature_type = str(feature_object(candidate).get("feature_type") or "")
    novelty = 1.2 if type_counts[feature_type] == 0 else -0.5 * type_counts[feature_type]
    uid = feature_uid(candidate)
    # Coverage is the primary incremental objective. A feature absent from all
    # ready groups receives a strong bonus, while affinity remains a hard gate.
    uncovered_bonus = 8.0 if planned_coverage[uid] == 0 else 0.0
    underuse = 2.0 / (1.0 + sampling_usage[uid])
    target_bonus = 1.4 if profile_match else 0.0
    return (
        max(affinities)
        + 0.35 * (sum(affinities) / len(affinities))
        + novelty
        + uncovered_bonus
        + underuse
        + target_bonus
    )


def sample_candidate_groups(
    records: Sequence[Dict[str, Any]],
    group_count: int = DEFAULT_GROUP_COUNT,
    min_features: int = DEFAULT_MIN_FEATURES,
    max_features: int = DEFAULT_MAX_FEATURES,
    seed: int = DEFAULT_SEED,
    target_profile: str = "loongarch",
    start_index: int = 1,
    existing_candidates: Sequence[Mapping[str, Any]] = (),
    covered_feature_uids: Sequence[str] = (),
    existing_candidates_cover: bool = True,
) -> List[Dict[str, Any]]:
    if group_count <= 0:
        raise PipelineError("group_count must be positive")
    if min_features < 2 or max_features < min_features:
        raise PipelineError("feature group size must satisfy 2 <= min_features <= max_features")
    if len({feature_bug_id(record) for record in records}) < min_features:
        raise PipelineError("feature pool does not contain enough distinct bugs for one group")

    rng = random.Random(seed)
    anchors = [
        record
        for record in records
        if str(feature_object(record).get("feature_type") or "") in CORE_FEATURE_TYPES
        and matches_profile(record, target_profile)
    ]
    if not anchors:
        raise PipelineError(f"no core feature matches target profile {target_profile!r}")

    if start_index <= 0:
        raise PipelineError("start_index must be positive")
    record_by_uid = {feature_uid(record): record for record in records}
    sampling_usage: Counter = Counter()
    planned_coverage: Counter = Counter(str(uid) for uid in covered_feature_uids)
    pair_usage: Counter = Counter()
    seen_groups: Set[Tuple[str, ...]] = set()
    for previous in existing_candidates:
        previous_uids = [
            str(uid) for uid in previous.get("source_feature_uids", []) if str(uid) in record_by_uid
        ]
        if len(previous_uids) >= 2:
            seen_groups.add(tuple(sorted(previous_uids)))
        for uid in previous_uids:
            sampling_usage[uid] += 1
            # Incremental prepare first aims to cover the feature pool at the
            # candidate layer. Features already present in any prior candidate
            # are planned-covered, even if that candidate has not been sent to
            # GroupLLM yet. Recombining rejected features belongs to a later
            # feedback iteration, after breadth coverage is established.
            if existing_candidates_cover:
                planned_coverage[uid] += 1
        for left_index, left in enumerate(previous_uids):
            for right in previous_uids[left_index + 1 :]:
                pair_usage[tuple(sorted((left, right)))] += 1
    groups: List[Dict[str, Any]] = []

    for group_index in range(start_index, start_index + group_count):
        selected: Optional[List[Dict[str, Any]]] = None
        for _attempt in range(80):
            uncovered_records = [
                item for item in records if planned_coverage[feature_uid(item)] == 0
            ]
            # Tail-coverage pass: support features (failure oracles and mutation
            # knobs) may never be selected as normal anchors. Once the broad
            # pool has been sampled, seed a candidate with those uncovered
            # records and let compatible core/profile features bridge them.
            coverage_window = uncovered_records or anchors
            least_covered = min(planned_coverage[feature_uid(item)] for item in coverage_window)
            coverage_window = [
                item for item in coverage_window if planned_coverage[feature_uid(item)] == least_covered
            ]
            least_sampled = min(sampling_usage[feature_uid(item)] for item in coverage_window)
            anchor_window = [
                item
                for item in coverage_window
                if sampling_usage[feature_uid(item)] <= least_sampled + 1
            ]
            anchor = rng.choice(anchor_window)
            desired_size = rng.randint(min_features, max_features)
            current = [anchor]
            bugs = {feature_bug_id(anchor)}
            type_counts = Counter([str(feature_object(anchor).get("feature_type") or "")])

            while len(current) < desired_size:
                ranked: List[Tuple[float, float, Dict[str, Any]]] = []
                for candidate in records:
                    uid = feature_uid(candidate)
                    if uid in {feature_uid(item) for item in current}:
                        continue
                    if feature_bug_id(candidate) in bugs:
                        continue
                    if any(not languages_compatible(candidate, item) for item in current):
                        continue
                    if any(not architectures_compatible(candidate, item) for item in current):
                        continue
                    support_count = sum(
                        1
                        for item in current
                        if str(feature_object(item).get("feature_type") or "") in SUPPORT_FEATURE_TYPES
                    )
                    candidate_type = str(feature_object(candidate).get("feature_type") or "")
                    if candidate_type in SUPPORT_FEATURE_TYPES and support_count >= 1:
                        continue
                    score = candidate_selection_score(
                        candidate,
                        current,
                        planned_coverage,
                        sampling_usage,
                        type_counts,
                        matches_profile(candidate, target_profile),
                    )
                    if score <= -999:
                        continue
                    repeated_pairs = sum(
                        pair_usage[tuple(sorted((uid, feature_uid(item))))] for item in current
                    )
                    score -= 0.7 * repeated_pairs
                    ranked.append((score, rng.random(), candidate))
                if not ranked:
                    break
                ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
                exploration_window = min(len(ranked), max(8, len(ranked) // 12))
                if rng.random() < 0.78:
                    pick_window = min(exploration_window, 12)
                else:
                    pick_window = min(len(ranked), max(exploration_window, 40))
                weights = [1.0 / (1.0 + index) for index in range(pick_window)]
                chosen = rng.choices([item[2] for item in ranked[:pick_window]], weights=weights, k=1)[0]
                current.append(chosen)
                bugs.add(feature_bug_id(chosen))
                type_counts[str(feature_object(chosen).get("feature_type") or "")] += 1

            if len(current) < min_features:
                continue
            if len(
                {
                    str(feature_object(item).get("feature_type") or "")
                    for item in current
                    if str(feature_object(item).get("feature_type") or "") in CORE_FEATURE_TYPES
                }
            ) < 2:
                continue
            if not any(
                str(feature_object(item).get("feature_type") or "") in CORE_FEATURE_TYPES
                and matches_profile(item, target_profile)
                for item in current
            ):
                continue
            fingerprint = tuple(sorted(feature_uid(item) for item in current))
            if fingerprint in seen_groups:
                continue
            selected = current
            seen_groups.add(fingerprint)
            break

        if selected is None:
            raise PipelineError(f"could not sample a unique compatible candidate for group {group_index}")

        uids = [feature_uid(item) for item in selected]
        for uid in uids:
            sampling_usage[uid] += 1
            planned_coverage[uid] += 1
        for left_index, left in enumerate(uids):
            for right in uids[left_index + 1 :]:
                pair_usage[tuple(sorted((left, right)))] += 1
        pairwise = [
            pair_affinity(left, right)
            for left_index, left in enumerate(selected)
            for right in selected[left_index + 1 :]
        ]
        source_features = [source_snapshot(item) for item in selected]
        source_sha = stable_hash(source_features, length=64)
        candidate_id = f"group-{group_index:04d}-{stable_hash({'seed': seed, 'uids': uids}, 12)}"
        groups.append(
            {
                "schema_version": SCHEMA_VERSION,
                "candidate_id": candidate_id,
                "sampled_at": utc_now(),
                "purpose": "Compiler quality testing for an owned LoongArch GCC fork; not security testing.",
                "target_profile": target_profile,
                "primary_language": choose_primary_language(selected),
                "source_feature_uids": uids,
                "source_bug_ids": [feature_bug_id(item) for item in selected],
                "source_features_sha256": source_sha,
                "source_features": source_features,
                "sampling": {
                    "algorithm": "incremental_uncovered_affinity_v2",
                    "seed": seed,
                    "group_index": group_index,
                    "requested_size_range": [min_features, max_features],
                    "actual_size": len(selected),
                    "distinct_source_bugs": len({feature_bug_id(item) for item in selected}),
                    "pairwise_affinities": pairwise,
                    "mean_pairwise_affinity": round(
                        sum(float(item["score"]) for item in pairwise) / len(pairwise), 4
                    )
                    if pairwise
                    else 0.0,
                },
            }
        )
    return groups


def prepare_candidates(
    feature_pool_path: Path,
    output_dir: Path,
    group_count: int = DEFAULT_GROUP_COUNT,
    min_features: int = DEFAULT_MIN_FEATURES,
    max_features: int = DEFAULT_MAX_FEATURES,
    seed: int = DEFAULT_SEED,
    target_profile: str = "loongarch",
    allowed_languages: Sequence[str] = DEFAULT_LANGUAGES,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    append_groups: int = 0,
    coverage_basis: str = "candidate",
) -> Dict[str, Any]:
    feature_pool_path = feature_pool_path.resolve()
    output_dir = output_dir.resolve()
    records = load_feature_pool(feature_pool_path, allowed_languages, min_confidence)
    if append_groups < 0:
        raise PipelineError("append_groups cannot be negative")
    if coverage_basis not in {"candidate", "ready"}:
        raise PipelineError("coverage_basis must be 'candidate' or 'ready'")
    existing_candidates: List[Dict[str, Any]] = []
    covered_feature_uids: List[str] = []
    prior_count = 0
    start_index = 1
    if append_groups:
        existing_path = output_dir / "group-candidates.jsonl"
        if not existing_path.is_file():
            raise PipelineError("cannot append: group-candidates.jsonl does not exist; run initial prepare")
        existing_candidates = list(iter_jsonl(existing_path))
        prior_count = len(existing_candidates)
        if not existing_candidates:
            raise PipelineError("cannot append to an empty candidate index")
        existing_manifest_path = output_dir / "prepare-manifest.json"
        if existing_manifest_path.is_file():
            existing_manifest = read_json(existing_manifest_path)
            prior_pool_hash = str(existing_manifest.get("feature_pool_sha256") or "")
            current_pool_hash = hashlib.sha256(feature_pool_path.read_bytes()).hexdigest()
            if prior_pool_hash and prior_pool_hash != current_pool_hash:
                raise PipelineError("feature pool changed since initial prepare; refusing unsafe append")
        indices = [
            int(item.get("sampling", {}).get("group_index") or 0)
            for item in existing_candidates
            if isinstance(item.get("sampling"), dict)
        ]
        start_index = max(indices or [prior_count]) + 1
        ready_pool_path = output_dir / "feature-groups.jsonl"
        if ready_pool_path.is_file():
            covered_feature_uids = sorted(
                {
                    str(uid)
                    for group in iter_jsonl(ready_pool_path)
                    for uid in group.get("source_feature_uids", [])
                }
            )
    requested_new_groups = append_groups if append_groups else group_count
    new_candidates = sample_candidate_groups(
        records,
        group_count=requested_new_groups,
        min_features=min_features,
        max_features=max_features,
        seed=seed,
        target_profile=target_profile,
        start_index=start_index,
        existing_candidates=existing_candidates,
        covered_feature_uids=covered_feature_uids,
        existing_candidates_cover=coverage_basis == "candidate",
    )
    candidates = existing_candidates + new_candidates
    candidates_path = output_dir / "group-candidates.jsonl"
    write_jsonl(candidates_path, candidates)
    candidates_dir = output_dir / "candidates"
    for candidate in new_candidates if append_groups else candidates:
        write_json(candidates_dir / f"{candidate['candidate_id']}.input.json", candidate)
    used_uids = {
        uid for candidate in candidates for uid in candidate.get("source_feature_uids", [])
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "feature_pool": str(feature_pool_path),
        "feature_pool_sha256": hashlib.sha256(feature_pool_path.read_bytes()).hexdigest(),
        "output_dir": str(output_dir),
        "candidates_file": str(candidates_path),
        "configuration": {
            "group_count": len(candidates),
            "groups_added": len(new_candidates),
            "prior_group_count": prior_count,
            "append": bool(append_groups),
            "coverage_basis": coverage_basis,
            "min_features": min_features,
            "max_features": max_features,
            "seed": seed,
            "target_profile": target_profile,
            "allowed_languages": list(allowed_languages),
            "min_confidence": min_confidence,
        },
        "counts": {
            "feature_pool_records": len(records),
            "candidate_groups": len(candidates),
            "candidate_groups_added": len(new_candidates),
            "prior_candidate_groups": prior_count,
            "source_feature_slots": sum(len(item["source_feature_uids"]) for item in candidates),
            "unique_source_features": len(used_uids),
            "unique_source_bugs": len(
                {bug for item in candidates for bug in item.get("source_bug_ids", [])}
            ),
            "profile_anchor_candidates": sum(
                1 for record in records if matches_profile(record, target_profile)
            ),
            "ready_features_before_append": len(set(covered_feature_uids)),
        },
        "policy": {
            "source_features_are_immutable": True,
            "distinct_bug_per_source_feature_within_group": True,
            "group_llm_adds_glue_only": True,
            "api_key_persisted": False,
            "incremental_sampling_prioritizes_uncovered_ready_features": True,
            "coverage_basis": coverage_basis,
        },
    }
    write_json(output_dir / "prepare-manifest.json", manifest)
    return manifest


def build_messages(
    candidate: Mapping[str, Any],
    max_witness_chars: int = DEFAULT_MAX_WITNESS_CHARS,
) -> List[Dict[str, str]]:
    compact_features = [
        compact_source_feature(item, max_witness_chars)
        for item in candidate.get("source_features", [])
        if isinstance(item, dict)
    ]
    output_contract = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate["candidate_id"],
        "synthesis_status": "ready | rejected",
        "group_title": "short descriptive title",
        "group_summary": "how the source features become one interdependent compiler test",
        "language": "c | c++ | fortran | asm | ada | d | cobol | c-header | shell | rtl | other | unknown",
        "test_mode": "compile_only | execute_differential | diagnostic | assembly_scan | link_test",
        "target_options": ["jointly compatible compiler/target options"],
        "shared_execution_context": {
            "container": "single_function | call_chain | loop_nest | shared_type | translation_units | other",
            "description": "one unified context for all features",
            "shared_state": ["state/types/values shared by multiple features"],
            "control_flow": "ordering, nesting, or branch relationship",
            "data_flow": "how values flow between features",
        },
        "preservation_plan": [
            {
                "feature_uid": "one exact source feature_uid",
                "preserved_invariant": "the invariant retained without weakening or rewriting it",
                "placement": "where it belongs in the future program",
                "must_not_change": ["trigger-critical constraints"],
            }
        ],
        "dependencies": [
            {
                "from": "source feature_uid or glue_id",
                "to": "source feature_uid or glue_id",
                "kind": "data_flow | control_flow | type_flow | call_graph | target_context | oracle",
                "description": "concrete logical dependency",
            }
        ],
        "glue_features": [
            {
                "glue_id": "G1",
                "description": "new auxiliary semantic feature; do not restate a source feature",
                "semantic_role": "shared_state | control_flow | data_flow | type_bridge | wrapper | call_graph | target_setup | oracle_scaffolding",
                "code_witness": "short schematic snippet, not a complete program",
                "language": "c | c++ | fortran | asm | ada | d | cobol | c-header | shell | rtl | other | unknown",
                "connects": ["at least two source feature_uids or glue_ids"],
                "mutation_knobs": ["local variations for later PoC generation"],
                "composition_tags": ["recombination tags"],
                "novelty_rationale": "why this glue expands the semantic search space",
            }
        ],
        "instantiation_constraints": ["constraints for the later PoC generator"],
        "recommended_oracles": ["quality-test oracle with no exploit framing"],
        "semantic_risks": [
            {"risk": "undefined/implementation-defined behavior or option conflict", "mitigation": "how to avoid it"}
        ],
        "conflicts": ["empty for ready groups; concrete reasons for rejected groups"],
        "confidence": 0.75,
        "notes": "brief notes",
    }
    system = (
        "You are GroupLLM in a compiler CI quality-testing pipeline. This is not security testing and "
        "you must not discuss exploitation. Your input is a small set of immutable, bug-prone semantic "
        "features sampled from historical GCC quality reports. Do not generate a complete program. "
        "Synthesize only auxiliary glue semantics and a dependency plan that will allow a later model "
        "to instantiate one coherent PoC.\n\n"
        "Never edit, merge, delete, weaken, paraphrase away, or replace an input feature. Preserve every "
        "source feature as an independent invariant. Make features interact through shared data flow, "
        "control flow, types, calls, target setup, or a shared oracle. Prefer dependencies where one "
        "feature's value or control result becomes another feature's input. Add 1 to 4 genuinely new glue "
        "features. If the immutable features cannot coexist under one language/target/test mode, return "
        "synthesis_status=rejected and explain the conflict rather than inventing compatibility.\n\n"
        "For executable wrong-code tests, require defined and deterministic source-language behavior. "
        "Identify undefined behavior, implementation-defined behavior, incompatible target options, or "
        "conflicting failure oracles in semantic_risks. Compile-only and diagnostic groups may retain "
        "source features whose purpose is rejection or error handling. Return exactly one JSON object, "
        "without Markdown or prose outside JSON."
    )
    user = (
        "Build one coherent feature group from all sampled source features below. The source records are "
        "immutable. Refer to them only by the exact feature_uid in preservation_plan, dependencies, and "
        "glue_features.connects. Every source feature must have exactly one preservation_plan entry and "
        "must participate in the connected dependency graph. Glue code_witness values must be small "
        "schematic fragments, never a full test program.\n\n"
        "Required JSON shape:\n"
        f"{json.dumps(output_contract, ensure_ascii=False, indent=2)}\n\n"
        "Candidate context:\n"
        f"{json.dumps({'candidate_id': candidate['candidate_id'], 'target_profile': candidate.get('target_profile'), 'primary_language': candidate.get('primary_language'), 'sampling': candidate.get('sampling'), 'source_features': compact_features}, ensure_ascii=False, indent=2, sort_keys=True)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def chat_endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise PipelineError("DeepSeek API endpoint is empty")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def call_deepseek_chat(
    api_key: str,
    messages: Sequence[Mapping[str, str]],
    base_url: str,
    model: str,
    timeout: float = DEFAULT_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 0.25,
    response_format: bool = True,
) -> Dict[str, Any]:
    if not api_key:
        raise PipelineError("DeepSeek API key is empty")
    body: Dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        body["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        chat_endpoint(base_url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "loongarch-gcc-group-llm/0.1 compiler-quality-testing",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise PipelineError(redact_secrets(f"DeepSeek HTTP {error.code}: {error_body[:1000]}")) from error
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as error:
        raise PipelineError(redact_secrets(f"DeepSeek request failed: {error}")) from error
    except json.JSONDecodeError as error:
        raise ModelParseError(f"DeepSeek HTTP response was not JSON: {error}") from error
    if not isinstance(value, dict):
        raise ModelParseError("DeepSeek HTTP response JSON was not an object")
    return value


def parse_json_content(content: str) -> Dict[str, Any]:
    text = content.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as first_error:
        fence = CODE_FENCE_RE.search(text)
        if fence:
            candidate = fence.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise ModelParseError(f"model output did not contain a JSON object: {first_error}") from first_error
            candidate = text[start : end + 1]
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as error:
            raise ModelParseError(f"model output contained invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ModelParseError("model output JSON was not an object")
    return value


def extract_model_content(raw_response: Mapping[str, Any]) -> str:
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelParseError("DeepSeek response did not include choices")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not str(content or "").strip():
        raise ModelParseError("DeepSeek response content was empty")
    return str(content)


def validate_group(group: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    expected_candidate = str(candidate.get("candidate_id"))
    if str(group.get("candidate_id")) != expected_candidate:
        raise GroupValidationError(
            f"wrong candidate_id: {group.get('candidate_id')} != {expected_candidate}"
        )
    status = str(group.get("synthesis_status") or "")
    if status not in VALID_STATUSES:
        raise GroupValidationError(f"invalid synthesis_status: {status!r}")
    source_uids = [str(item) for item in candidate.get("source_feature_uids", [])]
    source_set = set(source_uids)
    if len(source_set) != len(source_uids) or len(source_uids) < 2:
        raise GroupValidationError("candidate source_feature_uids are invalid")
    if group.get("source_feature_uids") != source_uids:
        raise GroupValidationError("source_feature_uids differ from immutable candidate order")
    if group.get("source_features_sha256") != candidate.get("source_features_sha256"):
        raise GroupValidationError("source feature snapshot hash differs from candidate")
    if group.get("source_features") != candidate.get("source_features"):
        raise GroupValidationError("source feature objects were modified")
    if status == "rejected":
        if not string_list(group.get("conflicts")):
            raise GroupValidationError("rejected group must explain at least one conflict")
        return

    language = canonical_language(group.get("language"))
    if language not in VALID_LANGUAGES:
        raise GroupValidationError(f"invalid language: {group.get('language')!r}")
    if str(group.get("test_mode") or "") not in VALID_TEST_MODES:
        raise GroupValidationError(f"invalid test_mode: {group.get('test_mode')!r}")
    if not str(group.get("group_title") or "").strip() or not str(
        group.get("group_summary") or ""
    ).strip():
        raise GroupValidationError("ready group must include group_title and group_summary")
    try:
        confidence = float(group.get("confidence"))
    except (TypeError, ValueError) as error:
        raise GroupValidationError("ready group confidence must be numeric") from error
    if not 0.0 < confidence <= 1.0:
        raise GroupValidationError("ready group confidence must be greater than 0 and at most 1")
    if not string_list(group.get("instantiation_constraints")):
        raise GroupValidationError("ready group must include instantiation_constraints")
    if not string_list(group.get("recommended_oracles")):
        raise GroupValidationError("ready group must include recommended_oracles")
    shared_context = group.get("shared_execution_context")
    if not isinstance(shared_context, dict) or not str(shared_context.get("description") or "").strip():
        raise GroupValidationError("ready group lacks a shared_execution_context description")

    preservation = group.get("preservation_plan")
    if not isinstance(preservation, list):
        raise GroupValidationError("preservation_plan must be a list")
    preservation_uids = [
        str(item.get("feature_uid"))
        for item in preservation
        if isinstance(item, dict) and item.get("feature_uid")
    ]
    if len(preservation_uids) != len(source_uids) or set(preservation_uids) != source_set:
        raise GroupValidationError("preservation_plan must cover each source feature exactly once")
    for item in preservation:
        if not isinstance(item, dict) or not str(item.get("preserved_invariant") or "").strip():
            raise GroupValidationError("preservation_plan entry lacks preserved_invariant")

    glue_features = group.get("glue_features")
    if not isinstance(glue_features, list) or not glue_features:
        raise GroupValidationError("ready group must contain at least one glue feature")
    if len(glue_features) > 4:
        raise GroupValidationError("ready group must contain at most four glue features")
    glue_ids: List[str] = []
    for glue in glue_features:
        if not isinstance(glue, dict):
            raise GroupValidationError("glue feature must be an object")
        glue_id = str(glue.get("glue_id") or "")
        if not re.fullmatch(r"G[1-9][0-9]*", glue_id):
            raise GroupValidationError(f"invalid glue_id: {glue_id!r}")
        if glue_id in glue_ids:
            raise GroupValidationError(f"duplicate glue_id: {glue_id}")
        glue_ids.append(glue_id)
        witness = str(glue.get("code_witness") or "")
        if len(witness) > 4000:
            raise GroupValidationError(f"glue {glue_id} code_witness is too large for a schematic fragment")
        if not str(glue.get("description") or "").strip():
            raise GroupValidationError(f"glue {glue_id} lacks description")

    known_nodes = source_set.union(glue_ids)
    adjacency: Dict[str, Set[str]] = {node: set() for node in known_nodes}
    for glue in glue_features:
        glue_id = str(glue["glue_id"])
        connects = string_list(glue.get("connects"))
        if len(set(connects)) < 2:
            raise GroupValidationError(f"glue {glue_id} must connect at least two nodes")
        for node in connects:
            if node not in known_nodes or node == glue_id:
                raise GroupValidationError(f"glue {glue_id} references unknown/self node {node!r}")
            adjacency[glue_id].add(node)
            adjacency[node].add(glue_id)

    dependencies = group.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise GroupValidationError("ready group must contain dependencies")
    for edge in dependencies:
        if not isinstance(edge, dict):
            raise GroupValidationError("dependency must be an object")
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source not in known_nodes or target not in known_nodes or source == target:
            raise GroupValidationError(f"dependency contains invalid edge {source!r} -> {target!r}")
        adjacency[source].add(target)
        adjacency[target].add(source)

    visited = set()
    frontier = [source_uids[0]]
    while frontier:
        node = frontier.pop()
        if node in visited:
            continue
        visited.add(node)
        frontier.extend(adjacency[node] - visited)
    missing = source_set - visited
    if missing:
        raise GroupValidationError(f"source features are disconnected: {sorted(missing)}")


def normalize_group_output(
    candidate: Mapping[str, Any],
    raw_response: Mapping[str, Any],
    model: str,
    base_url: str,
) -> Dict[str, Any]:
    parsed = parse_json_content(extract_model_content(raw_response))
    parsed["schema_version"] = SCHEMA_VERSION
    parsed["candidate_id"] = str(parsed.get("candidate_id") or candidate["candidate_id"])
    parsed["synthesis_status"] = str(parsed.get("synthesis_status") or "ready").lower()
    parsed.setdefault("group_title", "")
    parsed.setdefault("group_summary", "")
    parsed["language"] = canonical_language(parsed.get("language"))
    parsed.setdefault("test_mode", "compile_only")
    parsed.setdefault("target_options", [])
    parsed.setdefault("shared_execution_context", {})
    parsed.setdefault("preservation_plan", [])
    parsed.setdefault("dependencies", [])
    parsed.setdefault("glue_features", [])
    parsed.setdefault("instantiation_constraints", [])
    parsed.setdefault("recommended_oracles", [])
    parsed.setdefault("semantic_risks", [])
    parsed.setdefault("conflicts", [])
    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("notes", "")
    parsed["target_profile"] = candidate.get("target_profile")
    parsed["source_feature_uids"] = list(candidate.get("source_feature_uids", []))
    parsed["source_bug_ids"] = list(candidate.get("source_bug_ids", []))
    parsed["source_features_sha256"] = candidate.get("source_features_sha256")
    parsed["source_features"] = json.loads(
        json.dumps(candidate.get("source_features", []), ensure_ascii=False)
    )
    parsed["sampling"] = candidate.get("sampling")
    usage = raw_response.get("usage") if isinstance(raw_response.get("usage"), dict) else {}
    parsed["generated_by"] = {
        "tool": "group-llm",
        "mode": "deepseek_chat_completions",
        "model": model,
        "base_url": base_url.rstrip("/"),
        "response_id": raw_response.get("id"),
        "created_at": utc_now(),
        "usage": usage,
        "api_key_persisted": False,
    }
    validate_group(parsed, candidate)
    parsed["group_uid"] = f"{candidate['candidate_id']}-{stable_hash({'sources': parsed['source_feature_uids'], 'glue': parsed['glue_features'], 'dependencies': parsed['dependencies']}, 16)}"
    return parsed


def candidate_output_path(output_dir: Path, candidate_id: str) -> Path:
    return output_dir / "groups" / f"{candidate_id}.group.json"


def raw_response_path(output_dir: Path, candidate_id: str) -> Path:
    return output_dir / "raw-responses" / f"{candidate_id}.deepseek-response.json"


def successful_existing_output(path: Path, candidate: Mapping[str, Any]) -> bool:
    if not path.is_file():
        return False
    try:
        value = read_json(path)
        validate_group(value, candidate)
    except (OSError, ValueError, json.JSONDecodeError, PipelineError):
        return False
    return True


def error_record(candidate: Mapping[str, Any], status: str, error: Exception) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate.get("candidate_id"),
        "synthesis_status": status,
        "source_feature_uids": candidate.get("source_feature_uids", []),
        "source_features_sha256": candidate.get("source_features_sha256"),
        "error": redact_secrets(str(error))[:2000],
        "failed_at": utc_now(),
    }


def synthesize_one(
    candidate: Mapping[str, Any],
    output_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    retries: int,
    timeout: float,
    max_tokens: int,
    temperature: float,
    response_format: bool,
    max_witness_chars: int,
) -> Dict[str, Any]:
    messages = build_messages(candidate, max_witness_chars=max_witness_chars)
    last_error: Optional[Exception] = None
    last_status = "api_error"
    for attempt in range(1, retries + 1):
        try:
            raw = call_deepseek_chat(
                api_key=api_key,
                messages=messages,
                base_url=base_url,
                model=model,
                timeout=timeout,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
            )
            write_json(raw_response_path(output_dir, str(candidate["candidate_id"])), raw)
            group = normalize_group_output(candidate, raw, model=model, base_url=base_url)
            write_json(candidate_output_path(output_dir, str(candidate["candidate_id"])), group)
            return {"candidate_id": candidate["candidate_id"], "status": group["synthesis_status"]}
        except ModelParseError as error:
            last_error = error
            last_status = "parse_error"
        except GroupValidationError as error:
            last_error = error
            last_status = "validation_error"
        except (PipelineError, OSError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            last_status = "api_error"
        if attempt < retries:
            if last_status in {"parse_error", "validation_error"}:
                messages = list(messages) + [
                    {
                        "role": "user",
                        "content": (
                            "The previous response was invalid: "
                            + redact_secrets(str(last_error))[:1000]
                            + ". Regenerate the entire JSON object and satisfy every contract constraint."
                        ),
                    }
                ]
            time.sleep(min(8.0, 1.5 * attempt))
    assert last_error is not None
    failure = error_record(candidate, last_status, last_error)
    write_json(candidate_output_path(output_dir, str(candidate["candidate_id"])), failure)
    return {"candidate_id": candidate["candidate_id"], "status": last_status, "error": failure["error"]}


def run_synthesis(
    output_dir: Path,
    env_file: Path,
    candidates_file: Optional[Path] = None,
    group_ids: Optional[Sequence[str]] = None,
    limit: int = 0,
    refresh: bool = False,
    retries: int = 3,
    workers: int = 4,
    timeout: float = DEFAULT_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 0.25,
    response_format: bool = True,
    max_witness_chars: int = DEFAULT_MAX_WITNESS_CHARS,
) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    candidate_path = candidates_file.resolve() if candidates_file else output_dir / "group-candidates.jsonl"
    if not candidate_path.is_file():
        raise PipelineError(f"candidate file does not exist: {candidate_path}; run prepare first")
    values = load_env_file(env_file.resolve())
    api_key = values.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = values.get("DEEPSEEK_API_ENDPOINT") or os.environ.get(
        "DEEPSEEK_API_ENDPOINT", DEFAULT_BASE_URL
    )
    model = values.get("DEEPSEEK_MODEL") or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
    if not api_key:
        raise PipelineError("DEEPSEEK_API_KEY is not set in the env file or process environment")
    if retries <= 0 or workers <= 0 or timeout <= 0 or max_tokens <= 0:
        raise PipelineError("retries/workers/timeout/max_tokens must be positive")

    requested = set(group_ids or [])
    candidate_inventory = [item for item in iter_jsonl(candidate_path)]
    candidates = list(candidate_inventory)
    if requested:
        known = {str(item.get("candidate_id")) for item in candidates}
        missing = requested - known
        if missing:
            raise PipelineError(f"unknown group ids: {sorted(missing)}")
        candidates = [item for item in candidates if str(item.get("candidate_id")) in requested]
    if limit > 0:
        candidates = candidates[:limit]

    skipped: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for candidate in candidates:
        output_path = candidate_output_path(output_dir, str(candidate["candidate_id"]))
        if not refresh and successful_existing_output(output_path, candidate):
            existing = read_json(output_path)
            skipped.append(
                {"candidate_id": candidate["candidate_id"], "status": existing["synthesis_status"]}
            )
        else:
            pending.append(candidate)

    results: List[Dict[str, Any]] = list(skipped)
    print_lock = threading.Lock()

    def run_and_report(candidate: Dict[str, Any]) -> Dict[str, Any]:
        result = synthesize_one(
            candidate=candidate,
            output_dir=output_dir,
            api_key=api_key,
            base_url=base_url,
            model=model,
            retries=retries,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
            max_witness_chars=max_witness_chars,
        )
        with print_lock:
            print(f"[{result['status']}] {result['candidate_id']}", flush=True)
        return result

    if workers == 1:
        for candidate in pending:
            results.append(run_and_report(candidate))
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run_and_report, item): item for item in pending}
            for future in as_completed(futures):
                results.append(future.result())

    selected_counts = Counter(str(item.get("status")) for item in results)
    inventory_counts: Counter = Counter()
    inventory_missing = 0
    usage_totals: Counter = Counter()
    for candidate in candidate_inventory:
        path = candidate_output_path(output_dir, str(candidate["candidate_id"]))
        if not path.is_file():
            inventory_missing += 1
            continue
        value = read_json(path)
        inventory_counts[str(value.get("synthesis_status") or "unknown")] += 1
        generated = value.get("generated_by") if isinstance(value.get("generated_by"), dict) else {}
        usage = generated.get("usage") if isinstance(generated.get("usage"), dict) else {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                usage_totals[key] += int(usage.get(key) or 0)
            except (TypeError, ValueError):
                pass
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "candidates_file": str(candidate_path),
        "env_file": str(env_file.resolve()),
        "configuration": {
            "model": model,
            "base_url": base_url.rstrip("/"),
            "retries": retries,
            "workers": workers,
            "timeout": timeout,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": response_format,
            "max_witness_chars": max_witness_chars,
            "refresh": refresh,
            "api_key_persisted": False,
        },
        "counts": {
            "candidate_inventory": len(candidate_inventory),
            "selected_candidates": len(candidates),
            "submitted": len(pending),
            "skipped_valid_outputs": len(skipped),
            "inventory_missing_outputs": inventory_missing,
            "inventory_statuses": dict(sorted(inventory_counts.items())),
            "selected_statuses": dict(sorted(selected_counts.items())),
        },
        "usage": dict(usage_totals),
    }
    write_json(output_dir / "group-run-manifest.json", manifest)
    return manifest


def load_candidates(output_dir: Path) -> List[Dict[str, Any]]:
    path = output_dir.resolve() / "group-candidates.jsonl"
    if not path.is_file():
        raise PipelineError(f"candidate file does not exist: {path}")
    return list(iter_jsonl(path))


def load_group_results(output_dir: Path) -> List[Dict[str, Any]]:
    results = []
    for candidate in load_candidates(output_dir):
        path = candidate_output_path(output_dir.resolve(), str(candidate["candidate_id"]))
        if path.is_file():
            results.append(read_json(path))
    return results


def build_feature_coverage(
    output_dir: Path,
    candidates: Sequence[Mapping[str, Any]],
    ready_groups: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Write feature-level candidate/ready coverage and the remaining backlog."""

    prepare_path = output_dir / "prepare-manifest.json"
    if not prepare_path.is_file():
        return {}
    prepare = read_json(prepare_path)
    pool_path = Path(str(prepare.get("feature_pool") or ""))
    if not pool_path.is_file():
        return {}
    pool = list(iter_jsonl(pool_path))
    candidate_counts = Counter(
        str(uid) for candidate in candidates for uid in candidate.get("source_feature_uids", [])
    )
    ready_counts = Counter(
        str(uid) for group in ready_groups for uid in group.get("source_feature_uids", [])
    )
    coverage_records: List[Dict[str, Any]] = []
    for record in pool:
        uid = feature_uid(record)
        if ready_counts[uid]:
            status = "ready_covered"
        elif candidate_counts[uid]:
            status = "candidate_only"
        else:
            status = "never_sampled"
        coverage_records.append(
            {
                **record,
                "group_coverage": {
                    "status": status,
                    "candidate_group_count": candidate_counts[uid],
                    "ready_group_count": ready_counts[uid],
                },
            }
        )
    write_jsonl(output_dir / "feature-coverage.jsonl", coverage_records)
    uncovered = [
        record
        for record in coverage_records
        if record["group_coverage"]["status"] != "ready_covered"
    ]
    write_jsonl(output_dir / "uncovered-features.jsonl", uncovered)

    configuration = prepare.get("configuration") if isinstance(prepare.get("configuration"), dict) else {}
    allowed_languages = configuration.get("allowed_languages") or list(DEFAULT_LANGUAGES)
    configured_min_confidence = configuration.get("min_confidence")
    min_confidence = float(
        DEFAULT_MIN_CONFIDENCE
        if configured_min_confidence is None
        else configured_min_confidence
    )
    eligible = load_feature_pool(pool_path, allowed_languages, min_confidence)
    eligible_uids = {feature_uid(record) for record in eligible}
    ready_uids = set(ready_counts)
    candidate_uids = set(candidate_counts)
    by_status = Counter(record["group_coverage"]["status"] for record in coverage_records)
    uncovered_by_language = Counter(
        str(feature_object(record).get("language") or "unknown") for record in uncovered
    )
    uncovered_by_type = Counter(
        str(feature_object(record).get("feature_type") or "unknown") for record in uncovered
    )
    covered_by_language = Counter(
        str(feature_object(record).get("language") or "unknown")
        for record in coverage_records
        if record["group_coverage"]["status"] == "ready_covered"
    )
    counts = {
        "feature_pool_records": len(pool),
        "eligible_feature_pool_records": len(eligible_uids),
        "candidate_covered_features": len(candidate_uids),
        "eligible_candidate_covered_features": len(candidate_uids.intersection(eligible_uids)),
        "ready_covered_features": len(ready_uids),
        "eligible_ready_covered_features": len(ready_uids.intersection(eligible_uids)),
        "candidate_only_features": by_status["candidate_only"],
        "never_sampled_features": by_status["never_sampled"],
        "eligible_never_sampled_features": len(eligible_uids - candidate_uids),
        "uncovered_features": len(uncovered),
        "ready_coverage_of_full_pool": round(len(ready_uids) / len(pool), 4) if pool else 0.0,
        "ready_coverage_of_eligible_pool": round(
            len(ready_uids.intersection(eligible_uids)) / len(eligible_uids), 4
        )
        if eligible_uids
        else 0.0,
        "candidate_coverage_of_full_pool": round(len(candidate_uids) / len(pool), 4)
        if pool
        else 0.0,
        "candidate_coverage_of_eligible_pool": round(
            len(candidate_uids.intersection(eligible_uids)) / len(eligible_uids), 4
        )
        if eligible_uids
        else 0.0,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "feature_pool": str(pool_path.resolve()),
        "files": {
            "all_feature_coverage": str(output_dir / "feature-coverage.jsonl"),
            "uncovered_features": str(output_dir / "uncovered-features.jsonl"),
        },
        "counts": counts,
        "by_status": dict(sorted(by_status.items())),
        "covered_by_language": dict(sorted(covered_by_language.items())),
        "uncovered_by_language": dict(sorted(uncovered_by_language.items())),
        "uncovered_by_type": dict(sorted(uncovered_by_type.items())),
    }
    write_json(output_dir / "feature-coverage-manifest.json", manifest)
    return manifest


def build_group_pool(output_dir: Path) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    candidates = load_candidates(output_dir)
    by_id = {str(item["candidate_id"]): item for item in candidates}
    results = load_group_results(output_dir)
    ready: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for result in results:
        candidate_id = str(result.get("candidate_id"))
        candidate = by_id.get(candidate_id)
        status = str(result.get("synthesis_status") or "")
        if candidate is None:
            errors.append(result)
        elif status in VALID_STATUSES:
            validate_group(result, candidate)
            (ready if status == "ready" else rejected).append(result)
        else:
            errors.append(result)
    ready.sort(key=lambda item: str(item.get("candidate_id")))
    all_results = sorted(results, key=lambda item: str(item.get("candidate_id")))
    write_jsonl(output_dir / "feature-groups.jsonl", ready)
    write_json(output_dir / "feature-groups.json", {"schema_version": SCHEMA_VERSION, "groups": ready})
    write_jsonl(output_dir / "feature-group-results.jsonl", all_results)

    source_uids = {
        uid for group in ready for uid in group.get("source_feature_uids", [])
    }
    source_bugs = {bug for group in ready for bug in group.get("source_bug_ids", [])}
    glue_roles = Counter(
        str(glue.get("semantic_role") or "unknown")
        for group in ready
        for glue in group.get("glue_features", [])
        if isinstance(glue, dict)
    )
    languages = Counter(str(group.get("language") or "unknown") for group in ready)
    test_modes = Counter(str(group.get("test_mode") or "unknown") for group in ready)
    error_statuses = Counter(str(item.get("synthesis_status") or "unknown") for item in errors)
    glue_count = sum(len(group.get("glue_features", [])) for group in ready)
    source_slots = sum(len(group.get("source_feature_uids", [])) for group in ready)
    coverage = build_feature_coverage(output_dir, candidates, ready)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "files": {
            "ready_jsonl": str(output_dir / "feature-groups.jsonl"),
            "ready_json": str(output_dir / "feature-groups.json"),
            "all_results_jsonl": str(output_dir / "feature-group-results.jsonl"),
        },
        "counts": {
            "candidate_groups": len(candidates),
            "outputs": len(results),
            "ready_groups": len(ready),
            "rejected_groups": len(rejected),
            "error_outputs": len(errors),
            "missing_outputs": len(candidates) - len(results),
            "source_feature_slots": source_slots,
            "unique_source_features": len(source_uids),
            "unique_source_bugs": len(source_bugs),
            "glue_features": glue_count,
            "average_source_features_per_ready_group": round(source_slots / len(ready), 3)
            if ready
            else 0.0,
            "average_glue_features_per_ready_group": round(glue_count / len(ready), 3)
            if ready
            else 0.0,
        },
        "by_language": dict(sorted(languages.items())),
        "by_test_mode": dict(sorted(test_modes.items())),
        "by_glue_role": dict(sorted(glue_roles.items())),
        "error_statuses": dict(sorted(error_statuses.items())),
        "feature_coverage": coverage.get("counts", {}),
        "policy": {
            "ready_pool_excludes_rejected_and_error_outputs": True,
            "source_features_are_immutable": True,
            "glue_features_require_future_coverage_validation_before_pool_promotion": True,
        },
    }
    write_json(output_dir / "feature-group-manifest.json", manifest)
    write_group_summary(output_dir / "FEATURE_GROUPS_SUMMARY.md", manifest)
    return manifest


def write_group_summary(path: Path, manifest: Mapping[str, Any]) -> None:
    counts = manifest.get("counts", {})
    coverage = manifest.get("feature_coverage", {})
    lines = [
        "# GroupLLM Feature Group Summary",
        "",
        "This pool is for compiler CI quality testing of the owned LoongArch GCC fork, not security testing.",
        "",
        "## Totals",
        "",
        f"- Candidate groups: {counts.get('candidate_groups', 0)}",
        f"- Ready groups: {counts.get('ready_groups', 0)}",
        f"- Rejected groups: {counts.get('rejected_groups', 0)}",
        f"- Error outputs: {counts.get('error_outputs', 0)}",
        f"- Missing outputs: {counts.get('missing_outputs', 0)}",
        f"- Source feature slots: {counts.get('source_feature_slots', 0)}",
        f"- Unique source features: {counts.get('unique_source_features', 0)}",
        f"- Unique source bugs: {counts.get('unique_source_bugs', 0)}",
        f"- Synthesized glue features: {counts.get('glue_features', 0)}",
        f"- Ready feature coverage: {coverage.get('ready_covered_features', 0)} / {coverage.get('feature_pool_records', 0)} ({100 * float(coverage.get('ready_coverage_of_full_pool', 0.0)):.2f}%)",
        f"- Eligible-pool ready coverage: {coverage.get('eligible_ready_covered_features', 0)} / {coverage.get('eligible_feature_pool_records', 0)} ({100 * float(coverage.get('ready_coverage_of_eligible_pool', 0.0)):.2f}%)",
        "",
        "## Distribution",
        "",
        f"- Languages: {json.dumps(manifest.get('by_language', {}), ensure_ascii=False, sort_keys=True)}",
        f"- Test modes: {json.dumps(manifest.get('by_test_mode', {}), ensure_ascii=False, sort_keys=True)}",
        f"- Glue roles: {json.dumps(manifest.get('by_glue_role', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "## Handoff",
        "",
        "Each ready record preserves the exact ExtractLLM source-feature snapshot, then adds a shared execution context, preservation plan, dependency graph, glue features, instantiation constraints, semantic-risk review, and recommended quality-test oracles. The next InstanLLM stage should generate a program from these constraints and must validate compilation, defined behavior, and coverage before any glue feature is promoted into the global pool.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def verify_outputs(
    output_dir: Path,
    require_outputs: bool = False,
    fail_on_error: bool = False,
    min_ready_ratio: float = 0.0,
) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    if min_ready_ratio < 0.0 or min_ready_ratio > 1.0:
        raise PipelineError("min_ready_ratio must be between 0 and 1")
    candidates = load_candidates(output_dir)
    by_id = {str(item["candidate_id"]): item for item in candidates}
    statuses: Counter = Counter()
    missing = []
    invalid = []
    ready = 0
    for candidate_id, candidate in by_id.items():
        path = candidate_output_path(output_dir, candidate_id)
        if not path.is_file():
            missing.append(candidate_id)
            continue
        try:
            result = read_json(path)
            status = str(result.get("synthesis_status") or "unknown")
            statuses[status] += 1
            if status in VALID_STATUSES:
                validate_group(result, candidate)
                if status == "ready":
                    ready += 1
            else:
                invalid.append(f"{candidate_id}: {status}")
        except (OSError, ValueError, json.JSONDecodeError, PipelineError) as error:
            invalid.append(f"{candidate_id}: {redact_secrets(str(error))}")
    if require_outputs and missing:
        raise PipelineError(f"missing {len(missing)} group outputs; first: {missing[:5]}")
    if fail_on_error and invalid:
        raise PipelineError(f"invalid/error group outputs: {len(invalid)}; first: {invalid[:3]}")
    ready_ratio = ready / len(candidates) if candidates else 0.0
    if ready_ratio < min_ready_ratio:
        raise PipelineError(
            f"ready ratio {ready_ratio:.3f} is below required {min_ready_ratio:.3f}"
        )

    consolidated_path = output_dir / "feature-groups.jsonl"
    consolidated = list(iter_jsonl(consolidated_path)) if consolidated_path.is_file() else []
    consolidated_ids = [str(item.get("candidate_id")) for item in consolidated]
    if len(consolidated_ids) != len(set(consolidated_ids)):
        raise PipelineError("feature-groups.jsonl contains duplicate candidate_id values")
    if consolidated:
        expected_ready = {
            candidate_id
            for candidate_id, candidate in by_id.items()
            if successful_existing_output(candidate_output_path(output_dir, candidate_id), candidate)
            and read_json(candidate_output_path(output_dir, candidate_id)).get("synthesis_status") == "ready"
        }
        if set(consolidated_ids) != expected_ready:
            raise PipelineError("consolidated ready pool is stale; run build-groups")
    return {
        "schema_version": SCHEMA_VERSION,
        "verified_at": utc_now(),
        "counts": {
            "candidate_groups": len(candidates),
            "outputs": len(candidates) - len(missing),
            "missing_outputs": len(missing),
            "invalid_or_error_outputs": len(invalid),
            "ready_groups": ready,
            "ready_ratio": round(ready_ratio, 4),
            "consolidated_ready_groups": len(consolidated),
            "statuses": dict(sorted(statuses.items())),
        },
    }
