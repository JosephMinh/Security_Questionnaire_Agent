"""Unit coverage for retrieval from the validated Chroma index."""

from __future__ import annotations

import json
import unittest

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


if __name__ == "__main__":
    unittest.main()
