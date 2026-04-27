"""Unit coverage for row assembly and orchestration in the answer pipeline."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rag


def _runtime_row(
    *,
    question_id: str,
    category: str,
    question: str,
    answer: str = "",
    evidence: str = "",
    confidence: str = "",
    status: str = "",
    reviewer_notes: str = "",
) -> dict[str, object]:
    """Build one canonical runtime row for orchestration tests."""
    row = {
        "Question ID": question_id,
        "Category": category,
        "Question": question,
        "Answer": answer,
        "Evidence": evidence,
        "Confidence": confidence,
        "Status": status,
        "Reviewer Notes": reviewer_notes,
        "question_id": question_id,
        "category": category,
        "question": question,
        **rag.make_result_row_defaults(),
    }
    row["answer"] = answer
    row["confidence_band"] = confidence
    row["status"] = status
    row["reviewer_note"] = reviewer_notes
    row["evidence_labels"] = (
        evidence.split("; ") if evidence else []
    )
    return row


def _runtime_questionnaire(*rows: dict[str, object]) -> rag.RuntimeQuestionnaire:
    """Build one lightweight questionnaire fixture in workbook order."""
    return rag.RuntimeQuestionnaire(
        workbook_path=Path("data/questionnaires/Demo_Security_Questionnaire.xlsx"),
        visible_columns=rag.VISIBLE_EXPORT_COLUMNS,
        rows=[dict(row) for row in rows],
    )


def _citation(
    *,
    chunk_id: str,
    label: str,
    snippet: str,
    source: str,
    section: str | None = None,
    page: int | None = None,
) -> rag.ResolvedEvidenceCitation:
    """Build one reviewer-facing citation fixture."""
    return rag.ResolvedEvidenceCitation(
        chunk_id=chunk_id,
        display_label=label,
        snippet_text=snippet,
        source=source,
        source_path=rag.RUNTIME_EVIDENCE_DIR / source,
        doc_type=(
            rag.DOCUMENT_TYPE_PDF if source.endswith(".pdf") else rag.DOCUMENT_TYPE_POLICY
        ),
        section=section,
        page=page,
    )


def _answer_result(
    *,
    answer: str,
    answer_type: str,
    citation_ids: tuple[str, ...],
    citations: tuple[rag.ResolvedEvidenceCitation, ...],
    confidence_score: float,
    confidence_band: str,
    status: str,
    reviewer_note: str,
    failed_closed: bool = False,
    failure_reason: str | None = None,
    retry_count: int = 0,
) -> rag.GeneratedAnswerResult:
    """Build one completed answer result fixture."""
    return rag.GeneratedAnswerResult(
        answer=answer,
        answer_type=answer_type,
        citation_ids=citation_ids,
        citations=citations,
        confidence_score=confidence_score,
        confidence_band=confidence_band,
        status=status,
        reviewer_note=reviewer_note,
        failed_closed=failed_closed,
        failure_reason=failure_reason,
        retry_count=retry_count,
    )


def _ready_index_status(index_action: str = rag.INDEX_ACTION_REUSED) -> rag.ChromaIndexStatus:
    """Build one minimal ready index status for orchestration-only tests."""
    return rag.ChromaIndexStatus(
        collection_name=rag.COLLECTION_NAME,
        persist_directory=rag.CHROMA_DIR,
        workspace_hash="workspace-hash",
        stored_workspace_hash="workspace-hash",
        stored_chunk_count=9,
        actual_chunk_count=9,
        index_action=index_action,
        ready=True,
        reason=index_action,
        collection_handle=None,
    )


class RagPipelineTest(unittest.TestCase):
    """Verify row reset, row assembly, and orchestration behavior."""

    def test_prepare_questionnaire_run_resets_visible_outputs_and_internal_defaults(self):
        """A new run should clear prior outputs without mutating the source questionnaire."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
                answer="Old answer",
                evidence="Encryption Policy — Data at Rest",
                confidence="High",
                status="Ready for Review",
                reviewer_notes="Old note",
            )
        )
        questionnaire.rows[0]["citation_ids"] = ["old_chunk"]
        questionnaire.rows[0]["run_id"] = "old-run"

        prepared = rag.prepare_questionnaire_run(questionnaire)

        self.assertIsNot(prepared, questionnaire)
        self.assertEqual(questionnaire.rows[0]["Answer"], "Old answer")
        self.assertEqual(questionnaire.rows[0]["citation_ids"], ["old_chunk"])
        self.assertEqual(prepared.question_ids(), ("Q01",))
        self.assertEqual(prepared.rows[0]["Question"], "Is customer data encrypted at rest?")
        self.assertEqual(prepared.rows[0]["Answer"], "")
        self.assertEqual(prepared.rows[0]["Evidence"], "")
        self.assertEqual(prepared.rows[0]["Confidence"], "")
        self.assertEqual(prepared.rows[0]["Status"], "")
        self.assertEqual(prepared.rows[0]["Reviewer Notes"], "")
        self.assertEqual(prepared.rows[0]["citation_ids"], [])
        self.assertEqual(prepared.rows[0]["citations"], [])
        self.assertEqual(prepared.rows[0]["evidence_labels"], [])
        self.assertEqual(prepared.rows[0]["run_id"], "")

    def test_update_row_with_answer_result_populates_visible_and_internal_contract(self):
        """Merged row output should be immediately usable by UI and later export code."""
        row = _runtime_row(
            question_id="Q01",
            category="Encryption",
            question="Is customer data encrypted at rest?",
        )
        citations = (
            _citation(
                chunk_id="enc_001",
                label="Encryption Policy — Data at Rest",
                snippet="Customer data is encrypted at rest with AES-256.",
                source=rag.ENCRYPTION_POLICY_FILE_NAME,
                section="Data at Rest",
            ),
            _citation(
                chunk_id="soc2_001",
                label="SOC 2 Summary — Page 2",
                snippet="The SOC 2 Type II audit was performed by an independent third party.",
                source=rag.SOC2_SUMMARY_FILE_NAME,
                page=2,
            ),
        )

        updated = rag.update_row_with_answer_result(
            row,
            _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                citation_ids=("enc_001", "soc2_001"),
                citations=citations,
                confidence_score=rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_HIGH,
                status=rag.STATUS_READY_FOR_REVIEW,
                reviewer_note="",
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="run-001",
        )

        self.assertEqual(updated["Answer"], "Yes. Customer data is encrypted at rest.")
        self.assertEqual(
            updated["Evidence"],
            "Encryption Policy — Data at Rest; SOC 2 Summary — Page 2",
        )
        self.assertEqual(updated["Confidence"], rag.CONFIDENCE_BAND_HIGH)
        self.assertEqual(updated["Status"], rag.STATUS_READY_FOR_REVIEW)
        self.assertEqual(updated["Reviewer Notes"], rag.FALLBACK_REVIEWER_NOTE)
        self.assertEqual(updated["answer_type"], rag.ANSWER_TYPE_SUPPORTED)
        self.assertEqual(updated["citation_ids"], ["enc_001", "soc2_001"])
        self.assertEqual([citation.chunk_id for citation in updated["citations"]], ["enc_001", "soc2_001"])
        self.assertEqual(
            updated["evidence_labels"],
            ["Encryption Policy — Data at Rest", "SOC 2 Summary — Page 2"],
        )
        self.assertEqual(updated["index_action"], rag.INDEX_ACTION_REUSED)
        self.assertEqual(updated["run_id"], "run-001")

    def test_run_questionnaire_answer_pipeline_updates_rows_in_order_and_emits_incremental_callback(self):
        """The pipeline should preserve workbook order and expose each completed row immediately."""
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
        callback_events: list[tuple[int, str, str, str]] = []
        answers_by_question_id = {
            "Q01": _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                citation_ids=("enc_001", "soc2_001"),
                citations=(
                    _citation(
                        chunk_id="enc_001",
                        label="Encryption Policy — Data at Rest",
                        snippet="Customer data is encrypted at rest with AES-256.",
                        source=rag.ENCRYPTION_POLICY_FILE_NAME,
                        section="Data at Rest",
                    ),
                    _citation(
                        chunk_id="soc2_001",
                        label="SOC 2 Summary — Page 2",
                        snippet="The SOC 2 Type II audit was performed by an independent third party.",
                        source=rag.SOC2_SUMMARY_FILE_NAME,
                        page=2,
                    ),
                ),
                confidence_score=rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_HIGH,
                status=rag.STATUS_READY_FOR_REVIEW,
                reviewer_note="Primary evidence is explicit.",
            ),
            "Q02": _answer_result(
                answer="Partially. Backup encryption is described for core systems.",
                answer_type=rag.ANSWER_TYPE_PARTIAL,
                citation_ids=("bkp_001",),
                citations=(
                    _citation(
                        chunk_id="bkp_001",
                        label="Backup and Recovery Policy — Backup Scope",
                        snippet="Backups for production systems are encrypted at rest.",
                        source=rag.BACKUP_RECOVERY_POLICY_FILE_NAME,
                        section="Backup Scope",
                    ),
                ),
                confidence_score=rag.PARTIAL_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_LOW,
                status=rag.STATUS_NEEDS_REVIEW,
                reviewer_note="Scope is narrower than universal coverage.",
            ),
            "Q03": _answer_result(
                answer="Yes. Privileged access is reviewed on a scheduled basis.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                citation_ids=("acc_001",),
                citations=(
                    _citation(
                        chunk_id="acc_001",
                        label="Access Control Policy — Access Reviews",
                        snippet="Privileged access is reviewed quarterly.",
                        source=rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                        section="Access Reviews",
                    ),
                ),
                confidence_score=rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                status=rag.STATUS_READY_FOR_REVIEW,
                reviewer_note="Quarterly review statement is explicit.",
            ),
        }

        def fake_retrieve(row_like, *, index_status, top_k=rag.RETRIEVAL_TOP_K):
            question_id = str(row_like["question_id"])
            answer_result = answers_by_question_id[question_id]
            return tuple(
                rag.RetrievedEvidenceChunk(
                    chunk_id=citation.chunk_id,
                    source=citation.source,
                    source_path=citation.source_path,
                    doc_type=citation.doc_type,
                    text=citation.snippet_text,
                    rank=index + 1,
                    section=citation.section,
                    page=citation.page,
                )
                for index, citation in enumerate(answer_result.citations)
            )

        def fake_generate(question_text, retrieved_chunks, **kwargs):
            row = next(
                row for row in questionnaire.rows if row["question"] == question_text
            )
            return answers_by_question_id[str(row["question_id"])]

        def on_row_completed(run_questionnaire, row_index):
            row = run_questionnaire.rows[row_index]
            callback_events.append(
                (row_index, str(row["question_id"]), str(row["Status"]), str(row["run_id"]))
            )

        with patch.object(rag, "retrieve_evidence_chunks_for_row", side_effect=fake_retrieve):
            with patch.object(rag, "generate_answer_result", side_effect=fake_generate):
                run = rag.run_questionnaire_answer_pipeline(
                    questionnaire,
                    index_status=_ready_index_status(),
                    run_id="run-ordered",
                    on_row_completed=on_row_completed,
                )

        self.assertEqual(run.question_ids(), ("Q01", "Q02", "Q03"))
        self.assertEqual(
            callback_events,
            [
                (0, "Q01", rag.STATUS_READY_FOR_REVIEW, "run-ordered"),
                (1, "Q02", rag.STATUS_NEEDS_REVIEW, "run-ordered"),
                (2, "Q03", rag.STATUS_READY_FOR_REVIEW, "run-ordered"),
            ],
        )
        self.assertEqual(run.rows[0]["Evidence"], "Encryption Policy — Data at Rest; SOC 2 Summary — Page 2")
        self.assertEqual(run.rows[1]["Status"], rag.STATUS_NEEDS_REVIEW)
        self.assertEqual(run.rows[2]["run_id"], "run-ordered")
        self.assertTrue(all(row["index_action"] == rag.INDEX_ACTION_REUSED for row in run.rows))

    def test_run_questionnaire_answer_pipeline_contains_fail_closed_row_and_continues(self):
        """A fail-closed row should stay isolated to that question while later rows still complete."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            ),
            _runtime_row(
                question_id="Q02",
                category="Key Management",
                question="Do you support customer-managed keys?",
            ),
            _runtime_row(
                question_id="Q03",
                category="Access",
                question="Do you review privileged access?",
            ),
        )
        callback_statuses: list[tuple[str, str]] = []
        side_effects = [
            _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                citation_ids=("enc_001",),
                citations=(
                    _citation(
                        chunk_id="enc_001",
                        label="Encryption Policy — Data at Rest",
                        snippet="Customer data is encrypted at rest with AES-256.",
                        source=rag.ENCRYPTION_POLICY_FILE_NAME,
                        section="Data at Rest",
                    ),
                ),
                confidence_score=rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                status=rag.STATUS_READY_FOR_REVIEW,
                reviewer_note="Primary policy statement is explicit.",
            ),
            rag._build_fail_closed_answer_result(
                rag.FAILURE_REASON_NO_RETRIEVAL,
                retry_count=0,
            ),
            _answer_result(
                answer="Yes. Privileged access is reviewed quarterly.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                citation_ids=("acc_001",),
                citations=(
                    _citation(
                        chunk_id="acc_001",
                        label="Access Control Policy — Access Reviews",
                        snippet="Privileged access is reviewed quarterly.",
                        source=rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                        section="Access Reviews",
                    ),
                ),
                confidence_score=rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                status=rag.STATUS_READY_FOR_REVIEW,
                reviewer_note="Access review statement is explicit.",
            ),
        ]

        def fake_on_row_completed(run_questionnaire, row_index):
            row = run_questionnaire.rows[row_index]
            callback_statuses.append((str(row["question_id"]), str(row["Status"])))

        with patch.object(rag, "retrieve_evidence_chunks_for_row", return_value=()):
            with patch.object(rag, "generate_answer_result", side_effect=side_effects):
                run = rag.run_questionnaire_answer_pipeline(
                    questionnaire,
                    index_status=_ready_index_status(
                        index_action=rag.INDEX_ACTION_REBUILT_INTEGRITY
                    ),
                    run_id="run-fail-closed",
                    on_row_completed=fake_on_row_completed,
                )

        self.assertEqual(
            callback_statuses,
            [
                ("Q01", rag.STATUS_READY_FOR_REVIEW),
                ("Q02", rag.STATUS_NEEDS_REVIEW),
                ("Q03", rag.STATUS_READY_FOR_REVIEW),
            ],
        )
        self.assertEqual(run.rows[1]["Answer"], rag.FAIL_CLOSED_ANSWER)
        self.assertEqual(run.rows[1]["Status"], rag.STATUS_NEEDS_REVIEW)
        self.assertEqual(run.rows[1]["Reviewer Notes"], "No relevant evidence was retrieved; review manually.")
        self.assertEqual(run.rows[1]["citation_ids"], [])
        self.assertEqual(run.rows[1]["citations"], [])
        self.assertEqual(run.rows[1]["index_action"], rag.INDEX_ACTION_REBUILT_INTEGRITY)
        self.assertEqual(run.rows[2]["Answer"], "Yes. Privileged access is reviewed quarterly.")
        self.assertEqual(run.rows[2]["run_id"], "run-fail-closed")

    def test_run_questionnaire_answer_pipeline_emits_structured_pipeline_logs(self):
        """Pipeline orchestration should expose a stable structured event stream."""
        questionnaire = _runtime_questionnaire(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            )
        )
        retrieved_chunks = (
            rag.RetrievedEvidenceChunk(
                chunk_id="enc_001",
                source=rag.ENCRYPTION_POLICY_FILE_NAME,
                source_path=rag.RUNTIME_EVIDENCE_DIR / rag.ENCRYPTION_POLICY_FILE_NAME,
                doc_type=rag.DOCUMENT_TYPE_POLICY,
                text="Customer data is encrypted at rest with AES-256.",
                rank=1,
                section="Data at Rest",
            ),
        )
        log_events: list[dict[str, object]] = []

        with patch.object(
            rag,
            "retrieve_evidence_chunks_for_row",
            return_value=retrieved_chunks,
        ):
            with patch.object(
                rag,
                "generate_answer_result",
                return_value=_answer_result(
                    answer="Yes. Customer data is encrypted at rest.",
                    answer_type=rag.ANSWER_TYPE_SUPPORTED,
                    citation_ids=("enc_001",),
                    citations=(
                        _citation(
                            chunk_id="enc_001",
                            label="Encryption Policy — Data at Rest",
                            snippet="Customer data is encrypted at rest with AES-256.",
                            source=rag.ENCRYPTION_POLICY_FILE_NAME,
                            section="Data at Rest",
                        ),
                    ),
                    confidence_score=rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
                    confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                    status=rag.STATUS_READY_FOR_REVIEW,
                    reviewer_note="Primary policy statement is explicit.",
                ),
            ):
                rag.run_questionnaire_answer_pipeline(
                    questionnaire,
                    index_status=_ready_index_status(),
                    run_id="run-logs",
                    on_log_event=log_events.append,
                )

        self.assertEqual(
            [str(event["event"]) for event in log_events],
            [
                "pipeline_started",
                "row_started",
                "row_retrieved",
                "row_completed",
                "pipeline_completed",
            ],
        )
        row_completed_event = log_events[3]
        self.assertEqual(row_completed_event["question_id"], "Q01")
        self.assertEqual(row_completed_event["answer_type"], rag.ANSWER_TYPE_SUPPORTED)
        self.assertEqual(row_completed_event["confidence_band"], rag.CONFIDENCE_BAND_MEDIUM)
        self.assertEqual(row_completed_event["review_status"], rag.STATUS_READY_FOR_REVIEW)
        self.assertEqual(row_completed_event["valid_citation_count"], 1)
        self.assertEqual(row_completed_event["retrieved_chunk_count"], 1)
        self.assertEqual(log_events[-1]["status"], rag.LOG_STATUS_COMPLETED)

    def test_publish_export_packet_emits_structured_export_logs(self):
        """Export publication should emit staging and final publish events."""
        completed_row = rag.update_row_with_answer_result(
            _runtime_row(
                question_id="Q01",
                category="Encryption",
                question="Is customer data encrypted at rest?",
            ),
            _answer_result(
                answer="Yes. Customer data is encrypted at rest.",
                answer_type=rag.ANSWER_TYPE_SUPPORTED,
                citation_ids=("enc_001",),
                citations=(
                    _citation(
                        chunk_id="enc_001",
                        label="Encryption Policy — Data at Rest",
                        snippet="Customer data is encrypted at rest with AES-256.",
                        source=rag.ENCRYPTION_POLICY_FILE_NAME,
                        section="Data at Rest",
                    ),
                ),
                confidence_score=rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
                confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
                status=rag.STATUS_READY_FOR_REVIEW,
                reviewer_note="Primary policy statement is explicit.",
            ),
            index_action=rag.INDEX_ACTION_REUSED,
            run_id="run-export-logs",
        )
        questionnaire = _runtime_questionnaire(completed_row)
        log_events: list[dict[str, object]] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            packet = rag.publish_export_packet(
                questionnaire,
                output_dir=Path(temp_dir) / "outputs",
                completed_at="2026-04-27T23:00:00Z",
                workspace_hash="workspace-hash",
                on_log_event=log_events.append,
            )

        self.assertTrue(packet.output_dir.name == "outputs")
        self.assertEqual(
            [str(event["event"]) for event in log_events],
            [
                "export_publish_started",
                "answered_questionnaire_written",
                "review_summary_written",
                "needs_review_csv_written",
                "export_published",
            ],
        )
        self.assertEqual(log_events[-1]["status"], rag.LOG_STATUS_COMPLETED)
        self.assertTrue(
            str(log_events[-1]["artifact_path"]).endswith("outputs")
        )


if __name__ == "__main__":
    unittest.main()
