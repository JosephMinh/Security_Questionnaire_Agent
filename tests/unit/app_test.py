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
    reviewer_note: str = "",
    citations: tuple[rag.ResolvedEvidenceCitation, ...] = (),
) -> rag.GeneratedAnswerResult:
    """Build one deterministic generated-answer result for UI tests."""
    return rag.GeneratedAnswerResult(
        answer=answer,
        answer_type=answer_type,
        citation_ids=tuple(citation.chunk_id for citation in citations),
        citations=citations,
        confidence_score=confidence_score,
        confidence_band=confidence_band,
        status=status,
        reviewer_note=reviewer_note,
    )


def _citation(
    *,
    chunk_id: str,
    display_label: str,
    snippet_text: str,
    source: str,
    source_path: str,
    doc_type: str,
    section: str | None = None,
    page: int | None = None,
) -> rag.ResolvedEvidenceCitation:
    """Build one resolved citation fixture for the question inspector."""
    return rag.ResolvedEvidenceCitation(
        chunk_id=chunk_id,
        display_label=display_label,
        snippet_text=snippet_text,
        source=source,
        source_path=Path(source_path),
        doc_type=doc_type,
        section=section,
        page=page,
    )


def _published_export_packet(
    *,
    run_id: str,
    output_dir: str = "data/outputs",
    completed_at: str = "2026-04-27T22:30:00Z",
    workspace_hash: str = "workspace-hash",
    index_action: str = rag.INDEX_ACTION_REUSED,
) -> rag.PublishedExportPacket:
    """Build one published export packet fixture for app-level export tests."""
    output_root = Path(output_dir)
    return rag.PublishedExportPacket(
        output_dir=output_root,
        answered_questionnaire_path=output_root / rag.ANSWERED_QUESTIONNAIRE_FILE_NAME,
        review_summary_path=output_root / rag.REVIEW_SUMMARY_FILE_NAME,
        needs_review_csv_path=output_root / rag.NEEDS_REVIEW_FILE_NAME,
        run_id=run_id,
        completed_at=completed_at,
        workspace_hash=workspace_hash,
        index_action=index_action,
    )


class AppRunSectionTest(unittest.TestCase):
    """Verify the run-control UI stays wired to the canonical pipeline contract."""

    def test_header_and_workspace_controls_match_planned_labels(self) -> None:
        """The top-level framing and primary workspace controls should stay camera-ready."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            )
        )

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    at = AppTest.from_function(_run_app_main)
                    at.run()

        self.assertEqual([title.value for title in at.title], [rag.APP_TITLE])
        self.assertIn(rag.APP_SUBTITLE, [caption.value for caption in at.caption])
        self.assertTrue(
            any(rag.DEMO_MODE_LABEL in markdown.value for markdown in at.markdown)
        )
        self.assertEqual([expander.label for expander in at.expander], ["Advanced"])
        self.assertEqual(
            [(button.label, button.disabled) for button in at.button],
            [
                ("Load Demo Workspace", False),
                ("Rebuild Index", False),
                ("Reset Demo", False),
                ("Run Copilot", False),
                ("Publish Export Packet", True),
            ],
        )

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
                with patch.object(app, "_missing_required_environment", return_value=()):
                    at = AppTest.from_function(_run_app_main)
                    at.run()

        self.assertIn("Run Copilot", [button.label for button in at.button])
        self.assertEqual(len(at.metric), 1)
        self.assertEqual(at.metric[0].label, "Total Questions")
        self.assertEqual(str(at.metric[0].value), "3")
        self.assertTrue(
            any(
                "Single curated workspace demo" in markdown.value
                for markdown in at.markdown
            )
        )
        self.assertIn(
            "Completed 0 of 3 questions.",
            [caption.value for caption in at.caption],
        )
        self.assertTrue(
            any(
                "Recovery-only controls." in caption.value
                and "reset the curated demo workspace" in caption.value
                for caption in at.caption
            )
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
                with patch.object(app, "_missing_required_environment", return_value=()):
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
        self.assertEqual(
            {
                metric.label: str(metric.value)
                for metric in at.metric
            },
            {
                "Total Questions": "3",
                "Questions": "3",
                "Ready for Review": "2",
                "Needs Review": "1",
                "Sources Indexed": "5",
            },
        )
        self.assertEqual(len(at.dataframe), 2)
        dataframe = at.dataframe[0].value
        self.assertEqual(
            list(dataframe.columns),
            ["Question ID", "Category", "Answer", "Confidence", "Status"],
        )
        self.assertEqual(list(dataframe["Question ID"]), ["Q01", "Q02", "Q03"])
        self.assertEqual(
            list(dataframe["Status"]),
            [
                rag.STATUS_READY_FOR_REVIEW,
                rag.STATUS_NEEDS_REVIEW,
                rag.STATUS_READY_FOR_REVIEW,
            ],
        )
        review_queue_dataframe = at.dataframe[1].value
        self.assertEqual(
            list(review_queue_dataframe.columns),
            list(rag.REVIEW_QUEUE_COLUMNS),
        )
        self.assertEqual(list(review_queue_dataframe["Question ID"]), ["Q02"])
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

    def test_workspace_section_surfaces_invalid_workspace_guidance_and_recovery_controls(
        self,
    ) -> None:
        """Blocked workspace states should explain the problem and leave recovery controls visible."""
        invalid_snapshot = app.WorkspaceSnapshot(
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

        with patch.object(app, "_workspace_snapshot", return_value=invalid_snapshot):
            with patch.object(app, "_missing_required_environment", return_value=()):
                at = AppTest.from_function(_run_app_main)
                at.run()

        self.assertIn("Workspace validation failed.", [error.value for error in at.error])
        markdown_values = [markdown.value for markdown in at.markdown]
        self.assertTrue(
            any(
                "Run `Load Demo Workspace` to restore the curated assets."
                in value
                for value in markdown_values
            )
        )
        self.assertTrue(
            any(
                "use `Reset Demo` to rebuild the workspace from scratch." in value
                for value in markdown_values
            )
        )
        self.assertIn(
            "Fix the workspace validation issues above before starting the copilot run.",
            [caption.value for caption in at.caption],
        )
        self.assertEqual(
            [(button.label, button.disabled) for button in at.button[:4]],
            [
                ("Load Demo Workspace", False),
                ("Rebuild Index", False),
                ("Reset Demo", False),
                ("Run Copilot", True),
            ],
        )

    def test_run_section_blocks_when_required_environment_is_missing(self) -> None:
        """Missing provider configuration should disable the run path with guidance."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            )
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

        run_button = next(button for button in at.button if button.label == "Run Copilot")
        self.assertTrue(run_button.disabled)
        self.assertIn(
            "Set OPENAI_API_KEY in the shell or repo-local `.env` before running the copilot.",
            [caption.value for caption in at.caption],
        )

    def test_export_section_requires_completed_run_before_publish(self) -> None:
        """The export action should stay disabled until a completed run exists."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            )
        )

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    at = AppTest.from_function(_run_app_main)
                    at.run()

        export_button = next(
            button for button in at.button if button.label == "Publish Export Packet"
        )
        self.assertTrue(export_button.disabled)
        self.assertIn(
            "Finish a copilot run before publishing the export packet.",
            [caption.value for caption in at.caption],
        )

    def test_export_section_publishes_packet_and_shows_output_paths(self) -> None:
        """A completed run should publish the export packet and expose the canonical paths."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            )
        )
        completed_questionnaire = rag.prepare_questionnaire_run(questionnaire)
        completed_questionnaire.rows[0] = rag.update_row_with_answer_result(
            completed_questionnaire.rows[0],
            _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_HIGH,
                status=rag.STATUS_READY_FOR_REVIEW,
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="demo-run-export-001",
        )
        packet = _published_export_packet(run_id="demo-run-export-001")

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    with patch.object(app, "publish_export_packet", return_value=packet) as publish_mock:
                        at = AppTest.from_function(_run_app_main)
                        at.session_state[app.LAST_RUN_ID_KEY] = "demo-run-export-001"
                        at.session_state[app.LAST_RUN_QUESTIONNAIRE_KEY] = completed_questionnaire
                        at.session_state[app.RESULTS_QUESTIONNAIRE_KEY] = completed_questionnaire
                        at.run()
                        next(
                            button
                            for button in at.button
                            if button.label == "Publish Export Packet"
                        ).click()
                        at.run()

        publish_mock.assert_called_once_with(
            completed_questionnaire,
            workspace_hash="workspace-hash",
        )
        self.assertEqual(at.session_state[app.EXPORT_PACKET_KEY], packet)
        self.assertTrue(any("Export packet published." in value for value in [success.value for success in at.success]))
        markdown_values = [markdown.value for markdown in at.markdown]
        self.assertTrue(any(str(packet.output_dir) in value for value in markdown_values))
        self.assertTrue(
            any(str(packet.answered_questionnaire_path) in value for value in markdown_values)
        )
        self.assertTrue(any(str(packet.review_summary_path) in value for value in markdown_values))
        self.assertTrue(any(str(packet.needs_review_csv_path) in value for value in markdown_values))

    def test_export_failure_clears_stale_packet_surface(self) -> None:
        """A failed export attempt should clear stale packet state instead of implying success."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            )
        )
        completed_questionnaire = rag.prepare_questionnaire_run(questionnaire)
        completed_questionnaire.rows[0] = rag.update_row_with_answer_result(
            completed_questionnaire.rows[0],
            _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_HIGH,
                status=rag.STATUS_READY_FOR_REVIEW,
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="demo-run-export-002",
        )
        stale_packet = _published_export_packet(run_id="stale-export-run")

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    with patch.object(
                        app,
                        "publish_export_packet",
                        side_effect=ValueError("run contains mixed run ids"),
                    ):
                        at = AppTest.from_function(_run_app_main)
                        at.session_state[app.LAST_RUN_ID_KEY] = "demo-run-export-002"
                        at.session_state[app.LAST_RUN_QUESTIONNAIRE_KEY] = completed_questionnaire
                        at.session_state[app.RESULTS_QUESTIONNAIRE_KEY] = completed_questionnaire
                        at.session_state[app.EXPORT_PACKET_KEY] = stale_packet
                        at.run()
                        next(
                            button
                            for button in at.button
                            if button.label == "Publish Export Packet"
                        ).click()
                        at.run()

        self.assertNotIn(app.EXPORT_PACKET_KEY, at.session_state)
        warning_values = [warning.value for warning in at.warning]
        self.assertTrue(any("Export packet is blocked." in value for value in warning_values))
        self.assertTrue(any("run contains mixed run ids" in value for value in warning_values))
        markdown_values = [markdown.value for markdown in at.markdown]
        self.assertFalse(any(str(stale_packet.output_dir) in value for value in markdown_values))

    def test_load_demo_workspace_clears_stale_results_surface(self) -> None:
        """Workspace reload should clear prior run results instead of leaving stale tables."""
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
        )
        stale_questionnaire = rag.prepare_questionnaire_run(questionnaire)
        stale_questionnaire.rows[0] = rag.update_row_with_answer_result(
            stale_questionnaire.rows[0],
            _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                status=rag.STATUS_READY_FOR_REVIEW,
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="stale-run",
        )

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    with patch.object(app, "prepare_demo_workspace", return_value=()):
                        with patch.object(
                            app,
                            "ensure_curated_evidence_index",
                            return_value=_ready_index_status(),
                        ):
                            at = AppTest.from_function(_run_app_main)
                            at.session_state[app.RESULTS_QUESTIONNAIRE_KEY] = stale_questionnaire
                            at.session_state[app.LAST_RUN_ID_KEY] = "stale-run"
                            at.session_state[app.LAST_RUN_QUESTIONNAIRE_KEY] = stale_questionnaire
                            at.run()
                            self.assertEqual(len(at.dataframe), 1)
                            next(
                                button for button in at.button if button.label == "Load Demo Workspace"
                            ).click()
                            at.run()

        self.assertEqual(len(at.dataframe), 0)
        self.assertIn(
            "Results will populate here as questions finish processing.",
            [info.value for info in at.info],
        )
        self.assertNotIn(app.RESULTS_QUESTIONNAIRE_KEY, at.session_state)
        self.assertNotIn(app.LAST_RUN_ID_KEY, at.session_state)

    def test_busy_run_state_disables_conflicting_controls_and_explains_waiting(self) -> None:
        """While a run is busy, every conflicting visible control should stay disabled."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            )
        )

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    at = AppTest.from_function(_run_app_main)
                    at.session_state[app.RUN_BUSY_KEY] = True
                    at.run()

        self.assertEqual(
            [(button.label, button.disabled) for button in at.button],
            [
                ("Load Demo Workspace", True),
                ("Rebuild Index", True),
                ("Reset Demo", True),
                ("Run Copilot", True),
                ("Publish Export Packet", True),
            ],
        )
        caption_values = [caption.value for caption in at.caption]
        self.assertIn(
            "Another app action is finishing. Wait for it to complete before starting a new one.",
            caption_values,
        )
        self.assertIn(
            "Another app action is finishing. Wait for it to complete before exporting.",
            caption_values,
        )

    def test_results_surface_defaults_to_lowest_confidence_needs_review_and_sorts_queue(
        self,
    ) -> None:
        """Finished runs should focus the weakest Needs Review row and sort the queue by score."""
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
            _runtime_row(
                question_id="Q04",
                category="Monitoring",
                question="Do you monitor backup failures?",
            ),
        )
        results_questionnaire = rag.prepare_questionnaire_run(questionnaire)
        row_updates = (
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
                confidence_score=0.70,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                status=rag.STATUS_NEEDS_REVIEW,
                reviewer_note="Review the backup scope exceptions.",
            ),
            _answer_result(
                answer="Not stated with enough support.",
                answer_type=rag.ANSWER_TYPE_UNSUPPORTED,
                confidence_score=rag.PARTIAL_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_LOW,
                status=rag.STATUS_NEEDS_REVIEW,
                reviewer_note="Manual confirmation required.",
            ),
            _answer_result(
                answer="Yes. Backup failures are monitored by the operations team.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=0.70,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                status=rag.STATUS_READY_FOR_REVIEW,
            ),
        )
        for row_index, answer_result in enumerate(row_updates):
            results_questionnaire.rows[row_index] = rag.update_row_with_answer_result(
                results_questionnaire.rows[row_index],
                answer_result,
                index_action=rag.INDEX_ACTION_REUSED,
                run_id="demo-run-003",
            )

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    at = AppTest.from_function(_run_app_main)
                    at.session_state[app.RESULTS_QUESTIONNAIRE_KEY] = results_questionnaire
                    at.run()

        inspector_selectbox = at.selectbox[0]
        self.assertEqual(inspector_selectbox.value, "Q03")
        review_queue_dataframe = at.dataframe[1].value
        self.assertEqual(list(review_queue_dataframe["Question ID"]), ["Q03", "Q02", "Q04"])

    def test_results_surface_defaults_to_first_question_when_no_needs_review_exists(
        self,
    ) -> None:
        """Finished runs without review rows should default back to the first question."""
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
        )
        results_questionnaire = rag.prepare_questionnaire_run(questionnaire)
        results_questionnaire.rows[0] = rag.update_row_with_answer_result(
            results_questionnaire.rows[0],
            _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_HIGH,
                status=rag.STATUS_READY_FOR_REVIEW,
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="demo-run-004",
        )
        results_questionnaire.rows[1] = rag.update_row_with_answer_result(
            results_questionnaire.rows[1],
            _answer_result(
                answer="Yes. Backup jobs are encrypted.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=0.74,
                confidence_band=rag.CONFIDENCE_BAND_LOW,
                status=rag.STATUS_READY_FOR_REVIEW,
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="demo-run-004",
        )

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    at = AppTest.from_function(_run_app_main)
                    at.session_state[app.RESULTS_QUESTIONNAIRE_KEY] = results_questionnaire
                    at.run()

        inspector_selectbox = at.selectbox[0]
        self.assertEqual(inspector_selectbox.value, "Q01")
        review_queue_dataframe = at.dataframe[1].value
        self.assertEqual(list(review_queue_dataframe["Question ID"]), ["Q02"])

    def test_results_surface_question_inspector_shows_provenance_and_switches_rows(
        self,
    ) -> None:
        """The question inspector should expose processed rows, exact snippets, and row switching."""
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
        results_questionnaire = rag.prepare_questionnaire_run(questionnaire)
        results_questionnaire.rows[0] = rag.update_row_with_answer_result(
            results_questionnaire.rows[0],
            _answer_result(
                answer="Yes. Customer data is encrypted at rest using AES-256 controls.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                confidence_score=rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_HIGH,
                status=rag.STATUS_READY_FOR_REVIEW,
                reviewer_note="Validated against the policy control language.",
                citations=(
                    _citation(
                        chunk_id="enc-001",
                        display_label="Encryption Policy - Data at Rest",
                        snippet_text="Customer data at rest is encrypted using AES-256.",
                        source="Encryption_Policy.md",
                        source_path="data/evidence/Encryption_Policy.md",
                        doc_type=rag.DOCUMENT_TYPE_MARKDOWN,
                        section="Data at Rest",
                    ),
                ),
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="demo-run-002",
        )
        results_questionnaire.rows[1] = rag.update_row_with_answer_result(
            results_questionnaire.rows[1],
            _answer_result(
                answer="Partially. Backup encryption covers managed jobs but not every legacy path.",
                answer_type=rag.ANSWER_TYPE_PARTIAL,
                confidence_score=rag.PARTIAL_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_LOW,
                status=rag.STATUS_NEEDS_REVIEW,
                reviewer_note="Confirm the remaining legacy backup scope manually.",
                citations=(
                    _citation(
                        chunk_id="soc2-004",
                        display_label="AcmeCloud SOC 2 Summary - Backup Controls",
                        snippet_text="Backup jobs are encrypted in transit and at rest.",
                        source="AcmeCloud_SOC2_Summary.pdf",
                        source_path="data/evidence/AcmeCloud_SOC2_Summary.pdf",
                        doc_type=rag.DOCUMENT_TYPE_PDF,
                        page=4,
                    ),
                ),
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="demo-run-002",
        )

        with patch.object(app, "_workspace_snapshot", return_value=_ready_snapshot()):
            with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
                with patch.object(app, "_missing_required_environment", return_value=()):
                    at = AppTest.from_function(_run_app_main)
                    at.session_state[app.RESULTS_QUESTIONNAIRE_KEY] = results_questionnaire
                    at.run()

        self.assertEqual(len(at.selectbox), 1)
        inspector_selectbox = at.selectbox[0]
        self.assertEqual(inspector_selectbox.label, "Question ID")
        self.assertEqual(list(inspector_selectbox.options), ["Q01", "Q02"])
        self.assertEqual(inspector_selectbox.value, "Q01")

        markdown_values = [markdown.value for markdown in at.markdown]
        caption_values = [caption.value for caption in at.caption]
        self.assertTrue(any("Question Inspector" in value for value in markdown_values))
        self.assertTrue(
            any("Is customer data encrypted at rest?" in value for value in markdown_values)
        )
        self.assertTrue(
            any(
                "Yes. Customer data is encrypted at rest using AES-256 controls." in value
                for value in markdown_values
            )
        )
        self.assertTrue(
            any(
                "Validated against the policy control language." in value
                for value in markdown_values
            )
        )
        self.assertTrue(
            any("Ready for Review" in value for value in markdown_values)
        )
        self.assertTrue(
            any("Encryption Policy - Data at Rest" in value for value in markdown_values)
        )
        self.assertTrue(
            any(
                "Customer data at rest is encrypted using AES-256." in value
                for value in markdown_values
            )
        )
        self.assertIn(
            "Source file: Encryption_Policy.md | Section: Data at Rest",
            caption_values,
        )

        inspector_selectbox.set_value("Q02")
        at.run()

        switched_markdown_values = [markdown.value for markdown in at.markdown]
        switched_caption_values = [caption.value for caption in at.caption]
        self.assertTrue(any("Are backups encrypted?" in value for value in switched_markdown_values))
        self.assertTrue(
            any(
                "Partially. Backup encryption covers managed jobs but not every legacy path."
                in value
                for value in switched_markdown_values
            )
        )
        self.assertTrue(any("Needs Review" in value for value in switched_markdown_values))
        self.assertTrue(
            any(
                "Confirm the remaining legacy backup scope manually." in value
                for value in switched_markdown_values
            )
        )
        self.assertTrue(
            any(
                "Backup jobs are encrypted in transit and at rest." in value
                for value in switched_markdown_values
            )
        )
        self.assertIn(
            "Source file: AcmeCloud_SOC2_Summary.pdf | Page: 4",
            switched_caption_values,
        )


if __name__ == "__main__":
    unittest.main()
