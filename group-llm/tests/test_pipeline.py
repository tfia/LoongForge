import json
import tempfile
import unittest
from pathlib import Path

from group_llm.pipeline import (
    GroupValidationError,
    build_group_pool,
    build_messages,
    candidate_output_path,
    chat_endpoint,
    load_env_file,
    normalize_group_output,
    options_compatible,
    prepare_candidates,
    run_synthesis,
    sample_candidate_groups,
    stable_hash,
    validate_group,
    verify_outputs,
    write_json,
    write_jsonl,
)


def pool_record(index, language="c", feature_type="semantic_invariant", tags=None, target=True):
    target_tags = ["loongarch", "lsx"] if target else []
    return {
        "schema_version": 1,
        "feature_uid": f"bug-{1000 + index}-F1-{index:04d}",
        "bug_id": 1000 + index,
        "source_url": f"https://example.invalid/{1000 + index}",
        "root_cause_summary": f"root cause {index}",
        "feature": {
            "feature_id": "F1",
            "feature_type": feature_type,
            "description": f"Preserve vector loop invariant {index}",
            "code_witness": f"int f{index}(int x) {{ return x + {index}; }}",
            "witness_kind": "exact_poc",
            "evidence_strength": "strong",
            "language": language,
            "compiler_area": "vectorizer" if index % 2 else "target",
            "failure_mode": "wrong-code",
            "target_options": ["-O2", "-mlasx"] if target else ["-O2"],
            "mutation_knobs": ["loop bound"],
            "composition_tags": (tags or ["loop", "data-flow"]) + target_tags,
            "root_cause_link": "optimizer interaction",
            "confidence": 0.9,
        },
    }


def ready_payload(candidate):
    uids = candidate["source_feature_uids"]
    return {
        "schema_version": 1,
        "candidate_id": candidate["candidate_id"],
        "synthesis_status": "ready",
        "group_title": "Shared vector dataflow",
        "group_summary": "All values flow through one loop.",
        "language": "c",
        "test_mode": "execute_differential",
        "target_options": ["-O2", "-mlasx"],
        "shared_execution_context": {
            "container": "single_function",
            "description": "A single loop carries shared values.",
            "shared_state": ["accumulator"],
            "control_flow": "one loop",
            "data_flow": "each source feeds the next",
        },
        "preservation_plan": [
            {
                "feature_uid": uid,
                "preserved_invariant": f"Preserve {uid}",
                "placement": "inside the loop",
                "must_not_change": ["data dependency"],
            }
            for uid in uids
        ],
        "dependencies": [
            {
                "from": uid,
                "to": "G1",
                "kind": "data_flow",
                "description": "feeds shared accumulator",
            }
            for uid in uids
        ],
        "glue_features": [
            {
                "glue_id": "G1",
                "description": "A shared accumulator connects all feature values.",
                "semantic_role": "shared_state",
                "code_witness": "acc += value;",
                "language": "c",
                "connects": uids,
                "mutation_knobs": ["accumulator type"],
                "composition_tags": ["shared-state"],
                "novelty_rationale": "Creates cross-feature recurrence.",
            }
        ],
        "instantiation_constraints": ["avoid signed overflow"],
        "recommended_oracles": ["compare -O0 and -O2 output"],
        "semantic_risks": [{"risk": "overflow", "mitigation": "use unsigned values"}],
        "conflicts": [],
        "confidence": 0.9,
        "notes": "",
    }


class PipelineTests(unittest.TestCase):
    def setUp(self):
        feature_types = [
            "semantic_invariant",
            "code_shape",
            "pass_interaction",
            "target_condition",
            "failure_oracle",
            "mutation_knob",
        ]
        self.pool = [
            pool_record(index, feature_type=feature_types[index % len(feature_types)])
            for index in range(1, 25)
        ]

    def candidate(self):
        return sample_candidate_groups(
            self.pool,
            group_count=1,
            min_features=3,
            max_features=3,
            seed=7,
            target_profile="loongarch",
        )[0]

    def normalized(self, candidate):
        raw = {
            "id": "response-1",
            "choices": [{"message": {"content": json.dumps(ready_payload(candidate))}}],
            "usage": {"total_tokens": 100},
        }
        return normalize_group_output(candidate, raw, "test-model", "https://api.example")

    def test_sampling_is_deterministic_and_cross_bug(self):
        left = sample_candidate_groups(self.pool, group_count=5, seed=19)
        right = sample_candidate_groups(self.pool, group_count=5, seed=19)
        self.assertEqual(
            [item["source_feature_uids"] for item in left],
            [item["source_feature_uids"] for item in right],
        )
        for candidate in left:
            self.assertEqual(len(candidate["source_bug_ids"]), len(set(candidate["source_bug_ids"])))
            self.assertGreaterEqual(len(candidate["source_feature_uids"]), 3)

    def test_incompatible_abi_and_simd_options_are_filtered(self):
        soft = pool_record(30)
        soft["feature"]["target_options"] = ["-mabi=lp64s", "-msoft-float"]
        vector = pool_record(31)
        vector["feature"]["target_options"] = ["-mabi=lp64d", "-mlasx"]
        self.assertFalse(options_compatible(soft, vector))

    def test_prepare_can_append_without_replacing_existing_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool_path = root / "feature-pool.jsonl"
            output = root / "out"
            write_jsonl(pool_path, self.pool)
            initial = prepare_candidates(
                pool_path,
                output,
                group_count=3,
                min_features=3,
                max_features=3,
                seed=13,
            )
            initial_candidates = list(
                json.loads(line) for line in (output / "group-candidates.jsonl").read_text().splitlines()
            )
            appended = prepare_candidates(
                pool_path,
                output,
                min_features=3,
                max_features=3,
                seed=13,
                append_groups=4,
            )
            combined = list(
                json.loads(line) for line in (output / "group-candidates.jsonl").read_text().splitlines()
            )
            self.assertEqual(initial["counts"]["candidate_groups"], 3)
            self.assertEqual(appended["counts"]["candidate_groups"], 7)
            self.assertEqual(appended["counts"]["candidate_groups_added"], 4)
            self.assertEqual(combined[:3], initial_candidates)
            self.assertEqual([item["sampling"]["group_index"] for item in combined[-4:]], [4, 5, 6, 7])

    def test_candidate_snapshot_hash_covers_exact_source_features(self):
        candidate = self.candidate()
        self.assertEqual(candidate["source_features_sha256"], stable_hash(candidate["source_features"], 64))

    def test_normalize_attaches_immutable_sources(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        self.assertEqual(group["source_features"], candidate["source_features"])
        self.assertEqual(group["source_features_sha256"], candidate["source_features_sha256"])
        self.assertEqual(group["synthesis_status"], "ready")

    def test_validation_rejects_modified_source_snapshot(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        group["source_features"][0]["feature"]["description"] = "modified"
        with self.assertRaisesRegex(GroupValidationError, "modified"):
            validate_group(group, candidate)

    def test_validation_rejects_disconnected_source(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        missing_uid = candidate["source_feature_uids"][-1]
        group["dependencies"] = [
            edge for edge in group["dependencies"] if edge["from"] != missing_uid
        ]
        group["glue_features"][0]["connects"] = candidate["source_feature_uids"][:-1]
        with self.assertRaisesRegex(GroupValidationError, "disconnected"):
            validate_group(group, candidate)

    def test_validation_rejects_zero_confidence_ready_group(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        group["confidence"] = 0.0
        with self.assertRaisesRegex(GroupValidationError, "confidence"):
            validate_group(group, candidate)

    def test_validation_rejects_more_than_four_glue_features(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        original = group["glue_features"][0]
        group["glue_features"] = [
            {**original, "glue_id": f"G{index}"}
            for index in range(1, 6)
        ]
        with self.assertRaisesRegex(GroupValidationError, "at most four"):
            validate_group(group, candidate)

    def test_prompt_requires_glue_without_full_program(self):
        messages = build_messages(self.candidate())
        joined = "\n".join(item["content"] for item in messages)
        self.assertIn("Never edit, merge, delete, weaken", joined)
        self.assertIn("Do not generate a complete program", joined)
        self.assertIn("semantic_risks", joined)

    def test_dotenv_parser_and_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "DEEPSEEK_API_ENDPOINT='https://api.example/v1'\n"
                "DEEPSEEK_API_KEY=secret-value\n"
                "export DEEPSEEK_MODEL=group-model\n",
                encoding="utf-8",
            )
            values = load_env_file(path)
        self.assertEqual(values["DEEPSEEK_MODEL"], "group-model")
        self.assertEqual(chat_endpoint(values["DEEPSEEK_API_ENDPOINT"]), "https://api.example/v1/chat/completions")
        self.assertEqual(
            chat_endpoint("https://api.example/chat/completions"),
            "https://api.example/chat/completions",
        )

    def test_build_and_verify_consolidated_pool(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_jsonl(output / "group-candidates.jsonl", [candidate])
            write_json(candidate_output_path(output, candidate["candidate_id"]), group)
            manifest = build_group_pool(output)
            result = verify_outputs(
                output,
                require_outputs=True,
                fail_on_error=True,
                min_ready_ratio=1.0,
            )
            self.assertEqual(manifest["counts"]["ready_groups"], 1)
            self.assertEqual(result["counts"]["consolidated_ready_groups"], 1)

    def test_resumed_run_manifest_reports_full_inventory(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "DEEPSEEK_API_ENDPOINT=https://api.example\n"
                "DEEPSEEK_API_KEY=dummy-not-used\n"
                "DEEPSEEK_MODEL=test-model\n",
                encoding="utf-8",
            )
            write_jsonl(output / "group-candidates.jsonl", [candidate])
            write_json(candidate_output_path(output, candidate["candidate_id"]), group)
            manifest = run_synthesis(output, env_file, workers=1)
            self.assertEqual(manifest["counts"]["candidate_inventory"], 1)
            self.assertEqual(manifest["counts"]["skipped_valid_outputs"], 1)
            self.assertEqual(manifest["counts"]["inventory_statuses"], {"ready": 1})


if __name__ == "__main__":
    unittest.main()
