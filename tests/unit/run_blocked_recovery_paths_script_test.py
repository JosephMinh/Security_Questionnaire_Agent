"""Focused unit coverage for the blocked-recovery e2e script helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import rag


def _load_blocked_recovery_module():
    """Import the blocked-recovery e2e script by path for helper-level testing."""

    module_path = (
        Path(__file__).resolve().parents[1] / "e2e" / "run_blocked_recovery_paths_test.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_blocked_recovery_paths_test_script",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise AssertionError(
            f"Could not load blocked-recovery script module from {module_path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunBlockedRecoveryPathsScriptTest(unittest.TestCase):
    """Verify the blocked-recovery verifier preserves useful failure breadcrumbs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _load_blocked_recovery_module()

    def test_jsonl_log_sink_persists_records_before_flush(self) -> None:
        """Verification logs should survive a mid-run failure before flush is reached."""

        with TemporaryDirectory() as tmp_dir_name:
            log_path = Path(tmp_dir_name) / "run_blocked_recovery_paths_test.jsonl"
            log_sink = self.script.JsonlLogSink(log_path=log_path, verbose=False)
            log_sink.emit(
                event="suite_started",
                status=rag.LOG_STATUS_STARTED,
                message="Starting the blocked-state and recovery e2e suite.",
                reason="preflight",
            )

            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event"], "suite_started")
        self.assertEqual(records[0]["status"], rag.LOG_STATUS_STARTED)
        self.assertEqual(records[0]["reason"], "preflight")


if __name__ == "__main__":
    unittest.main()
