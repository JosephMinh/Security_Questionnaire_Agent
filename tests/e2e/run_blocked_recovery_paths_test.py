#!/usr/bin/env python3
"""Deterministic e2e checks for blocked-state guidance and recovery flows."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Final
from unittest.mock import patch

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from streamlit.testing.v1 import AppTest

import app
import rag

logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(
    logging.ERROR
)


SCRIPT_NAME: Final[str] = "run_blocked_recovery_paths_test"
LOG_FILE_NAME: Final[str] = f"{SCRIPT_NAME}.jsonl"
SUITE_RUN_ID: Final[str] = "blocked-recovery-e2e"


def _run_app_main() -> None:
    """Run the Streamlit entrypoint through AppTest's function wrapper."""
    import app as app_module

    app_module.main()


def _runtime_row(*, question_id: str, category: str, question: str) -> dict[str, object]:
    """Build one canonical runtime row for deterministic app scenarios."""
    return {
        "Question ID": question_id,
        "Category": category,
        "Question": question,
        "Answer": "",
        "Evidence": "",
        "Confidence": "",
        "Status": "",
        "Reviewer Notes": "",
        "question_id": question_id,
        "category": category,
        "question": question,
        **rag.make_result_row_defaults(),
    }


def _runtime_questionnaire(*rows: dict[str, object]) -> rag.RuntimeQuestionnaire:
    """Build one lightweight runtime questionnaire fixture."""
    return rag.RuntimeQuestionnaire(
        workbook_path=Path("data/questionnaires/Demo_Security_Questionnaire.xlsx"),
        visible_columns=rag.VISIBLE_EXPORT_COLUMNS,
        rows=[dict(row) for row in rows],
    )


def _ready_snapshot(
    *,
    workspace_hash: str = "workspace-hash-ready",
    index_action: str = rag.INDEX_ACTION_REUSED,
    index_reason: str = "reused",
) -> app.WorkspaceSnapshot:
    """Return one clean workspace snapshot for healthy-state scenarios."""
    return app.WorkspaceSnapshot(
        questionnaire_exists=True,
        manifest_exists=True,
        evidence_present_count=5,
        evidence_total_count=5,
        validation_ok=True,
        validation_lines=(),
        workspace_hash=workspace_hash,
        index_ready=True,
        index_action=index_action,
        index_reason=index_reason,
        actual_chunk_count=9,
        stored_chunk_count=9,
        stored_workspace_hash=workspace_hash,
    )


def _invalid_workspace_snapshot() -> app.WorkspaceSnapshot:
    """Return one blocked workspace snapshot with operator-facing recovery guidance."""
    return app.WorkspaceSnapshot(
        questionnaire_exists=False,
        manifest_exists=False,
        evidence_present_count=0,
        evidence_total_count=5,
        validation_ok=False,
        validation_lines=(
            "Runtime workspace manifest is missing. Run `Load Demo Workspace` to restore the curated assets.",
            "If the local cache still looks stale after reload, use `Reset Demo` to rebuild the workspace from scratch.",
        ),
        workspace_hash=None,
        index_ready=False,
        index_action=rag.INDEX_ACTION_BLOCKED,
        index_reason="manifest_unavailable",
        actual_chunk_count=0,
        stored_chunk_count=None,
        stored_workspace_hash=None,
    )


def _recovered_index_status() -> rag.ChromaIndexStatus:
    """Return one ready status that proves integrity checks forced a safe rebuild."""
    return rag.ChromaIndexStatus(
        collection_name=rag.COLLECTION_NAME,
        persist_directory=rag.CHROMA_DIR,
        workspace_hash="workspace-hash-recovered",
        stored_workspace_hash="workspace-hash-recovered",
        stored_chunk_count=9,
        actual_chunk_count=9,
        index_action=rag.INDEX_ACTION_REBUILT_INTEGRITY,
        ready=True,
        reason="collection_payload_mismatch",
        collection_handle=None,
    )


def _button_by_label(at: AppTest, label: str):
    return next(button for button in at.button if button.label == label)


def _widget_values(widgets: list[object]) -> list[str]:
    return [str(widget.value) for widget in widgets]


def _markdown_values(at: AppTest) -> list[str]:
    return _widget_values(at.markdown)


def _caption_values(at: AppTest) -> list[str]:
    return _widget_values(at.caption)


def _success_values(at: AppTest) -> list[str]:
    return _widget_values(at.success)


def _error_values(at: AppTest) -> list[str]:
    return _widget_values(at.error)


def _warning_values(at: AppTest) -> list[str]:
    return _widget_values(at.warning)


def _surface_values(at: AppTest) -> list[str]:
    """Return the combined visible text surface for broad message assertions."""
    return (
        _error_values(at)
        + _warning_values(at)
        + _success_values(at)
        + _caption_values(at)
        + _markdown_values(at)
        + _widget_values(getattr(at, "info", []))
    )


def _contains_text(values: list[str], expected_substring: str) -> bool:
    return any(expected_substring in value for value in values)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class JsonlLogSink:
    """Collect and persist machine-readable verification events."""

    def __init__(self, *, log_path: Path, verbose: bool) -> None:
        self._log_path = log_path
        self._verbose = verbose
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.write_text("", encoding="utf-8")
        self._records: list[dict[str, object]] = []

    def emit(
        self,
        *,
        event: str,
        status: str,
        message: str,
        level: str = "INFO",
        run_id: str = SUITE_RUN_ID,
        index_action: str | None = None,
        artifact_path: str | Path | None = None,
        reason: str | None = None,
    ) -> None:
        record = rag.build_structured_log_record(
            component=rag.LOG_COMPONENT_VERIFICATION,
            event=event,
            run_id=run_id,
            status=status,
            message=message,
            level=level,
            index_action=index_action,
            artifact_path=artifact_path,
            reason=reason,
        )
        self._records.append(record)
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")
        if self._verbose:
            print(json.dumps(record, sort_keys=True))

    def flush(self) -> Path:
        return self._log_path


def _scenario_invalid_workspace_then_recovery(log_sink: JsonlLogSink) -> None:
    """Verify blocked invalid-workspace guidance and recovery through safe rebuild."""
    scenario_run_id = "invalid-workspace-recovery"
    questionnaire = _runtime_questionnaire(
        _runtime_row(
            question_id="Q01",
            category="Encryption",
            question="Is customer data encrypted at rest?",
        )
    )
    copied_assets = tuple(rag.SEED_TO_RUNTIME_PATHS)

    log_sink.emit(
        event="scenario_started",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_STARTED,
        message="Starting the invalid-workspace recovery scenario.",
        reason="invalid_workspace",
    )

    with patch.object(
        app,
        "_workspace_snapshot",
        side_effect=(_invalid_workspace_snapshot(), _ready_snapshot(workspace_hash="workspace-hash-recovered")),
    ):
        with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
            with patch.object(app, "_missing_required_environment", return_value=()):
                with patch.object(app, "prepare_demo_workspace", return_value=copied_assets):
                    with patch.object(
                        app,
                        "ensure_curated_evidence_index",
                        return_value=_recovered_index_status(),
                    ):
                        at = AppTest.from_function(_run_app_main)
                        at.run()

                        run_button = _button_by_label(at, "Run Copilot")
                        _require(run_button.disabled, "Run button should be disabled while the workspace is invalid.")
                        _require(
                            _contains_text(_error_values(at), "Workspace validation failed."),
                            "Invalid workspace scenario should surface a validation failure error.",
                        )
                        _require(
                            _contains_text(
                                _surface_values(at),
                                "Run `Load Demo Workspace` to restore the curated assets.",
                            ),
                            "Invalid workspace guidance should tell the operator to load the demo workspace.",
                        )
                        _require(
                            _contains_text(
                                _caption_values(at),
                                "Fix the workspace validation issues above before starting the copilot run.",
                            ),
                            "Run section should explain that validation must be fixed before running.",
                        )
                        log_sink.emit(
                            event="blocked_state_observed",
                            run_id=scenario_run_id,
                            status=rag.LOG_STATUS_BLOCKED,
                            level="WARNING",
                            message="Observed invalid-workspace guidance before any recovery action.",
                            reason="invalid_workspace",
                        )

                        _button_by_label(at, "Load Demo Workspace").click()
                        at.run()

    recovered_run_button = _button_by_label(at, "Run Copilot")
    _require(
        not recovered_run_button.disabled,
        "Run button should be enabled after loading the recovered workspace.",
    )
    _require(
        _contains_text(_success_values(at), "Demo workspace is ready."),
        "Recovery path should surface a successful workspace action.",
    )
    _require(
        _contains_text(
            _success_values(at),
            "Index action: Rebuilt the index after integrity checks found an unsafe cache.",
        ),
        "Recovery path should explain that integrity checks forced a safe rebuild.",
    )
    _require(
        _contains_text(
            _success_values(at),
            "Index detail: The cached collection payload no longer matches the curated evidence set.",
        ),
        "Recovery path should explain why the integrity rebuild happened.",
    )
    log_sink.emit(
        event="recovery_action_applied",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_COMPLETED,
        message="Operator reloaded the demo workspace and the UI reported an integrity-triggered rebuild.",
        index_action=rag.INDEX_ACTION_REBUILT_INTEGRITY,
        reason="collection_payload_mismatch",
    )
    log_sink.emit(
        event="scenario_completed",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_COMPLETED,
        message="Invalid-workspace recovery scenario reached a healthy runnable state.",
        index_action=rag.INDEX_ACTION_REBUILT_INTEGRITY,
    )


def _scenario_missing_openai_key(log_sink: JsonlLogSink) -> None:
    """Verify provider-configuration guidance blocks the run button clearly."""
    scenario_run_id = "missing-openai-api-key"
    questionnaire = _runtime_questionnaire(
        _runtime_row(
            question_id="Q01",
            category="Encryption",
            question="Is customer data encrypted at rest?",
        )
    )
    log_sink.emit(
        event="scenario_started",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_STARTED,
        message="Starting the missing-provider-configuration scenario.",
        reason="missing_openai_api_key",
    )

    with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
        with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
            with patch.object(
                app,
                "_missing_required_environment",
                return_value=("OPENAI_API_KEY",),
            ):
                at = AppTest.from_function(_run_app_main)
                at.run()

    run_button = _button_by_label(at, "Run Copilot")
    _require(
        run_button.disabled,
        "Run button should be disabled when OPENAI_API_KEY is unavailable.",
    )
    _require(
        _contains_text(
            _caption_values(at),
            "Set OPENAI_API_KEY in the shell or repo-local `.env` before running the copilot.",
        ),
        "Missing-environment scenario should tell the operator exactly how to recover.",
    )
    log_sink.emit(
        event="blocked_state_observed",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_BLOCKED,
        level="WARNING",
        message="Observed explicit OPENAI_API_KEY guidance before the run could start.",
        reason="missing_openai_api_key",
    )
    log_sink.emit(
        event="scenario_completed",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_COMPLETED,
        message="Missing-provider-configuration scenario surfaced the expected recovery guidance.",
        reason="missing_openai_api_key",
    )


def _scenario_busy_action_block(log_sink: JsonlLogSink) -> None:
    """Verify conflicting actions stay blocked while another app action is busy."""
    scenario_run_id = "busy-action-block"
    questionnaire = _runtime_questionnaire(
        _runtime_row(
            question_id="Q01",
            category="Encryption",
            question="Is customer data encrypted at rest?",
        )
    )
    log_sink.emit(
        event="scenario_started",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_STARTED,
        message="Starting the busy-action blocking scenario.",
        reason="actions_locked",
    )

    with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
        with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
            with patch.object(app, "_missing_required_environment", return_value=()):
                at = AppTest.from_function(_run_app_main)
                at.session_state[app.RUN_BUSY_KEY] = True
                at.run()

    _require(
        _button_by_label(at, "Run Copilot").disabled,
        "Run button should be disabled while another app action is busy.",
    )
    _require(
        _button_by_label(at, "Load Demo Workspace").disabled,
        "Workspace actions should be disabled while another app action is busy.",
    )
    _require(
        _contains_text(
            _caption_values(at),
            "Another app action is finishing. Wait for it to complete before starting a new one.",
        ),
        "Busy-state scenario should explain that the operator must wait before retrying.",
    )
    log_sink.emit(
        event="blocked_state_observed",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_BLOCKED,
        level="WARNING",
        message="Observed busy-state action locking in the run section.",
        reason="actions_locked",
    )
    log_sink.emit(
        event="scenario_completed",
        run_id=scenario_run_id,
        status=rag.LOG_STATUS_COMPLETED,
        message="Busy-state scenario surfaced the expected wait-for-completion guidance.",
        reason="actions_locked",
    )


def run_suite(*, log_dir: Path, verbose: bool) -> Path:
    """Execute the deterministic blocked-state e2e suite and write JSONL logs."""
    log_sink = JsonlLogSink(log_path=log_dir / LOG_FILE_NAME, verbose=verbose)
    log_sink.emit(
        event="suite_started",
        status=rag.LOG_STATUS_STARTED,
        message="Starting the blocked-state and recovery e2e suite.",
        artifact_path=log_dir / LOG_FILE_NAME,
    )
    _scenario_invalid_workspace_then_recovery(log_sink)
    _scenario_missing_openai_key(log_sink)
    _scenario_busy_action_block(log_sink)
    log_sink.emit(
        event="suite_completed",
        status=rag.LOG_STATUS_COMPLETED,
        message="Completed the blocked-state and recovery e2e suite successfully.",
        artifact_path=log_dir / LOG_FILE_NAME,
    )
    return log_sink.flush()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=rag.E2E_TEST_LOGS_DIR,
        help="Directory for the JSONL verification log.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each structured verification record to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        log_path = run_suite(log_dir=args.log_dir, verbose=args.verbose)
    except Exception as exc:
        print(f"{SCRIPT_NAME}: FAIL: {exc}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"{SCRIPT_NAME}: PASS -> {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
