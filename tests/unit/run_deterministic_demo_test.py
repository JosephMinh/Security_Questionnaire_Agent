"""Focused unit coverage for the deterministic golden-path e2e script helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import rag


def _load_deterministic_demo_module():
    """Import the e2e script by path so helper tests do not require package layout."""

    module_path = (
        Path(__file__).resolve().parents[1] / "e2e" / "run_deterministic_demo.py"
    )
    spec = importlib.util.spec_from_file_location("run_deterministic_demo", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(
            f"Could not load deterministic-demo script module from {module_path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunDeterministicDemoScriptTest(unittest.TestCase):
    """Verify the helper surfaces behind the deterministic demo e2e script stay stable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _load_deterministic_demo_module()
        fixture = cls.script._load_expected_fixture()
        cls.questions_by_id = {
            str(question["question_id"]): dict(question)
            for question in fixture["questions"]
        }

    def _assert_result_matches_expected_fixture(
        self,
        question_id: str,
        result: rag.GeneratedAnswerResult,
    ) -> None:
        """Assert one deterministic helper result stays aligned to the expected fixture."""

        expected = self.questions_by_id[question_id]
        self.assertEqual(result.answer_type, expected["expected_answer_type"])
        self.assertEqual(result.status, expected["expected_status"])
        self.assertIn(result.confidence_band, expected["allowed_confidence_bands"])
        self.assertTrue(result.answer.startswith(expected["expected_opening_token"]))

        if expected["expected_status"] == rag.STATUS_NEEDS_REVIEW:
            self.assertEqual(result.reviewer_note, expected["rationale"])
        else:
            self.assertEqual(result.reviewer_note, "")

        if expected.get("primary_source") is None:
            self.assertEqual(len(result.citations), 0)
        else:
            self.assertEqual(len(result.citations), 1)

    def test_citation_helper_preserves_markdown_section_and_pdf_page(self) -> None:
        """Primary-source citations should expose stable reviewer-facing provenance."""

        with patch.object(self.script.rag, "RUNTIME_EVIDENCE_DIR", rag.SEED_EVIDENCE_DIR):
            markdown_citation = self.script._citation_for_expected(
                self.questions_by_id["Q01"]
            )[0]
            pdf_citation = self.script._citation_for_expected(
                self.questions_by_id["Q14"]
            )[0]

        self.assertEqual(markdown_citation.source, rag.ENCRYPTION_POLICY_FILE_NAME)
        self.assertEqual(markdown_citation.section, "Data at Rest")
        self.assertEqual(
            markdown_citation.display_label,
            "Encryption Policy - Data at Rest",
        )
        self.assertIn(
            "AcmeCloud encrypts customer data at rest in production systems using AES-256.",
            markdown_citation.snippet_text,
        )

        self.assertEqual(pdf_citation.source, rag.SOC2_SUMMARY_FILE_NAME)
        self.assertEqual(pdf_citation.page, 1)
        self.assertEqual(
            pdf_citation.display_label,
            "AcmeCloud SOC 2 Summary - Page 1",
        )
        self.assertIn(
            "AcmeCloud completed a SOC 2 Type II examination for its cloud service environment.",
            pdf_citation.snippet_text,
        )

    def test_answer_result_helper_matches_fixture_review_posture(self) -> None:
        """Supported, partial, and unsupported rows should map onto the planned row contract."""

        with patch.object(self.script.rag, "RUNTIME_EVIDENCE_DIR", rag.SEED_EVIDENCE_DIR):
            supported = self.script._answer_result_for_expected(self.questions_by_id["Q01"])
            partial = self.script._answer_result_for_expected(self.questions_by_id["Q17"])
            unsupported = self.script._answer_result_for_expected(
                self.questions_by_id["Q19"]
            )

        self._assert_result_matches_expected_fixture("Q01", supported)
        self._assert_result_matches_expected_fixture("Q17", partial)
        self._assert_result_matches_expected_fixture("Q19", unsupported)

    def test_canonical_smoke_triad_matches_expected_fixture(self) -> None:
        """The Q01/Q17/Q21 smoke triad should preserve the planned support matrix."""

        with patch.object(self.script.rag, "RUNTIME_EVIDENCE_DIR", rag.SEED_EVIDENCE_DIR):
            q01 = self.script._answer_result_for_expected(self.questions_by_id["Q01"])
            q17 = self.script._answer_result_for_expected(self.questions_by_id["Q17"])
            q21 = self.script._answer_result_for_expected(self.questions_by_id["Q21"])

        self._assert_result_matches_expected_fixture("Q01", q01)
        self._assert_result_matches_expected_fixture("Q17", q17)
        self._assert_result_matches_expected_fixture("Q21", q21)

    def test_clear_stale_publish_artifacts_removes_only_deterministic_rerun_paths(self) -> None:
        """Deterministic reruns should clear only their own stale backup/staging dirs."""

        with TemporaryDirectory() as tmp_dir_name:
            output_dir = Path(tmp_dir_name) / "deterministic_demo_packet"
            backup_dir = self.script._deterministic_backup_dir(output_dir)
            staging_dir = output_dir.parent / (
                f".{output_dir.name}-staging-{rag._safe_filesystem_token(self.script.RUN_ID)}-demo"
            )
            unrelated_dir = output_dir.parent / ".deterministic_demo_packet-staging-other-run-demo"
            backup_dir.mkdir(parents=True)
            staging_dir.mkdir(parents=True)
            unrelated_dir.mkdir(parents=True)

            removed_paths = self.script._clear_stale_publish_artifacts(output_dir)

            self.assertEqual(
                removed_paths,
                (backup_dir, staging_dir),
            )
            self.assertFalse(backup_dir.exists())
            self.assertFalse(staging_dir.exists())
            self.assertTrue(unrelated_dir.exists())


if __name__ == "__main__":
    unittest.main()
