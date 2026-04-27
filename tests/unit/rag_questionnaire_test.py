"""Unit coverage for questionnaire loading and incremental result-row assembly."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import rag


def _resolved_citation(
    *,
    chunk_id: str,
    display_label: str,
    snippet_text: str,
) -> rag.ResolvedEvidenceCitation:
    """Build one resolved citation in the shared row/export shape."""
    return rag.ResolvedEvidenceCitation(
        chunk_id=chunk_id,
        display_label=display_label,
        snippet_text=snippet_text,
        source=rag.ENCRYPTION_POLICY_FILE_NAME,
        source_path=rag.RUNTIME_EVIDENCE_DIR / rag.ENCRYPTION_POLICY_FILE_NAME,
        doc_type=rag.DOCUMENT_TYPE_POLICY,
        section="Data at Rest",
    )


def _generated_result(
    *,
    answer: str,
    answer_type: str,
    confidence_score: float,
    confidence_band: str,
    status: str,
    reviewer_note: str,
    citation_ids: tuple[str, ...] = (),
    citations: tuple[rag.ResolvedEvidenceCitation, ...] = (),
) -> rag.GeneratedAnswerResult:
    """Return one deterministic generated-answer result for row-assembly tests."""
    return rag.GeneratedAnswerResult(
        answer=answer,
        answer_type=answer_type,
        citation_ids=citation_ids,
        citations=citations,
        confidence_score=confidence_score,
        confidence_band=confidence_band,
        status=status,
        reviewer_note=reviewer_note,
    )


class RagQuestionnaireTest(unittest.TestCase):
    """Verify questionnaire loading and row-assembly contracts stay stable."""

    def test_load_runtime_questionnaire_preserves_seed_order_and_result_contract(self):
        """Loading the canonical workbook should add the planned output/internal fields."""
        questionnaire = rag.load_runtime_questionnaire(
            rag.SEED_QUESTIONNAIRE_DIR / rag.QUESTIONNAIRE_FILE_NAME
        )
        dataframe = questionnaire.to_dataframe()

        self.assertEqual(questionnaire.visible_columns, rag.VISIBLE_EXPORT_COLUMNS)
        self.assertEqual(questionnaire.question_ids(), rag.EXPECTED_QUESTION_IDS)
        self.assertEqual(len(questionnaire.rows), 22)
        self.assertEqual(
            list(dataframe.columns),
            [
                *rag.VISIBLE_EXPORT_COLUMNS,
                "question_id",
                "category",
                "question",
                "answer",
                "answer_type",
                "citation_ids",
                "citations",
                "confidence_score",
                "confidence_band",
                "status",
                "reviewer_note",
                "evidence_labels",
                "index_action",
                "run_id",
            ],
        )

        first_row = questionnaire.rows[0]
        self.assertEqual(first_row["Question ID"], "Q01")
        self.assertEqual(first_row["question_id"], "Q01")
        self.assertEqual(first_row["Category"], "Encryption")
        self.assertEqual(first_row["Answer"], "")
        self.assertEqual(first_row["answer"], "")
        self.assertEqual(first_row["citation_ids"], [])
        self.assertEqual(first_row["citations"], [])
        self.assertEqual(first_row["confidence_score"], 0.0)
        self.assertEqual(first_row["evidence_labels"], [])
        self.assertEqual(first_row["run_id"], "")
        self.assertEqual(dataframe.iloc[0]["Question ID"], "Q01")
        self.assertEqual(dataframe.iloc[-1]["Question ID"], "Q22")

    def test_prepare_questionnaire_run_clears_stale_results_without_reordering_questions(self):
        """Fresh run state should reset result fields while preserving row order and seeds."""
        questionnaire = rag.load_runtime_questionnaire(
            rag.SEED_QUESTIONNAIRE_DIR / rag.QUESTIONNAIRE_FILE_NAME
        )
        questionnaire.rows[0]["Answer"] = "stale answer"
        questionnaire.rows[0]["Evidence"] = "stale evidence"
        questionnaire.rows[0]["Confidence"] = "High"
        questionnaire.rows[0]["Status"] = rag.STATUS_READY_FOR_REVIEW
        questionnaire.rows[0]["Reviewer Notes"] = "stale note"
        questionnaire.rows[0]["answer"] = "stale answer"
        questionnaire.rows[0]["citation_ids"] = ["enc_001"]
        questionnaire.rows[0]["citations"] = [
            _resolved_citation(
                chunk_id="enc_001",
                display_label="Encryption Policy — Data at Rest",
                snippet_text="stale snippet",
            )
        ]
        questionnaire.rows[0]["confidence_score"] = 0.90
        questionnaire.rows[0]["confidence_band"] = rag.CONFIDENCE_BAND_HIGH
        questionnaire.rows[0]["status"] = rag.STATUS_READY_FOR_REVIEW
        questionnaire.rows[0]["reviewer_note"] = "stale note"
        questionnaire.rows[0]["evidence_labels"] = [
            "Encryption Policy — Data at Rest"
        ]
        questionnaire.rows[0]["index_action"] = rag.INDEX_ACTION_REUSED
        questionnaire.rows[0]["run_id"] = "old-run"

        prepared = rag.prepare_questionnaire_run(questionnaire)

        self.assertEqual(prepared.question_ids(), questionnaire.question_ids())
        self.assertEqual(prepared.rows[0]["Question ID"], "Q01")
        self.assertEqual(prepared.rows[0]["Question"], questionnaire.rows[0]["Question"])
        self.assertEqual(prepared.rows[0]["Answer"], "")
        self.assertEqual(prepared.rows[0]["Evidence"], "")
        self.assertEqual(prepared.rows[0]["Confidence"], "")
        self.assertEqual(prepared.rows[0]["Status"], "")
        self.assertEqual(prepared.rows[0]["Reviewer Notes"], "")
        self.assertEqual(prepared.rows[0]["answer"], "")
        self.assertEqual(prepared.rows[0]["citation_ids"], [])
        self.assertEqual(prepared.rows[0]["citations"], [])
        self.assertEqual(prepared.rows[0]["confidence_score"], 0.0)
        self.assertEqual(prepared.rows[0]["evidence_labels"], [])
        self.assertEqual(prepared.rows[0]["index_action"], "")
        self.assertEqual(prepared.rows[0]["run_id"], "")

        self.assertEqual(questionnaire.rows[0]["Answer"], "stale answer")
        self.assertEqual(questionnaire.rows[0]["run_id"], "old-run")

    def test_run_questionnaire_answer_pipeline_updates_rows_incrementally_in_order(self):
        """The pipeline runner should fill rows one at a time without stale-run bleed-through."""
        questionnaire = rag.RuntimeQuestionnaire(
            workbook_path=Path("demo.xlsx"),
            visible_columns=rag.VISIBLE_EXPORT_COLUMNS,
            rows=[
                {
                    "Question ID": "Q01",
                    "Category": "Residency",
                    "Question": "Can customers choose the region where data is stored?",
                    "Answer": "",
                    "Evidence": "",
                    "Confidence": "",
                    "Status": "",
                    "Reviewer Notes": "",
                    "question_id": "Q01",
                    "category": "Residency",
                    "question": "Can customers choose the region where data is stored?",
                    **rag.make_result_row_defaults(),
                },
                {
                    "Question ID": "Q02",
                    "Category": "Encryption",
                    "Question": "Is customer data encrypted at rest in production systems?",
                    "Answer": "",
                    "Evidence": "",
                    "Confidence": "",
                    "Status": "",
                    "Reviewer Notes": "",
                    "question_id": "Q02",
                    "category": "Encryption",
                    "question": "Is customer data encrypted at rest in production systems?",
                    **rag.make_result_row_defaults(),
                },
                {
                    "Question ID": "Q03",
                    "Category": "Residency",
                    "Question": "Do the policies mention customer-selectable data residency?",
                    "Answer": "",
                    "Evidence": "",
                    "Confidence": "",
                    "Status": "",
                    "Reviewer Notes": "",
                    "question_id": "Q03",
                    "category": "Residency",
                    "question": "Do the policies mention customer-selectable data residency?",
                    **rag.make_result_row_defaults(),
                },
            ],
        )

        fail_closed_result = rag.generate_answer_result(
            "Can customers choose the region where data is stored?",
            (),
        )
        supported_result = _generated_result(
            answer="Yes. Customer data is encrypted at rest in production systems.",
            answer_type=rag.ANSWER_TYPE_SUPPORTED,
            citation_ids=("enc_001",),
            citations=(
                _resolved_citation(
                    chunk_id="enc_001",
                    display_label="Encryption Policy — Data at Rest",
                    snippet_text="Customer data is encrypted at rest with AES-256.",
                ),
            ),
            confidence_score=rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
            confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
            status=rag.STATUS_READY_FOR_REVIEW,
            reviewer_note="grounded in policy",
        )
        unsupported_result = _generated_result(
            answer="Not stated. The current evidence does not mention region selection.",
            answer_type=rag.ANSWER_TYPE_UNSUPPORTED,
            confidence_score=rag.FAIL_CLOSED_SCORE,
            confidence_band=rag.CONFIDENCE_BAND_LOW,
            status=rag.STATUS_NEEDS_REVIEW,
            reviewer_note="No source describes customer-selectable data residency.",
        )

        def fake_retrieve(
            row_like: dict[str, object],
            *,
            index_status: object,
            top_k: int = rag.RETRIEVAL_TOP_K,
        ) -> tuple[rag.RetrievedEvidenceChunk, ...]:
            del index_status, top_k
            if row_like["question_id"] == "Q01":
                return ()
            if row_like["question_id"] == "Q02":
                chunk_id = "enc_001"
                text = "Customer data is encrypted at rest with AES-256."
            else:
                chunk_id = "res_001"
                text = "The policy does not mention customer-selectable data residency."
            return (
                rag.RetrievedEvidenceChunk(
                    chunk_id=chunk_id,
                    source=rag.ENCRYPTION_POLICY_FILE_NAME,
                    source_path=rag.RUNTIME_EVIDENCE_DIR / rag.ENCRYPTION_POLICY_FILE_NAME,
                    doc_type=rag.DOCUMENT_TYPE_POLICY,
                    text=text,
                    rank=1,
                    section="Data at Rest",
                ),
            )

        def fake_generate(
            question_text: str,
            retrieved_chunks: tuple[rag.RetrievedEvidenceChunk, ...],
            **_: object,
        ) -> rag.GeneratedAnswerResult:
            del question_text
            if not retrieved_chunks:
                return fail_closed_result
            if retrieved_chunks[0].chunk_id == "enc_001":
                return supported_result
            return unsupported_result

        callback_snapshots: list[tuple[int, list[str], list[str]]] = []

        def on_row_completed(
            run_questionnaire: rag.RuntimeQuestionnaire,
            row_index: int,
        ) -> None:
            callback_snapshots.append(
                (
                    row_index,
                    [str(row["Answer"]) for row in run_questionnaire.rows],
                    [str(row["run_id"]) for row in run_questionnaire.rows],
                )
            )

        with patch.object(
            rag,
            "retrieve_evidence_chunks_for_row",
            side_effect=fake_retrieve,
        ), patch.object(
            rag,
            "generate_answer_result",
            side_effect=fake_generate,
        ):
            completed = rag.run_questionnaire_answer_pipeline(
                questionnaire,
                index_status=SimpleNamespace(index_action=rag.INDEX_ACTION_REUSED),
                run_id="run-001",
                on_row_completed=on_row_completed,
            )

        self.assertEqual(
            [row["question_id"] for row in completed.rows],
            ["Q01", "Q02", "Q03"],
        )
        self.assertEqual(completed.rows[0]["Answer"], rag.FAIL_CLOSED_ANSWER)
        self.assertEqual(completed.rows[0]["Status"], rag.STATUS_NEEDS_REVIEW)
        self.assertEqual(
            completed.rows[0]["Reviewer Notes"],
            "No relevant evidence was retrieved; review manually.",
        )
        self.assertEqual(
            completed.rows[1]["Answer"],
            "Yes. Customer data is encrypted at rest in production systems.",
        )
        self.assertEqual(
            completed.rows[1]["Evidence"],
            "Encryption Policy — Data at Rest",
        )
        self.assertEqual(completed.rows[1]["citation_ids"], ["enc_001"])
        self.assertEqual(
            completed.rows[1]["citations"][0].snippet_text,
            "Customer data is encrypted at rest with AES-256.",
        )
        self.assertEqual(completed.rows[1]["run_id"], "run-001")
        self.assertEqual(completed.rows[1]["index_action"], rag.INDEX_ACTION_REUSED)
        self.assertEqual(
            completed.rows[2]["Answer"],
            "Not stated. The current evidence does not mention region selection.",
        )
        self.assertEqual(completed.rows[2]["Evidence"], "")
        self.assertEqual(completed.rows[2]["Status"], rag.STATUS_NEEDS_REVIEW)
        self.assertEqual(
            callback_snapshots,
            [
                (0, [rag.FAIL_CLOSED_ANSWER, "", ""], ["run-001", "", ""]),
                (
                    1,
                    [
                        rag.FAIL_CLOSED_ANSWER,
                        "Yes. Customer data is encrypted at rest in production systems.",
                        "",
                    ],
                    ["run-001", "run-001", ""],
                ),
                (
                    2,
                    [
                        rag.FAIL_CLOSED_ANSWER,
                        "Yes. Customer data is encrypted at rest in production systems.",
                        "Not stated. The current evidence does not mention region selection.",
                    ],
                    ["run-001", "run-001", "run-001"],
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
