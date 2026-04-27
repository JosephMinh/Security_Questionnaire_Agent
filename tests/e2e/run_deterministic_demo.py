#!/usr/bin/env python3
"""Deterministic e2e checks for the full curated golden-path demo workflow."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
import shutil
import sys
from typing import Final
from unittest.mock import patch

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from streamlit.testing.v1 import AppTest

import app
from generate_demo_data import (
    WorkspaceValidationError,
    expected_runtime_evidence_paths,
    prepare_demo_workspace,
    validate_runtime_workspace,
)
import rag

logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(
    logging.ERROR
)


SCRIPT_NAME: Final[str] = "run_deterministic_demo"
LOG_FILE_NAME: Final[str] = f"{SCRIPT_NAME}.jsonl"
SUITE_RUN_ID: Final[str] = "deterministic-demo-e2e"
RUN_ID: Final[str] = "deterministic-demo-run-001"
COMPLETED_AT: Final[str] = "2026-04-27T23:10:00Z"

ANSWER_TYPE_SCORES: Final[dict[str, tuple[float, str]]] = {
    rag.ANSWER_TYPE_SUPPORTED: (
        rag.SUPPORTED_WITH_ONE_CITATION_SCORE,
        rag.CONFIDENCE_BAND_MEDIUM,
    ),
    rag.ANSWER_TYPE_PARTIAL: (rag.PARTIAL_SCORE, rag.CONFIDENCE_BAND_LOW),
    rag.ANSWER_TYPE_UNSUPPORTED: (rag.UNSUPPORTED_SCORE, rag.CONFIDENCE_BAND_LOW),
}

SOURCE_TITLE_OVERRIDES: Final[dict[str, str]] = {
    rag.ENCRYPTION_POLICY_FILE_NAME: "Encryption Policy",
    rag.ACCESS_CONTROL_POLICY_FILE_NAME: "Access Control Policy",
    rag.INCIDENT_RESPONSE_POLICY_FILE_NAME: "Incident Response Policy",
    rag.BACKUP_RECOVERY_POLICY_FILE_NAME: "Backup and Recovery Policy",
    rag.SOC2_SUMMARY_FILE_NAME: "AcmeCloud SOC 2 Summary",
}


def _run_app_main() -> None:
    """Run the Streamlit entrypoint through AppTest's function wrapper."""
    import app as app_module

    app_module.main()


def _button_by_label(at: AppTest, label: str):
    return next(button for button in at.button if button.label == label)


def _widget_values(widgets: list[object]) -> list[str]:
    return [str(widget.value) for widget in widgets]


def _markdown_values(at: AppTest) -> list[str]:
    return _widget_values(at.markdown)


def _caption_values(at: AppTest) -> list[str]:
    return _widget_values(at.caption)


def _success_values(at: AppTest) -> list[str]:
    return _widget_values(at.success)


def _info_values(at: AppTest) -> list[str]:
    return _widget_values(getattr(at, "info", []))


def _contains_text(values: list[str], expected_substring: str) -> bool:
    return any(expected_substring in value for value in values)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _deterministic_backup_dir(output_dir: Path) -> Path:
    """Return the one stable backup dir name used by the deterministic publish path."""
    return output_dir.parent / (
        f".{output_dir.name}-backup-"
        f"{rag._safe_filesystem_token(RUN_ID)}-"
        f"{rag._safe_filesystem_token(COMPLETED_AT)}"
    )


def _clear_stale_publish_artifacts(output_dir: Path) -> tuple[Path, ...]:
    """Remove stale deterministic backup/staging dirs so the verifier stays rerunnable."""
    removed_paths: list[Path] = []

    backup_dir = _deterministic_backup_dir(output_dir)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
        removed_paths.append(backup_dir)

    staging_pattern = (
        f".{output_dir.name}-staging-{rag._safe_filesystem_token(RUN_ID)}-*"
    )
    for staging_dir in sorted(output_dir.parent.glob(staging_pattern)):
        if staging_dir.is_dir():
            shutil.rmtree(staging_dir)
            removed_paths.append(staging_dir)

    return tuple(removed_paths)


class JsonlLogSink:
    """Collect and persist machine-readable verification events."""

    def __init__(self, *, log_path: Path, verbose: bool) -> None:
        self._log_path = log_path
        self._verbose = verbose
        self._records: list[dict[str, object]] = []

    def emit(
        self,
        *,
        event: str,
        status: str,
        message: str,
        level: str = "INFO",
        run_id: str = SUITE_RUN_ID,
        question_id: str | None = None,
        workspace_hash: str | None = None,
        index_action: str | None = None,
        valid_citation_count: int | None = None,
        answer_type: str | None = None,
        confidence_band: str | None = None,
        review_status: str | None = None,
        artifact_path: str | Path | None = None,
        reason: str | None = None,
    ) -> None:
        record = rag.build_structured_log_record(
            component=rag.LOG_COMPONENT_VERIFICATION,
            event=event,
            run_id=run_id,
            status=status,
            message=message,
            level=level,
            question_id=question_id,
            workspace_hash=workspace_hash,
            index_action=index_action,
            valid_citation_count=valid_citation_count,
            answer_type=answer_type,
            confidence_band=confidence_band,
            review_status=review_status,
            artifact_path=artifact_path,
            reason=reason,
        )
        self._records.append(record)
        if self._verbose:
            print(json.dumps(record, sort_keys=True))

    def flush(self) -> Path:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("w", encoding="utf-8") as handle:
            for record in self._records:
                handle.write(json.dumps(record, sort_keys=True))
                handle.write("\n")
        return self._log_path


def _load_expected_fixture() -> dict[str, object]:
    fixture_path = rag.SEED_QUESTIONNAIRE_DIR / "Demo_Security_Questionnaire.expected.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _ensure_workspace_ready(
    log_sink: JsonlLogSink,
) -> tuple[rag.RuntimeQuestionnaire, str, int]:
    """Reuse the existing curated workspace or restore it from seed data if needed."""
    try:
        validate_runtime_workspace()
        prepared = False
    except WorkspaceValidationError:
        prepare_demo_workspace(reset_index=False)
        validate_runtime_workspace()
        prepared = True

    questionnaire = rag.load_runtime_questionnaire()
    workspace_hash = rag.current_workspace_hash()
    evidence_count = len(expected_runtime_evidence_paths())
    log_sink.emit(
        event="workspace_ready",
        status=rag.LOG_STATUS_COMPLETED,
        message=(
            "Prepared the curated runtime workspace from seed data."
            if prepared
            else "Validated and reused the existing curated runtime workspace."
        ),
        run_id=RUN_ID,
        workspace_hash=workspace_hash,
        index_action=rag.INDEX_ACTION_REUSED,
        artifact_path=questionnaire.workbook_path,
        reason="prepared_from_seed" if prepared else "reused_runtime_workspace",
    )
    return questionnaire, workspace_hash, evidence_count


def _ready_snapshot(*, workspace_hash: str, evidence_count: int) -> app.WorkspaceSnapshot:
    """Return one stable healthy snapshot for the deterministic happy path."""
    return app.WorkspaceSnapshot(
        questionnaire_exists=True,
        manifest_exists=True,
        evidence_present_count=evidence_count,
        evidence_total_count=evidence_count,
        validation_ok=True,
        validation_lines=(),
        workspace_hash=workspace_hash,
        index_ready=True,
        index_action=rag.INDEX_ACTION_REUSED,
        index_reason="reused",
        actual_chunk_count=evidence_count,
        stored_chunk_count=evidence_count,
        stored_workspace_hash=workspace_hash,
    )


def _ready_index_status(
    *,
    workspace_hash: str,
    evidence_count: int,
) -> rag.ChromaIndexStatus:
    """Return one stable ready index status for deterministic app runs."""
    return rag.ChromaIndexStatus(
        collection_name=rag.COLLECTION_NAME,
        persist_directory=rag.CHROMA_DIR,
        workspace_hash=workspace_hash,
        stored_workspace_hash=workspace_hash,
        stored_chunk_count=evidence_count,
        actual_chunk_count=evidence_count,
        index_action=rag.INDEX_ACTION_REUSED,
        ready=True,
        reason="reused",
        collection_handle=None,
    )


def _source_title(source_name: str) -> str:
    return SOURCE_TITLE_OVERRIDES.get(source_name, Path(source_name).stem.replace("_", " "))


def _markdown_section_snippet(source_path: Path, section_title: str) -> str:
    """Return the literal paragraph text beneath one markdown section heading."""
    lines = source_path.read_text(encoding="utf-8").splitlines()
    in_section = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            if in_section and heading != section_title:
                break
            in_section = heading == section_title
            continue
        if in_section and stripped:
            collected.append(stripped)
    if not collected:
        raise AssertionError(
            f"Section {section_title!r} was not found in markdown evidence {source_path.name}."
        )
    return " ".join(collected)


def _pdf_page_snippet(source_path: Path, anchor_hint: str) -> tuple[int, str]:
    """Return the literal page text that contains the expected anchor hint."""
    for page_document in rag.load_pdf_evidence_pages(source_path):
        normalized_text = " ".join(
            line.strip() for line in page_document.text.splitlines() if line.strip()
        )
        if anchor_hint.lower() in normalized_text.lower():
            if page_document.page_number is None:
                raise AssertionError(f"Expected a page number for PDF evidence {source_path.name}.")
            return page_document.page_number, normalized_text
    raise AssertionError(
        f"Anchor {anchor_hint!r} was not found in PDF evidence {source_path.name}."
    )


def _citation_for_expected(question: dict[str, object]) -> tuple[rag.ResolvedEvidenceCitation, ...]:
    """Build the deterministic primary-source citation promised by the expected fixture."""
    primary_source = question.get("primary_source")
    anchor_hint = question.get("anchor_hint")
    if not isinstance(primary_source, str) or not primary_source:
        return ()
    if not isinstance(anchor_hint, str) or not anchor_hint:
        raise AssertionError(
            f"Question {question['question_id']} expected a primary source but has no anchor hint."
        )

    source_path = rag.RUNTIME_EVIDENCE_DIR / primary_source
    if primary_source.endswith(".md"):
        snippet_text = _markdown_section_snippet(source_path, anchor_hint)
        return (
            rag.ResolvedEvidenceCitation(
                chunk_id=f"{str(question['question_id']).lower()}-primary",
                display_label=f"{_source_title(primary_source)} - {anchor_hint}",
                snippet_text=snippet_text,
                source=primary_source,
                source_path=source_path,
                doc_type=rag.DOCUMENT_TYPE_MARKDOWN,
                section=anchor_hint,
            ),
        )

    page_number, snippet_text = _pdf_page_snippet(source_path, anchor_hint)
    return (
        rag.ResolvedEvidenceCitation(
            chunk_id=f"{str(question['question_id']).lower()}-primary",
            display_label=f"{_source_title(primary_source)} - Page {page_number}",
            snippet_text=snippet_text,
            source=primary_source,
            source_path=source_path,
            doc_type=rag.DOCUMENT_TYPE_PDF,
            page=page_number,
        ),
    )


def _answer_result_for_expected(question: dict[str, object]) -> rag.GeneratedAnswerResult:
    """Convert one expected-fixture row into the deterministic answer contract."""
    answer_type = str(question["expected_answer_type"])
    if answer_type not in ANSWER_TYPE_SCORES:
        raise AssertionError(f"Unsupported expected answer type {answer_type!r}.")

    confidence_score, confidence_band = ANSWER_TYPE_SCORES[answer_type]
    citations = _citation_for_expected(question)
    status = str(question["expected_status"])
    reviewer_note = (
        str(question["rationale"])
        if status == rag.STATUS_NEEDS_REVIEW
        else ""
    )
    answer = f"{question['expected_opening_token']} {question['rationale']}"
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


def _question_by_id(
    questions: tuple[dict[str, object], ...],
) -> dict[str, dict[str, object]]:
    return {str(question["question_id"]): question for question in questions}


def _review_queue_expected_ids(questionnaire: rag.RuntimeQuestionnaire) -> list[str]:
    queue_rows = [
        row
        for row in questionnaire.rows
        if str(row["status"]) == rag.STATUS_NEEDS_REVIEW
        or float(row["confidence_score"]) < rag.REVIEW_QUEUE_THRESHOLD
    ]
    return [
        str(row["Question ID"])
        for row in sorted(
            queue_rows,
            key=lambda row: (float(row["confidence_score"]), str(row["Question ID"])),
        )
    ]


def _validate_completed_questionnaire(
    completed_questionnaire: rag.RuntimeQuestionnaire,
    *,
    expected_fixture: dict[str, object],
    log_sink: JsonlLogSink,
    workspace_hash: str,
) -> None:
    """Assert the completed questionnaire matches the full canonical fixture."""
    expected_questions = tuple(expected_fixture["questions"])
    expected_by_id = _question_by_id(expected_questions)
    _require(
        len(completed_questionnaire.rows) == int(expected_fixture["question_count"]),
        "Completed questionnaire row count does not match the expected 22-question fixture.",
    )
    _require(
        completed_questionnaire.question_ids()
        == tuple(str(question["question_id"]) for question in expected_questions),
        "Completed questionnaire question order drifted from the curated workbook order.",
    )

    answer_type_counts: dict[str, int] = {
        rag.ANSWER_TYPE_SUPPORTED: 0,
        rag.ANSWER_TYPE_PARTIAL: 0,
        rag.ANSWER_TYPE_UNSUPPORTED: 0,
    }
    for row in completed_questionnaire.rows:
        question_id = str(row["Question ID"])
        expected_question = expected_by_id[question_id]
        expected_answer_type = str(expected_question["expected_answer_type"])
        expected_status = str(expected_question["expected_status"])
        allowed_confidence_bands = {
            str(confidence_band)
            for confidence_band in expected_question["allowed_confidence_bands"]
        }
        answer_type_counts[expected_answer_type] += 1

        _require(
            str(row["Question"]) == str(expected_question["question"]),
            f"{question_id} question text drifted from the curated expected fixture.",
        )
        _require(
            str(row["answer_type"]) == expected_answer_type,
            f"{question_id} answer type did not match the canonical expected fixture.",
        )
        _require(
            str(row["Status"]) == expected_status,
            f"{question_id} status did not match the canonical expected fixture.",
        )
        _require(
            str(row["Confidence"]) in allowed_confidence_bands,
            f"{question_id} confidence band fell outside the allowed fixture bands.",
        )
        _require(
            str(row["Answer"]).startswith(str(expected_question["expected_opening_token"])),
            f"{question_id} answer did not start with the expected opening token.",
        )
        if expected_status == rag.STATUS_NEEDS_REVIEW:
            _require(
                str(row["Reviewer Notes"]) == str(expected_question["rationale"]),
                f"{question_id} reviewer note did not propagate into the row contract.",
            )
        else:
            _require(
                str(row["Reviewer Notes"]) == rag.FALLBACK_REVIEWER_NOTE,
                f"{question_id} supported row did not retain the fallback reviewer note.",
            )

        primary_source = expected_question.get("primary_source")
        if primary_source is None:
            _require(
                list(row["citations"]) == [],
                f"{question_id} should not carry citations when the expected fixture has no primary source.",
            )
            _require(
                str(row["Evidence"]) == "",
                f"{question_id} should leave the visible Evidence cell empty when no citation is expected.",
            )
        else:
            citations = list(row["citations"])
            _require(
                len(citations) == 1,
                f"{question_id} should carry exactly one deterministic primary-source citation.",
            )
            citation = citations[0]
            _require(
                citation.source == primary_source,
                f"{question_id} did not retain the expected primary source file.",
            )
            if citation.section is not None:
                _require(
                    citation.section == expected_question["anchor_hint"],
                    f"{question_id} markdown citation section drifted from the expected anchor.",
                )
            _require(
                str(expected_question["anchor_hint"]).lower() in citation.display_label.lower()
                or citation.page is not None,
                f"{question_id} citation label does not expose the expected anchor or page.",
            )
            _require(
                citation.snippet_text.strip(),
                f"{question_id} citation snippet should include literal evidence text.",
            )

    expected_distribution = expected_fixture["expected_distribution"]
    _require(
        answer_type_counts[rag.ANSWER_TYPE_SUPPORTED] == int(expected_distribution["supported"]),
        "Supported-answer count drifted from the canonical fixture.",
    )
    _require(
        answer_type_counts[rag.ANSWER_TYPE_PARTIAL] == int(expected_distribution["partial"]),
        "Partial-answer count drifted from the canonical fixture.",
    )
    _require(
        answer_type_counts[rag.ANSWER_TYPE_UNSUPPORTED] == int(expected_distribution["unsupported"]),
        "Unsupported-answer count drifted from the canonical fixture.",
    )
    log_sink.emit(
        event="questionnaire_validated",
        run_id=RUN_ID,
        status=rag.LOG_STATUS_COMPLETED,
        message="Validated all 22 question outcomes against the canonical expected fixture.",
        workspace_hash=workspace_hash,
        index_action=rag.INDEX_ACTION_REUSED,
        artifact_path=completed_questionnaire.workbook_path,
    )


def _validate_inspector_surfaces(
    at: AppTest,
    *,
    expected_fixture: dict[str, object],
    log_sink: JsonlLogSink,
    workspace_hash: str,
) -> None:
    """Assert the reviewer-facing inspector surfaces the expected provenance and notes."""
    review_fixture = _question_by_id(tuple(expected_fixture["questions"]))
    _require(len(at.selectbox) == 1, "Golden-path run should expose one question-inspector selector.")
    inspector_selectbox = at.selectbox[0]
    _require(
        list(inspector_selectbox.options)
        == [str(question["question_id"]) for question in expected_fixture["questions"]],
        "Inspector options should stay aligned with the workbook question order.",
    )
    _require(
        inspector_selectbox.value == "Q19",
        "Inspector should default to the lowest-confidence Needs Review row after a full run.",
    )
    default_markdown_values = _markdown_values(at)
    default_info_values = _info_values(at)
    _require(
        _contains_text(default_markdown_values, str(review_fixture["Q19"]["rationale"])),
        "Unsupported default inspector row should show its reviewer note.",
    )
    _require(
        _contains_text(default_info_values, "No validated evidence snippets were attached to this row."),
        "Unsupported default inspector row should explain the absence of citations.",
    )
    log_sink.emit(
        event="inspector_default_validated",
        run_id=RUN_ID,
        status=rag.LOG_STATUS_COMPLETED,
        message="Validated the default unsupported inspector row and no-citation guidance.",
        question_id="Q19",
        workspace_hash=workspace_hash,
        index_action=rag.INDEX_ACTION_REUSED,
        answer_type=rag.ANSWER_TYPE_UNSUPPORTED,
        confidence_band=rag.CONFIDENCE_BAND_LOW,
        review_status=rag.STATUS_NEEDS_REVIEW,
    )

    inspector_selectbox.set_value("Q01")
    at.run()
    markdown_values = _markdown_values(at)
    caption_values = _caption_values(at)
    _require(
        _contains_text(markdown_values, "Yes."),
        "Supported markdown inspector row should show the drafted answer text.",
    )
    _require(
        _contains_text(markdown_values, "Encryption Policy - Data at Rest"),
        "Supported markdown inspector row should show the primary-source display label.",
    )
    _require(
        _contains_text(markdown_values, "AcmeCloud encrypts customer data at rest in production systems using AES-256."),
        "Supported markdown inspector row should show literal evidence snippet text.",
    )
    _require(
        "Source file: Encryption_Policy.md | Section: Data at Rest" in caption_values,
        "Supported markdown inspector row should show source-file and section provenance.",
    )
    log_sink.emit(
        event="inspector_markdown_validated",
        run_id=RUN_ID,
        status=rag.LOG_STATUS_COMPLETED,
        message="Validated markdown-source provenance and literal snippet rendering in the question inspector.",
        question_id="Q01",
        workspace_hash=workspace_hash,
        index_action=rag.INDEX_ACTION_REUSED,
        answer_type=rag.ANSWER_TYPE_SUPPORTED,
        confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
        review_status=rag.STATUS_READY_FOR_REVIEW,
    )

    inspector_selectbox = at.selectbox[0]
    inspector_selectbox.set_value("Q14")
    at.run()
    pdf_markdown_values = _markdown_values(at)
    pdf_caption_values = _caption_values(at)
    _require(
        _contains_text(pdf_markdown_values, "AcmeCloud SOC 2 Summary - Page 1"),
        "Supported PDF inspector row should show the page-based citation label.",
    )
    _require(
        _contains_text(
            pdf_markdown_values,
            "AcmeCloud completed a SOC 2 Type II examination for its cloud service environment.",
        ),
        "Supported PDF inspector row should show literal page text from the SOC 2 summary.",
    )
    _require(
        "Source file: AcmeCloud_SOC2_Summary.pdf | Page: 1" in pdf_caption_values,
        "Supported PDF inspector row should show source-file and page provenance.",
    )
    log_sink.emit(
        event="inspector_pdf_validated",
        run_id=RUN_ID,
        status=rag.LOG_STATUS_COMPLETED,
        message="Validated PDF-source provenance and literal snippet rendering in the question inspector.",
        question_id="Q14",
        workspace_hash=workspace_hash,
        index_action=rag.INDEX_ACTION_REUSED,
        answer_type=rag.ANSWER_TYPE_SUPPORTED,
        confidence_band=rag.CONFIDENCE_BAND_MEDIUM,
        review_status=rag.STATUS_READY_FOR_REVIEW,
    )


def _validate_export_artifacts(
    packet: rag.PublishedExportPacket,
    *,
    completed_questionnaire: rag.RuntimeQuestionnaire,
    expected_fixture: dict[str, object],
    review_queue_ids: list[str],
    workspace_hash: str,
    log_sink: JsonlLogSink,
) -> None:
    """Assert the published artifact packet matches the completed questionnaire state."""
    _require(packet.run_id == RUN_ID, "Published packet run id drifted from the deterministic run id.")
    _require(
        packet.completed_at == COMPLETED_AT,
        "Published packet completed timestamp drifted from the deterministic verification clock.",
    )
    _require(
        packet.workspace_hash == workspace_hash,
        "Published packet workspace hash drifted from the verified runtime workspace.",
    )
    for artifact_path in (
        packet.answered_questionnaire_path,
        packet.review_summary_path,
        packet.needs_review_csv_path,
    ):
        _require(artifact_path.exists(), f"Expected export artifact {artifact_path} was not created.")

    exported_questionnaire = rag.load_runtime_questionnaire(packet.answered_questionnaire_path)
    _require(
        exported_questionnaire.question_ids() == completed_questionnaire.question_ids(),
        "Answered workbook question order drifted from the completed questionnaire.",
    )
    exported_rows_by_id = {str(row["Question ID"]): row for row in exported_questionnaire.rows}
    completed_rows_by_id = {str(row["Question ID"]): row for row in completed_questionnaire.rows}
    for question_id, completed_row in completed_rows_by_id.items():
        exported_row = exported_rows_by_id[question_id]
        for column_name in rag.VISIBLE_EXPORT_COLUMNS:
            _require(
                str(exported_row[column_name]) == str(completed_row[column_name]),
                f"Answered workbook column {column_name!r} drifted for {question_id}.",
            )

    summary_lines = packet.review_summary_path.read_text(encoding="utf-8").splitlines()
    _require(
        summary_lines[0] == f"Completed Run: {COMPLETED_AT}",
        "Review summary completed-run line drifted from the deterministic export contract.",
    )
    _require(
        summary_lines[1] == f"Workspace Hash: {workspace_hash}",
        "Review summary workspace-hash line drifted from the deterministic export contract.",
    )
    _require(
        summary_lines[2] == f"Index State: {rag.INDEX_ACTION_REUSED}",
        "Review summary index-state line drifted from the deterministic export contract.",
    )
    _require("# Review Summary" in summary_lines, "Review summary heading is missing.")
    _require("- Total Questions: 22" in summary_lines, "Review summary total-question count is wrong.")
    _require("- Ready for Review: 15" in summary_lines, "Review summary ready count is wrong.")
    _require("- Needs Review: 7" in summary_lines, "Review summary review count is wrong.")
    for left_question_id, right_question_id in zip(review_queue_ids, review_queue_ids[1:]):
        left_note = f"- {left_question_id}: {completed_rows_by_id[left_question_id]['Reviewer Notes']}"
        right_note = f"- {right_question_id}: {completed_rows_by_id[right_question_id]['Reviewer Notes']}"
        _require(
            summary_lines.index(left_note) < summary_lines.index(right_note),
            "Review summary needs-review queue order drifted from the reviewer priority order.",
        )

    with packet.needs_review_csv_path.open(newline="", encoding="utf-8") as handle:
        review_rows = list(csv.DictReader(handle))
    _require(
        list(review_rows[0].keys()) == list(rag.REVIEW_QUEUE_COLUMNS),
        "Needs-review CSV columns drifted from the canonical reviewer-facing contract.",
    )
    _require(
        [row["Question ID"] for row in review_rows] == review_queue_ids,
        "Needs-review CSV row order drifted from the expected review queue order.",
    )
    for review_row in review_rows:
        question_id = review_row["Question ID"]
        expected_row = completed_rows_by_id[question_id]
        _require(
            review_row["Reviewer Notes"] == str(expected_row["Reviewer Notes"]),
            f"Needs-review CSV reviewer note drifted for {question_id}.",
        )
        _require(
            review_row["Status"] == rag.STATUS_NEEDS_REVIEW,
            f"Needs-review CSV included a non-review row for {question_id}.",
        )

    log_sink.emit(
        event="export_artifacts_validated",
        run_id=RUN_ID,
        status=rag.LOG_STATUS_COMPLETED,
        message="Validated the answered workbook, review summary, and needs-review CSV against the completed deterministic run.",
        workspace_hash=workspace_hash,
        index_action=rag.INDEX_ACTION_REUSED,
        artifact_path=packet.output_dir,
    )


def run_suite(
    *,
    log_dir: Path,
    output_dir: Path,
    verbose: bool,
) -> Path:
    """Execute the deterministic golden-path suite and write JSONL logs."""
    removed_paths = _clear_stale_publish_artifacts(output_dir)
    log_sink = JsonlLogSink(log_path=log_dir / LOG_FILE_NAME, verbose=verbose)
    expected_fixture = _load_expected_fixture()
    expected_questions = tuple(expected_fixture["questions"])
    expected_by_id = _question_by_id(expected_questions)

    log_sink.emit(
        event="suite_started",
        status=rag.LOG_STATUS_STARTED,
        message="Starting the deterministic golden-path e2e suite.",
        run_id=RUN_ID,
        artifact_path=log_dir / LOG_FILE_NAME,
    )
    if removed_paths:
        log_sink.emit(
            event="publish_artifacts_reset",
            status=rag.LOG_STATUS_COMPLETED,
            message="Removed stale deterministic export artifacts before rerunning the suite.",
            run_id=RUN_ID,
            artifact_path=output_dir,
            reason="rerun_preflight",
        )
    questionnaire, workspace_hash, evidence_count = _ensure_workspace_ready(log_sink)
    _require(
        questionnaire.question_ids()
        == tuple(str(question["question_id"]) for question in expected_questions),
        "Runtime questionnaire order drifted from the canonical expected fixture.",
    )

    ready_snapshot = _ready_snapshot(
        workspace_hash=workspace_hash,
        evidence_count=evidence_count,
    )
    ready_index_status = _ready_index_status(
        workspace_hash=workspace_hash,
        evidence_count=evidence_count,
    )

    def fake_run_pipeline(
        runtime_questionnaire: rag.RuntimeQuestionnaire,
        *,
        index_status: rag.ChromaIndexStatus,
        run_id: str,
        model: str = rag.DEFAULT_OPENAI_ANSWER_MODEL,
        openai_client: object | None = None,
        on_row_completed=None,
        on_log_event=None,
    ) -> rag.RuntimeQuestionnaire:
        del model, openai_client, on_log_event
        _require(run_id == RUN_ID, "App generated an unexpected run id for the deterministic suite.")
        _require(
            index_status.workspace_hash == workspace_hash,
            "App run used an unexpected workspace hash in the deterministic suite.",
        )
        run_questionnaire = rag.prepare_questionnaire_run(runtime_questionnaire)
        for row_index, row in enumerate(run_questionnaire.rows):
            question_id = str(row["Question ID"])
            answer_result = _answer_result_for_expected(expected_by_id[question_id])
            updated_row = rag.update_row_with_answer_result(
                row,
                answer_result,
                index_action=index_status.index_action,
                run_id=run_id,
            )
            run_questionnaire.rows[row_index] = updated_row
            if on_row_completed is not None:
                on_row_completed(run_questionnaire, row_index)
            log_sink.emit(
                event="row_completed",
                run_id=RUN_ID,
                status=rag.LOG_STATUS_COMPLETED,
                message=(
                    f"Completed {question_id} as {answer_result.answer_type} "
                    f"with {len(answer_result.citations)} validated citation(s)."
                ),
                question_id=question_id,
                workspace_hash=workspace_hash,
                index_action=index_status.index_action,
                valid_citation_count=len(answer_result.citations),
                answer_type=answer_result.answer_type,
                confidence_band=answer_result.confidence_band,
                review_status=answer_result.status,
            )
        return run_questionnaire

    def publish_packet_for_verification(
        completed_questionnaire: rag.RuntimeQuestionnaire,
        *,
        workspace_hash: str,
    ) -> rag.PublishedExportPacket:
        return rag.publish_export_packet(
            completed_questionnaire,
            output_dir=output_dir,
            completed_at=COMPLETED_AT,
            workspace_hash=workspace_hash,
        )

    with patch.object(app, "_workspace_snapshot", return_value=ready_snapshot):
        with patch.object(app, "load_runtime_questionnaire", return_value=questionnaire):
            with patch.object(app, "_missing_required_environment", return_value=()):
                with patch.object(
                    app,
                    "ensure_curated_evidence_index",
                    return_value=ready_index_status,
                ):
                    with patch.object(app, "_new_run_id", return_value=RUN_ID):
                        with patch.object(
                            app,
                            "run_questionnaire_answer_pipeline",
                            side_effect=fake_run_pipeline,
                        ):
                            with patch.object(
                                app,
                                "publish_export_packet",
                                side_effect=publish_packet_for_verification,
                            ):
                                at = AppTest.from_function(_run_app_main)
                                at.run()
                                _require(
                                    _button_by_label(at, "Run Copilot").disabled is False,
                                    "Golden-path run button should be enabled in the ready workspace state.",
                                )
                                _button_by_label(at, "Run Copilot").click()
                                at.run()

                                completed_questionnaire = at.session_state[app.LAST_RUN_QUESTIONNAIRE_KEY]
                                _require(
                                    isinstance(completed_questionnaire, rag.RuntimeQuestionnaire),
                                    "Completed run should persist a RuntimeQuestionnaire in session state.",
                                )
                                _require(
                                    at.session_state[app.LAST_RUN_ID_KEY] == RUN_ID,
                                    "Last run id did not persist the deterministic run id.",
                                )
                                _validate_completed_questionnaire(
                                    completed_questionnaire,
                                    expected_fixture=expected_fixture,
                                    log_sink=log_sink,
                                    workspace_hash=workspace_hash,
                                )

                                metric_map = {
                                    metric.label: str(metric.value)
                                    for metric in at.metric
                                }
                                _require(
                                    metric_map
                                    == {
                                        "Total Questions": "22",
                                        "Questions": "22",
                                        "Ready for Review": "15",
                                        "Needs Review": "7",
                                        "Sources Indexed": str(evidence_count),
                                    },
                                    "Results metrics drifted from the expected deterministic golden-path counts.",
                                )
                                _require(
                                    len(at.dataframe) == 2,
                                    "Golden-path run should expose the main results table and the review queue table.",
                                )
                                results_dataframe = at.dataframe[0].value
                                _require(
                                    list(results_dataframe.columns)
                                    == ["Question ID", "Category", "Answer", "Confidence", "Status"],
                                    "Results table columns drifted from the golden-path UI contract.",
                                )
                                _require(
                                    list(results_dataframe["Question ID"])
                                    == list(questionnaire.question_ids()),
                                    "Results table question order drifted from the workbook order.",
                                )
                                _require(
                                    _contains_text(
                                        _success_values(at),
                                        "Run finished after Q22 - Do you perform annual external penetration testing? (Needs Review).",
                                    ),
                                    "Final run status message drifted from the last-row golden-path contract.",
                                )
                                _require(
                                    _contains_text(_success_values(at), "Copilot run finished."),
                                    "Run success feedback did not render after the deterministic golden-path run.",
                                )

                                review_queue_ids = _review_queue_expected_ids(completed_questionnaire)
                                review_queue_dataframe = at.dataframe[1].value
                                _require(
                                    list(review_queue_dataframe["Question ID"]) == review_queue_ids,
                                    "Review queue table drifted from the expected reviewer-priority order.",
                                )
                                _validate_inspector_surfaces(
                                    at,
                                    expected_fixture=expected_fixture,
                                    log_sink=log_sink,
                                    workspace_hash=workspace_hash,
                                )

                                _require(
                                    _button_by_label(at, "Publish Export Packet").disabled is False,
                                    "Publish Export Packet should be enabled after the deterministic run completes.",
                                )
                                _button_by_label(at, "Publish Export Packet").click()
                                at.run()

                                packet = at.session_state[app.EXPORT_PACKET_KEY]
                                _require(
                                    isinstance(packet, rag.PublishedExportPacket),
                                    "Export action should persist the published export packet in session state.",
                                )
                                _require(
                                    _contains_text(_success_values(at), "Export packet published."),
                                    "Export success feedback did not render after the deterministic publish.",
                                )
                                exported_markdown_values = _markdown_values(at)
                                _require(
                                    _contains_text(exported_markdown_values, str(packet.output_dir)),
                                    "Export surface did not show the published output directory.",
                                )
                                _require(
                                    _contains_text(exported_markdown_values, str(packet.answered_questionnaire_path)),
                                    "Export surface did not show the answered workbook path.",
                                )
                                _require(
                                    _contains_text(exported_markdown_values, str(packet.review_summary_path)),
                                    "Export surface did not show the review summary path.",
                                )
                                _require(
                                    _contains_text(exported_markdown_values, str(packet.needs_review_csv_path)),
                                    "Export surface did not show the needs-review CSV path.",
                                )
                                _validate_export_artifacts(
                                    packet,
                                    completed_questionnaire=completed_questionnaire,
                                    expected_fixture=expected_fixture,
                                    review_queue_ids=review_queue_ids,
                                    workspace_hash=workspace_hash,
                                    log_sink=log_sink,
                                )

    log_sink.emit(
        event="suite_completed",
        run_id=RUN_ID,
        status=rag.LOG_STATUS_COMPLETED,
        message="Completed the deterministic golden-path e2e suite successfully.",
        workspace_hash=workspace_hash,
        index_action=rag.INDEX_ACTION_REUSED,
        artifact_path=log_dir / LOG_FILE_NAME,
    )
    return log_sink.flush()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=rag.E2E_TEST_LOGS_DIR,
        help="Directory for the JSONL verification log.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=rag.E2E_TEST_LOGS_DIR / "deterministic_demo_packet",
        help="Directory where the deterministic export packet should be published.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each structured verification record to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        log_path = run_suite(
            log_dir=args.log_dir,
            output_dir=args.output_dir,
            verbose=args.verbose,
        )
    except Exception as exc:
        print(f"{SCRIPT_NAME}: FAIL: {exc}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"{SCRIPT_NAME}: PASS -> {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
