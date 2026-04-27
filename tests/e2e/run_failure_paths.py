#!/usr/bin/env python3
"""Deterministic failure-path e2e coverage for the Security Questionnaire Agent."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Iterator
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import generate_demo_data as gdd
import rag


FIXED_COMPLETED_AT = "2026-04-27T00:00:00Z"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable.")


@dataclass(frozen=True)
class ScriptPaths:
    artifact_root: Path
    log_path: Path
    isolated_data_dir: Path
    runtime_questionnaires_dir: Path
    runtime_evidence_dir: Path
    outputs_dir: Path
    chroma_dir: Path


class JsonlLogger:
    """Write one high-signal JSONL stream for script and backend events."""

    def __init__(self, log_path: Path, *, verbose: bool) -> None:
        self.log_path = log_path
        self.verbose = verbose
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")

    def emit(
        self,
        *,
        component: str,
        event: str,
        status: str,
        message: str,
        level: str = "INFO",
        **fields: object,
    ) -> None:
        record = {
            "ts": _utc_timestamp(),
            "level": level,
            "component": component,
            "event": event,
            "status": status,
            "message": message,
            **fields,
        }
        line = json.dumps(record, sort_keys=True, default=_json_default)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
        if self.verbose:
            print(line)

    def capture_rag_event(self, record: dict[str, object]) -> None:
        self.emit(
            component="rag",
            event=str(record.get("event", "unknown")),
            status=str(record.get("status", "unknown")),
            message=str(record.get("message", "")),
            level=str(record.get("level", "INFO")),
            source_component=record.get("component"),
            rag_record=record,
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _selected_questionnaire(question_ids: tuple[str, ...]) -> rag.RuntimeQuestionnaire:
    loaded = rag.load_runtime_questionnaire()
    rows_by_id = {str(row["question_id"]): dict(row) for row in loaded.rows}
    selected_rows = [rows_by_id[question_id] for question_id in question_ids]
    return rag.RuntimeQuestionnaire(
        workbook_path=loaded.workbook_path,
        visible_columns=loaded.visible_columns,
        rows=selected_rows,
    )


def _sample_chunk(
    chunk_id: str,
    *,
    source: str,
    section: str,
    text: str,
    rank: int,
) -> rag.RetrievedEvidenceChunk:
    return rag.RetrievedEvidenceChunk(
        chunk_id=chunk_id,
        source=source,
        source_path=rag.RUNTIME_EVIDENCE_DIR / source,
        doc_type=rag.DOCUMENT_TYPE_POLICY,
        text=text,
        rank=rank,
        section=section,
    )


def _runtime_overrides(base_dir: Path) -> tuple[dict[str, object], dict[str, object], ScriptPaths]:
    isolated_data_dir = base_dir / "isolated_data"
    runtime_questionnaires_dir = isolated_data_dir / "questionnaires"
    runtime_evidence_dir = isolated_data_dir / "evidence"
    outputs_dir = isolated_data_dir / "outputs"
    chroma_dir = isolated_data_dir / "chroma"

    runtime_directories = (
        runtime_questionnaires_dir,
        runtime_evidence_dir,
        outputs_dir,
        chroma_dir,
    )
    workspace_hash_directories = (
        runtime_questionnaires_dir,
        runtime_evidence_dir,
    )
    seed_to_runtime_paths = (
        (
            rag.SEED_QUESTIONNAIRE_DIR / gdd.QUESTIONNAIRE_FILE_NAME,
            runtime_questionnaires_dir / gdd.QUESTIONNAIRE_FILE_NAME,
        ),
        *tuple(
            (
                rag.SEED_EVIDENCE_DIR / evidence_file_name,
                runtime_evidence_dir / evidence_file_name,
            )
            for evidence_file_name in gdd.EXPECTED_EVIDENCE_FILE_NAMES
        ),
    )
    paths = ScriptPaths(
        artifact_root=base_dir,
        log_path=base_dir / "run_failure_paths.jsonl",
        isolated_data_dir=isolated_data_dir,
        runtime_questionnaires_dir=runtime_questionnaires_dir,
        runtime_evidence_dir=runtime_evidence_dir,
        outputs_dir=outputs_dir,
        chroma_dir=chroma_dir,
    )
    gdd_updates = {
        "DATA_DIR": isolated_data_dir,
        "RUNTIME_QUESTIONNAIRES_DIR": runtime_questionnaires_dir,
        "RUNTIME_EVIDENCE_DIR": runtime_evidence_dir,
        "OUTPUTS_DIR": outputs_dir,
        "CHROMA_DIR": chroma_dir,
        "RUNTIME_DIRECTORIES": runtime_directories,
        "WORKSPACE_HASH_DIRECTORIES": workspace_hash_directories,
        "SEED_TO_RUNTIME_PATHS": seed_to_runtime_paths,
    }
    rag_updates = {
        "DATA_DIR": isolated_data_dir,
        "RUNTIME_QUESTIONNAIRES_DIR": runtime_questionnaires_dir,
        "RUNTIME_EVIDENCE_DIR": runtime_evidence_dir,
        "OUTPUTS_DIR": outputs_dir,
        "CHROMA_DIR": chroma_dir,
        "RUNTIME_DIRECTORIES": runtime_directories,
        "WORKSPACE_HASH_DIRECTORIES": workspace_hash_directories,
        "SEED_TO_RUNTIME_PATHS": seed_to_runtime_paths,
    }
    return gdd_updates, rag_updates, paths


@contextmanager
def isolated_workspace(base_dir: Path) -> Iterator[ScriptPaths]:
    """Patch workspace globals into one isolated temp area for deterministic e2e work."""

    gdd_updates, rag_updates, paths = _runtime_overrides(base_dir)
    with ExitStack() as stack:
        for attribute_name, value in gdd_updates.items():
            stack.enter_context(patch.object(gdd, attribute_name, value))
        for attribute_name, value in rag_updates.items():
            stack.enter_context(patch.object(rag, attribute_name, value))
        yield paths


def _scenario_index_transitions(logger: JsonlLogger) -> rag.ChromaIndexStatus:
    """Prove create, reuse, force-rebuild, and integrity-rebuild flows stay explicit."""

    logger.emit(
        component="e2e",
        event="index_scenario_started",
        status="started",
        message="Preparing the isolated workspace and exercising index transition scenarios.",
    )
    copied_assets = gdd.prepare_demo_workspace(reset_index=True)
    _require(copied_assets, "prepare_demo_workspace() should copy the curated seed assets.")

    created = rag.ensure_curated_evidence_index(on_log_event=logger.capture_rag_event)
    _require(
        created.index_action == rag.INDEX_ACTION_CREATED,
        f"Expected created index action, received {created.index_action!r}.",
    )
    _require(created.ready, "The newly created index should be ready.")

    reused = rag.ensure_curated_evidence_index(on_log_event=logger.capture_rag_event)
    _require(
        reused.index_action == rag.INDEX_ACTION_REUSED,
        f"Expected reused index action, received {reused.index_action!r}.",
    )
    _require(reused.ready, "The reused index should stay ready.")

    forced = rag.ensure_curated_evidence_index(
        force_rebuild=True,
        on_log_event=logger.capture_rag_event,
    )
    _require(
        forced.index_action == rag.INDEX_ACTION_REBUILT_CONTENT_CHANGE,
        f"Expected force rebuild action, received {forced.index_action!r}.",
    )
    _require(
        forced.reason == "force_rebuild",
        f"Expected force_rebuild reason, received {forced.reason!r}.",
    )

    handle = forced.collection_handle
    _require(handle is not None, "A rebuilt index should expose a collection handle.")
    collection_payload = handle.collection.get()
    all_ids = collection_payload.get("ids", [])
    _require(
        isinstance(all_ids, list) and all_ids,
        "The forced rebuild should leave the isolated collection populated before corruption.",
    )
    handle.collection.delete(ids=all_ids)

    rebuilt_integrity = rag.ensure_curated_evidence_index(
        on_log_event=logger.capture_rag_event,
    )
    _require(
        rebuilt_integrity.index_action == rag.INDEX_ACTION_REBUILT_INTEGRITY,
        "Corrupt or empty collection state should rebuild as rebuilt_integrity.",
    )
    _require(
        rebuilt_integrity.reason in rag.AUTO_REBUILD_INTEGRITY_REASONS,
        f"Integrity rebuild should report a known integrity reason, received {rebuilt_integrity.reason!r}.",
    )
    _require(
        rebuilt_integrity.index_action != rag.INDEX_ACTION_REUSED,
        "Integrity-corrupted state must not silently pass as reused.",
    )
    logger.emit(
        component="e2e",
        event="index_scenario_completed",
        status="completed",
        message="Create, reuse, force-rebuild, and integrity-rebuild transitions passed.",
        final_index_action=rebuilt_integrity.index_action,
        final_reason=rebuilt_integrity.reason,
        workspace_hash=rebuilt_integrity.workspace_hash,
    )
    return rebuilt_integrity


def _scenario_pipeline_and_exports(
    logger: JsonlLogger,
    *,
    index_status: rag.ChromaIndexStatus,
    output_dir: Path,
) -> None:
    """Exercise retry ceilings, canonical fail-closed outputs, ordering, and reviewer exports."""

    logger.emit(
        component="e2e",
        event="pipeline_scenario_started",
        status="started",
        message="Running the deterministic negative-path questionnaire scenario.",
    )
    questionnaire = _selected_questionnaire(("Q01", "Q02", "Q03"))
    questionnaire.rows[1]["Answer"] = "STALE ANSWER"
    questionnaire.rows[1]["Evidence"] = "STALE EVIDENCE"
    questionnaire.rows[1]["Confidence"] = "STALE CONFIDENCE"
    questionnaire.rows[1]["Status"] = "STALE STATUS"
    questionnaire.rows[1]["Reviewer Notes"] = "STALE NOTE"
    questionnaire.rows[1]["answer"] = "STALE ANSWER"
    questionnaire.rows[1]["reviewer_note"] = "STALE NOTE"
    questionnaire.rows[1]["index_action"] = "STALE INDEX ACTION"
    questionnaire.rows[1]["run_id"] = "STALE-RUN"

    retrieved_supported = (
        _sample_chunk(
            "enc_001",
            source=rag.ENCRYPTION_POLICY_FILE_NAME,
            section="Data at Rest",
            text="Customer data is encrypted at rest using AES-256 in production.",
            rank=1,
        ),
        _sample_chunk(
            "soc2_001",
            source=rag.SOC2_SUMMARY_FILE_NAME,
            section="Encryption Controls",
            text="SOC 2 summary confirms encryption controls are enforced in production.",
            rank=2,
        ),
    )
    retrieved_invalid = (
        _sample_chunk(
            "acc_001",
            source=rag.ACCESS_CONTROL_POLICY_FILE_NAME,
            section="Administrative Access",
            text="Administrative access requires approval and is logged centrally.",
            rank=1,
        ),
    )

    generate_calls: dict[str, int] = defaultdict(int)
    question_id_by_text = {
        str(row["question"]).strip(): str(row["question_id"]) for row in questionnaire.rows
    }

    def fake_retrieve(
        row_like: dict[str, object],
        *,
        index_status: object,
        top_k: int = rag.RETRIEVAL_TOP_K,
    ) -> tuple[rag.RetrievedEvidenceChunk, ...]:
        del index_status, top_k
        question_id = str(row_like["question_id"])
        if question_id == "Q01":
            return ()
        if question_id == "Q02":
            return retrieved_supported
        if question_id == "Q03":
            return retrieved_invalid
        raise AssertionError(f"Unexpected question id {question_id!r} in fake retrieval.")

    def fake_generate_answer_payload(
        question_text: str,
        retrieved_chunks: tuple[rag.RetrievedEvidenceChunk, ...],
        *,
        model: str = rag.DEFAULT_OPENAI_ANSWER_MODEL,
        openai_client: Any | None = None,
    ) -> dict[str, object]:
        del retrieved_chunks, model, openai_client
        question_id = question_id_by_text[question_text.strip()]
        generate_calls[question_id] += 1
        if question_id == "Q02":
            if generate_calls[question_id] == 1:
                raise RuntimeError(
                    "OpenAI answer generation returned malformed JSON for the answer payload."
                )
            return {
                "answer": "Yes. Customer data is encrypted at rest in production systems.",
                "answer_type": rag.ANSWER_TYPE_SUPPORTED,
                "citation_ids": ["enc_001", "soc2_001"],
                "reviewer_note": "Grounded in the encryption policy and SOC 2 summary.",
            }
        if question_id == "Q03":
            return {
                "answer": (
                    "Not stated. The retrieved evidence does not confirm "
                    "customer-selectable residency controls."
                ),
                "answer_type": rag.ANSWER_TYPE_UNSUPPORTED,
                "citation_ids": ["missing_999"],
                "reviewer_note": "This note should be replaced by the fail-closed rationale.",
            }
        raise AssertionError(f"Unexpected question text routed to fake payload: {question_text!r}")

    callback_order: list[tuple[int, str, str]] = []
    rag_events: list[dict[str, object]] = []

    def on_row_completed(
        completed_questionnaire: rag.RuntimeQuestionnaire,
        row_index: int,
    ) -> None:
        callback_order.append(
            (
                row_index,
                str(completed_questionnaire.rows[row_index]["question_id"]),
                str(completed_questionnaire.rows[row_index]["status"]),
            )
        )

    def on_log_event(record: dict[str, object]) -> None:
        rag_events.append(record)
        logger.capture_rag_event(record)

    with patch.object(rag, "retrieve_evidence_chunks_for_row", side_effect=fake_retrieve), patch.object(
        rag,
        "generate_answer_payload",
        side_effect=fake_generate_answer_payload,
    ):
        completed = rag.run_questionnaire_answer_pipeline(
            questionnaire,
            index_status=index_status,
            run_id="failure-e2e-run",
            on_row_completed=on_row_completed,
            on_log_event=on_log_event,
        )

    _require(
        callback_order == [
            (0, "Q01", rag.STATUS_NEEDS_REVIEW),
            (1, "Q02", rag.STATUS_READY_FOR_REVIEW),
            (2, "Q03", rag.STATUS_NEEDS_REVIEW),
        ],
        f"Expected incremental callback order Q01/Q02/Q03, received {callback_order!r}.",
    )
    _require(
        generate_calls["Q01"] == 0,
        "No-retrieval rows should fail closed without invoking provider payload generation.",
    )
    _require(
        generate_calls["Q02"] == 2,
        f"Retryable provider failures should consume exactly one retry, observed {generate_calls['Q02']} calls.",
    )
    _require(
        generate_calls["Q03"] == 1,
        "All-invalid-citation rows should fail closed without retrying a second payload attempt.",
    )
    _require(
        completed.rows[1]["Answer"] != "STALE ANSWER",
        "Fresh pipeline runs must clear stale visible answer state before writing new results.",
    )
    _require(
        completed.rows[1]["run_id"] == "failure-e2e-run",
        "Fresh pipeline runs must overwrite stale run ids with the current run id.",
    )
    _require(
        str(completed.rows[0]["status"]) == rag.STATUS_NEEDS_REVIEW,
        "No-retrieval rows should route to Needs Review.",
    )
    _require(
        str(completed.rows[0]["Answer"]) == rag.FAIL_CLOSED_ANSWER,
        "No-retrieval rows should use the canonical fail-closed answer text.",
    )
    _require(
        str(completed.rows[0]["Confidence"]) == rag.CONFIDENCE_BAND_LOW,
        "No-retrieval rows should fail closed with Low confidence.",
    )
    _require(
        str(completed.rows[0]["Reviewer Notes"])
        == rag.FAIL_CLOSED_REVIEWER_NOTE_BY_REASON[rag.FAILURE_REASON_NO_RETRIEVAL],
        "No-retrieval rows should expose the canonical reviewer note.",
    )
    _require(
        str(completed.rows[1]["status"]) == rag.STATUS_READY_FOR_REVIEW,
        "Retry-success rows should land in Ready for Review.",
    )
    _require(
        str(completed.rows[2]["status"]) == rag.STATUS_NEEDS_REVIEW,
        "All-invalid-citation rows should route to Needs Review.",
    )
    _require(
        str(completed.rows[1]["Answer"]).startswith("Yes."),
        "The retry-success row should retain the successful supported answer.",
    )
    _require(
        str(completed.rows[2]["Answer"]) == rag.FAIL_CLOSED_ANSWER,
        "All-invalid-citation rows should use the canonical fail-closed answer text.",
    )
    _require(
        str(completed.rows[2]["Confidence"]) == rag.CONFIDENCE_BAND_LOW,
        "All-invalid-citation rows should fail closed with Low confidence.",
    )
    _require(
        str(completed.rows[2]["Reviewer Notes"])
        == rag.FAIL_CLOSED_REVIEWER_NOTE_BY_REASON["no_valid_citations"],
        "All-invalid-citation rows should expose the canonical reviewer note.",
    )

    retrying_events = [
        record
        for record in rag_events
        if record.get("event") == "answer_retrying"
    ]
    _require(
        [record.get("question_id") for record in retrying_events] == ["Q02"],
        f"Expected exactly one retry event for Q02, received {retrying_events!r}.",
    )
    failed_closed_by_question = {
        str(record.get("question_id")): record
        for record in rag_events
        if record.get("event") == "answer_failed_closed"
    }
    _require(
        str(failed_closed_by_question["Q01"].get("reason")) == rag.FAILURE_REASON_NO_RETRIEVAL,
        "Q01 should fail closed for the no_retrieval reason.",
    )
    _require(
        str(failed_closed_by_question["Q03"].get("reason"))
        == "no_valid_citations",
        "Q03 should fail closed because every cited chunk was invalid after validation.",
    )

    review_rows = rag.review_rows_in_priority_order(completed)
    _require(
        [str(row["question_id"]) for row in review_rows] == ["Q01", "Q03"],
        "Review queue rows should stay sorted by reviewer priority after negative-path routing.",
    )

    packet = rag.publish_export_packet(
        completed,
        output_dir=output_dir,
        completed_at=FIXED_COMPLETED_AT,
        workspace_hash=index_status.workspace_hash,
        on_log_event=on_log_event,
    )
    _require(
        packet.index_action == index_status.index_action,
        "Published export packets should preserve the final run index action.",
    )
    _require(
        packet.answered_questionnaire_path.exists()
        and packet.review_summary_path.exists()
        and packet.needs_review_csv_path.exists(),
        "Failure-path exports should still publish the canonical three-artifact packet.",
    )

    review_summary = packet.review_summary_path.read_text(encoding="utf-8")
    _require(
        "Index State: rebuilt_integrity" in review_summary,
        "Review summary should record the integrity-triggered rebuild provenance.",
    )
    _require(
        "Q01:" in review_summary and "Q03:" in review_summary,
        "Review summary should include every review-bound row from the negative-path scenario.",
    )

    with packet.needs_review_csv_path.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    _require(
        [row["Question ID"] for row in csv_rows] == ["Q01", "Q03"],
        "Needs_Review.csv should contain only review-bound rows in reviewer-priority order.",
    )
    _require(
        all(row["Reviewer Notes"].strip() for row in csv_rows),
        "Reviewer notes must stay non-blank when propagated into the failure-path CSV.",
    )

    logger.emit(
        component="e2e",
        event="pipeline_scenario_completed",
        status="completed",
        message="Negative-path pipeline, review queue, and export assertions passed.",
        callback_order=callback_order,
        review_queue=[row["Question ID"] for row in csv_rows],
        export_dir=packet.output_dir,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic failure-path, retry, review-routing, and index-rebuild "
            "coverage with detailed JSONL logs."
        )
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=rag.E2E_TEST_LOGS_DIR,
        help="Directory where the script should write its JSONL log stream and artifacts.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo each JSONL log record to stdout while the script runs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.log_dir / f"failure-path-{_utc_timestamp().replace(':', '-')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    with isolated_workspace(run_dir) as workspace:
        logger = JsonlLogger(workspace.log_path, verbose=args.verbose)
        logger.emit(
            component="e2e",
            event="failure_e2e_started",
            status="started",
            message="Starting the deterministic failure-path end-to-end script.",
            artifact_root=workspace.artifact_root,
        )
        try:
            index_status = _scenario_index_transitions(logger)
            _scenario_pipeline_and_exports(
                logger,
                index_status=index_status,
                output_dir=workspace.outputs_dir,
            )
        except Exception as error:
            logger.emit(
                component="e2e",
                event="failure_e2e_failed",
                status="failed",
                level="ERROR",
                message=f"Failure-path e2e assertions failed: {error}",
                error_type=type(error).__name__,
            )
            if not args.verbose:
                print(workspace.log_path)
            return 1

        logger.emit(
            component="e2e",
            event="failure_e2e_completed",
            status="completed",
            message="Deterministic failure-path e2e coverage completed successfully.",
            log_path=workspace.log_path,
        )
        if not args.verbose:
            print(workspace.log_path)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
