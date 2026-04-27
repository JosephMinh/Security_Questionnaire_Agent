"""Unit coverage for Chroma index creation, reuse, rebuild, and integrity gating."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import rag


class _FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self.metadata: dict[str, object] = {}
        self._documents_by_id: dict[str, str] = {}
        self._metadatas_by_id: dict[str, dict[str, object]] = {}

    def count(self) -> int:
        return len(self._documents_by_id)

    def get(self, include: list[str] | None = None) -> dict[str, object]:
        ids = list(self._documents_by_id.keys())
        payload: dict[str, object] = {"ids": ids}
        if include and "metadatas" in include:
            payload["metadatas"] = [
                self._metadatas_by_id.get(chunk_id) for chunk_id in ids
            ]
        return payload

    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, object]],
    ) -> None:
        for chunk_id, document, metadata in zip(ids, documents, metadatas, strict=True):
            self._documents_by_id[chunk_id] = document
            self._metadatas_by_id[chunk_id] = dict(metadata)

    def delete(self, *, ids: list[str]) -> None:
        for chunk_id in ids:
            self._documents_by_id.pop(chunk_id, None)
            self._metadatas_by_id.pop(chunk_id, None)

    def modify(self, *, metadata: dict[str, object]) -> None:
        self.metadata = dict(metadata)


class _FakePersistentClient:
    _collections_by_path: dict[str, dict[str, _FakeCollection]] = {}

    def __init__(self, *, path: str):
        self.path = path
        self._collections = self._collections_by_path.setdefault(path, {})

    @classmethod
    def reset(cls) -> None:
        cls._collections_by_path = {}

    def list_collections(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=name) for name in sorted(self._collections)]

    def get_or_create_collection(self, *, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection(name))

    def get_collection(self, *, name: str) -> _FakeCollection:
        return self._collections[name]

    def delete_collection(self, *, name: str) -> None:
        self._collections.pop(name, None)


class RagIndexingTest(unittest.TestCase):
    """Verify the Chroma index lifecycle remains deterministic and safe."""

    def setUp(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.persist_directory = Path(self._temp_dir.name) / "chroma"
        self.workspace_hash = "workspace-hash-v1"
        self._fixture_chunks = (
            self._make_chunk("enc_001", rag.ENCRYPTION_POLICY_FILE_NAME, "Encryption body 1"),
            self._make_chunk("enc_002", rag.ENCRYPTION_POLICY_FILE_NAME, "Encryption body 2"),
            self._make_chunk("acc_001", rag.ACCESS_CONTROL_POLICY_FILE_NAME, "Access body 1"),
        )
        _FakePersistentClient.reset()
        self._patch_stack = ExitStack()
        self._patch_stack.enter_context(
            patch.dict(
                sys.modules,
                {"chromadb": SimpleNamespace(PersistentClient=_FakePersistentClient)},
            )
        )

    def tearDown(self) -> None:
        self._patch_stack.close()
        self._temp_dir.cleanup()

    def test_get_or_create_demo_chroma_collection_reconnects_to_canonical_name(self) -> None:
        first_handle = rag.get_or_create_demo_chroma_collection(self.persist_directory)
        first_handle.collection.modify(metadata={"marker": "persisted"})

        second_handle = rag.get_or_create_demo_chroma_collection(self.persist_directory)

        self.assertEqual(first_handle.collection_name, rag.COLLECTION_NAME)
        self.assertEqual(second_handle.collection_name, rag.COLLECTION_NAME)
        self.assertEqual(second_handle.persist_directory, self.persist_directory.resolve())
        self.assertEqual(second_handle.collection.metadata, {"marker": "persisted"})

    def test_persist_curated_evidence_chunks_records_workspace_state_and_replaces_stale_entries(
        self,
    ) -> None:
        with patch.object(
            rag, "build_curated_evidence_chunks", return_value=self._fixture_chunks
        ), patch.object(rag, "current_workspace_hash", return_value=self.workspace_hash):
            handle = rag.get_or_create_demo_chroma_collection(self.persist_directory)
            handle.collection.upsert(
                ids=["stale_001"],
                documents=["stale"],
                metadatas=[
                    {
                        "chunk_id": "stale_001",
                        "source": rag.ENCRYPTION_POLICY_FILE_NAME,
                        "doc_type": rag.DOCUMENT_TYPE_POLICY,
                    }
                ],
            )

            persisted_chunks = rag.persist_curated_evidence_chunks(
                persist_directory=self.persist_directory
            )

        collection_payload = handle.collection.get(include=["metadatas"])
        self.assertEqual(persisted_chunks, self._fixture_chunks)
        self.assertEqual(
            collection_payload["ids"],
            ["enc_001", "enc_002", "acc_001"],
        )
        self.assertEqual(
            handle.collection.metadata,
            {
                "workspace_hash": self.workspace_hash,
                "chunk_count": len(self._fixture_chunks),
            },
        )

    def test_ensure_curated_evidence_index_creates_then_reuses_when_manifest_matches(self) -> None:
        with patch.object(
            rag, "build_curated_evidence_chunks", return_value=self._fixture_chunks
        ), patch.object(rag, "current_workspace_hash", return_value=self.workspace_hash):
            created_status = rag.ensure_curated_evidence_index(
                persist_directory=self.persist_directory
            )
            reused_status = rag.ensure_curated_evidence_index(
                persist_directory=self.persist_directory
            )

        self.assertTrue(created_status.ready)
        self.assertEqual(created_status.index_action, rag.INDEX_ACTION_CREATED)
        self.assertEqual(created_status.reason, "created")
        self.assertTrue(reused_status.ready)
        self.assertEqual(reused_status.index_action, rag.INDEX_ACTION_REUSED)
        self.assertEqual(reused_status.reason, "reused")

    def test_ensure_curated_evidence_index_rebuilds_when_workspace_hash_changes(self) -> None:
        with patch.object(
            rag, "build_curated_evidence_chunks", return_value=self._fixture_chunks
        ):
            with patch.object(rag, "current_workspace_hash", return_value="hash-v1"):
                initial_status = rag.ensure_curated_evidence_index(
                    persist_directory=self.persist_directory
                )

            existing_handle = rag.get_existing_chroma_collection(
                persist_directory=self.persist_directory
            )
            self.assertIsNotNone(existing_handle)
            assert existing_handle is not None
            existing_handle.collection.modify(
                metadata={
                    "workspace_hash": "hash-v1",
                    "chunk_count": len(self._fixture_chunks),
                    "stale_marker": "old-state",
                }
            )

            with patch.object(rag, "current_workspace_hash", return_value="hash-v2"):
                rebuilt_status = rag.ensure_curated_evidence_index(
                    persist_directory=self.persist_directory
                )

        rebuilt_handle = rag.get_existing_chroma_collection(
            persist_directory=self.persist_directory
        )
        self.assertTrue(initial_status.ready)
        self.assertTrue(rebuilt_status.ready)
        self.assertEqual(
            rebuilt_status.index_action, rag.INDEX_ACTION_REBUILT_CONTENT_CHANGE
        )
        self.assertEqual(rebuilt_status.reason, "workspace_hash_changed")
        self.assertIsNotNone(rebuilt_handle)
        assert rebuilt_handle is not None
        self.assertEqual(
            rebuilt_handle.collection.metadata,
            {"workspace_hash": "hash-v2", "chunk_count": len(self._fixture_chunks)},
        )

    def test_ensure_curated_evidence_index_force_rebuild_recreates_even_when_hash_matches(
        self,
    ) -> None:
        with patch.object(
            rag, "build_curated_evidence_chunks", return_value=self._fixture_chunks
        ), patch.object(rag, "current_workspace_hash", return_value=self.workspace_hash):
            rag.ensure_curated_evidence_index(persist_directory=self.persist_directory)
            existing_handle = rag.get_existing_chroma_collection(
                persist_directory=self.persist_directory
            )
            self.assertIsNotNone(existing_handle)
            assert existing_handle is not None
            existing_handle.collection.modify(
                metadata={
                    "workspace_hash": self.workspace_hash,
                    "chunk_count": len(self._fixture_chunks),
                    "stale_marker": "old-state",
                }
            )

            rebuilt_status = rag.ensure_curated_evidence_index(
                persist_directory=self.persist_directory,
                force_rebuild=True,
            )

        rebuilt_handle = rag.get_existing_chroma_collection(
            persist_directory=self.persist_directory
        )
        self.assertTrue(rebuilt_status.ready)
        self.assertEqual(
            rebuilt_status.index_action, rag.INDEX_ACTION_REBUILT_CONTENT_CHANGE
        )
        self.assertEqual(rebuilt_status.reason, "force_rebuild")
        self.assertIsNotNone(rebuilt_handle)
        assert rebuilt_handle is not None
        self.assertEqual(
            rebuilt_handle.collection.metadata,
            {
                "workspace_hash": self.workspace_hash,
                "chunk_count": len(self._fixture_chunks),
            },
        )

    def test_evaluate_chroma_reuse_rejects_empty_partial_and_duplicate_states(self) -> None:
        with patch.object(
            rag, "build_curated_evidence_chunks", return_value=self._fixture_chunks
        ), patch.object(rag, "current_workspace_hash", return_value=self.workspace_hash):
            rag.ensure_curated_evidence_index(persist_directory=self.persist_directory)
            handle = rag.get_existing_chroma_collection(
                persist_directory=self.persist_directory
            )
            self.assertIsNotNone(handle)
            assert handle is not None

            with self.subTest(reason="collection_empty"):
                handle.collection.delete(ids=list(handle.collection.get()["ids"]))
                empty_status = rag.evaluate_chroma_reuse(
                    persist_directory=self.persist_directory
                )
                self.assertFalse(empty_status.reusable)
                self.assertEqual(empty_status.reason, "collection_empty")

            rag.ensure_curated_evidence_index(
                persist_directory=self.persist_directory,
                force_rebuild=True,
            )
            handle = rag.get_existing_chroma_collection(
                persist_directory=self.persist_directory
            )
            self.assertIsNotNone(handle)
            assert handle is not None

            with self.subTest(reason="chunk_count_mismatch"):
                payload = handle.collection.get()
                handle.collection.delete(ids=[payload["ids"][-1]])
                partial_status = rag.evaluate_chroma_reuse(
                    persist_directory=self.persist_directory
                )
                self.assertFalse(partial_status.reusable)
                self.assertEqual(partial_status.reason, "chunk_count_mismatch")

            rag.ensure_curated_evidence_index(
                persist_directory=self.persist_directory,
                force_rebuild=True,
            )
            handle = rag.get_existing_chroma_collection(
                persist_directory=self.persist_directory
            )
            self.assertIsNotNone(handle)
            assert handle is not None

            with self.subTest(reason="duplicate_logical_chunk_ids"):
                payload = handle.collection.get(include=["metadatas"])
                metadatas = payload["metadatas"]
                self.assertIsInstance(metadatas, list)
                metadatas[1]["chunk_id"] = metadatas[0]["chunk_id"]
                duplicate_status = rag.evaluate_chroma_reuse(
                    persist_directory=self.persist_directory
                )
                self.assertFalse(duplicate_status.reusable)
                self.assertEqual(duplicate_status.reason, "duplicate_logical_chunk_ids")

    @staticmethod
    def _make_chunk(chunk_id: str, source: str, text: str) -> rag.EvidenceChunk:
        suffix = chunk_id.rsplit("_", 1)[-1]
        chunk_number = int(suffix)
        return rag.EvidenceChunk(
            chunk_id=chunk_id,
            source=source,
            source_path=Path(source),
            doc_type=rag.DOCUMENT_TYPE_POLICY,
            text=text,
            chunk_number=chunk_number,
            start_offset=(chunk_number - 1) * 10,
            end_offset=(chunk_number - 1) * 10 + len(text),
            section=f"Section {chunk_number}",
            page=None,
        )


if __name__ == "__main__":
    unittest.main()
