"""Unit coverage for retrieval from the validated Chroma index."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
