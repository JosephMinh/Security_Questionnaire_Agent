"""Unit tests for the demo workspace setup and validation script."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

import generate_demo_data as setup_script


class GenerateDemoDataSetupTests(unittest.TestCase):
    """Exercise setup-script behavior in isolated temporary workspaces."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.seed_root = self.root / "seed_data"
        self.seed_questionnaire_dir = self.seed_root / "questionnaire"
        self.seed_evidence_dir = self.seed_root / "evidence"
        self.data_dir = self.root / "data"
        self.runtime_questionnaires_dir = self.data_dir / "questionnaires"
        self.runtime_evidence_dir = self.data_dir / "evidence"
        self.outputs_dir = self.data_dir / "outputs"
        self.chroma_dir = self.data_dir / "chroma"
        self.repo_seed_paths = tuple(source for source, _ in setup_script.SEED_TO_RUNTIME_PATHS)
        self.runtime_seed_to_runtime_paths = self._copy_repo_seed_assets()
        self.patchers = self._build_patchers()
        self.patch_stack = ExitStack()
        for patcher in self.patchers:
            self.patch_stack.enter_context(patcher)

    def tearDown(self) -> None:
        self.patch_stack.close()
        self._temp_dir.cleanup()

    def test_main_default_run_creates_runtime_workspace_and_manifest(self) -> None:
        exit_code, output = self._run_main()

        self.assertEqual(exit_code, 0, msg=f"default CLI path should succeed:\n{output}")
        for directory in setup_script.RUNTIME_DIRECTORIES:
            self.assertTrue(
                directory.is_dir(),
                msg=f"expected runtime directory to be created: {directory}",
            )

        copied_questionnaire = setup_script.questionnaire_path()
        self.assertTrue(
            copied_questionnaire.exists(),
            msg="expected curated questionnaire workbook to be copied into the runtime workspace",
        )
        runtime_evidence_names = sorted(
            path.name for path in self.runtime_evidence_dir.iterdir() if path.is_file()
        )
        self.assertEqual(
            runtime_evidence_names,
            sorted(setup_script.EXPECTED_EVIDENCE_FILE_NAMES),
            msg="expected exactly the five curated evidence files in the runtime workspace",
        )

        manifest = self._load_manifest()
        self.assertEqual(manifest["manifest_version"], 1)
        self.assertEqual(
            len(manifest["files"]),
            6,
            msg="manifest should cover one questionnaire workbook plus five evidence files",
        )
        self.assertIn("Prepared demo workspace.", output)
        self.assertIn("Workspace manifest:", output)
        self.assertIn("Index reset requested: False", output)

    def test_repeated_default_run_is_idempotent_and_clears_outputs_only(self) -> None:
        first_exit_code, first_output = self._run_main()
        self.assertEqual(first_exit_code, 0, msg=first_output)
        first_manifest = self._load_manifest()

        stale_output = self.outputs_dir / "stale.txt"
        stale_output.write_text("old output", encoding="utf-8")
        retained_index_file = self.chroma_dir / "retained-index.bin"
        retained_index_file.parent.mkdir(parents=True, exist_ok=True)
        retained_index_file.write_text("keep me", encoding="utf-8")

        second_exit_code, second_output = self._run_main()
        self.assertEqual(second_exit_code, 0, msg=second_output)
        second_manifest = self._load_manifest()

        self.assertFalse(
            stale_output.exists(),
            msg="default setup reruns should clear prior output artifacts only",
        )
        self.assertTrue(
            retained_index_file.exists(),
            msg="default setup reruns should not clear the Chroma cache without --reset-index",
        )
        self.assertEqual(
            first_manifest["workspace_hash"],
            second_manifest["workspace_hash"],
            msg="repeated default runs against unchanged seed assets should be idempotent",
        )

    def test_reset_index_cli_clears_chroma_without_touching_runtime_files(self) -> None:
        initial_exit_code, initial_output = self._run_main()
        self.assertEqual(initial_exit_code, 0, msg=initial_output)
        runtime_questionnaire_hash = setup_script.file_sha256(setup_script.questionnaire_path())
        runtime_evidence_hashes = {
            path.name: setup_script.file_sha256(path)
            for path in setup_script.expected_runtime_evidence_paths()
        }

        stale_index_file = self.chroma_dir / "old-embeddings.bin"
        stale_index_file.parent.mkdir(parents=True, exist_ok=True)
        stale_index_file.write_text("cached vectors", encoding="utf-8")

        reset_exit_code, reset_output = self._run_main("--reset-index")
        self.assertEqual(reset_exit_code, 0, msg=reset_output)
        self.assertFalse(
            stale_index_file.exists(),
            msg="`--reset-index` should clear only the local Chroma cache directory",
        )
        self.assertEqual(
            runtime_questionnaire_hash,
            setup_script.file_sha256(setup_script.questionnaire_path()),
            msg="reset-index should not rewrite or corrupt the runtime questionnaire copy",
        )
        self.assertEqual(
            runtime_evidence_hashes,
            {
                path.name: setup_script.file_sha256(path)
                for path in setup_script.expected_runtime_evidence_paths()
            },
            msg="reset-index should preserve the copied runtime evidence files",
        )
        self.assertIn("Index reset requested: True", reset_output)

    def test_validate_runtime_workspace_reports_actionable_runtime_breakage(self) -> None:
        exit_code, output = self._run_main()
        self.assertEqual(exit_code, 0, msg=output)

        unexpected_file = self.runtime_evidence_dir / "Unexpected.txt"
        unexpected_file.write_text("not part of the curated demo", encoding="utf-8")
        unexpected_nested_file = self.runtime_evidence_dir / "archive" / "Unexpected.txt"
        unexpected_nested_file.parent.mkdir()
        unexpected_nested_file.write_text("nested evidence", encoding="utf-8")
        unexpected_questionnaire = self.runtime_questionnaires_dir / "Unexpected.xlsx"
        unexpected_questionnaire.write_text("unexpected workbook", encoding="utf-8")
        unexpected_nested_questionnaire = (
            self.runtime_questionnaires_dir / "archive" / "Unexpected.xlsx"
        )
        unexpected_nested_questionnaire.parent.mkdir()
        unexpected_nested_questionnaire.write_text("nested workbook", encoding="utf-8")
        missing_file = self.runtime_evidence_dir / setup_script.EXPECTED_EVIDENCE_FILE_NAMES[1]
        missing_file.unlink()

        with self.assertRaises(setup_script.WorkspaceValidationError) as raised:
            setup_script.validate_runtime_workspace()

        rendered_issues = "\n".join(issue.render() for issue in raised.exception.issues)
        self.assertIn("Unexpected runtime evidence file present", rendered_issues)
        self.assertIn("Unexpected runtime questionnaire file present", rendered_issues)
        self.assertIn("evidence/archive/Unexpected.txt", rendered_issues)
        self.assertIn("questionnaires/archive/Unexpected.xlsx", rendered_issues)
        self.assertIn("curated runtime evidence file is missing", rendered_issues)
        self.assertIn("Rerun `python generate_demo_data.py`", rendered_issues)

    def test_main_reports_recovery_oriented_validation_failure_for_bad_seed_copy(self) -> None:
        workbook_path = self.seed_questionnaire_dir / setup_script.QUESTIONNAIRE_FILE_NAME
        workbook = load_workbook(workbook_path)
        worksheet = workbook[setup_script.QUESTION_SHEET_NAME]
        worksheet["A2"] = "BAD01"
        workbook.save(workbook_path)
        workbook.close()

        exit_code, output = self._run_main()

        self.assertEqual(
            exit_code,
            1,
            msg="main() should fail fast when the copied runtime workspace violates the curated contract",
        )
        self.assertIn("Workspace validation failed.", output)
        self.assertIn("Expected question IDs in order", output)
        self.assertIn("Rerun `python generate_demo_data.py`", output)

    def _copy_repo_seed_assets(self) -> tuple[tuple[Path, Path], ...]:
        self.seed_questionnaire_dir.mkdir(parents=True, exist_ok=True)
        self.seed_evidence_dir.mkdir(parents=True, exist_ok=True)

        runtime_pairs: list[tuple[Path, Path]] = []
        for source_path, _ in setup_script.SEED_TO_RUNTIME_PATHS:
            if source_path.name == setup_script.QUESTIONNAIRE_FILE_NAME:
                copied_source = self.seed_questionnaire_dir / source_path.name
                runtime_path = self.runtime_questionnaires_dir / source_path.name
            else:
                copied_source = self.seed_evidence_dir / source_path.name
                runtime_path = self.runtime_evidence_dir / source_path.name
            shutil.copy2(source_path, copied_source)
            runtime_pairs.append((copied_source, runtime_path))
        return tuple(runtime_pairs)

    def _build_patchers(self) -> tuple[object, ...]:
        return (
            patch.object(setup_script, "DATA_DIR", self.data_dir),
            patch.object(setup_script, "RUNTIME_QUESTIONNAIRES_DIR", self.runtime_questionnaires_dir),
            patch.object(setup_script, "RUNTIME_EVIDENCE_DIR", self.runtime_evidence_dir),
            patch.object(setup_script, "OUTPUTS_DIR", self.outputs_dir),
            patch.object(setup_script, "CHROMA_DIR", self.chroma_dir),
            patch.object(
                setup_script,
                "RUNTIME_DIRECTORIES",
                (
                    self.runtime_questionnaires_dir,
                    self.runtime_evidence_dir,
                    self.outputs_dir,
                    self.chroma_dir,
                ),
            ),
            patch.object(
                setup_script,
                "WORKSPACE_HASH_DIRECTORIES",
                (
                    self.runtime_questionnaires_dir,
                    self.runtime_evidence_dir,
                ),
            ),
            patch.object(setup_script, "SEED_TO_RUNTIME_PATHS", self.runtime_seed_to_runtime_paths),
        )

    def _load_manifest(self) -> dict[str, object]:
        return json.loads(setup_script.manifest_path().read_text(encoding="utf-8"))

    def _run_main(self, *args: str) -> tuple[int, str]:
        stdout = io.StringIO()
        argv = ["generate_demo_data.py", *args]
        with patch.object(sys, "argv", argv), redirect_stdout(stdout):
            exit_code = setup_script.main()
        return exit_code, stdout.getvalue()


if __name__ == "__main__":
    unittest.main()
