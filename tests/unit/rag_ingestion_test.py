"""Unit coverage for evidence loading, normalization, chunking, and labels."""

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
    """Verify the curated ingestion helpers stay deterministic and readable."""

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


if __name__ == "__main__":
    unittest.main()
