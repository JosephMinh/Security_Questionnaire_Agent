"""Focused unit coverage for the deterministic failure-path e2e script helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import rag


def _load_failure_paths_module():
    """Import the e2e script by path so helper tests do not require package layout."""

    module_path = (
        Path(__file__).resolve().parents[1] / "e2e" / "run_failure_paths.py"
    )
    spec = importlib.util.spec_from_file_location("run_failure_paths", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load failure-path script module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunFailurePathsScriptTest(unittest.TestCase):
    """Verify the helper surfaces behind the failure-path e2e script stay stable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _load_failure_paths_module()

    def test_runtime_overrides_point_to_one_isolated_workspace_tree(self) -> None:
        """The e2e script should redirect runtime paths into one isolated temp tree."""

        with TemporaryDirectory() as tmp_dir_name:
            base_dir = Path(tmp_dir_name) / "failure-path-artifacts"
            gdd_updates, rag_updates, paths = self.script._runtime_overrides(base_dir)

        self.assertEqual(paths.artifact_root, base_dir)
        self.assertEqual(paths.log_path, base_dir / "run_failure_paths.jsonl")
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

    def test_jsonl_logger_writes_script_and_rag_records(self) -> None:
        """The helper logger should preserve both direct script records and backend relay records."""

        with TemporaryDirectory() as tmp_dir_name:
            log_path = Path(tmp_dir_name) / "run_failure_paths.jsonl"
            logger = self.script.JsonlLogger(log_path, verbose=False)
            logger.emit(
                component="e2e",
                event="scenario_started",
                status="started",
                message="Beginning one deterministic scenario.",
                phase="setup",
            )
            logger.capture_rag_event(
                {
                    "component": "pipeline",
                    "event": "row_completed",
                    "status": "completed",
                    "level": "INFO",
                    "message": "Completed Q01 as supported.",
                    "run_id": "failure-e2e-run",
                    "question_id": "Q01",
                    "workspace_hash": "workspace-hash",
                    "manifest_hash": "manifest-hash",
                    "index_action": rag.INDEX_ACTION_REUSED,
                    "retrieved_chunk_count": 4,
                    "valid_citation_count": 1,
                    "answer_type": rag.ANSWER_TYPE_SUPPORTED,
                    "confidence_band": rag.CONFIDENCE_BAND_MEDIUM,
                    "review_status": rag.STATUS_READY_FOR_REVIEW,
                    "retry_attempt": 0,
                    "artifact_path": Path("data/outputs/failure.jsonl"),
                    "reason": "reused",
                }
            )

            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["component"], "e2e")
        self.assertEqual(records[0]["event"], "scenario_started")
        self.assertEqual(records[0]["phase"], "setup")
        self.assertEqual(records[1]["component"], "rag")
        self.assertEqual(records[1]["event"], "row_completed")
        self.assertEqual(records[1]["run_id"], "failure-e2e-run")
        self.assertEqual(records[1]["question_id"], "Q01")
        self.assertEqual(records[1]["workspace_hash"], "workspace-hash")
        self.assertEqual(records[1]["manifest_hash"], "manifest-hash")
        self.assertEqual(records[1]["index_action"], rag.INDEX_ACTION_REUSED)
        self.assertEqual(records[1]["retrieved_chunk_count"], 4)
        self.assertEqual(records[1]["valid_citation_count"], 1)
        self.assertEqual(records[1]["answer_type"], rag.ANSWER_TYPE_SUPPORTED)
        self.assertEqual(records[1]["confidence_band"], rag.CONFIDENCE_BAND_MEDIUM)
        self.assertEqual(records[1]["review_status"], rag.STATUS_READY_FOR_REVIEW)
        self.assertEqual(records[1]["retry_attempt"], 0)
        self.assertEqual(records[1]["artifact_path"], "data/outputs/failure.jsonl")
        self.assertEqual(records[1]["reason"], "reused")
        self.assertEqual(records[1]["source_component"], "pipeline")
        self.assertEqual(records[1]["rag_record"]["question_id"], "Q01")


if __name__ == "__main__":
    unittest.main()
