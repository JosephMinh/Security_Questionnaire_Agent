"""Unit coverage for the curated demo workspace setup script."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
import io
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import generate_demo_data as gdd


class GenerateDemoDataTest(unittest.TestCase):
    """Verify workspace setup, reset, manifest, and validation behavior."""

    @contextmanager
    def isolated_workspace(self):
        """Patch the setup module so one test uses a fully isolated runtime workspace."""
        with TemporaryDirectory() as tmp_dir_name:
            temp_root = Path(tmp_dir_name)
            data_dir = temp_root / "data"
            runtime_questionnaires_dir = data_dir / "questionnaires"
            runtime_evidence_dir = data_dir / "evidence"
            outputs_dir = data_dir / "outputs"
            chroma_dir = data_dir / "chroma"

            original_seed_paths = gdd.SEED_TO_RUNTIME_PATHS
            questionnaire_source_path = next(
                source_path
                for source_path, _ in original_seed_paths
                if source_path.name == gdd.QUESTIONNAIRE_FILE_NAME
            )
            evidence_source_paths = {
                source_path.name: source_path
                for source_path, _ in original_seed_paths
                if source_path.name != gdd.QUESTIONNAIRE_FILE_NAME
            }

            runtime_directories = (
                runtime_questionnaires_dir,
                runtime_evidence_dir,
                outputs_dir,
                chroma_dir,
            )
            seed_to_runtime_paths = (
                (
                    questionnaire_source_path,
                    runtime_questionnaires_dir / gdd.QUESTIONNAIRE_FILE_NAME,
                ),
                *tuple(
                    (
                        evidence_source_paths[file_name],
                        runtime_evidence_dir / file_name,
                    )
                    for file_name in gdd.EXPECTED_EVIDENCE_FILE_NAMES
                ),
            )

            with patch.multiple(
                gdd,
                DATA_DIR=data_dir,
                RUNTIME_QUESTIONNAIRES_DIR=runtime_questionnaires_dir,
                RUNTIME_EVIDENCE_DIR=runtime_evidence_dir,
                OUTPUTS_DIR=outputs_dir,
                CHROMA_DIR=chroma_dir,
                RUNTIME_DIRECTORIES=runtime_directories,
                WORKSPACE_HASH_DIRECTORIES=(
                    runtime_questionnaires_dir,
                    runtime_evidence_dir,
                ),
                SEED_TO_RUNTIME_PATHS=seed_to_runtime_paths,
            ):
                yield

    def test_prepare_demo_workspace_copies_seed_assets_and_writes_manifest(self):
        """A fresh setup run should create runtime dirs, copy seed files, and write hashes."""
        with self.isolated_workspace():
            gdd.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
            stale_output = gdd.OUTPUTS_DIR / "old-output.txt"
            stale_output.write_text("old output", encoding="utf-8")

            copied_assets = gdd.prepare_demo_workspace(reset_index=False)

            self.assertEqual(
                len(copied_assets),
                6,
                "Expected one questionnaire plus five evidence assets to be copied.",
            )
            for directory in gdd.RUNTIME_DIRECTORIES:
                self.assertTrue(directory.is_dir(), f"Runtime directory missing: {directory}")
            self.assertFalse(
                stale_output.exists(),
                "prepare_demo_workspace should clear prior outputs without preserving stale files.",
            )

            manifest = json.loads(gdd.manifest_path().read_text(encoding="utf-8"))
            expected_relative_paths = {
                "questionnaires/Demo_Security_Questionnaire.xlsx",
                "evidence/AcmeCloud_SOC2_Summary.pdf",
                "evidence/Encryption_Policy.md",
                "evidence/Access_Control_Policy.md",
                "evidence/Incident_Response_Policy.md",
                "evidence/Backup_and_Recovery_Policy.md",
            }
            actual_relative_paths = {
                entry["relative_path"] for entry in manifest["files"]
            }
            self.assertEqual(
                actual_relative_paths,
                expected_relative_paths,
                "Manifest should describe the exact curated runtime questionnaire and evidence files.",
            )
            self.assertTrue(
                manifest["workspace_hash"],
                "Manifest should include a combined workspace hash for the runtime questionnaire/evidence set.",
            )

    def test_prepare_demo_workspace_reset_index_clears_only_chroma(self):
        """Reset-index should clear cached index files without removing runtime content."""
        with self.isolated_workspace():
            gdd.ensure_runtime_directories()
            stale_output = gdd.OUTPUTS_DIR / "stale.csv"
            stale_output.write_text("stale output", encoding="utf-8")
            stale_index_file = gdd.CHROMA_DIR / "cache.bin"
            stale_index_file.write_text("cached index data", encoding="utf-8")

            gdd.prepare_demo_workspace(reset_index=True)

            self.assertFalse(stale_output.exists(), "Output cleanup should remove stale artifacts.")
            self.assertFalse(
                stale_index_file.exists(),
                "Reset-index should remove existing Chroma cache artifacts.",
            )
            self.assertTrue(
                gdd.questionnaire_path().exists(),
                "Reset-index must not prevent the curated runtime questionnaire from being copied.",
            )
            for evidence_path in gdd.expected_runtime_evidence_paths():
                self.assertTrue(
                    evidence_path.exists(),
                    f"Reset-index must preserve the runtime evidence copy: {evidence_path.name}",
                )

    def test_prepare_demo_workspace_removes_unexpected_runtime_files_before_copy(self):
        """Setup reruns should self-heal unexpected runtime artifacts instead of failing validation."""
        with self.isolated_workspace():
            gdd.prepare_demo_workspace(reset_index=False)
            unexpected_questionnaire = (
                gdd.RUNTIME_QUESTIONNAIRES_DIR / "Unexpected_Workbook.xlsx"
            )
            unexpected_questionnaire.write_text("stale workbook", encoding="utf-8")
            unexpected_evidence = gdd.RUNTIME_EVIDENCE_DIR / "Unexpected.txt"
            unexpected_evidence.write_text("stale evidence", encoding="utf-8")
            missing_evidence = gdd.expected_runtime_evidence_paths()[0]
            missing_evidence.unlink()

            copied_assets = gdd.prepare_demo_workspace(reset_index=False)

            self.assertEqual(len(copied_assets), 6)
            self.assertFalse(unexpected_questionnaire.exists())
            self.assertFalse(unexpected_evidence.exists())
            self.assertTrue(gdd.questionnaire_path().exists())
            for evidence_path in gdd.expected_runtime_evidence_paths():
                self.assertTrue(evidence_path.exists())

    def test_validate_runtime_workspace_reports_actionable_error_for_missing_questionnaire(self):
        """Broken curated workspaces should fail with a recovery-oriented validation error."""
        with self.isolated_workspace():
            gdd.prepare_demo_workspace(reset_index=False)
            gdd.questionnaire_path().unlink()

            with self.assertRaises(gdd.WorkspaceValidationError) as context:
                gdd.validate_runtime_workspace()

            rendered_issues = "\n".join(issue.render() for issue in context.exception.issues)
            self.assertIn("missing", rendered_issues.lower())
            self.assertIn("Recovery:", rendered_issues)
            self.assertIn("generate_demo_data.py", rendered_issues)

    def test_validate_runtime_workspace_reports_missing_evidence_directory_as_issues(self):
        """Missing runtime evidence directories should produce actionable validation issues."""
        with self.isolated_workspace():
            gdd.prepare_demo_workspace(reset_index=False)
            shutil.rmtree(gdd.RUNTIME_EVIDENCE_DIR)

            with self.assertRaises(gdd.WorkspaceValidationError) as context:
                gdd.validate_runtime_workspace()

            rendered_issues = "\n".join(issue.render() for issue in context.exception.issues)
            self.assertIn("curated runtime evidence file is missing", rendered_issues)
            self.assertIn("Recovery:", rendered_issues)

    def test_validate_questionnaire_workbook_closes_read_only_workbook_handle(self):
        """Workbook validation should always close the openpyxl handle after inspection."""
        with self.isolated_workspace():
            gdd.ensure_runtime_directories()
            gdd.questionnaire_path().write_text("placeholder", encoding="utf-8")
            worksheet = MagicMock()
            worksheet.iter_rows.return_value = iter(
                [
                    gdd.SEED_QUESTION_COLUMNS,
                    *(
                        (question_id, "Category", f"Question {question_id}")
                        for question_id in gdd.EXPECTED_QUESTION_IDS
                    ),
                ]
            )
            workbook = MagicMock()
            workbook.sheetnames = [gdd.QUESTION_SHEET_NAME]
            workbook.__getitem__.return_value = worksheet

            with patch.object(gdd, "load_workbook", return_value=workbook):
                issues = gdd.validate_questionnaire_workbook()

            self.assertEqual(issues, ())
            workbook.close.assert_called_once_with()

    def test_main_reports_success_for_default_cli_flow(self):
        """The default CLI path should prepare the workspace and print summary lines."""
        with self.isolated_workspace():
            stdout = io.StringIO()
            with patch.object(
                gdd,
                "parse_args",
                return_value=argparse.Namespace(reset_index=False),
            ), redirect_stdout(stdout):
                exit_code = gdd.main()

            output = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Prepared demo workspace.", output)
            self.assertIn("Workspace manifest:", output)
            self.assertIn("Index reset requested: False", output)

    def test_main_reset_index_cli_clears_chroma_and_reports_true(self):
        """The reset-index CLI path should clear Chroma state and report the flag in output."""
        with self.isolated_workspace():
            gdd.ensure_runtime_directories()
            stale_index_file = gdd.CHROMA_DIR / "stale-index.bin"
            stale_index_file.write_text("old", encoding="utf-8")

            stdout = io.StringIO()
            with patch.object(
                gdd,
                "parse_args",
                return_value=argparse.Namespace(reset_index=True),
            ), redirect_stdout(stdout):
                exit_code = gdd.main()

            self.assertEqual(exit_code, 0)
            self.assertFalse(stale_index_file.exists())
            self.assertIn("Index reset requested: True", stdout.getvalue())

    def test_main_reports_validation_failure_for_broken_copy_flow(self):
        """The CLI path should fail fast with recovery text when validation catches bad runtime state."""
        with self.isolated_workspace():
            original_copy_seed_assets = gdd.copy_seed_assets

            def broken_copy_seed_assets():
                copied_assets = original_copy_seed_assets()
                gdd.questionnaire_path().unlink()
                return copied_assets

            stdout = io.StringIO()
            with patch.object(
                gdd,
                "copy_seed_assets",
                side_effect=broken_copy_seed_assets,
            ), patch.object(
                gdd,
                "parse_args",
                return_value=argparse.Namespace(reset_index=False),
            ), redirect_stdout(stdout):
                exit_code = gdd.main()

            output = stdout.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertIn("Workspace validation failed.", output)
            self.assertIn("Recovery:", output)


if __name__ == "__main__":
    unittest.main()
