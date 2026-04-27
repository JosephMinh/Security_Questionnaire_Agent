"""Unit coverage for retrieval from the validated Chroma index."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import rag


class _FakeCollection:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload
        self.query_calls: list[dict[str, object]] = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return self.payload


def _ready_index_status(
    collection: _FakeCollection,
    *,
    actual_chunk_count: int,
) -> rag.ChromaIndexStatus:
    handle = rag.ChromaCollectionHandle(
        collection_name=rag.COLLECTION_NAME,
        persist_directory=rag.CHROMA_DIR,
        client=object(),
        collection=collection,
    )
    return rag.ChromaIndexStatus(
        collection_name=rag.COLLECTION_NAME,
        persist_directory=rag.CHROMA_DIR,
        workspace_hash="workspace-hash",
        stored_workspace_hash="workspace-hash",
        stored_chunk_count=actual_chunk_count,
        actual_chunk_count=actual_chunk_count,
        index_action=rag.INDEX_ACTION_REUSED,
        ready=True,
        reason="reused",
        collection_handle=handle,
    )


def _retrieved_chunk(
    chunk_id: str,
    *,
    source: str,
    doc_type: str,
    text: str,
    rank: int,
    section: str | None = None,
    page: int | None = None,
) -> rag.RetrievedEvidenceChunk:
    """Build one compact retrieved chunk fixture for prompt and answer tests."""
    return rag.RetrievedEvidenceChunk(
        chunk_id=chunk_id,
        source=source,
        source_path=rag.RUNTIME_EVIDENCE_DIR / source,
        doc_type=doc_type,
        text=text,
        rank=rank,
        section=section,
        page=page,
    )


class RagRetrievalTest(unittest.TestCase):
    """Verify retrieval stays bounded, deduplicated, and prompt-ready."""

    def _expected_fixture_question(self, question_id: str) -> dict[str, object]:
        """Return one canonical expected-outcomes row by question id."""
        fixture_path = rag.SEED_QUESTIONNAIRE_DIR / "Demo_Security_Questionnaire.expected.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for question in fixture["questions"]:
            if question["question_id"] == question_id:
                return dict(question)
        raise AssertionError(f"Question {question_id!r} was not found in the expected fixture.")

    def test_retrieve_evidence_chunks_dedupes_and_preserves_relevance_order(self):
        """Duplicate logical chunk ids should collapse while later unique hits still surface."""
        collection = _FakeCollection(
            {
                "ids": [[
                    "enc_002",
                    "enc_002-duplicate",
                    "soc2_001",
                    "bkp_001",
                    "ir_001",
                    "acc_001",
                ]],
                "documents": [[
                    "Encryption evidence.",
                    "Duplicate encryption evidence.",
                    "SOC 2 page evidence.",
                    "Backup evidence.",
                    "Incident evidence.",
                    "Access review evidence.",
                ]],
                "metadatas": [[
                    {
                        "chunk_id": "enc_002",
                        "source": rag.ENCRYPTION_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Encryption Standard",
                        "page": None,
                    },
                    {
                        "chunk_id": "enc_002",
                        "source": rag.ENCRYPTION_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Encryption Standard",
                        "page": None,
                    },
                    {
                        "chunk_id": "soc2_001",
                        "source": rag.SOC2_SUMMARY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_PDF,
                        "section": None,
                        "page": 1,
                    },
                    {
                        "chunk_id": "bkp_001",
                        "source": rag.BACKUP_RECOVERY_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Backup Policy",
                        "page": None,
                    },
                    {
                        "chunk_id": "ir_001",
                        "source": rag.INCIDENT_RESPONSE_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Escalation",
                        "page": None,
                    },
                    {
                        "chunk_id": "acc_001",
                        "source": rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Access Reviews",
                        "page": None,
                    },
                ]],
                "distances": [[0.01, 0.02, 0.03, 0.04, 0.05, 0.06]],
            }
        )
        index_status = _ready_index_status(collection, actual_chunk_count=6)

        retrieved = rag.retrieve_evidence_chunks(
            "  Do you encrypt production data at rest?  ",
            index_status=index_status,
            top_k=3,
        )

        self.assertEqual(
            collection.query_calls,
            [
                {
                    "query_texts": ["Do you encrypt production data at rest?"],
                    "n_results": 6,
                    "include": ["documents", "metadatas", "distances"],
                }
            ],
        )
        self.assertEqual(
            [chunk.chunk_id for chunk in retrieved],
            ["enc_002", "soc2_001", "bkp_001"],
        )
        self.assertEqual([chunk.rank for chunk in retrieved], [1, 2, 3])
        self.assertEqual(
            [chunk.source_path for chunk in retrieved],
            [
                rag.RUNTIME_EVIDENCE_DIR / rag.ENCRYPTION_POLICY_FILE_NAME,
                rag.RUNTIME_EVIDENCE_DIR / rag.SOC2_SUMMARY_FILE_NAME,
                rag.RUNTIME_EVIDENCE_DIR / rag.BACKUP_RECOVERY_POLICY_FILE_NAME,
            ],
        )
        self.assertEqual(
            retrieved[1].metadata(),
            {
                "chunk_id": "soc2_001",
                "source": rag.SOC2_SUMMARY_FILE_NAME,
                "doc_type": rag.DOCUMENT_TYPE_PDF,
                "section": None,
                "page": 1,
            },
        )

    def test_retrieve_evidence_chunks_for_row_supports_visible_question_key(self):
        """The row helper should work with the visible workbook `Question` field."""
        collection = _FakeCollection(
            {
                "ids": [["acc_001"]],
                "documents": [["Access review evidence."]],
                "metadatas": [[
                    {
                        "chunk_id": "acc_001",
                        "source": rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Access Reviews",
                        "page": None,
                    }
                ]],
                "distances": [[0.11]],
            }
        )
        index_status = _ready_index_status(collection, actual_chunk_count=1)

        retrieved = rag.retrieve_evidence_chunks_for_row(
            {
                "Question ID": "Q05",
                "Question": "Do you review access permissions?",
            },
            index_status=index_status,
        )

        self.assertEqual([chunk.chunk_id for chunk in retrieved], ["acc_001"])
        self.assertEqual(
            collection.query_calls[0]["query_texts"],
            ["Do you review access permissions?"],
        )

    def test_retrieve_evidence_chunks_rejects_malformed_payload(self):
        """Retrieval should fail loudly when Chroma omits the logical chunk metadata."""
        collection = _FakeCollection(
            {
                "ids": [["enc_001"]],
                "documents": [["Encryption evidence."]],
                "metadatas": [[{"source": rag.ENCRYPTION_POLICY_FILE_NAME}]],
                "distances": [[0.01]],
            }
        )
        index_status = _ready_index_status(collection, actual_chunk_count=1)

        with self.assertRaises(RuntimeError) as context:
            rag.retrieve_evidence_chunks(
                "Do you encrypt production data at rest?",
                index_status=index_status,
            )

        self.assertIn("logical chunk id", str(context.exception))

    def test_retrieve_evidence_chunks_caps_at_five_unique_results(self):
        """Default retrieval should stop at five unique logical chunks in relevance order."""
        collection = _FakeCollection(
            {
                "ids": [[
                    "enc_001-hit-a",
                    "enc_001-hit-b",
                    "acc_001-hit",
                    "ir_001-hit",
                    "bkp_001-hit",
                    "soc2_001-hit",
                    "enc_003-hit",
                ]],
                "documents": [[
                    "Encryption evidence primary.",
                    "Encryption evidence duplicate.",
                    "Access review evidence.",
                    "Incident response evidence.",
                    "Backup evidence.",
                    "SOC 2 evidence.",
                    "Lower-ranked encryption evidence.",
                ]],
                "metadatas": [[
                    {
                        "chunk_id": "enc_001",
                        "source": rag.ENCRYPTION_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Data at Rest",
                        "page": None,
                    },
                    {
                        "chunk_id": "enc_001",
                        "source": rag.ENCRYPTION_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Data at Rest",
                        "page": None,
                    },
                    {
                        "chunk_id": "acc_001",
                        "source": rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Access Reviews",
                        "page": None,
                    },
                    {
                        "chunk_id": "ir_001",
                        "source": rag.INCIDENT_RESPONSE_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Incident Triage Timeline",
                        "page": None,
                    },
                    {
                        "chunk_id": "bkp_001",
                        "source": rag.BACKUP_RECOVERY_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Backup Frequency",
                        "page": None,
                    },
                    {
                        "chunk_id": "soc2_001",
                        "source": rag.SOC2_SUMMARY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_PDF,
                        "section": None,
                        "page": 1,
                    },
                    {
                        "chunk_id": "enc_003",
                        "source": rag.ENCRYPTION_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                        "section": "Centralized Key Management",
                        "page": None,
                    },
                ]],
                "distances": [[0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07]],
            }
        )
        index_status = _ready_index_status(collection, actual_chunk_count=7)

        retrieved = rag.retrieve_evidence_chunks(
            "Which five evidence chunks should reach the model?",
            index_status=index_status,
        )

        self.assertEqual(collection.query_calls[0]["n_results"], 7)
        self.assertEqual(
            [chunk.chunk_id for chunk in retrieved],
            ["enc_001", "acc_001", "ir_001", "bkp_001", "soc2_001"],
        )
        self.assertEqual([chunk.rank for chunk in retrieved], [1, 2, 3, 4, 5])
        self.assertEqual(len(retrieved), 5)

    def test_retrieve_evidence_chunks_for_row_preserves_fixture_primary_source_anchors(self):
        """Representative fixture rows should keep the expected primary source visible first."""
        cases = ("Q01", "Q14")
        for question_id in cases:
            with self.subTest(question_id=question_id):
                question = self._expected_fixture_question(question_id)
                primary_source = str(question["primary_source"])
                anchor_hint = str(question["anchor_hint"])
                primary_doc_type = (
                    rag.DOCUMENT_TYPE_PDF
                    if primary_source.endswith(".pdf")
                    else rag.DOCUMENT_TYPE_POLICY
                )
                primary_section = None if primary_doc_type == rag.DOCUMENT_TYPE_PDF else anchor_hint
                primary_page = 1 if primary_doc_type == rag.DOCUMENT_TYPE_PDF else None

                collection = _FakeCollection(
                    {
                        "ids": [["primary-hit", "secondary-hit"]],
                        "documents": [[
                            f"{anchor_hint}: evidence text for {question_id}.",
                            "Secondary supporting evidence.",
                        ]],
                        "metadatas": [[
                            {
                                "chunk_id": f"{question_id.lower()}_primary",
                                "source": primary_source,
                                "doc_type": primary_doc_type,
                                "section": primary_section,
                                "page": primary_page,
                            },
                            {
                                "chunk_id": f"{question_id.lower()}_secondary",
                                "source": rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                                "doc_type": rag.DOCUMENT_TYPE_POLICY,
                                "section": "Secondary Evidence",
                                "page": None,
                            },
                        ]],
                        "distances": [[0.01, 0.09]],
                    }
                )
                index_status = _ready_index_status(collection, actual_chunk_count=2)

                retrieved = rag.retrieve_evidence_chunks_for_row(
                    {
                        "Question ID": question_id,
                        "Question": str(question["question"]),
                    },
                    index_status=index_status,
                    top_k=2,
                )

                self.assertEqual(
                    collection.query_calls[0]["query_texts"],
                    [str(question["question"])],
                )
                self.assertEqual(retrieved[0].source, primary_source)
                self.assertIn(anchor_hint, retrieved[0].text)
                self.assertEqual(retrieved[0].source_path, rag.RUNTIME_EVIDENCE_DIR / primary_source)
                self.assertEqual(
                    retrieved[0].metadata(),
                    {
                        "chunk_id": f"{question_id.lower()}_primary",
                        "source": primary_source,
                        "doc_type": primary_doc_type,
                        "section": primary_section,
                        "page": primary_page,
                    },
                )


class RagAnswerPipelineTest(unittest.TestCase):
    """Verify prompt, validation, scoring, retry, and fail-closed answer behavior."""

    def _expected_fixture_question(self, question_id: str) -> dict[str, object]:
        """Return one canonical expected-outcomes row by question id."""
        fixture_path = rag.SEED_QUESTIONNAIRE_DIR / "Demo_Security_Questionnaire.expected.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for question in fixture["questions"]:
            if question["question_id"] == question_id:
                return dict(question)
        raise AssertionError(f"Question {question_id!r} was not found in the expected fixture.")

    def _sample_retrieved_chunks(self) -> tuple[rag.RetrievedEvidenceChunk, ...]:
        """Return one deterministic retrieved chunk set for answer-pipeline tests."""
        return (
            _retrieved_chunk(
                "enc_001",
                source=rag.ENCRYPTION_POLICY_FILE_NAME,
                doc_type=rag.DOCUMENT_TYPE_POLICY,
                text="Data at Rest: Customer data is encrypted using AES-256 in production.",
                rank=1,
                section="Data at Rest",
            ),
            _retrieved_chunk(
                "acc_001",
                source=rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                doc_type=rag.DOCUMENT_TYPE_POLICY,
                text=(
                    "Single Sign-On Scope: SSO is used for core workforce systems, "
                    "but not every application is covered."
                ),
                rank=2,
                section="Single Sign-On Scope",
            ),
            _retrieved_chunk(
                "soc2_001",
                source=rag.SOC2_SUMMARY_FILE_NAME,
                doc_type=rag.DOCUMENT_TYPE_PDF,
                text="SOC 2 summary page one evidence.",
                rank=3,
                page=1,
            ),
        )

    def test_build_answer_prompt_messages_uses_exact_conservative_contract(self):
        """Prompt construction should preserve the canonical system and user message shape."""
        retrieved_chunks = self._sample_retrieved_chunks()[:2]

        messages = rag.build_answer_prompt_messages(
            "  Do you encrypt customer data at rest?  ",
            retrieved_chunks,
        )

        expected_user_prompt = "\n".join(
            (
                "Question:",
                "Do you encrypt customer data at rest?",
                "",
                "Evidence chunks:",
                (
                    f"[enc_001] source={rag.ENCRYPTION_POLICY_FILE_NAME} section=Data at Rest\n"
                    "Data at Rest: Customer data is encrypted using AES-256 in production."
                ),
                "",
                (
                    f"[acc_001] source={rag.ACCESS_CONTROL_POLICY_FILE_NAME} "
                    "section=Single Sign-On Scope\n"
                    "Single Sign-On Scope: SSO is used for core workforce systems, "
                    "but not every application is covered."
                ),
            )
        )
        self.assertEqual(
            messages,
            (
                {"role": "system", "content": rag.CONSERVATIVE_ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": expected_user_prompt},
            ),
        )

    def test_validate_answer_payload_filters_invalid_citations_and_normalizes_blank_note(self):
        """Validation should dedupe valid citations, drop invalid ones, and normalize notes."""
        result = rag.validate_answer_payload(
            {
                "answer": "Yes. Encryption at rest is enforced in production.",
                "answer_type": rag.ANSWER_TYPE_SUPPORTED,
                "citation_ids": ["enc_001", "missing_chunk", "enc_001"],
                "reviewer_note": "   ",
            },
            self._sample_retrieved_chunks(),
        )

        self.assertTrue(result.usable)
        self.assertEqual(
            result.outcome,
            rag.ANSWER_PAYLOAD_OUTCOME_ACCEPTED_WITH_CITATION_IDS_REMOVED,
        )
        self.assertEqual(result.answer, "Yes. Encryption at rest is enforced in production.")
        self.assertEqual(result.answer_type, rag.ANSWER_TYPE_SUPPORTED)
        self.assertEqual(result.citation_ids, ("enc_001",))
        self.assertEqual(result.invalid_citation_ids, ("missing_chunk",))
        self.assertEqual(result.reviewer_note, rag.FALLBACK_REVIEWER_NOTE)
        self.assertIsNone(result.failure_reason)

    def test_score_answer_confidence_matches_planned_rules(self):
        """Confidence score, band, and review status should follow the planned thresholds exactly."""
        cases = (
            (
                rag.ANSWER_TYPE_SUPPORTED,
                1,
                rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
                rag.CONFIDENCE_BAND_MEDIUM,
                rag.STATUS_READY_FOR_REVIEW,
            ),
            (
                rag.ANSWER_TYPE_SUPPORTED,
                2,
                rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE,
                rag.CONFIDENCE_BAND_HIGH,
                rag.STATUS_READY_FOR_REVIEW,
            ),
            (
                rag.ANSWER_TYPE_PARTIAL,
                1,
                rag.PARTIAL_SCORE,
                rag.CONFIDENCE_BAND_LOW,
                rag.STATUS_NEEDS_REVIEW,
            ),
            (
                rag.ANSWER_TYPE_UNSUPPORTED,
                1,
                rag.UNSUPPORTED_SCORE,
                rag.CONFIDENCE_BAND_LOW,
                rag.STATUS_NEEDS_REVIEW,
            ),
            (
                rag.ANSWER_TYPE_SUPPORTED,
                0,
                rag.FAIL_CLOSED_SCORE,
                rag.CONFIDENCE_BAND_LOW,
                rag.STATUS_NEEDS_REVIEW,
            ),
        )

        for answer_type, citation_count, score, band, status in cases:
            with self.subTest(answer_type=answer_type, citation_count=citation_count):
                result = rag.score_answer_confidence(
                    answer_type,
                    valid_citation_count=citation_count,
                )
                self.assertEqual(result.confidence_score, score)
                self.assertEqual(result.confidence_band, band)
                self.assertEqual(result.status, status)

    def test_resolve_validated_citations_returns_literal_snippets_and_stable_labels(self):
        """Resolved citations should preserve literal snippet text and cap visible citations at two."""
        question = self._expected_fixture_question("Q01")
        primary_source = str(question["primary_source"])
        anchor_hint = str(question["anchor_hint"])
        retrieved_chunks = (
            _retrieved_chunk(
                "q01_primary",
                source=primary_source,
                doc_type=rag.DOCUMENT_TYPE_POLICY,
                text=f"{anchor_hint}: evidence text copied verbatim for Q01.",
                rank=1,
                section=anchor_hint,
            ),
            _retrieved_chunk(
                "q01_secondary",
                source=rag.SOC2_SUMMARY_FILE_NAME,
                doc_type=rag.DOCUMENT_TYPE_PDF,
                text="SOC 2 summary text copied verbatim for Q01.",
                rank=2,
                page=1,
            ),
            _retrieved_chunk(
                "q01_extra",
                source=rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                doc_type=rag.DOCUMENT_TYPE_POLICY,
                text="Extra lower-priority text that should be hidden by the two-citation cap.",
                rank=3,
                section="Secondary Evidence",
            ),
        )

        resolved = rag.resolve_validated_citations(
            ("q01_primary", "q01_secondary", "q01_extra"),
            retrieved_chunks,
        )

        self.assertEqual(len(resolved), 2)
        self.assertEqual(resolved[0].chunk_id, "q01_primary")
        self.assertEqual(
            resolved[0].display_label,
            rag.build_citation_display_label(primary_source, anchor_hint, None),
        )
        self.assertEqual(
            resolved[0].snippet_text,
            f"{anchor_hint}: evidence text copied verbatim for Q01.",
        )
        self.assertIn(anchor_hint, resolved[0].snippet_text)
        self.assertEqual(resolved[1].chunk_id, "q01_secondary")
        self.assertEqual(
            resolved[1].display_label,
            rag.build_citation_display_label(rag.SOC2_SUMMARY_FILE_NAME, None, 1),
        )
        self.assertEqual(resolved[1].snippet_text, "SOC 2 summary text copied verbatim for Q01.")

    def test_generate_answer_result_matches_representative_fixture_review_posture(self):
        """Representative supported, partial, and unsupported rows should match fixture posture."""
        cases = (
            (
                "Q01",
                self._sample_retrieved_chunks(),
                {
                    "answer": (
                        "Yes. Customer data at rest is encrypted in production systems "
                        "using AES-256."
                    ),
                    "answer_type": rag.ANSWER_TYPE_SUPPORTED,
                    "citation_ids": ["enc_001", "soc2_001"],
                    "reviewer_note": "Primary policy statement is explicit.",
                },
            ),
            (
                "Q16",
                self._sample_retrieved_chunks(),
                {
                    "answer": (
                        "Partially. SSO is used for core workforce systems, but the "
                        "evidence does not claim universal application coverage."
                    ),
                    "answer_type": rag.ANSWER_TYPE_PARTIAL,
                    "citation_ids": ["acc_001"],
                    "reviewer_note": "Scope is narrower than universal enforcement.",
                },
            ),
            (
                "Q19",
                self._sample_retrieved_chunks(),
                {
                    "answer": (
                        "Not stated. The available evidence does not describe support "
                        "for customer-managed encryption keys."
                    ),
                    "answer_type": rag.ANSWER_TYPE_UNSUPPORTED,
                    "citation_ids": [],
                    "reviewer_note": "   ",
                },
            ),
        )

        for question_id, retrieved_chunks, payload in cases:
            with self.subTest(question_id=question_id):
                question = self._expected_fixture_question(question_id)
                with patch.object(rag, "generate_answer_payload", return_value=payload):
                    result = rag.generate_answer_result(
                        str(question["question"]),
                        retrieved_chunks,
                    )

                self.assertFalse(result.failed_closed)
                self.assertEqual(result.answer_type, str(question["expected_answer_type"]))
                self.assertTrue(result.answer.startswith(str(question["expected_opening_token"])))
                self.assertEqual(result.status, str(question["expected_status"]))
                self.assertIn(result.confidence_band, tuple(question["allowed_confidence_bands"]))
                if question_id == "Q19":
                    self.assertEqual(result.reviewer_note, rag.FALLBACK_REVIEWER_NOTE)
                    self.assertEqual(result.citations, ())
                else:
                    self.assertTrue(result.reviewer_note)
                    self.assertTrue(result.citations)

    def test_generate_answer_result_retries_once_for_retryable_runtime_error_then_succeeds(self):
        """Malformed provider output should consume one retry and still allow a later success."""
        retrieved_chunks = self._sample_retrieved_chunks()
        side_effect = [
            RuntimeError("OpenAI answer generation returned malformed JSON for the answer payload."),
            {
                "answer": "Yes. Encryption at rest is enforced in production systems.",
                "answer_type": rag.ANSWER_TYPE_SUPPORTED,
                "citation_ids": ["enc_001", "soc2_001"],
                "reviewer_note": "Citations map directly to the retrieved evidence.",
            },
        ]

        with patch.object(rag, "generate_answer_payload", side_effect=side_effect) as generate:
            result = rag.generate_answer_result(
                "Is customer data encrypted at rest in production systems?",
                retrieved_chunks,
            )

        self.assertEqual(generate.call_count, 2)
        self.assertFalse(result.failed_closed)
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(result.citation_ids, ("enc_001", "soc2_001"))
        self.assertEqual(result.invalid_citation_ids, ())
        self.assertEqual(result.confidence_score, rag.SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE)
        self.assertEqual(result.confidence_band, rag.CONFIDENCE_BAND_HIGH)
        self.assertEqual(result.status, rag.STATUS_READY_FOR_REVIEW)

    def test_generate_answer_result_fail_closes_after_single_retry_for_validation_failure(self):
        """Schema-invalid payloads should retry once and then fail closed with the mapped reason."""
        retrieved_chunks = self._sample_retrieved_chunks()
        invalid_payload = {
            "answer": "Yes. Encryption exists.",
            "answer_type": rag.ANSWER_TYPE_SUPPORTED,
            "citation_ids": "enc_001",
            "reviewer_note": "Will be replaced by the fail-closed reason.",
        }

        with patch.object(
            rag,
            "generate_answer_payload",
            side_effect=[invalid_payload, invalid_payload],
        ) as generate:
            result = rag.generate_answer_result(
                "Is customer data encrypted at rest in production systems?",
                retrieved_chunks,
            )

        self.assertEqual(generate.call_count, 2)
        self.assertTrue(result.failed_closed)
        self.assertEqual(result.failure_reason, "citation_ids_invalid")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(result.answer, rag.FAIL_CLOSED_ANSWER)
        self.assertEqual(
            result.reviewer_note,
            "Model citations were unusable after retry; review manually.",
        )
        self.assertEqual(result.confidence_score, rag.FAIL_CLOSED_SCORE)
        self.assertEqual(result.confidence_band, rag.CONFIDENCE_BAND_LOW)
        self.assertEqual(result.status, rag.STATUS_NEEDS_REVIEW)

    def test_generate_answer_result_fail_closes_immediately_when_no_retrieval_exists(self):
        """Empty retrieval is an evidence failure and should not consume the model retry."""
        with patch.object(rag, "generate_answer_payload") as generate:
            result = rag.generate_answer_result(
                "Do you support customer-managed encryption keys?",
                (),
            )

        generate.assert_not_called()
        self.assertTrue(result.failed_closed)
        self.assertEqual(result.failure_reason, rag.FAILURE_REASON_NO_RETRIEVAL)
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(result.answer, rag.FAIL_CLOSED_ANSWER)
        self.assertEqual(
            result.reviewer_note,
            "No relevant evidence was retrieved; review manually.",
        )
        self.assertEqual(result.answer_type, rag.ANSWER_TYPE_UNSUPPORTED)
        self.assertEqual(result.confidence_score, rag.FAIL_CLOSED_SCORE)
        self.assertEqual(result.confidence_band, rag.CONFIDENCE_BAND_LOW)
        self.assertEqual(result.status, rag.STATUS_NEEDS_REVIEW)

    def test_generate_answer_result_fail_closes_without_retry_when_all_citations_are_invalid(self):
        """All-invalid citations should fail closed immediately because the evidence set is unusable."""
        retrieved_chunks = self._sample_retrieved_chunks()
        payload = {
            "answer": "Yes. Encryption at rest is enforced in production systems.",
            "answer_type": rag.ANSWER_TYPE_SUPPORTED,
            "citation_ids": ["missing_chunk"],
            "reviewer_note": "This note should be replaced by the fail-closed reason.",
        }

        with patch.object(rag, "generate_answer_payload", return_value=payload) as generate:
            result = rag.generate_answer_result(
                "Is customer data encrypted at rest in production systems?",
                retrieved_chunks,
            )

        generate.assert_called_once()
        self.assertTrue(result.failed_closed)
        self.assertEqual(result.failure_reason, "no_valid_citations")
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(
            result.reviewer_note,
            "All cited evidence was invalid; review manually.",
        )
        self.assertEqual(result.answer, rag.FAIL_CLOSED_ANSWER)
        self.assertEqual(result.citation_ids, ())
        self.assertEqual(result.citations, ())


if __name__ == "__main__":
    unittest.main()
