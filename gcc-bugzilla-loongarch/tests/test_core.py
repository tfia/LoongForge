import json
import tempfile
import unittest
from pathlib import Path

from loongarch_bug_corpus.core import (
    classify_relevance,
    classify_architecture_scope,
    classify_general_quality,
    classify_full_relevance,
    extract_comment_testcases,
    is_source_attachment,
    safe_filename,
    sha256_bytes,
    language_for,
    language_for_content,
    verify_archive,
)


class RelevanceTests(unittest.TestCase):
    def test_summary_is_architecture_specific(self):
        result = classify_relevance("LoongArch: ICE with LSX", "")
        self.assertEqual(result["tier"], "architecture_specific")
        self.assertEqual(result["reason"], "summary_mentions_loongarch")

    def test_loongarch_only_target_is_architecture_specific(self):
        result = classify_relevance("unrecognizable insn", "loongarch64-linux-gnu")
        self.assertEqual(result["tier"], "architecture_specific")

    def test_multi_arch_target_is_not_llm_ready_tier(self):
        result = classify_relevance("generic optimizer issue", "aarch64, loongarch64, x86_64")
        self.assertEqual(result["tier"], "multi_arch_shared")

    def test_unrelated_is_rejected(self):
        result = classify_relevance("x86 ICE", "x86_64-linux-gnu")
        self.assertEqual(result["tier"], "not_loongarch")

    def test_explicit_loongarch64_scope(self):
        result = classify_architecture_scope(
            {
                "metadata": {"summary": "LoongArch ICE", "cf_gcctarget": "loongarch"},
                "description": "Compile with -mlasx on LA664.",
                "comments": [],
                "testcases": [],
            }
        )
        self.assertEqual(result["scope"], "loongarch64")

    def test_loongarch32_is_not_loongarch64(self):
        result = classify_architecture_scope(
            {
                "metadata": {"summary": "LoongArch32 ABI", "cf_gcctarget": "loongarch32"},
                "description": "Build with -mabi=ilp32d.",
                "comments": [],
                "testcases": [],
            }
        )
        self.assertEqual(result["scope"], "loongarch32")

    def test_comment_failure_becomes_observed_tier(self):
        result = classify_full_relevance(
            {"summary": "generic combine regression", "cf_gcctarget": ""},
            [{"count": 4, "text": "This ICE is reproducible on loongarch64-linux-gnu."}],
            [],
            ["public_comment_contains_loongarch"],
        )
        self.assertEqual(result["tier"], "loongarch_observed")

    def test_comment_regtest_only_is_validation_tier(self):
        result = classify_full_relevance(
            {"summary": "generic optimizer patch", "cf_gcctarget": ""},
            [{"count": 2, "text": "Bootstrapped and regtested on loongarch64."}],
            [],
            ["public_comment_contains_loongarch"],
        )
        self.assertEqual(result["tier"], "loongarch_validation_only")


    def test_general_quality_scores_reduced_ice_with_testcase(self):
        report = {
            "metadata": {
                "summary": "ICE in tree optimizer with reduced testcase",
                "component": "tree-optimization",
                "resolution": "FIXED",
                "keywords": ["regression"],
            },
            "description": "Reduced testcase: compile with gcc -O2 t.c and get an internal compiler error.",
            "comments": [],
            "testcases": [{"path": "testcases/t.c", "provenance": {}}],
        }
        quality = classify_general_quality(report)
        self.assertGreaterEqual(quality["score"], 6)
        self.assertIn("ice", quality["signals"])
        self.assertIn("has_extractable_testcase", quality["signals"])

    def test_general_quality_penalizes_invalid_without_testcase(self):
        report = {
            "metadata": {"summary": "question", "component": "other", "resolution": "INVALID"},
            "description": "not a compiler bug",
            "comments": [],
            "testcases": [],
        }
        quality = classify_general_quality(report)
        self.assertLess(quality["score"], 6)

    def test_regression_tested_footer_is_not_an_observed_failure(self):
        result = classify_full_relevance(
            {"summary": "generic optimizer regression", "cf_gcctarget": ""},
            [
                {
                    "count": 7,
                    "text": (
                        "Fix the optimizer failure described above. "
                        "Bootstrapped and regression tested on x86_64, loongarch64, and riscv64."
                    ),
                }
            ],
            [],
            ["comments_fulltext_loongarch"],
        )
        self.assertEqual(result["tier"], "loongarch_validation_only")


class ExtractionTests(unittest.TestCase):
    def test_source_attachment_detection(self):
        self.assertTrue(
            is_source_attachment(
                {"file_name": "repro.out", "content_type": "text/x-csrc", "is_patch": 0}
            )
        )
        self.assertFalse(
            is_source_attachment(
                {"file_name": "fix.patch", "content_type": "text/plain", "is_patch": 1}
            )
        )

    def test_fenced_code_extraction(self):
        comments = [
            {
                "count": 3,
                "text": "Reduced testcase:\n```c\nint main(void) { return 0; }\n```",
            }
        ]
        result = extract_comment_testcases(comments)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["language"], "c")
        self.assertIn("int main", result[0]["content"])

    def test_safe_filename_drops_path_traversal(self):
        self.assertNotIn("/", safe_filename("../../test.c"))

    def test_uppercase_c_and_cpp_suffixes(self):
        self.assertEqual(language_for("test.C"), "c++")
        self.assertEqual(language_for("test.cpp", "text/x-csrc"), "c++")

    def test_language_inference_for_unlabelled_code(self):
        self.assertEqual(language_for_content("#include <mutex>\nstd::once_flag f;"), "c++")
        self.assertEqual(language_for_content("int main(void) { return 0; }"), "c")


class VerificationTests(unittest.TestCase):
    def test_minimal_valid_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            report_dir = archive / "reports" / "bug-1"
            testcase = report_dir / "testcases" / "test.c"
            testcase.parent.mkdir(parents=True)
            data = b"int main(void) { return 0; }\n"
            testcase.write_bytes(data)
            report = {
                "schema_version": 2,
                "metadata": {"id": 1},
                "source_url": "https://gcc.gnu.org/bugzilla/show_bug.cgi?id=1",
                "relevance": {"tier": "architecture_specific"},
                "architecture_scope": {"scope": "loongarch64"},
                "disposition": {"eligible_as_gcc_bug_report": True},
                "description": "ICE on loongarch64",
                "comments": [{"text": "ICE on loongarch64"}],
                "llm_ready": True,
                "expanded_llm_ready": True,
                "testcases": [
                    {"path": "testcases/test.c", "sha256": sha256_bytes(data)}
                ],
            }
            (report_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
            (report_dir / "report.md").write_text("# Bug 1\n", encoding="utf-8")
            raw = report_dir / "raw"
            raw.mkdir()
            for name in ("bug.json", "comments.json", "attachments.json"):
                (raw / name).write_text("{}\n", encoding="utf-8")
            record = {
                "bug_id": 1,
                "llm_ready": True,
                "expanded_llm_ready": True,
                "report_path": "reports/bug-1/report.json",
            }
            line = json.dumps(record) + "\n"
            (archive / "index.jsonl").write_text(line, encoding="utf-8")
            (archive / "llm-ready.jsonl").write_text(line, encoding="utf-8")
            (archive / "llm-expanded-ready.jsonl").write_text(line, encoding="utf-8")
            (archive / "llm-dataset.jsonl").write_text(
                json.dumps(
                    {
                        "bug_id": 1,
                        "description": "ICE on loongarch64",
                        "architecture_scope": {"scope": "loongarch64"},
                        "testcases": [
                            {
                                "source_path": "reports/bug-1/testcases/test.c",
                                "source_sha256": sha256_bytes(data),
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (archive / "llm-expanded-dataset.jsonl").write_text(
                (archive / "llm-dataset.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (archive / "index.csv").write_text("bug_id\n1\n", encoding="utf-8")
            (archive / "SUMMARY.md").write_text("# Summary\n", encoding="utf-8")
            (archive / "manifest.json").write_text(
                json.dumps(
                    {
                        "base_url": "https://gcc.gnu.org/bugzilla/rest.cgi",
                        "errors": [],
                        "counts": {
                            "candidate_reports": 1,
                            "llm_ready_reports": 1,
                            "llm_dataset_records": 1,
                            "expanded_llm_ready_reports": 1,
                            "expanded_llm_dataset_records": 1,
                            "testcase_artifacts": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )
            archive_raw = archive / "raw"
            archive_raw.mkdir()
            for name in (
                "version.json",
                "search-summary-loongarch.json",
                "search-target-loongarch.json",
                "search-comments-loongarch.json",
                "search-testsuite-pr-ids.json",
            ):
                (archive_raw / name).write_text("{}\n", encoding="utf-8")
            self.assertEqual(verify_archive(archive)["reports"], 1)


if __name__ == "__main__":
    unittest.main()
