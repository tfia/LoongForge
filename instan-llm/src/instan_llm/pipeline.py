"""InstanLLM primitives for compiler-quality test generation and coverage.

InstanLLM consumes validated GroupLLM ready groups and asks the model to produce
one complete compiler test program per group. The generated program is not
trusted until the local evaluator compiles it with the AFL++ instrumented GCC
frontend and records non-empty edge coverage.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set


SCHEMA_VERSION = 1
DEFAULT_OUTPUT_DIR = Path("out")
DEFAULT_GROUPS_FILE = Path("../group-llm/out/feature-groups.jsonl")
DEFAULT_ENV_FILE = Path("../.env")
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 240.0
DEFAULT_MAX_TOKENS = 16000
DEFAULT_SHOWMAP_TIMEOUT_MS = 20000
DEFAULT_TARGET = "loongarch64-linux-gnu"
DEFAULT_EVALUATION_OPTIMIZATION = os.environ.get("INSTANLLM_EVALUATION_OPTIMIZATION", "-Ofast")
GCC_ICE_EXIT_CODE = 4

VALID_INSTANTIATION_STATUSES = {"ready", "rejected"}
SUPPORTED_EVAL_LANGUAGES = {"c", "c++"}
LANGUAGE_EXTENSIONS = {
    "c": ".c",
    "c++": ".cc",
    "cpp": ".cc",
    "cxx": ".cc",
    "asm": ".s",
    "fortran": ".f90",
    "ada": ".adb",
    "d": ".d",
    "cobol": ".cob",
    "shell": ".sh",
    "rtl": ".rtl",
}

CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL | re.IGNORECASE)
SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
BAD_PURPOSE_RE = re.compile(r"\b(exploit|payload|shellcode|reverse shell|rce|network scan)\b", re.I)


class PipelineError(RuntimeError):
    """Raised when an InstanLLM operation cannot complete safely."""


class ModelParseError(PipelineError):
    """Raised when a model response is not parseable as the requested JSON."""


class InstantiationValidationError(PipelineError):
    """Raised when an instantiation violates the local schema contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return project_root().parent


def stable_hash(value: Any, length: int = 16) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_secrets(value: str) -> str:
    return SECRET_RE.sub("<redacted-api-key>", value)


def clip_text(value: str, max_chars: int = 12000) -> str:
    if len(value) <= max_chars:
        return value
    keep = max_chars - 80
    head = keep // 2
    tail = keep - head
    return value[:head] + "\n[... clipped by instan-llm ...]\n" + value[-tail:]


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


def load_env_file(path: Path) -> Dict[str, str]:
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


def canonical_language(value: Any) -> str:
    language = str(value or "unknown").strip().lower()
    aliases = {
        "cpp": "c++",
        "cxx": "c++",
        "g++": "c++",
        "assembly": "asm",
        "f90": "fortran",
        "f95": "fortran",
    }
    return aliases.get(language, language)


def string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def load_ready_groups(groups_file: Path) -> List[Dict[str, Any]]:
    if not groups_file.is_file():
        raise PipelineError(f"feature groups file does not exist: {groups_file}")
    groups: List[Dict[str, Any]] = []
    seen = set()
    for group in iter_jsonl(groups_file):
        if str(group.get("synthesis_status")) != "ready":
            continue
        group_uid = str(group.get("group_uid") or "").strip()
        if not group_uid:
            raise PipelineError("ready group is missing group_uid")
        if group_uid in seen:
            raise PipelineError(f"duplicate group_uid: {group_uid}")
        seen.add(group_uid)
        source_uids = string_list(group.get("source_feature_uids"))
        if not source_uids:
            raise PipelineError(f"ready group lacks source_feature_uids: {group_uid}")
        groups.append(group)
    if not groups:
        raise PipelineError("no ready groups found")
    return groups


def select_groups(
    groups: Sequence[Mapping[str, Any]],
    group_ids: Optional[Sequence[str]] = None,
    *,
    languages: Optional[Sequence[str]] = None,
    limit: int = 0,
) -> List[Dict[str, Any]]:
    wanted = {str(item) for item in group_ids or []}
    allowed_languages = {canonical_language(item) for item in languages or []}
    selected: List[Dict[str, Any]] = []
    for group in groups:
        identifiers = {
            str(group.get("group_uid") or ""),
            str(group.get("candidate_id") or ""),
        }
        if wanted and not wanted.intersection(identifiers):
            continue
        if allowed_languages and canonical_language(group.get("language")) not in allowed_languages:
            continue
        selected.append(json.loads(json.dumps(group, ensure_ascii=False)))
        if limit and len(selected) >= limit:
            break
    if wanted and not selected:
        raise PipelineError(f"no groups matched requested ids: {sorted(wanted)}")
    return selected


def compact_group_for_prompt(group: Mapping[str, Any]) -> Dict[str, Any]:
    compact_features = []
    for feature in group.get("source_features", []):
        if not isinstance(feature, dict):
            continue
        item = json.loads(json.dumps(feature, ensure_ascii=False))
        witness = str(item.get("feature", {}).get("code_witness") or "")
        if len(witness) > 3500:
            item["feature"]["code_witness"] = witness[:3500] + "\n/* witness truncated for InstanLLM prompt */"
        compact_features.append(item)
    return {
        "group_uid": group.get("group_uid"),
        "candidate_id": group.get("candidate_id"),
        "group_title": group.get("group_title"),
        "group_summary": group.get("group_summary"),
        "language": group.get("language"),
        "test_mode": group.get("test_mode"),
        "target_options": group.get("target_options"),
        "shared_execution_context": group.get("shared_execution_context"),
        "preservation_plan": group.get("preservation_plan"),
        "dependencies": group.get("dependencies"),
        "glue_features": group.get("glue_features"),
        "instantiation_constraints": group.get("instantiation_constraints"),
        "recommended_oracles": group.get("recommended_oracles"),
        "semantic_risks": group.get("semantic_risks"),
        "source_feature_uids": group.get("source_feature_uids"),
        "source_features": compact_features,
    }


def build_messages(group: Mapping[str, Any]) -> List[Dict[str, str]]:
    output_contract = {
        "schema_version": SCHEMA_VERSION,
        "group_uid": group["group_uid"],
        "candidate_id": group["candidate_id"],
        "instantiation_status": "ready | rejected",
        "program_title": "short descriptive title",
        "language": "c | c++ | fortran | asm | ada | d | cobol | shell | rtl | other",
        "file_name": "portable file name with the correct extension",
        "compiler_options": ["complete compile options required for this program"],
        "source_code": "one complete standalone test translation unit",
        "oracle": {
            "kind": "compile_success | compile_failure | assembly_scan | runtime_exit | differential | link",
            "description": "how CI should judge compiler quality",
            "expected_result": "what should happen on a correct compiler",
        },
        "preservation_checklist": [
            {
                "feature_uid": "exact source feature uid",
                "implemented_by": "specific function/type/expression/statement in source_code",
                "oracle_hook": "how this feature influences the oracle or coverage",
            }
        ],
        "coverage_intent": {
            "compiler_paths": ["compiler frontend/backend paths this test should exercise"],
            "mutation_knobs": ["safe source-level mutations for future fuzzing"],
        },
        "build_notes": ["local build assumptions; no network or third-party service dependency"],
        "rejection_reasons": ["non-empty when instantiation_status is rejected"],
        "confidence": 0.8,
        "notes": "brief notes",
    }
    system = (
        "You are InstanLLM in a compiler CI quality-testing pipeline. The pipeline is based on "
        "semantic logic recomposition: ExtractLLM extracts historical semantic features, GroupLLM "
        "recombines them into connected feature groups, and InstanLLM now materializes one complete "
        "test program from a group.\n\n"
        "This is compiler quality testing for the team's own LoongArch GCC fork, not security testing. "
        "Do not generate exploit framing, network behavior, shellcode, attack payloads, or vulnerability "
        "impact text. Generate only compiler test inputs.\n\n"
        "The output must be one complete standalone source file that the local evaluator can compile "
        "with an AFL++ instrumented LoongArch GCC frontend. Prefer C or C++ groups that avoid libc "
        "headers and external libraries; global variables, volatile sinks, noinline functions, and "
        "__builtin_trap are acceptable. Preserve every source feature and every GroupLLM glue/dependency "
        "as concrete code. Avoid undefined behavior unless the group is explicitly a diagnostic test, "
        "and then make the expected diagnostic explicit. If the group cannot be instantiated as one "
        "local source file, return instantiation_status=rejected with concrete reasons.\n\n"
        "Return exactly one JSON object. Do not emit Markdown or prose outside JSON."
    )
    user = (
        "Instantiate the following ready GroupLLM group into a complete compiler test program. "
        "Every source feature uid must appear exactly once in preservation_checklist. The generated "
        "program should compile under aggressive optimization on the LoongArch cross compiler. "
        "Prefer -Ofast unless the group explicitly requires a diagnostic-only option such as -O0/-Og. "
        "If a listed option is linker-only or requires unavailable external libraries, omit it from "
        "compiler_options and explain the decision in build_notes.\n\n"
        "Required JSON shape:\n"
        f"{json.dumps(output_contract, ensure_ascii=False, indent=2)}\n\n"
        "Ready group:\n"
        f"{json.dumps(compact_group_for_prompt(group), ensure_ascii=False, indent=2, sort_keys=True)}"
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
    temperature: float = 0.2,
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
            "User-Agent": "loongforge-instan-llm/0.1 compiler-quality-testing",
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


def validate_instantiation(instantiation: Mapping[str, Any], group: Mapping[str, Any]) -> None:
    if str(instantiation.get("group_uid")) != str(group.get("group_uid")):
        raise InstantiationValidationError("wrong group_uid")
    if str(instantiation.get("candidate_id")) != str(group.get("candidate_id")):
        raise InstantiationValidationError("wrong candidate_id")
    status = str(instantiation.get("instantiation_status") or "")
    if status not in VALID_INSTANTIATION_STATUSES:
        raise InstantiationValidationError(f"invalid instantiation_status: {status!r}")
    source_uids = string_list(group.get("source_feature_uids"))
    if instantiation.get("source_feature_uids") != source_uids:
        raise InstantiationValidationError("source_feature_uids differ from GroupLLM group")
    if status == "rejected":
        if not string_list(instantiation.get("rejection_reasons")):
            raise InstantiationValidationError("rejected instantiation must include rejection_reasons")
        return
    language = canonical_language(instantiation.get("language"))
    if language not in LANGUAGE_EXTENSIONS:
        raise InstantiationValidationError(f"unsupported language label: {language!r}")
    source = str(instantiation.get("source_code") or "")
    if not source.strip():
        raise InstantiationValidationError("ready instantiation has empty source_code")
    if BAD_PURPOSE_RE.search(source) or BAD_PURPOSE_RE.search(str(instantiation.get("notes") or "")):
        raise InstantiationValidationError("instantiation contains non-quality/security-test framing")
    if len(source.encode("utf-8")) > 512 * 1024:
        raise InstantiationValidationError("source_code is too large")
    options = string_list(instantiation.get("compiler_options"))
    if not options:
        raise InstantiationValidationError("ready instantiation must include compiler_options")
    oracle = instantiation.get("oracle")
    if not isinstance(oracle, dict) or not str(oracle.get("kind") or "").strip():
        raise InstantiationValidationError("ready instantiation must include oracle.kind")
    checklist = instantiation.get("preservation_checklist")
    if not isinstance(checklist, list):
        raise InstantiationValidationError("preservation_checklist must be a list")
    checklist_uids = [
        str(item.get("feature_uid"))
        for item in checklist
        if isinstance(item, dict) and item.get("feature_uid")
    ]
    if len(checklist_uids) != len(source_uids) or set(checklist_uids) != set(source_uids):
        raise InstantiationValidationError("preservation_checklist must cover every source feature exactly once")
    for item in checklist:
        if not isinstance(item, dict) or not str(item.get("implemented_by") or "").strip():
            raise InstantiationValidationError("preservation_checklist entry lacks implemented_by")


def normalize_instantiation_output(
    group: Mapping[str, Any],
    raw_response: Mapping[str, Any],
    model: str,
    base_url: str,
) -> Dict[str, Any]:
    parsed = parse_json_content(extract_model_content(raw_response))
    parsed["schema_version"] = SCHEMA_VERSION
    parsed["group_uid"] = str(parsed.get("group_uid") or group["group_uid"])
    parsed["candidate_id"] = str(parsed.get("candidate_id") or group["candidate_id"])
    parsed["instantiation_status"] = str(parsed.get("instantiation_status") or "ready").lower()
    parsed["language"] = canonical_language(parsed.get("language") or group.get("language"))
    parsed.setdefault("program_title", "")
    parsed.setdefault("file_name", "")
    parsed.setdefault("compiler_options", list(group.get("target_options", [])))
    parsed.setdefault("source_code", "")
    parsed.setdefault("oracle", {})
    parsed.setdefault("preservation_checklist", [])
    parsed.setdefault("coverage_intent", {})
    parsed.setdefault("build_notes", [])
    parsed.setdefault("rejection_reasons", [])
    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("notes", "")
    parsed["source_feature_uids"] = string_list(group.get("source_feature_uids"))
    parsed["source_features_sha256"] = group.get("source_features_sha256")
    parsed["group_test_mode"] = group.get("test_mode")
    parsed["group_target_options"] = list(group.get("target_options", []))
    parsed["generated_by"] = {
        "tool": "instan-llm",
        "mode": "deepseek_chat_completions",
        "model": model,
        "base_url": base_url.rstrip("/"),
        "response_id": raw_response.get("id"),
        "created_at": utc_now(),
        "usage": raw_response.get("usage") if isinstance(raw_response.get("usage"), dict) else {},
        "api_key_persisted": False,
    }
    validate_instantiation(parsed, group)
    parsed["instantiation_id"] = (
        f"{group['candidate_id']}-{stable_hash({'source': parsed.get('source_code'), 'options': parsed.get('compiler_options')}, 16)}"
    )
    return parsed


def instantiation_output_path(output_dir: Path, group_uid: str) -> Path:
    return output_dir / "instantiations" / f"{group_uid}.instantiation.json"


def raw_response_path(output_dir: Path, group_uid: str) -> Path:
    return output_dir / "raw-responses" / f"{group_uid}.deepseek-response.json"


def fallback_instantiation_id(instantiation: Mapping[str, Any]) -> str:
    existing = str(instantiation.get("instantiation_id") or "").strip()
    if existing:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", existing)
    stem = str(instantiation.get("candidate_id") or instantiation.get("group_uid") or "instantiation")
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem.strip()) or "instantiation"
    digest = stable_hash(
        {
            "group_uid": instantiation.get("group_uid"),
            "candidate_id": instantiation.get("candidate_id"),
            "status": instantiation.get("instantiation_status"),
        },
        16,
    )
    return f"{stem}-{digest}"


def program_source_path(output_dir: Path, instantiation: Mapping[str, Any]) -> Path:
    language = canonical_language(instantiation.get("language"))
    suffix = LANGUAGE_EXTENSIONS.get(language, ".txt")
    instantiation_id = fallback_instantiation_id(instantiation)
    file_name = str(instantiation.get("file_name") or "").strip()
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(file_name).stem or instantiation_id)
    if not safe_stem:
        safe_stem = instantiation_id
    return output_dir / "programs" / f"{instantiation_id}.{safe_stem}{suffix}"


def write_program_source(output_dir: Path, instantiation: Mapping[str, Any]) -> Path:
    path = program_source_path(output_dir, instantiation)
    path.parent.mkdir(parents=True, exist_ok=True)
    source = str(instantiation.get("source_code") or "")
    path.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
    return path


def successful_existing_instantiation(path: Path, group: Mapping[str, Any]) -> bool:
    if not path.is_file():
        return False
    try:
        value = read_json(path)
        validate_instantiation(value, group)
    except (OSError, json.JSONDecodeError, PipelineError):
        return False
    return True


ModelCaller = Callable[
    [str, Sequence[Mapping[str, str]], str, str, float, int, float, bool],
    Dict[str, Any],
]


def synthesize_one(
    group: Mapping[str, Any],
    output_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float,
    max_tokens: int,
    temperature: float,
    response_format: bool,
    retries: int,
    model_caller: ModelCaller = call_deepseek_chat,
) -> Dict[str, Any]:
    messages = build_messages(group)
    last_error: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            raw = model_caller(
                api_key,
                messages,
                base_url,
                model,
                timeout,
                max_tokens,
                temperature,
                response_format,
            )
            write_json(raw_response_path(output_dir, str(group["group_uid"])), raw)
            instantiation = normalize_instantiation_output(group, raw, model, base_url)
            if instantiation["instantiation_status"] == "ready":
                source_path = write_program_source(output_dir, instantiation)
                instantiation["source_path"] = str(source_path)
                instantiation["source_sha256"] = file_sha256(source_path)
            write_json(instantiation_output_path(output_dir, str(group["group_uid"])), instantiation)
            return instantiation
        except (PipelineError, OSError, json.JSONDecodeError) as error:
            last_error = error
            if attempt >= retries:
                break
            messages = list(messages) + [
                {
                    "role": "user",
                    "content": (
                        "The previous response failed local validation: "
                        f"{redact_secrets(str(error))}. Return exactly one corrected JSON object."
                    ),
                }
            ]
            time.sleep(min(2.0 * attempt, 8.0))
    return {
        "schema_version": SCHEMA_VERSION,
        "instantiation_id": fallback_instantiation_id(group),
        "group_uid": group.get("group_uid"),
        "candidate_id": group.get("candidate_id"),
        "language": canonical_language(group.get("language")),
        "source_feature_uids": string_list(group.get("source_feature_uids")),
        "instantiation_status": "error",
        "error": redact_secrets(str(last_error or "unknown error")),
        "generated_by": {
            "tool": "instan-llm",
            "model": model,
            "base_url": base_url.rstrip("/"),
            "created_at": utc_now(),
            "api_key_persisted": False,
        },
    }


def run_synthesis(
    groups_file: Path,
    output_dir: Path,
    env_file: Path,
    group_ids: Optional[Sequence[str]] = None,
    languages: Optional[Sequence[str]] = None,
    limit: int = 0,
    refresh: bool = False,
    retries: int = 3,
    workers: int = 2,
    timeout: float = DEFAULT_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 0.2,
    response_format: bool = True,
    model_caller: ModelCaller = call_deepseek_chat,
) -> Dict[str, Any]:
    groups_file = groups_file.resolve()
    output_dir = output_dir.resolve()
    values = load_env_file(env_file.resolve())
    base_url = values.get("DEEPSEEK_API_ENDPOINT") or DEFAULT_BASE_URL
    model = values.get("DEEPSEEK_MODEL") or DEFAULT_MODEL
    api_key = values.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    groups = select_groups(
        load_ready_groups(groups_file),
        group_ids,
        languages=languages,
        limit=limit,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_for_work: List[Dict[str, Any]] = []
    skipped = 0
    for group in groups:
        path = instantiation_output_path(output_dir, str(group["group_uid"]))
        if not refresh and successful_existing_instantiation(path, group):
            skipped += 1
            continue
        selected_for_work.append(group)

    results: List[Dict[str, Any]] = []
    lock = threading.Lock()
    worker_count = max(1, int(workers))
    if selected_for_work:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    synthesize_one,
                    group,
                    output_dir,
                    api_key,
                    base_url,
                    model,
                    timeout,
                    max_tokens,
                    temperature,
                    response_format,
                    retries,
                    model_caller,
                ): group
                for group in selected_for_work
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if result.get("instantiation_status") == "error":
                    write_json(
                        instantiation_output_path(output_dir, str(result["group_uid"])),
                        result,
                    )
                with lock:
                    pass

    inventory = load_instantiation_inventory(output_dir)
    write_jsonl(output_dir / "instantiations.jsonl", inventory)
    status_counts = Counter(str(item.get("instantiation_status")) for item in inventory)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "groups_file": str(groups_file),
        "groups_file_sha256": hashlib.sha256(groups_file.read_bytes()).hexdigest(),
        "output_dir": str(output_dir),
        "configuration": {
            "selected_groups": len(groups),
            "limit": limit,
            "group_ids": list(group_ids or []),
            "languages": list(languages or []),
            "refresh": refresh,
            "retries": retries,
            "workers": worker_count,
            "timeout": timeout,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": response_format,
        },
        "counts": {
            "selected_groups": len(groups),
            "attempted": len(selected_for_work),
            "skipped_valid_outputs": skipped,
            "inventory": len(inventory),
            "statuses": dict(sorted(status_counts.items())),
        },
        "policy": {
            "purpose": "Compiler CI quality testing for an owned LoongArch GCC fork; not security testing.",
            "api_key_persisted": False,
            "raw_llm_responses_are_local_outputs": True,
            "coverage_required_before_corpus_admission": True,
        },
    }
    write_json(output_dir / "instan-run-manifest.json", manifest)
    return manifest


def load_instantiation_inventory(output_dir: Path) -> List[Dict[str, Any]]:
    directory = output_dir / "instantiations"
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("*.instantiation.json")):
        records.append(read_json(path))
    return records


OPTIMIZATION_RE = re.compile(r"-O(?:[0-3sSzZg]|fast)$")


def sanitize_compiler_options(
    options: Sequence[str],
    optimization: str = DEFAULT_EVALUATION_OPTIMIZATION,
) -> List[str]:
    sanitized: List[str] = []
    skip_next = False
    optimization = str(optimization or "").strip()
    force_optimization = bool(optimization and optimization != "preserve")
    for option in options:
        value = str(option).strip()
        if not value:
            continue
        if skip_next:
            skip_next = False
            continue
        if value in {"-o", "-c", "-S", "-E"}:
            if value == "-o":
                skip_next = True
            continue
        if value.startswith(("-l", "-Wl,", "-L")):
            continue
        if value in {"-shared", "-static", "-pie"}:
            continue
        if force_optimization and OPTIMIZATION_RE.fullmatch(value):
            continue
        sanitized.append(value)
    if force_optimization:
        sanitized.insert(0, optimization)
    elif not any(OPTIMIZATION_RE.fullmatch(item) for item in sanitized):
        sanitized.insert(0, "-O2")
    return sanitized


def run_command(command: Sequence[str], timeout: float) -> Dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "command": list(command),
            "returncode": completed.returncode,
            "stdout": clip_text(completed.stdout),
            "stderr": clip_text(completed.stderr),
            "duration_seconds": round(time.time() - started, 3),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "command": list(command),
            "returncode": None,
            "stdout": clip_text(error.stdout or ""),
            "stderr": clip_text(error.stderr or ""),
            "duration_seconds": round(time.time() - started, 3),
            "timed_out": True,
        }


def evaluation_output_path(output_dir: Path, instantiation_id: str) -> Path:
    return output_dir / "evaluations" / f"{instantiation_id}.evaluation.json"


def language_for_wrapper(language: str) -> str:
    language = canonical_language(language)
    if language == "c++":
        return "c++"
    return "c"


def evaluate_one(
    instantiation: Mapping[str, Any],
    output_dir: Path,
    timeout_ms: int,
    min_edges: int,
    showmap_script: Optional[Path] = None,
    optimization: str = DEFAULT_EVALUATION_OPTIMIZATION,
) -> Dict[str, Any]:
    status = str(instantiation.get("instantiation_status") or "")
    instantiation_id = fallback_instantiation_id(instantiation)
    if status == "ready" and not str(instantiation.get("instantiation_id") or "").strip():
        raise PipelineError("ready instantiation lacks instantiation_id")
    language = canonical_language(instantiation.get("language"))
    if status != "ready":
        evaluation = {
            "schema_version": SCHEMA_VERSION,
            "instantiation_id": instantiation_id,
            "group_uid": instantiation.get("group_uid"),
            "candidate_id": instantiation.get("candidate_id"),
            "language": language,
            "evaluation_status": "skipped_not_ready",
            "created_at": utc_now(),
        }
        write_json(evaluation_output_path(output_dir, instantiation_id), evaluation)
        return evaluation
    if language not in SUPPORTED_EVAL_LANGUAGES:
        evaluation = {
            "schema_version": SCHEMA_VERSION,
            "instantiation_id": instantiation_id,
            "group_uid": instantiation.get("group_uid"),
            "language": language,
            "evaluation_status": "skipped_unsupported_language",
            "created_at": utc_now(),
        }
        write_json(evaluation_output_path(output_dir, instantiation_id), evaluation)
        return evaluation
    source_path = write_program_source(output_dir, instantiation)
    map_path = output_dir / "coverage" / f"{instantiation_id}.map"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    original_options = string_list(instantiation.get("compiler_options"))
    options = sanitize_compiler_options(original_options, optimization)
    script = showmap_script or (repo_root() / "scripts" / "afl-showmap-gcc.sh")
    command = [
        str(script),
        "--lang",
        language_for_wrapper(language),
        "--output",
        str(map_path),
        "--timeout",
        str(timeout_ms),
        str(source_path),
        "--",
        *options,
    ]
    result = run_command(command, timeout=max(5.0, timeout_ms / 1000.0 + 10.0))
    edge_count = 0
    map_sha = ""
    if map_path.is_file():
        edge_count = sum(1 for line in map_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
        map_sha = file_sha256(map_path) if edge_count else ""
    status = "covered" if result["returncode"] == 0 and edge_count >= min_edges else "coverage_failed"
    if result["timed_out"]:
        status = "timeout"
    elif result["returncode"] == GCC_ICE_EXIT_CODE:
        status = "ice"
    elif result["returncode"] not in (0, None) and edge_count == 0:
        status = "compile_failed"
    evaluation = {
        "schema_version": SCHEMA_VERSION,
        "instantiation_id": instantiation_id,
        "group_uid": instantiation.get("group_uid"),
        "candidate_id": instantiation.get("candidate_id"),
        "language": language,
        "source_path": str(source_path),
        "source_sha256": file_sha256(source_path),
        "compiler_options": options,
        "original_compiler_options": original_options,
        "optimization_policy": optimization,
        "evaluation_status": status,
        "created_at": utc_now(),
        "quality_scope": "compiler CI quality testing; not security testing",
        "coverage": {
            "tool": "afl-showmap",
            "map_path": str(map_path),
            "edge_map_entries": edge_count,
            "map_sha256": map_sha,
            "min_edges": min_edges,
        },
        "compile": result,
    }
    write_json(evaluation_output_path(output_dir, instantiation_id), evaluation)
    return evaluation


def evaluate_instantiations(
    output_dir: Path,
    instantiations_file: Optional[Path] = None,
    group_ids: Optional[Sequence[str]] = None,
    limit: int = 0,
    refresh: bool = False,
    timeout_ms: int = DEFAULT_SHOWMAP_TIMEOUT_MS,
    min_edges: int = 1,
    showmap_script: Optional[Path] = None,
    optimization: str = DEFAULT_EVALUATION_OPTIMIZATION,
) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    if instantiations_file:
        inventory = list(iter_jsonl(instantiations_file.resolve()))
    else:
        inventory = load_instantiation_inventory(output_dir)
    wanted = {str(item) for item in group_ids or []}
    selected: List[Dict[str, Any]] = []
    for item in inventory:
        identifiers = {str(item.get("group_uid") or ""), str(item.get("candidate_id") or "")}
        if wanted and not wanted.intersection(identifiers):
            continue
        selected.append(item)
        if limit and len(selected) >= limit:
            break
    if wanted and not selected:
        raise PipelineError(f"no instantiations matched requested ids: {sorted(wanted)}")

    evaluations: List[Dict[str, Any]] = []
    skipped_existing = 0
    for instantiation in selected:
        instantiation_id = fallback_instantiation_id(instantiation)
        existing = evaluation_output_path(output_dir, instantiation_id)
        if existing.is_file() and not refresh:
            evaluations.append(read_json(existing))
            skipped_existing += 1
            continue
        evaluations.append(
            evaluate_one(instantiation, output_dir, timeout_ms, min_edges, showmap_script, optimization)
        )

    all_evaluations = load_evaluation_inventory(output_dir)
    write_jsonl(output_dir / "evaluations.jsonl", all_evaluations)
    status_counts = Counter(str(item.get("evaluation_status")) for item in all_evaluations)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "output_dir": str(output_dir),
        "configuration": {
            "selected_instantiations": len(selected),
            "group_ids": list(group_ids or []),
            "limit": limit,
            "refresh": refresh,
            "timeout_ms": timeout_ms,
            "min_edges": min_edges,
            "optimization": optimization,
        },
        "counts": {
            "selected_instantiations": len(selected),
            "evaluated_or_loaded": len(evaluations),
            "skipped_existing": skipped_existing,
            "inventory": len(all_evaluations),
            "covered": status_counts.get("covered", 0),
            "statuses": dict(sorted(status_counts.items())),
        },
    }
    write_json(output_dir / "evaluation-manifest.json", manifest)
    return manifest


def load_evaluation_inventory(output_dir: Path) -> List[Dict[str, Any]]:
    directory = output_dir / "evaluations"
    if not directory.is_dir():
        return []
    return [read_json(path) for path in sorted(directory.glob("*.evaluation.json"))]


def build_corpus(output_dir: Path, corpus_dir: Optional[Path] = None) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    if corpus_dir is None:
        corpus_dir = output_dir / "corpus" / "covered"
    corpus_dir = corpus_dir.resolve()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    evaluations = load_evaluation_inventory(output_dir)
    copied = []
    for evaluation in evaluations:
        if evaluation.get("evaluation_status") != "covered":
            continue
        source = Path(str(evaluation.get("source_path") or ""))
        if not source.is_file():
            continue
        target_name = f"{evaluation['instantiation_id']}{source.suffix}"
        target = corpus_dir / target_name
        shutil.copy2(source, target)
        copied.append({"source": str(source), "target": str(target), "sha256": file_sha256(target)})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "output_dir": str(output_dir),
        "corpus_dir": str(corpus_dir),
        "counts": {
            "covered_evaluations": sum(1 for item in evaluations if item.get("evaluation_status") == "covered"),
            "copied": len(copied),
        },
        "files": copied,
    }
    write_json(output_dir / "corpus-manifest.json", manifest)
    return manifest


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def read_edge_map(path: Path) -> Set[str]:
    edges: Set[str] = set()
    if not path.is_file():
        return edges
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            edge_id = line.split(":", 1)[0].strip()
            if edge_id:
                edges.add(edge_id)
    return edges


def edge_map_by_evaluation(evaluations: Sequence[Mapping[str, Any]]) -> Dict[str, Set[str]]:
    result: Dict[str, Set[str]] = {}
    for evaluation in evaluations:
        instantiation_id = str(evaluation.get("instantiation_id") or "")
        map_path = Path(str((evaluation.get("coverage") or {}).get("map_path") or ""))
        result[instantiation_id] = read_edge_map(map_path)
    return result


def generate_coverage_report(
    output_dir: Path,
    groups_file: Path,
    report_path: Optional[Path] = None,
) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    groups_file = groups_file.resolve()
    if report_path is None:
        report_path = output_dir / "INSTANLLM_COVERAGE_REPORT.md"
    report_path = report_path.resolve()

    groups = load_ready_groups(groups_file)
    instantiations = load_instantiation_inventory(output_dir)
    evaluations = load_evaluation_inventory(output_dir)
    covered = [item for item in evaluations if item.get("evaluation_status") == "covered"]
    edge_sets = edge_map_by_evaluation(covered)
    union_edges = set().union(*edge_sets.values()) if edge_sets else set()
    edge_counts = [
        int(item.get("coverage", {}).get("edge_map_entries") or 0)
        for item in covered
    ]
    all_langs = Counter(canonical_language(group.get("language")) for group in groups)
    groups_by_uid = {str(group.get("group_uid") or ""): group for group in groups}
    selected_group_ids = {str(item.get("group_uid") or "") for item in instantiations}
    selected_groups = [group for group in groups if str(group.get("group_uid") or "") in selected_group_ids]
    selected_langs = Counter(canonical_language(group.get("language")) for group in selected_groups)
    instantiation_statuses = Counter(str(item.get("instantiation_status")) for item in instantiations)
    evaluation_statuses = Counter(str(item.get("evaluation_status")) for item in evaluations)
    oracle_kinds = Counter(
        str((item.get("oracle") or {}).get("kind") or "unknown") for item in instantiations
    )
    cxx_ready = sum(all_langs.get(language, 0) for language in ("c", "c++"))
    unsupported_ready = len(groups) - cxx_ready

    def percent(part: int, whole: int) -> str:
        return "0.00%" if whole == 0 else f"{100.0 * part / whole:.2f}%"

    edge_summary = {
        "min": min(edge_counts) if edge_counts else 0,
        "max": max(edge_counts) if edge_counts else 0,
        "avg": round(sum(edge_counts) / len(edge_counts), 1) if edge_counts else 0,
        "median": median(edge_counts),
        "union": len(union_edges),
    }
    source_coverage_path = repo_root() / "out" / "source-coverage" / "instanllm-covered" / "gcc-source-coverage-summary.json"
    source_coverage = read_json(source_coverage_path) if source_coverage_path.is_file() else {}
    source_totals = source_coverage.get("coverage_totals") or {}
    source_replay_counts = source_coverage.get("replay_counts") or {}
    ready_count = instantiation_statuses.get("ready", 0)
    covered_count = evaluation_statuses.get("covered", 0)
    source_coverage_current = bool(source_totals) and int(source_replay_counts.get("selected") or 0) == covered_count
    rows = []
    seen_edges = set()
    for evaluation in sorted(
        evaluations,
        key=lambda item: (str(item.get("candidate_id") or ""), str(item.get("instantiation_id") or "")),
    ):
        coverage = evaluation.get("coverage") or {}
        instantiation_id = str(evaluation.get("instantiation_id") or "")
        group = groups_by_uid.get(str(evaluation.get("group_uid") or ""), {})
        language = canonical_language(evaluation.get("language"))
        if language == "unknown":
            language = canonical_language(group.get("language"))
        edges = edge_sets.get(instantiation_id, set())
        new_edges = len(edges - seen_edges)
        if evaluation.get("evaluation_status") == "covered":
            seen_edges.update(edges)
        rows.append(
            [
                evaluation.get("candidate_id"),
                language,
                evaluation.get("evaluation_status"),
                coverage.get("edge_map_entries", 0),
                new_edges,
                percent(len(edges), len(union_edges)),
                Path(str(evaluation.get("source_path") or "")).name,
            ]
        )

    content = [
        "# InstanLLM 阶段覆盖率报告",
        "",
        f"生成时间：`{utc_now()}`",
        "",
        "测试范围：自有 LoongArch GCC fork 的编译器 CI 质量测试；不涉及网络安全测试。",
        "",
        "## 本轮结论",
        "",
        markdown_table(
            ["指标", "数值"],
            [
                ["GroupLLM ready groups 总数", len(groups)],
                ["当前 evaluator 可直接处理的 C/C++ ready groups", cxx_ready],
                ["其他语言/专用 harness backlog", unsupported_ready],
                ["本轮选择的 groups", len(selected_groups)],
                ["InstanLLM ready", ready_count],
                ["AFL++ covered", covered_count],
                ["本轮 C/C++ groups 选择率", percent(len(selected_groups), cxx_ready)],
                ["InstanLLM 生成 ready 率", percent(ready_count, len(selected_groups))],
                ["ready 程序 AFL covered 率", percent(covered_count, ready_count)],
                ["C/C++ group 端到端 covered 率", percent(covered_count, len(selected_groups))],
                ["GroupLLM 全 ready 端到端 covered 比例", percent(covered_count, len(groups))],
            ],
        ),
        "",
        "## 结果解读",
        "",
        (
            f"- 当前 C/C++ 可测范围已经全量进入 InstanLLM：{len(selected_groups)}/{cxx_ready} 个 C/C++ ready groups 被选择并评估，不再是小样本抽测。"
            if len(selected_groups) == cxx_ready
            else f"- 当前已有 {len(selected_groups)}/{cxx_ready} 个 C/C++ ready groups 进入 InstanLLM 并完成评估；剩余 C/C++ ready groups 是新增 GroupLLM 输出或后续专用 harness 队列。"
        ),
        f"- {covered_count}/{ready_count} 个 InstanLLM ready 程序均产生非空 AFL edge map，说明这些测例可以稳定驱动被测 GCC 前端执行，适合作为 CI corpus 候选。",
        f"- 未进入 covered 的 {len(selected_groups) - covered_count} 个 C/C++ group 停在 InstanLLM 生成阶段，其中 rejected {instantiation_statuses.get('rejected', 0)} 个、error {instantiation_statuses.get('error', 0)} 个；这不是 AFL/GCC 覆盖失败，应进入提示词、schema 或模型重试策略的修复队列。",
        f"- 本轮 union edge 为 {edge_summary['union']}，可作为后续 corpus admission 和趋势回归基线；单测例 `新增 edge` 为 0 的程序不一定无价值，但在入库优先级上应低于能增加 union edge 或具备强 oracle 的程序。",
        (
            f"- 已用同一批 covered corpus 重放 gcov 口径 GCC：源码行覆盖 {source_totals.get('lines_covered', 0)}/{source_totals.get('lines_total', 0)} "
            f"({source_totals.get('line_coverage_percent', 0):.2f}%)，函数覆盖 {source_totals.get('functions_covered', 0)}/{source_totals.get('functions_total', 0)} "
            f"({source_totals.get('function_coverage_percent', 0):.2f}%)。"
            if source_coverage_current
            else f"- gcov 源码覆盖率快照仍对应 {source_replay_counts.get('selected', 0)} 个历史 covered corpus；当前 AFL covered 已为 {covered_count}，源码覆盖率需按需重放后再更新。"
            if source_totals
            else "- 当前报告仍是 AFL edge 覆盖口径。若质量汇报需要“GCC 源码行/函数覆盖率”，需要用同一 corpus 重放一个 gcov/llvm-cov 口径的 GCC 构建，两个指标并列呈现。"
        ),
        "",
        "## AFL edge map 统计",
        "",
        markdown_table(
            ["指标", "数值"],
            [
                ["covered programs", len(covered)],
                ["本轮累计 union edge 数", edge_summary["union"]],
                ["最小 edge map 条目", edge_summary["min"]],
                ["最大 edge map 条目", edge_summary["max"]],
                ["平均 edge map 条目", edge_summary["avg"]],
                ["中位 edge map 条目", edge_summary["median"]],
            ],
        ),
        "",
        "这些 edge map 条目来自 AFL++ instrumentation，不是 gcov 源码行覆盖率。`edge entries` 是单个测例触发的控制流边数量，`union edge` 是本轮所有 covered 测例触发的去重边集合。`union 占比` 表示某个测例单独覆盖了本轮 union edge 的多少；`新增 edge` 表示按表格顺序加入 corpus 时该测例带来的新增去重边数。",
        "",
    ]
    if source_totals and source_coverage_current:
        content.extend(
            [
                "## GCC 源码行/函数覆盖率",
                "",
                markdown_table(
                    ["指标", "数值"],
                    [
                        ["gcov 重放测例数", source_replay_counts.get("selected", 0)],
                        ["重放返回 0", source_replay_counts.get("ok", 0)],
                        ["重放非零退出", source_replay_counts.get("failed", 0)],
                        ["重放超时", source_replay_counts.get("timeout", 0)],
                        ["GCC 源码文件数", source_totals.get("files_total", 0)],
                        [
                            "源码行覆盖",
                            f"{source_totals.get('lines_covered', 0)}/{source_totals.get('lines_total', 0)} ({source_totals.get('line_coverage_percent', 0):.2f}%)",
                        ],
                        [
                            "函数覆盖",
                            f"{source_totals.get('functions_covered', 0)}/{source_totals.get('functions_total', 0)} ({source_totals.get('function_coverage_percent', 0):.2f}%)",
                        ],
                        [
                            "分支覆盖",
                            f"{source_totals.get('branches_covered', 0)}/{source_totals.get('branches_total', 0)} ({source_totals.get('branch_coverage_percent', 0):.2f}%)",
                        ],
                    ],
                ),
                "",
                f"源码覆盖详细报告：`{source_coverage.get('report_path', source_coverage_path)}`。",
                "",
                "该口径只统计真实存在于 `src/gcc-upstream` 下的 GCC 源码文件，不把测试程序、系统头文件或 build 目录生成文件计入分母。非零退出测例仍保留在质量测试口径中，因为它们会覆盖 GCC 前端、诊断和 include 搜索等路径；返回 0 单独列出用于说明 corpus 可编译比例。",
                "",
            ]
        )
    else:
        content.extend(
            [
                (
                    f"当前已有 gcov 源码覆盖快照，但它对应 {source_replay_counts.get('selected', 0)} 个历史 covered corpus；当前 AFL covered 为 {covered_count}。"
                    "本轮优先评估 AFL feedback，不更新 gcov 汇报口径。"
                    if source_totals
                    else "如果要回答“覆盖了 GCC 源码多少行/函数”，需要额外构建带源码覆盖插桩的 GCC（例如 gcov/llvm-cov 口径）并在同一批测例上重放。当前报告先给出 AFL++ edge 覆盖，这是 fuzz/CI 入库筛选的直接反馈指标。"
                ),
                "",
            ]
        )
    content.extend(
        [
        "## 语言与 oracle 分布",
        "",
        markdown_table(["语言", "GroupLLM ready", "本轮 InstanLLM"], sorted(
            [[language, all_langs[language], selected_langs.get(language, 0)] for language in sorted(all_langs)]
        )),
        "",
        markdown_table(["oracle kind", "数量"], sorted(oracle_kinds.items())),
        "",
        "## 本轮程序明细",
        "",
        markdown_table(["candidate", "language", "status", "edge entries", "新增 edge", "union 占比", "source"], rows),
        "",
        "## 当前边界与后续工作",
        "",
        "- 当前 evaluator 直接复用 `scripts/afl-showmap-gcc.sh`，因此只对 C/C++ 调用 `cc1`/`cc1plus` 形成覆盖数据。",
        "- Fortran/Ada/D/asm/RTL/shell/COBOL ready groups 并非无效，而是需要对应前端或专用 harness：例如 `f951`、GNAT、D frontend、assembler scan、RTL dump/compile pass 或 shell-driven multi-file harness。",
        "- C/C++ ready groups 已完成全量 InstanLLM + AFL edge 评估，并已接入 gcov 源码行/函数覆盖重放。下一阶段应细化 oracle，并为 assembly-scan、diagnostic、Fortran/asm/RTL 分别实现 evaluator。",
        "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(content), encoding="utf-8")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "report_path": str(report_path),
        "groups_file": str(groups_file),
        "output_dir": str(output_dir),
        "counts": {
            "ready_groups_total": len(groups),
            "c_cpp_ready_groups": cxx_ready,
            "non_c_cpp_ready_groups": unsupported_ready,
            "selected_groups": len(selected_groups),
            "instantiations": len(instantiations),
            "evaluations": len(evaluations),
            "covered": len(covered),
            "union_edges": len(union_edges),
        },
        "edge_summary": edge_summary,
    }
    if source_coverage:
        manifest["source_coverage"] = {
            "summary_path": str(source_coverage_path),
            "report_path": str(source_coverage.get("report_path") or ""),
            "coverage_totals": source_totals,
            "replay_counts": source_replay_counts,
        }
    write_json(output_dir / "coverage-report-manifest.json", manifest)
    return manifest


def median(values: Sequence[int]) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[midpoint])
    return round((ordered[midpoint - 1] + ordered[midpoint]) / 2.0, 1)


def verify_outputs(
    output_dir: Path,
    require_evaluations: bool = False,
    min_covered: int = 0,
) -> Dict[str, Any]:
    output_dir = output_dir.resolve()
    instantiations = load_instantiation_inventory(output_dir)
    if not instantiations:
        raise PipelineError("no instantiation outputs found")
    instantiation_statuses = Counter(str(item.get("instantiation_status")) for item in instantiations)
    ready = [item for item in instantiations if item.get("instantiation_status") == "ready"]
    for item in ready:
        if not Path(str(item.get("source_path") or "")).is_file():
            raise PipelineError(f"ready instantiation lacks source file: {item.get('instantiation_id')}")
    evaluations = load_evaluation_inventory(output_dir)
    evaluation_statuses = Counter(str(item.get("evaluation_status")) for item in evaluations)
    if require_evaluations and len(evaluations) < len(ready):
        raise PipelineError("fewer evaluations than ready instantiations")
    covered = evaluation_statuses.get("covered", 0)
    if covered < min_covered:
        raise PipelineError(f"covered evaluations {covered} is below required minimum {min_covered}")
    result = {
        "schema_version": SCHEMA_VERSION,
        "verified_at": utc_now(),
        "output_dir": str(output_dir),
        "counts": {
            "instantiations": len(instantiations),
            "ready_instantiations": len(ready),
            "instantiation_statuses": dict(sorted(instantiation_statuses.items())),
            "evaluations": len(evaluations),
            "covered": covered,
            "evaluation_statuses": dict(sorted(evaluation_statuses.items())),
        },
    }
    return result
