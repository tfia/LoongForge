from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extract_llm.pipeline import (
    build_feature_pool,
    compact_record_for_prompt,
    extract_fix_history,
    parse_json_content,
    prepare_corpus,
    run_extraction,
    verify_outputs,
    write_json,
)


class PipelineTests(unittest.TestCase):
    def make_corpus(self, root: Path) -> Path:
        corpus = root / "corpus"
        bug_dir = corpus / "archive" / "reports" / "bug-1"
        testcase_dir = bug_dir / "testcases"
        testcase_dir.mkdir(parents=True)
        testcase = testcase_dir / "poc.c"
        testcase.write_text("int f(int x) { return x + 1; }\n", encoding="utf-8")
        report = {
            "metadata": {
                "id": 1,
                "summary": "ICE on loongarch64",
                "component": "target",
                "status": "RESOLVED",
                "resolution": "FIXED",
                "cf_gcctarget": "loongarch64-linux-gnu",
            },
            "description": "Compiler ICE with a reduced testcase.",
            "comments": [
                {"count": 0, "creation_time": "2024-01-01T00:00:00Z", "text": "Compiler ICE."},
                {
                    "count": 1,
                    "creation_time": "2024-01-02T00:00:00Z",
                    "text": "The master branch has been updated:\ncommit abcdef1234567890\nFix register class.",
                },
            ],
            "attachments": [],
            "testcases": [
                {
                    "kind": "bugzilla_attachment",
                    "language": "c",
                    "path": "testcases/poc.c",
                    "sha256": "unused",
                }
            ],
        }
        write_json(bug_dir / "report.json", report)
        return corpus

    def test_prepare_corpus_extracts_program_and_fix_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = self.make_corpus(root)
            out = root / "out"
            manifest = prepare_corpus(corpus, out)
            self.assertEqual(manifest["counts"]["bug_reports"], 1)
            self.assertEqual(manifest["counts"]["with_program_and_fix_history"], 1)
            record = json.loads((out / "extract-inputs.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(record["bug_triggering_programs"][0]["content"], "int f(int x) { return x + 1; }\n")
            self.assertTrue(record["fix_history"]["available"])

    def test_extract_fix_history_finds_commit_hash(self) -> None:
        report = {
            "comments": [
                {"count": 7, "text": "commit 020b7d98589bbc928b5a66b1ed56b42af8791355\nFixed."}
            ],
            "attachments": [],
        }
        history = extract_fix_history(report, max_comment_chars=1000)
        self.assertTrue(history["available"])
        self.assertIn("020b7d98589bbc928b5a66b1ed56b42af8791355", history["commit_hashes"])

    def test_parse_json_content_accepts_fenced_json(self) -> None:
        self.assertEqual(parse_json_content("```json\n{\"a\": 1}\n```"), {"a": 1})

    def test_compact_record_preserves_array_programs(self) -> None:
        record = {
            "bug_id": 7,
            "bug_report": {
                "description": "desc",
                "comments": [{"count": i, "text": "x" * 5000} for i in range(10)],
            },
            "bug_triggering_programs": [
                {"program_id": "p1", "content": "a" * 10000},
                {"program_id": "p2", "content": "b" * 10000},
            ],
            "fix_history": {
                "evidence": [{"kind": "bugzilla_comment", "count": 9, "text": "fix" * 2000}]
            },
        }
        compacted = compact_record_for_prompt(record, max_prompt_chars=15000)
        self.assertTrue(compacted["prompt_compaction"]["enabled"])
        self.assertGreaterEqual(len(compacted["bug_triggering_programs"]), 1)
        self.assertIsInstance(compacted["bug_triggering_programs"], list)

    def test_build_pool_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "extract-inputs.jsonl").write_text(
                json.dumps({"bug_id": 1}, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            write_json(
                out / "features" / "bug-1.features.json",
                {
                    "schema_version": 1,
                    "bug_id": 1,
                    "source_url": "https://example.invalid",
                    "input_sha256": "abc",
                    "extraction_status": "ok",
                    "root_cause_summary": "root cause",
                    "features": [
                        {
                            "feature_id": "F1",
                            "feature_type": "semantic_invariant",
                            "description": "Loop invariant is used after a loop.",
                            "code_witness": "for (int i=0; i<n; ++i) x = g; return x;",
                            "mutation_knobs": ["loop bound"],
                        },
                        {
                            "feature_id": "F2",
                            "feature_type": "code_shape",
                            "description": "A noinline helper is called through a conditionally reachable path.",
                            "code_witness": "if (flag) helper(&x); return x;",
                            "composition_tags": ["conditional-call"],
                        }
                    ],
                },
            )
            summary = build_feature_pool(out)
            self.assertEqual(summary["counts"]["features"], 2)
            self.assertEqual(summary["counts"]["by_feature_type"]["semantic_invariant"], 1)
            self.assertEqual(summary["counts"]["by_feature_type"]["code_shape"], 1)
            result = verify_outputs(out, require_outputs=True, fail_on_api_error=True)
            self.assertEqual(result["counts"]["feature_pool_records"], 2)

    def test_run_calls_llm_even_without_poc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "extract-inputs.jsonl").write_text(
                json.dumps(
                    {
                        "bug_id": 2,
                        "source_url": "https://example.invalid",
                        "input_sha256": "abc",
                        "eligibility": {"has_bug_triggering_program": False},
                        "bug_report": {"description": "ICE in backend.", "comments": []},
                        "bug_triggering_programs": [],
                        "fix_history": {"evidence": [{"text": "Fixed target register handling."}]},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            calls = {"count": 0}

            import extract_llm.pipeline as pipeline

            old_call = pipeline.call_deepseek_chat
            try:
                def fake_call(**kwargs):
                    calls["count"] += 1
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "bug_id": 2,
                                            "extraction_status": "ok",
                                            "features": [
                                                {
                                                    "description": "A backend register rule is preserved.",
                                                    "code_witness": "int f(int x) { return x; }",
                                                    "witness_kind": "synthetic_from_report",
                                                },
                                                {
                                                    "description": "CI observes backend ICE as the failure oracle.",
                                                    "code_witness": "/* compile-only */",
                                                    "feature_type": "failure_oracle",
                                                    "witness_kind": "synthetic_from_report",
                                                },
                                            ],
                                        }
                                    )
                                }
                            }
                        ]
                    }

                pipeline.call_deepseek_chat = fake_call  # type: ignore[assignment]
                manifest = run_extraction(
                    out,
                    api_key="dummy",
                    keep_going=True,
                    retries=1,
                    delay_seconds=0,
                )
            finally:
                pipeline.call_deepseek_chat = old_call  # type: ignore[assignment]

            self.assertEqual(calls["count"], 1)
            self.assertEqual(manifest["counts"]["api_success"], 1)
            self.assertNotIn("deterministic_insufficient_evidence", manifest["counts"])

    def test_run_manifest_separates_api_and_parse_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "extract-inputs.jsonl").write_text(
                json.dumps(
                    {
                        "bug_id": 1,
                        "source_url": "https://example.invalid",
                        "input_sha256": "abc",
                        "eligibility": {"has_bug_triggering_program": True},
                        "bug_report": {"description": "", "comments": []},
                        "bug_triggering_programs": [{"program_id": "p1", "content": "int main(){}"}],
                        "fix_history": {"evidence": []},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            import extract_llm.pipeline as pipeline

            old_call = pipeline.call_deepseek_chat
            try:
                pipeline.call_deepseek_chat = lambda **kwargs: {  # type: ignore[assignment]
                    "choices": [{"message": {"content": "not json"}}]
                }
                manifest = run_extraction(
                    out,
                    api_key="dummy",
                    keep_going=True,
                    retries=1,
                    delay_seconds=0,
                )
            finally:
                pipeline.call_deepseek_chat = old_call  # type: ignore[assignment]

            self.assertEqual(manifest["counts"]["api_errors"], 0)
            self.assertEqual(manifest["counts"]["parse_errors"], 1)

    def test_features_normalize_insufficient_status_to_ok(self) -> None:
        from extract_llm.pipeline import normalize_feature_output

        record = {"bug_id": 7, "source_url": "https://example.invalid", "input_sha256": "abc"}
        raw = {
            "id": "r1",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "bug_id": 7,
                                "extraction_status": "insufficient_evidence",
                                "evidence_gaps": ["missing_explicit_fix_history"],
                                "features": [
                                    {
                                        "description": "A value remains invariant across loop iterations.",
                                        "code_witness": "for (int i=0;i<n;i++) x=g;",
                                    }
                                ],
                            }
                        )
                    }
                }
            ],
        }
        output = normalize_feature_output(record, {}, raw, "model", "base")
        self.assertEqual(output["extraction_status"], "ok")


if __name__ == "__main__":
    unittest.main()
