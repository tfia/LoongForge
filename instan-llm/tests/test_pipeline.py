import json
import os
import tempfile
import unittest
from pathlib import Path

from instan_llm.pipeline import (
    InstantiationValidationError,
    build_corpus,
    build_messages,
    evaluate_instantiations,
    generate_coverage_report,
    instantiation_output_path,
    load_env_file,
    normalize_instantiation_output,
    run_synthesis,
    sanitize_compiler_options,
    stable_hash,
    validate_instantiation,
    verify_outputs,
    write_json,
    write_jsonl,
)


def ready_group(language="c"):
    uids = [
        "bug-1001-F1-aaaa",
        "bug-1002-F1-bbbb",
        "bug-1003-F1-cccc",
    ]
    return {
        "schema_version": 1,
        "candidate_id": "group-0001-test",
        "group_uid": "group-0001-test-deadbeef",
        "synthesis_status": "ready",
        "group_title": "Shared arithmetic test",
        "group_summary": "Three features flow through one accumulator.",
        "language": language,
        "test_mode": "compile_only",
        "target_options": ["-O2", "-march=loongarch64", "-lffi", "-shared"],
        "source_feature_uids": uids,
        "source_bug_ids": [1001, 1002, 1003],
        "source_features_sha256": "sha",
        "source_features": [
            {
                "feature_uid": uid,
                "bug_id": 1000 + index,
                "source_url": "https://example.invalid",
                "root_cause_summary": "root cause",
                "feature": {
                    "feature_id": "F1",
                    "feature_type": "semantic_invariant",
                    "description": f"feature {index}",
                    "code_witness": f"int f{index}(int x) {{ return x + {index}; }}",
                    "language": language,
                    "target_options": ["-O2"],
                    "confidence": 0.9,
                },
            }
            for index, uid in enumerate(uids, start=1)
        ],
        "shared_execution_context": {
            "container": "single_function",
            "description": "one accumulator",
            "shared_state": ["acc"],
            "control_flow": "linear",
            "data_flow": "chained",
        },
        "preservation_plan": [
            {
                "feature_uid": uid,
                "preserved_invariant": f"preserve {uid}",
                "placement": "test function",
                "must_not_change": ["dependency"],
            }
            for uid in uids
        ],
        "dependencies": [
            {"from": uids[0], "to": "G1", "kind": "data_flow", "description": "feeds"},
            {"from": "G1", "to": uids[1], "kind": "data_flow", "description": "feeds"},
            {"from": uids[1], "to": uids[2], "kind": "data_flow", "description": "feeds"},
        ],
        "glue_features": [
            {
                "glue_id": "G1",
                "description": "shared accumulator",
                "semantic_role": "shared_state",
                "code_witness": "acc += x;",
                "language": language,
                "connects": uids,
                "mutation_knobs": ["type"],
                "composition_tags": ["acc"],
                "novelty_rationale": "connects all features",
            }
        ],
        "instantiation_constraints": ["avoid overflow"],
        "recommended_oracles": ["compile succeeds"],
        "semantic_risks": [],
        "target_profile": "loongarch",
        "confidence": 0.9,
    }


def instantiation_payload(group):
    source = """
volatile unsigned sink;
__attribute__((noinline)) unsigned f1(unsigned x) { return x + 1u; }
__attribute__((noinline)) unsigned f2(unsigned x) { return x ^ 3u; }
__attribute__((noinline)) unsigned f3(unsigned x) { return x * 5u; }
int test(void) {
  unsigned acc = f1(7u);
  acc = f2(acc);
  acc = f3(acc);
  sink = acc;
  return acc == 45u ? 0 : 1;
}
""".strip()
    return {
        "schema_version": 1,
        "group_uid": group["group_uid"],
        "candidate_id": group["candidate_id"],
        "instantiation_status": "ready",
        "program_title": "Accumulator test",
        "language": group["language"],
        "file_name": "accumulator.c" if group["language"] == "c" else "accumulator.cc",
        "compiler_options": ["-O2", "-march=loongarch64", "-lffi", "-shared"],
        "source_code": source,
        "oracle": {
            "kind": "compile_success",
            "description": "compiled frontend should accept the translation unit",
            "expected_result": "compile succeeds",
        },
        "preservation_checklist": [
            {
                "feature_uid": uid,
                "implemented_by": f"function for {uid}",
                "oracle_hook": "contributes to sink",
            }
            for uid in group["source_feature_uids"]
        ],
        "coverage_intent": {
            "compiler_paths": ["frontend", "optimizer"],
            "mutation_knobs": ["constants"],
        },
        "build_notes": ["no external libraries needed"],
        "rejection_reasons": [],
        "confidence": 0.9,
        "notes": "",
    }


def raw_response(payload):
    return {
        "id": "response-1",
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"total_tokens": 100},
    }


class PipelineTests(unittest.TestCase):
    def test_prompt_requests_complete_program_and_quality_scope(self):
        messages = build_messages(ready_group())
        joined = "\n".join(message["content"] for message in messages)
        self.assertIn("one complete standalone source file", joined)
        self.assertIn("not security testing", joined)
        self.assertIn("preservation_checklist", joined)

    def test_normalize_attaches_ids_and_validates_checklist(self):
        group = ready_group()
        normalized = normalize_instantiation_output(
            group,
            raw_response(instantiation_payload(group)),
            "model",
            "https://api.example",
        )
        self.assertEqual(normalized["group_uid"], group["group_uid"])
        self.assertEqual(normalized["source_feature_uids"], group["source_feature_uids"])
        self.assertTrue(normalized["instantiation_id"].startswith(group["candidate_id"]))

    def test_validation_rejects_missing_feature_checklist(self):
        group = ready_group()
        normalized = normalize_instantiation_output(
            group,
            raw_response(instantiation_payload(group)),
            "model",
            "https://api.example",
        )
        normalized["preservation_checklist"].pop()
        with self.assertRaisesRegex(InstantiationValidationError, "cover every source feature"):
            validate_instantiation(normalized, group)

    def test_sanitize_options_removes_linker_only_flags(self):
        self.assertEqual(
            sanitize_compiler_options(["-lffi", "-Wl,-rpath,x", "-L/tmp", "-shared", "-O3", "-mlasx"]),
            ["-O3", "-mlasx"],
        )
        self.assertEqual(sanitize_compiler_options(["-mlsx"]), ["-O2", "-mlsx"])

    def test_run_synthesis_with_fake_model_and_verify(self):
        group = ready_group()

        def fake_model(api_key, messages, base_url, model, timeout, max_tokens, temperature, response_format):
            return raw_response(instantiation_payload(group))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            groups_file = root / "groups.jsonl"
            output = root / "out"
            env_file = root / ".env"
            write_jsonl(groups_file, [group])
            env_file.write_text(
                "DEEPSEEK_API_ENDPOINT=https://api.example\n"
                "DEEPSEEK_API_KEY=dummy-not-used\n"
                "DEEPSEEK_MODEL=test-model\n",
                encoding="utf-8",
            )
            manifest = run_synthesis(
                groups_file,
                output,
                env_file,
                workers=1,
                model_caller=fake_model,
            )
            self.assertEqual(manifest["counts"]["attempted"], 1)
            result = verify_outputs(output)
            self.assertEqual(result["counts"]["ready_instantiations"], 1)
            self.assertTrue(instantiation_output_path(output, group["group_uid"]).is_file())

    def test_evaluate_with_fake_showmap_and_build_corpus(self):
        group = ready_group()
        instantiation = normalize_instantiation_output(
            group,
            raw_response(instantiation_payload(group)),
            "model",
            "https://api.example",
        )
        instantiation["instantiation_id"] = f"{group['candidate_id']}-{stable_hash('test')}"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            output.mkdir()
            source = output / "programs" / "accumulator.c"
            source.parent.mkdir()
            source.write_text(instantiation["source_code"] + "\n", encoding="utf-8")
            instantiation["source_path"] = str(source)
            write_json(instantiation_output_path(output, group["group_uid"]), instantiation)

            fake_showmap = root / "fake-showmap.sh"
            fake_showmap.write_text(
                "#!/usr/bin/env bash\n"
                "out=''\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = '--output' ] || [ \"$1\" = '-o' ]; then out=\"$2\"; shift 2; continue; fi\n"
                "  shift\n"
                "done\n"
                "mkdir -p \"$(dirname \"$out\")\"\n"
                "printf '1:1\\n2:1\\n' > \"$out\"\n",
                encoding="utf-8",
            )
            os.chmod(fake_showmap, 0o755)

            manifest = evaluate_instantiations(output, showmap_script=fake_showmap)
            self.assertEqual(manifest["counts"]["covered"], 1)
            verify_outputs(output, require_evaluations=True, min_covered=1)
            corpus = build_corpus(output)
            self.assertEqual(corpus["counts"]["copied"], 1)
            groups_file = root / "groups.jsonl"
            write_jsonl(groups_file, [group])
            report = generate_coverage_report(output, groups_file)
            self.assertEqual(report["counts"]["covered"], 1)
            self.assertIn("InstanLLM 阶段覆盖率报告", Path(report["report_path"]).read_text(encoding="utf-8"))

    def test_evaluate_skips_unsupported_language(self):
        group = ready_group(language="fortran")
        instantiation = instantiation_payload(group)
        instantiation["instantiation_id"] = "unsupported-1"
        instantiation["source_feature_uids"] = group["source_feature_uids"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            output.mkdir()
            write_json(instantiation_output_path(output, group["group_uid"]), instantiation)
            manifest = evaluate_instantiations(output)
            self.assertEqual(manifest["counts"]["statuses"], {"skipped_unsupported_language": 1})

    def test_dotenv_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("export DEEPSEEK_MODEL='x'\nDEEPSEEK_API_KEY=dummy\n", encoding="utf-8")
            values = load_env_file(env_file)
        self.assertEqual(values["DEEPSEEK_MODEL"], "x")


if __name__ == "__main__":
    unittest.main()
