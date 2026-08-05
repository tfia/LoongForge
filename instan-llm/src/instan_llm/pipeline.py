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
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence


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
    limit: int = 0,
) -> List[Dict[str, Any]]:
    wanted = {str(item) for item in group_ids or []}
    selected: List[Dict[str, Any]] = []
    for group in groups:
        identifiers = {
            str(group.get("group_uid") or ""),
            str(group.get("candidate_id") or ""),
        }
        if wanted and not wanted.intersection(identifiers):
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
        "program should compile under the listed compiler options on the LoongArch cross compiler. "
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


def program_source_path(output_dir: Path, instantiation: Mapping[str, Any]) -> Path:
    language = canonical_language(instantiation.get("language"))
    suffix = LANGUAGE_EXTENSIONS.get(language, ".txt")
    file_name = str(instantiation.get("file_name") or "").strip()
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(file_name).stem or str(instantiation["instantiation_id"]))
    if not safe_stem:
        safe_stem = str(instantiation["instantiation_id"])
    return output_dir / "programs" / f"{safe_stem}{suffix}"


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
        "group_uid": group.get("group_uid"),
        "candidate_id": group.get("candidate_id"),
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
    groups = select_groups(load_ready_groups(groups_file), group_ids, limit)
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


def sanitize_compiler_options(options: Sequence[str]) -> List[str]:
    sanitized: List[str] = []
    skip_next = False
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
        sanitized.append(value)
    if not any(re.fullmatch(r"-O[0-3sSzZgfast]+", item) for item in sanitized):
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
) -> Dict[str, Any]:
    instantiation_id = str(instantiation.get("instantiation_id") or "")
    if not instantiation_id:
        raise PipelineError("instantiation lacks instantiation_id")
    language = canonical_language(instantiation.get("language"))
    if instantiation.get("instantiation_status") != "ready":
        evaluation = {
            "schema_version": SCHEMA_VERSION,
            "instantiation_id": instantiation_id,
            "group_uid": instantiation.get("group_uid"),
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
    source_path = Path(str(instantiation.get("source_path") or ""))
    if not source_path.is_file():
        source_path = write_program_source(output_dir, instantiation)
    map_path = output_dir / "coverage" / f"{instantiation_id}.map"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    options = sanitize_compiler_options(string_list(instantiation.get("compiler_options")))
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
        instantiation_id = str(instantiation.get("instantiation_id") or "")
        existing = evaluation_output_path(output_dir, instantiation_id)
        if instantiation_id and existing.is_file() and not refresh:
            evaluations.append(read_json(existing))
            skipped_existing += 1
            continue
        evaluations.append(
            evaluate_one(instantiation, output_dir, timeout_ms, min_edges, showmap_script)
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
