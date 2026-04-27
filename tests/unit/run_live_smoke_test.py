"""Focused unit coverage for the optional live-provider smoke e2e script helpers."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import rag


def _load_live_smoke_module():
    """Import the e2e script by path so helper tests do not require package layout."""

    module_path = Path(__file__).resolve().parents[1] / "e2e" / "run_live_smoke.py"
    spec = importlib.util.spec_from_file_location("run_live_smoke", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load live-smoke script module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunLiveSmokeScriptTest(unittest.TestCase):
    """Verify the helper surfaces behind the live-provider smoke script stay stable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _load_live_smoke_module()

    def test_runtime_overrides_point_to_one_isolated_workspace_tree(self) -> None:
        """The live-smoke script should redirect runtime paths into one isolated temp tree."""

        with TemporaryDirectory() as tmp_dir_name:
            base_dir = Path(tmp_dir_name) / "live-smoke-artifacts"
            gdd_updates, rag_updates, paths = self.script._runtime_overrides(base_dir)

        self.assertEqual(paths.artifact_root, base_dir)
        self.assertEqual(paths.log_path, base_dir / "run_live_smoke.jsonl")
        self.assertEqual(paths.isolated_data_dir, base_dir / "isolated_data")
        self.assertEqual(
            gdd_updates["RUNTIME_QUESTIONNAIRES_DIR"],
            paths.runtime_questionnaires_dir,
        )
        self.assertEqual(rag_updates["RUNTIME_EVIDENCE_DIR"], paths.runtime_evidence_dir)
        self.assertEqual(gdd_updates["OUTPUTS_DIR"], paths.outputs_dir)
        self.assertEqual(rag_updates["CHROMA_DIR"], paths.chroma_dir)
        self.assertEqual(
            gdd_updates["WORKSPACE_HASH_DIRECTORIES"],
            (
                paths.runtime_questionnaires_dir,
                paths.runtime_evidence_dir,
            ),
        )
        self.assertEqual(
            rag_updates["RUNTIME_DIRECTORIES"],
            (
                paths.runtime_questionnaires_dir,
                paths.runtime_evidence_dir,
                paths.outputs_dir,
                paths.chroma_dir,
            ),
        )
        seed_to_runtime_paths = gdd_updates["SEED_TO_RUNTIME_PATHS"]
        self.assertEqual(
            seed_to_runtime_paths[0],
            (
                rag.SEED_QUESTIONNAIRE_DIR / rag.QUESTIONNAIRE_FILE_NAME,
                paths.runtime_questionnaires_dir / rag.QUESTIONNAIRE_FILE_NAME,
            ),
        )
        self.assertEqual(len(seed_to_runtime_paths), 1 + len(rag.EXPECTED_EVIDENCE_FILE_NAMES))
        self.assertTrue(
            all(destination.is_relative_to(paths.isolated_data_dir) for _, destination in seed_to_runtime_paths)
        )

    def test_jsonl_logger_writes_safe_script_and_rag_records(self) -> None:
        """The live-smoke logger should preserve safe metadata without dumping transcripts."""

        with TemporaryDirectory() as tmp_dir_name:
            log_path = Path(tmp_dir_name) / "run_live_smoke.jsonl"
            logger = self.script.JsonlLogger(log_path, verbose=False)
            logger.emit(
                event="question_completed",
                status=rag.LOG_STATUS_COMPLETED,
                message="Validated one live-provider smoke row.",
                question_id="Q01",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                review_status=rag.STATUS_READY_FOR_REVIEW,
                opening_token="Yes.",
                retrieved_sources=("Encryption_Policy.md", "AcmeCloud_SOC2_Summary.pdf"),
                cited_sources=("Encryption_Policy.md",),
            )
            logger.capture_rag_event(
                {
                    "component": "pipeline",
                    "event": "answer_generated",
                    "status": "completed",
                    "level": "INFO",
                    "message": "Generated a supported answer with 1 valid citations and routed the row to Ready for Review.",
                    "question_id": "Q01",
                    "run_id": "live-smoke-e2e-q01",
                }
            )

            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["component"], rag.LOG_COMPONENT_VERIFICATION)
        self.assertEqual(records[0]["event"], "question_completed")
        self.assertEqual(records[0]["question_id"], "Q01")
        self.assertEqual(records[0]["opening_token"], "Yes.")
        self.assertEqual(records[0]["retrieved_sources"][0], "Encryption_Policy.md")
        self.assertNotIn("answer", records[0])
        self.assertEqual(records[1]["component"], rag.LOG_COMPONENT_VERIFICATION)
        self.assertEqual(records[1]["source_component"], "pipeline")
        self.assertEqual(records[1]["rag_record"]["question_id"], "Q01")

    def test_expectations_follow_canonical_fixture_contract(self) -> None:
        """The canonical live-smoke trio should stay aligned to the expected-outcomes fixture."""

        expectations = self.script._expectations_for(("Q01", "Q17", "Q21"))
        q01, q17, q21 = expectations

        self.assertEqual(q01.question_id, "Q01")
        self.assertEqual(q01.expected_answer_type, rag.ANSWER_TYPE_SUPPORTED)
        self.assertEqual(q01.expected_status, rag.STATUS_READY_FOR_REVIEW)
        self.assertEqual(q01.expected_opening_token, "Yes.")
        self.assertEqual(q01.primary_source, rag.ENCRYPTION_POLICY_FILE_NAME)
        self.assertEqual(
            q01.allowed_confidence_bands,
            (rag.CONFIDENCE_BAND_MEDIUM, rag.CONFIDENCE_BAND_HIGH),
        )

        self.assertEqual(q17.question_id, "Q17")
        self.assertEqual(q17.expected_answer_type, rag.ANSWER_TYPE_PARTIAL)
        self.assertEqual(q17.expected_status, rag.STATUS_NEEDS_REVIEW)
        self.assertEqual(q17.expected_opening_token, "Partially.")
        self.assertEqual(q17.primary_source, rag.INCIDENT_RESPONSE_POLICY_FILE_NAME)
        self.assertEqual(q17.allowed_confidence_bands, (rag.CONFIDENCE_BAND_LOW,))

        self.assertEqual(q21.question_id, "Q21")
        self.assertEqual(q21.expected_answer_type, rag.ANSWER_TYPE_UNSUPPORTED)
        self.assertEqual(q21.expected_status, rag.STATUS_NEEDS_REVIEW)
        self.assertEqual(q21.expected_opening_token, "Not stated.")
        self.assertIsNone(q21.primary_source)
        self.assertEqual(q21.allowed_confidence_bands, (rag.CONFIDENCE_BAND_LOW,))

    def test_main_skips_cleanly_when_openai_api_key_is_missing(self) -> None:
        """Missing credentials should produce one clean skip instead of a confusing failure."""

        with TemporaryDirectory() as tmp_dir_name:
            log_dir = Path(tmp_dir_name) / "logs"
            with patch.object(self.script, "_load_repo_dotenv_if_available", return_value=None):
                with patch.dict(os.environ, {}, clear=True):
                    exit_code = self.script.main(["--log-dir", str(log_dir)])

            log_path = log_dir / "run_live_smoke.jsonl"
            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event"], "live_smoke_skipped")
        self.assertEqual(records[0]["status"], rag.LOG_STATUS_SKIPPED)
        self.assertEqual(records[0]["reason"], "missing_openai_api_key")


if __name__ == "__main__":
    unittest.main()
