"""Unit coverage for the Streamlit app run-control orchestration."""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import app
import rag


def _run_app_main() -> None:
    """Run the Streamlit entrypoint through AppTest's function wrapper."""
    import app as app_module

    app_module.main()


def _runtime_row(*, question_id: str, category: str, question: str) -> dict[str, object]:
    """Build one canonical runtime row for app-level tests."""
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


def _ready_snapshot() -> app.WorkspaceSnapshot:
    """Return one clean workspace snapshot for run-control tests."""
    return app.WorkspaceSnapshot(
        questionnaire_exists=True,
        manifest_exists=True,
        evidence_present_count=5,
        evidence_total_count=5,
        validation_ok=True,
        validation_lines=(),
        workspace_hash="workspace-hash",
        index_ready=True,
        index_action=rag.INDEX_ACTION_REUSED,
        index_reason="reused",
        actual_chunk_count=9,
        stored_chunk_count=9,
        stored_workspace_hash="workspace-hash",
    )


def _ready_index_status() -> rag.ChromaIndexStatus:
    """Return one reusable index status fixture."""
    return rag.ChromaIndexStatus(
        collection_name=rag.COLLECTION_NAME,
        persist_directory=rag.CHROMA_DIR,
        workspace_hash="workspace-hash",
        stored_workspace_hash="workspace-hash",
        stored_chunk_count=9,
        actual_chunk_count=9,
        index_action=rag.INDEX_ACTION_REUSED,
        ready=True,
        reason="reused",
        collection_handle=None,
    )


def _answer_result(
    *,
    answer: str,
    answer_type: str,
    confidence_score: float,
    confidence_band: str,
    status: str,
) -> rag.GeneratedAnswerResult:
    """Build one deterministic generated-answer result for UI tests."""
    return rag.GeneratedAnswerResult(
        answer=answer,
        answer_type=answer_type,
        citation_ids=(),
        citations=(),
        confidence_score=confidence_score,
        confidence_band=confidence_band,
        status=status,
        reviewer_note="",
    )


class AppRunSectionTest(unittest.TestCase):
    """Verify the run-control UI stays wired to the canonical pipeline contract."""

    def test_run_section_shows_total_count_and_idle_status(self) -> None:
        """The run section should expose count, trigger, and resting progress copy."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            ),
            _runtime_row(
                question_id="Q02",
                category="Backups",
                question="Are backups encrypted?",
            ),
            _runtime_row(
                question_id="Q03",
                category="Access",
                question="Do you review privileged access?",
            ),
        )

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                at = AppTest.from_function(_run_app_main)
                at.run()

        self.assertIn("Run Copilot", [button.label for button in at.button])
        self.assertEqual(len(at.metric), 1)
        self.assertEqual(at.metric[0].label, "Total Questions")
        self.assertEqual(str(at.metric[0].value), "3")
        self.assertIn(
            "Completed 0 of 3 questions.",
            [caption.value for caption in at.caption],
        )
        self.assertIn(
            "Current question status will appear here once the run starts.",
            [info.value for info in at.info],
        )

    def test_run_copilot_click_updates_progress_and_persists_results(self) -> None:
        """Clicking Run Copilot should process rows in order and retain the finished run."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            ),
            _runtime_row(
                question_id="Q02",
                category="Backups",
                question="Are backups encrypted?",
            ),
            _runtime_row(
                question_id="Q03",
                category="Access",
                question="Do you review access logs?",
            ),
        )
        callback_events: list[tuple[int, str, str]] = []
        answers = (
            _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_HIGH,
                status=rag.STATUS_READY_FOR_REVIEW,
            ),
            _answer_result(
                answer="Partially. Backup coverage is narrower than the full estate.",
                answer_type=rag.ANSWER_TYPE_PARTIAL,
                confidence_score=rag.PARTIAL_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_LOW,
                status=rag.STATUS_NEEDS_REVIEW,
            ),
            _answer_result(
                answer="Yes. Access logs are reviewed on a scheduled basis.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                status=rag.STATUS_READY_FOR_REVIEW,
            ),
        )

        def fake_run_pipeline(
            questionnaire: rag.RuntimeQuestionnaire,
            *,
            index_status: rag.ChromaIndexStatus,
            run_id: str,
            model: str = rag.DEFAULT_OPENAI_ANSWER_MODEL,
            openai_client: object | None = None,
            on_row_completed=None,
        ) -> rag.RuntimeQuestionnaire:
            del model, openai_client
            run_questionnaire = rag.prepare_questionnaire_run(questionnaire)
            for row_index, answer_result in enumerate(answers):
                updated_row = rag.update_row_with_answer_result(
                    run_questionnaire.rows[row_index],
                    answer_result,
                    index_action=index_status.index_action,
                    run_id=run_id,
                )
                run_questionnaire.rows[row_index] = updated_row
                callback_events.append(
                    (
                        row_index,
                        str(updated_row["question_id"]),
                        str(updated_row["Status"]),
                    )
                )
                if on_row_completed is not None:
                    on_row_completed(run_questionnaire, row_index)
            return run_questionnaire

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(
                    app,
                    "ensure_curated_evidence_index",
                    return_value=_ready_index_status(),
                ):
                    with patch.object(app, "_new_run_id", return_value="demo-run-001"):
                        with patch.object(
                            app,
                            "run_questionnaire_answer_pipeline",
                            side_effect=fake_run_pipeline,
                        ):
                            at = AppTest.from_function(_run_app_main)
                            at.run()
                            next(
                                button for button in at.button if button.label == "Run Copilot"
                            ).click()
                            at.run()

        self.assertEqual(
            callback_events,
            [
                (0, "Q01", rag.STATUS_READY_FOR_REVIEW),
                (1, "Q02", rag.STATUS_NEEDS_REVIEW),
                (2, "Q03", rag.STATUS_READY_FOR_REVIEW),
            ],
        )
        self.assertEqual(at.session_state[app.LAST_RUN_ID_KEY], "demo-run-001")
        completed_questionnaire = at.session_state[app.LAST_RUN_QUESTIONNAIRE_KEY]
        self.assertIsInstance(completed_questionnaire, rag.RuntimeQuestionnaire)
        self.assertEqual(
            [str(row["Status"]) for row in completed_questionnaire.rows],
            [
                rag.STATUS_READY_FOR_REVIEW,
                rag.STATUS_NEEDS_REVIEW,
                rag.STATUS_READY_FOR_REVIEW,
            ],
        )
        self.assertIn(
            "Completed 3 of 3 questions.",
            [caption.value for caption in at.caption],
        )
        self.assertTrue(
            any(
                "Run finished after Q03 - Do you review access logs? (Ready for Review)."
                in success.value
                for success in at.success
            )
        )
        self.assertTrue(
            any("Copilot run finished." in success.value for success in at.success)
        )


if __name__ == "__main__":
    unittest.main()
