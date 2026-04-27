"""Unit coverage for evidence loading, chunking, and index lifecycle decisions."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import rag


class _FakePdfPage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakePdfReader:
    def __init__(self, _path: str):
        self.pages = [
            _FakePdfPage("SOC 2 summary page one."),
            _FakePdfPage("   "),
            _FakePdfPage("SOC 2 summary page three."),
        ]


class RagIngestionTest(unittest.TestCase):
    """Verify the curated ingestion and indexing helpers stay deterministic."""

    def _sample_evidence_chunks(self) -> tuple[rag.EvidenceChunk, ...]:
        """Return one compact deterministic chunk set for index lifecycle tests."""
        return (
            rag.EvidenceChunk(
                chunk_id="enc_001",
                source=rag.ENCRYPTION_POLICY_FILE_NAME,
                source_path=Path(rag.ENCRYPTION_POLICY_FILE_NAME),
                doc_type=rag.DOCUMENT_TYPE_POLICY,
                text="Encryption policy chunk.",
                chunk_number=1,
                start_offset=0,
                end_offset=24,
                section="Encryption Policy",
                page=None,
            ),
            rag.EvidenceChunk(
                chunk_id="acc_001",
                source=rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                source_path=Path(rag.ACCESS_CONTROL_POLICY_FILE_NAME),
                doc_type=rag.DOCUMENT_TYPE_POLICY,
                text="Access control chunk.",
                chunk_number=1,
                start_offset=0,
                end_offset=21,
                section="Access Control Policy",
                page=None,
            ),
            rag.EvidenceChunk(
                chunk_id="soc2_001",
                source=rag.SOC2_SUMMARY_FILE_NAME,
                source_path=Path(rag.SOC2_SUMMARY_FILE_NAME),
                doc_type=rag.DOCUMENT_TYPE_PDF,
                text="SOC 2 summary chunk.",
                chunk_number=1,
                start_offset=0,
                end_offset=20,
                section=None,
                page=1,
            ),
        )

    def _assert_collection_matches_expected(
        self,
        status: rag.ChromaIndexStatus,
        *,
        expected_chunks: tuple[rag.EvidenceChunk, ...],
        expected_workspace_hash: str,
    ) -> None:
        """Assert one ready status points at the expected current collection state."""
        self.assertTrue(status.ready)
        self.assertIsNotNone(status.collection_handle)

        collection_handle = status.collection_handle
        assert collection_handle is not None
        payload = collection_handle.collection.get(include=["metadatas"])

        self.assertEqual(status.actual_chunk_count, len(expected_chunks))
        self.assertEqual(
            collection_handle.collection.metadata,
            {
                "workspace_hash": expected_workspace_hash,
                "chunk_count": len(expected_chunks),
            },
        )
        self.assertEqual(
            set(payload["ids"]),
            {str(chunk.chunk_id) for chunk in expected_chunks},
        )
        self.assertEqual(
            {
                metadata["source"]
                for metadata in payload["metadatas"]
                if isinstance(metadata, dict)
            },
            {chunk.source for chunk in expected_chunks},
        )

    def test_load_text_evidence_document_reads_supported_text_formats(self):
        """Markdown and plain-text evidence should load into the shared document shape."""
        with TemporaryDirectory() as tmp_dir_name:
            temp_root = Path(tmp_dir_name)
            cases = {
                "policy.md": rag.DOCUMENT_TYPE_MARKDOWN,
                "notes.txt": rag.DOCUMENT_TYPE_TEXT,
            }
            for file_name, expected_doc_type in cases.items():
                with self.subTest(file_name=file_name):
                    source_path = temp_root / file_name
                    source_path.write_text("Line one.\nLine two.\n", encoding="utf-8")

                    document = rag.load_text_evidence_document(source_path)

                    self.assertEqual(document.source_file_name, file_name)
                    self.assertEqual(document.source_path, source_path)
                    self.assertEqual(document.doc_type, expected_doc_type)
                    self.assertEqual(document.text, "Line one.\nLine two.\n")
                    self.assertIsNone(document.page_number)

    def test_load_pdf_evidence_pages_uses_page_text_and_page_numbers(self):
        """The PDF loader should keep non-blank page text and preserve page numbers."""
        fake_pypdf_module = SimpleNamespace(PdfReader=_FakePdfReader)
        with patch.dict(sys.modules, {"pypdf": fake_pypdf_module}):
            page_documents = rag.load_pdf_evidence_pages(Path("AcmeCloud_SOC2_Summary.pdf"))

        self.assertEqual(len(page_documents), 2)
        self.assertEqual(
            [document.source_file_name for document in page_documents],
            ["AcmeCloud_SOC2_Summary.pdf", "AcmeCloud_SOC2_Summary.pdf"],
        )
        self.assertEqual(
            [document.doc_type for document in page_documents],
            [rag.DOCUMENT_TYPE_PDF, rag.DOCUMENT_TYPE_PDF],
        )
        self.assertEqual([document.page_number for document in page_documents], [1, 3])
        self.assertEqual(
            [document.text for document in page_documents],
            ["SOC 2 summary page one.", "SOC 2 summary page three."],
        )

    def test_normalize_evidence_text_is_stable_and_idempotent(self):
        """Normalization should standardize line endings, spaces, and blank lines once."""
        raw_text = "Heading\r\n\r\nBody line   \r\n\r\n\r\n# Section\rTrailing space   \n"
        expected_text = "Heading\n\nBody line\n\n# Section\nTrailing space"

        normalized_text = rag.normalize_evidence_text(raw_text)

        self.assertEqual(normalized_text, expected_text)
        self.assertEqual(rag.normalize_evidence_text(normalized_text), expected_text)

    def test_chunk_evidence_document_uses_fixed_boundaries_and_overlap(self):
        """One normalized document should chunk with the planned 700/100 contract."""
        document = rag.EvidenceDocument(
            source_file_name=rag.ENCRYPTION_POLICY_FILE_NAME,
            source_path=Path(rag.ENCRYPTION_POLICY_FILE_NAME),
            doc_type=rag.DOCUMENT_TYPE_MARKDOWN,
            text=("A" * 750) + ("B" * 200),
        )

        chunks = rag.chunk_evidence_document(document)

        self.assertEqual(len(chunks), 2)
        self.assertEqual([len(chunk.text) for chunk in chunks], [700, 350])
        self.assertEqual(
            [(chunk.start_offset, chunk.end_offset) for chunk in chunks],
            [(0, 700), (600, 950)],
        )
        self.assertEqual(
            chunks[0].text[-rag.CHUNK_OVERLAP_CHARS :],
            chunks[1].text[: rag.CHUNK_OVERLAP_CHARS],
        )
        self.assertEqual([chunk.chunk_id for chunk in chunks], [None, None])

    def test_chunk_evidence_documents_assigns_stable_ids_and_metadata(self):
        """Final chunk assembly should assign stable source-level IDs and metadata fields."""
        encryption_document = rag.EvidenceDocument(
            source_file_name=rag.ENCRYPTION_POLICY_FILE_NAME,
            source_path=Path(rag.ENCRYPTION_POLICY_FILE_NAME),
            doc_type=rag.DOCUMENT_TYPE_MARKDOWN,
            text=("A" * 750) + ("B" * 200),
        )
        pdf_page_one = rag.EvidenceDocument(
            source_file_name=rag.SOC2_SUMMARY_FILE_NAME,
            source_path=Path(rag.SOC2_SUMMARY_FILE_NAME),
            doc_type=rag.DOCUMENT_TYPE_PDF,
            text="First SOC 2 page.",
            page_number=1,
        )
        pdf_page_two = rag.EvidenceDocument(
            source_file_name=rag.SOC2_SUMMARY_FILE_NAME,
            source_path=Path(rag.SOC2_SUMMARY_FILE_NAME),
            doc_type=rag.DOCUMENT_TYPE_PDF,
            text="Second SOC 2 page.",
            page_number=2,
        )

        chunks = rag.chunk_evidence_documents(
            (encryption_document, pdf_page_one, pdf_page_two)
        )

        self.assertEqual(
            [chunk.chunk_id for chunk in chunks],
            ["enc_001", "enc_002", "soc2_001", "soc2_002"],
        )
        self.assertEqual(
            [chunk.doc_type for chunk in chunks],
            [
                rag.DOCUMENT_TYPE_POLICY,
                rag.DOCUMENT_TYPE_POLICY,
                rag.DOCUMENT_TYPE_PDF,
                rag.DOCUMENT_TYPE_PDF,
            ],
        )
        self.assertEqual([chunk.page for chunk in chunks], [None, None, 1, 2])
        self.assertEqual(
            chunks[-1].metadata(),
            {
                "chunk_id": "soc2_002",
                "source": rag.SOC2_SUMMARY_FILE_NAME,
                "doc_type": rag.DOCUMENT_TYPE_PDF,
                "section": None,
                "page": 2,
            },
        )

    def test_chunk_evidence_documents_derives_sections_and_clean_fallback_labels(self):
        """Heading-aware sections should be captured, and fallback labels should stay readable."""
        heading_document = rag.EvidenceDocument(
            source_file_name=rag.ACCESS_CONTROL_POLICY_FILE_NAME,
            source_path=Path(rag.ACCESS_CONTROL_POLICY_FILE_NAME),
            doc_type=rag.DOCUMENT_TYPE_MARKDOWN,
            text="\n".join(
                (
                    "# Access Control Policy",
                    "",
                    "Introductory policy summary.",
                    "",
                    "## Access Reviews",
                    "",
                    ("Review narrative. " * 60).strip(),
                )
            ),
        )
        fallback_document = rag.EvidenceDocument(
            source_file_name=rag.ENCRYPTION_POLICY_FILE_NAME,
            source_path=Path(rag.ENCRYPTION_POLICY_FILE_NAME),
            doc_type=rag.DOCUMENT_TYPE_MARKDOWN,
            text=("Plain body text without markdown heading. " * 30).strip(),
        )

        chunks = rag.chunk_evidence_documents((heading_document, fallback_document))

        self.assertEqual(chunks[0].section, "Access Control Policy")
        self.assertEqual(chunks[1].section, "Access Reviews")
        self.assertEqual(chunks[-1].section, "Encryption Policy")
        self.assertEqual(
            rag.build_citation_display_label(
                chunks[-1].source,
                chunks[-1].section,
                chunks[-1].page,
            ),
            "Encryption Policy",
        )

    def test_ensure_curated_evidence_index_covers_create_reuse_and_rebuild_paths(self):
        """Create, reuse, force-rebuild, and hash-change flows should stay explicit."""
        expected_chunks = self._sample_evidence_chunks()
        with TemporaryDirectory() as tmp_dir_name:
            persist_directory = Path(tmp_dir_name) / "chroma"
            with patch.object(
                rag,
                "build_curated_evidence_chunks",
                return_value=expected_chunks,
            ), patch.object(rag, "current_workspace_hash", return_value="hash-a"):
                created = rag.ensure_curated_evidence_index(
                    persist_directory=persist_directory
                )
                self.assertEqual(created.index_action, rag.INDEX_ACTION_CREATED)
                self.assertEqual(created.reason, "created")
                self._assert_collection_matches_expected(
                    created,
                    expected_chunks=expected_chunks,
                    expected_workspace_hash="hash-a",
                )

                reused = rag.ensure_curated_evidence_index(
                    persist_directory=persist_directory
                )
                self.assertEqual(reused.index_action, rag.INDEX_ACTION_REUSED)
                self.assertEqual(reused.reason, "reused")
                self._assert_collection_matches_expected(
                    reused,
                    expected_chunks=expected_chunks,
                    expected_workspace_hash="hash-a",
                )

                forced = rag.ensure_curated_evidence_index(
                    persist_directory=persist_directory,
                    force_rebuild=True,
                )
                self.assertEqual(forced.index_action, rag.INDEX_ACTION_REBUILT_CONTENT_CHANGE)
                self.assertEqual(forced.reason, "force_rebuild")
                self._assert_collection_matches_expected(
                    forced,
                    expected_chunks=expected_chunks,
                    expected_workspace_hash="hash-a",
                )

            with patch.object(
                rag,
                "build_curated_evidence_chunks",
                return_value=expected_chunks,
            ), patch.object(rag, "current_workspace_hash", return_value="hash-b"):
                changed = rag.ensure_curated_evidence_index(
                    persist_directory=persist_directory
                )
            self.assertEqual(changed.index_action, rag.INDEX_ACTION_REBUILT_CONTENT_CHANGE)
            self.assertEqual(changed.reason, "workspace_hash_changed")
            self._assert_collection_matches_expected(
                changed,
                expected_chunks=expected_chunks,
                expected_workspace_hash="hash-b",
            )

    def test_ensure_curated_evidence_index_rebuilds_integrity_failures(self):
        """Empty, partial, duplicated, and source-mismatched collections should rebuild."""
        expected_chunks = self._sample_evidence_chunks()
        scenarios = (
            (
                "collection_empty",
                lambda handle: handle.collection.delete(ids=handle.collection.get()["ids"]),
            ),
            (
                "duplicate_logical_chunk_ids",
                lambda handle: handle.collection.upsert(
                    ids=["enc_001"],
                    documents=["duplicate logical chunk id"],
                    metadatas=[
                        {
                            "chunk_id": "acc_001",
                            "source": rag.ENCRYPTION_POLICY_FILE_NAME,
                            "doc_type": rag.DOCUMENT_TYPE_POLICY,
                            "section": "Encryption Policy",
                        }
                    ],
                ),
            ),
            (
                "collection_payload_mismatch",
                lambda handle: (
                    handle.collection.delete(ids=["enc_001"]),
                    handle.collection.upsert(
                        ids=["rogue_001"],
                        documents=["rogue chunk"],
                        metadatas=[
                            {
                                "chunk_id": "rogue_001",
                                "source": rag.ENCRYPTION_POLICY_FILE_NAME,
                                "doc_type": rag.DOCUMENT_TYPE_POLICY,
                                "section": "Encryption Policy",
                            }
                        ],
                    ),
                ),
            ),
            (
                "source_coverage_mismatch",
                lambda handle: handle.collection.upsert(
                    ids=["enc_001"],
                    documents=["source coverage swap"],
                    metadatas=[
                        {
                            "chunk_id": "enc_001",
                            "source": rag.ACCESS_CONTROL_POLICY_FILE_NAME,
                            "doc_type": rag.DOCUMENT_TYPE_POLICY,
                            "section": "Encryption Policy",
                        }
                    ],
                ),
            ),
        )

        for expected_reason, mutate_collection in scenarios:
            with self.subTest(reason=expected_reason):
                with TemporaryDirectory() as tmp_dir_name:
                    persist_directory = Path(tmp_dir_name) / "chroma"
                    with patch.object(
                        rag,
                        "build_curated_evidence_chunks",
                        return_value=expected_chunks,
                    ), patch.object(rag, "current_workspace_hash", return_value="hash-a"):
                        baseline = rag.ensure_curated_evidence_index(
                            persist_directory=persist_directory
                        )
                        baseline_handle = baseline.collection_handle
                        assert baseline_handle is not None
                        mutate_collection(baseline_handle)

                        blocked_reuse = rag.evaluate_chroma_reuse(
                            persist_directory=persist_directory
                        )
                        rebuilt = rag.ensure_curated_evidence_index(
                            persist_directory=persist_directory
                        )

                        self.assertFalse(blocked_reuse.reusable)
                        self.assertEqual(blocked_reuse.reason, expected_reason)
                        self.assertEqual(
                            rebuilt.index_action,
                            rag.INDEX_ACTION_REBUILT_INTEGRITY,
                        )
                        self.assertEqual(rebuilt.reason, expected_reason)
                        self._assert_collection_matches_expected(
                            rebuilt,
                            expected_chunks=expected_chunks,
                            expected_workspace_hash="hash-a",
                        )

    def test_ensure_curated_evidence_index_blocks_unrebuildable_state(self):
        """Manifest or expected-chunk failures should stay blocked instead of rebuilding."""
        expected_chunks = self._sample_evidence_chunks()
        with TemporaryDirectory() as tmp_dir_name:
            persist_directory = Path(tmp_dir_name) / "chroma"
            with patch.object(
                rag,
                "build_curated_evidence_chunks",
                return_value=expected_chunks,
            ), patch.object(rag, "current_workspace_hash", return_value="hash-a"):
                rag.ensure_curated_evidence_index(persist_directory=persist_directory)

            with patch.object(
                rag,
                "build_curated_evidence_chunks",
                return_value=expected_chunks,
            ), patch.object(
                rag,
                "current_workspace_hash",
                side_effect=FileNotFoundError("workspace manifest missing"),
            ):
                manifest_blocked = rag.ensure_curated_evidence_index(
                    persist_directory=persist_directory
                )

            with patch.object(
                rag,
                "build_curated_evidence_chunks",
                side_effect=FileNotFoundError("expected chunks missing"),
            ), patch.object(rag, "current_workspace_hash", return_value="hash-a"):
                chunk_blocked = rag.ensure_curated_evidence_index(
                    persist_directory=persist_directory
                )

        self.assertFalse(manifest_blocked.ready)
        self.assertEqual(manifest_blocked.index_action, rag.INDEX_ACTION_BLOCKED)
        self.assertEqual(manifest_blocked.reason, "manifest_unavailable")

        self.assertFalse(chunk_blocked.ready)
        self.assertEqual(chunk_blocked.index_action, rag.INDEX_ACTION_BLOCKED)
        self.assertEqual(chunk_blocked.reason, "expected_chunks_unavailable")


if __name__ == "__main__":
    unittest.main()
