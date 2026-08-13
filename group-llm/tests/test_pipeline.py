import json
import tempfile
import unittest
from pathlib import Path

from group_llm.pipeline import (
    GroupValidationError,
    build_afl_feedback,
    build_group_pool,
    build_messages,
    candidate_output_path,
    chat_endpoint,
    feedback_iteration_compatible,
    pair_affinity,
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

    def test_required_architecture_and_test_mode_conflicts_are_filtered(self):
        loong = pool_record(40)
        loong["feature"]["description"] = "LoongArch-specific missed optimization."
        loong["feature"]["target_options"] = ["-march=loongarch64", "-O2"]
        x86 = pool_record(41)
        x86["feature"]["description"] = "x86-64 target GOTPCREL assembly check."
        x86["feature"]["target_options"] = ["-m32", "-mfpmath=387"]
        self.assertLess(pair_affinity(loong, x86)["score"], -999)

        diagnostic = pool_record(42)
        diagnostic["feature"]["failure_mode"] = "rejects-valid"
        diagnostic["feature"]["description"] = "Must emit a diagnostic error message."
        runtime = pool_record(43)
        runtime["feature"]["failure_mode"] = "wrong-code"
        runtime["feature"]["description"] = "Runtime wrong-code differential test."
        self.assertLess(pair_affinity(diagnostic, runtime)["score"], -999)

    def test_feedback_loop_excludes_non_loongarch_hard_constraints(self):
        mips = pool_record(50)
        mips["feature"]["description"] = "MIPS32 shift-sign-branch optimization."
        mips["feature"]["target_options"] = ["-mips32", "-O2"]
        self.assertFalse(feedback_iteration_compatible(mips, "loongarch"))

        big_endian = pool_record(51)
        big_endian["feature"]["description"] = "Big-endian _BitInt limb access."
        big_endian["feature"]["target_options"] = ["-mbig-endian", "-std=gnu2x"]
        self.assertFalse(feedback_iteration_compatible(big_endian, "loongarch"))

        x86_reg = pool_record(52)
        x86_reg["feature"]["description"] = "x86 hard register vector indexing."
        x86_reg["feature"]["code_witness"] = 'register int v asm("xmm0");'
        self.assertFalse(feedback_iteration_compatible(x86_reg, "loongarch"))

    def test_sampling_filters_pairwise_option_and_mode_conflicts(self):
        soft = pool_record(60)
        soft["feature"]["target_options"] = ["-mabi=lp64s", "-msoft-float"]
        vector = pool_record(61)
        vector["feature"]["target_options"] = ["-mabi=lp64d", "-mlasx"]
        self.assertFalse(options_compatible(soft, vector))

        diagnostic = pool_record(62)
        diagnostic["feature"]["failure_mode"] = "rejects-valid"
        diagnostic["feature"]["description"] = "Must emit a diagnostic error message."
        runtime = pool_record(63)
        runtime["feature"]["failure_mode"] = "wrong-code"
        runtime["feature"]["description"] = "Runtime wrong-code differential test."
        sampled = sample_candidate_groups(
            self.pool + [soft, vector, diagnostic, runtime],
            group_count=4,
            min_features=3,
            max_features=3,
            seed=61,
            target_profile="loongarch",
        )
        for candidate in sampled:
            uids = set(candidate["source_feature_uids"])
            self.assertFalse({soft["feature_uid"], vector["feature_uid"]}.issubset(uids))
            self.assertFalse({diagnostic["feature_uid"], runtime["feature_uid"]}.issubset(uids))

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

    def test_normalize_canonicalizes_descriptive_glue_ids(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        group["glue_features"][0]["glue_id"] = "G1-shared-accumulator"
        for edge in group["dependencies"]:
            if edge["to"] == "G1":
                edge["to"] = "G1-shared-accumulator"
        raw = {
            "id": "response-1",
            "choices": [{"message": {"content": json.dumps(group)}}],
            "usage": {},
        }

        normalized = normalize_group_output(candidate, raw, "model", "https://api.example")

        self.assertEqual(normalized["glue_features"][0]["glue_id"], "G1")
        self.assertTrue(
            all(
                edge["from"] != "G1-shared-accumulator"
                and edge["to"] != "G1-shared-accumulator"
                for edge in normalized["dependencies"]
            )
        )

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

    def test_afl_feedback_rewards_features_and_prepare_consumes_it(self):
        candidate = self.candidate()
        group = self.normalized(candidate)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group_output = root / "group-out"
            instan_output = root / "instan-out"
            write_jsonl(group_output / "group-candidates.jsonl", [candidate])
            write_jsonl(group_output / "feature-groups.jsonl", [group])
            coverage_dir = instan_output / "coverage"
            coverage_dir.mkdir(parents=True)
            map_path = coverage_dir / f"{candidate['candidate_id']}.map"
            map_path.write_text("1:1\n2:1\n3:1\n", encoding="utf-8")
            write_jsonl(
                instan_output / "evaluations.jsonl",
                [
                    {
                        "evaluation_status": "covered",
                        "candidate_id": candidate["candidate_id"],
                        "group_uid": group["group_uid"],
                        "instantiation_id": "inst-1",
                        "language": "c",
                        "coverage": {"map_path": str(map_path), "edge_map_entries": 3},
                    }
                ],
            )
            manifest = build_afl_feedback(group_output, instan_output)
            self.assertEqual(manifest["counts"]["union_edges"], 3)
            self.assertEqual(manifest["counts"]["rewarded_source_features"], len(candidate["source_feature_uids"]))
            rewards = [
                json.loads(line)
                for line in (group_output / "afl-feedback" / "feature-afl-rewards.jsonl").read_text().splitlines()
            ]
            self.assertTrue(all(item["reward_score"] > 0 for item in rewards))

            pool_path = root / "feature-pool.jsonl"
            write_jsonl(pool_path, self.pool)
            prepared = prepare_candidates(
                pool_path,
                group_output,
                min_features=3,
                max_features=3,
                seed=13,
                append_groups=1,
            )
            self.assertEqual(prepared["configuration"]["feedback_rewarded_features"], len(rewards))
            new_candidate = json.loads((group_output / "group-candidates.jsonl").read_text().splitlines()[-1])
            self.assertIn("coverage_feedback", new_candidate)

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
