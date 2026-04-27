#!/usr/bin/env python3
"""Optional live-provider smoke checks for the canonical demo verification trio."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Final, Iterator, Sequence
from unittest.mock import patch

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import generate_demo_data as gdd
import rag


SCRIPT_NAME: Final[str] = "run_live_smoke"
LOG_FILE_NAME: Final[str] = f"{SCRIPT_NAME}.jsonl"
SUITE_RUN_ID: Final[str] = "live-smoke-e2e"
DEFAULT_QUESTION_IDS: Final[tuple[str, ...]] = ("Q01", "Q17", "Q21")


@dataclass(frozen=True)
class ScriptPaths:
    artifact_root: Path
    log_path: Path
    isolated_data_dir: Path
    runtime_questionnaires_dir: Path
    runtime_evidence_dir: Path
    outputs_dir: Path
    chroma_dir: Path


@dataclass(frozen=True)
class SmokeExpectation:
    question_id: str
    question: str
    expected_answer_type: str
    expected_status: str
    expected_opening_token: str
    allowed_confidence_bands: tuple[str, ...]
    primary_source: str | None
    rationale: str


def _utc_timestamp() -> str:
    return rag.completed_run_timestamp()


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable.")


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
        **fields: object,
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
        for name, value in fields.items():
            if value is not None:
                record[name] = value

        line = json.dumps(record, sort_keys=True, default=_json_default)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.write("\n")
        if self.verbose:
            print(line)

    def capture_rag_event(self, record: dict[str, object]) -> None:
        question_id = record.get("question_id")
        workspace_hash = record.get("workspace_hash")
        index_action = record.get("index_action")
        valid_citation_count = record.get("valid_citation_count")
        answer_type = record.get("answer_type")
        confidence_band = record.get("confidence_band")
        review_status = record.get("review_status")
        self.emit(
            event=str(record.get("event", "unknown")),
            status=str(record.get("status", "unknown")),
            message=str(record.get("message", "")),
            level=str(record.get("level", "INFO")),
            run_id=str(record.get("run_id", SUITE_RUN_ID)),
            question_id=str(question_id) if question_id is not None else None,
            workspace_hash=str(workspace_hash) if workspace_hash is not None else None,
            index_action=str(index_action) if index_action is not None else None,
            valid_citation_count=(
                int(valid_citation_count)
                if isinstance(valid_citation_count, int)
                else None
            ),
            answer_type=str(answer_type) if answer_type is not None else None,
            confidence_band=(
                str(confidence_band) if confidence_band is not None else None
            ),
            review_status=str(review_status) if review_status is not None else None,
            artifact_path=record.get("artifact_path"),
            reason=str(record.get("reason")) if record.get("reason") is not None else None,
            retrieved_chunk_count=record.get("retrieved_chunk_count"),
            retry_attempt=record.get("retry_attempt"),
            source_component=record.get("component"),
            rag_record=record,
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_repo_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv(REPO_ROOT / ".env", override=False)


def _configured_openai_api_key() -> str:
    _load_repo_dotenv_if_available()
    return os.getenv("OPENAI_API_KEY", "").strip()


def _load_expected_fixture() -> dict[str, object]:
    fixture_path = rag.SEED_QUESTIONNAIRE_DIR / "Demo_Security_Questionnaire.expected.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _expectations_for(question_ids: Sequence[str]) -> tuple[SmokeExpectation, ...]:
    fixture = _load_expected_fixture()
    questions_by_id = {
        str(question["question_id"]): dict(question)
        for question in fixture["questions"]
    }
    expectations: list[SmokeExpectation] = []
    for question_id in question_ids:
        question = questions_by_id.get(question_id)
        if question is None:
            raise AssertionError(f"Unknown smoke question id {question_id!r}.")

        expected_opening_token = str(question["expected_opening_token"]).strip()
        _require(
            bool(expected_opening_token),
            f"Fixture row {question_id} is missing expected_opening_token.",
        )

        allowed_confidence_bands = tuple(
            str(value)
            for value in question.get("allowed_confidence_bands", ())
            if str(value).strip()
        )
        _require(
            bool(allowed_confidence_bands),
            f"Fixture row {question_id} is missing allowed_confidence_bands.",
        )

        primary_source = question.get("primary_source")
        normalized_primary_source = (
            str(primary_source).strip() if isinstance(primary_source, str) and primary_source.strip() else None
        )

        expectations.append(
            SmokeExpectation(
                question_id=question_id,
                question=str(question["question"]),
                expected_answer_type=str(question["expected_answer_type"]),
                expected_status=str(question["expected_status"]),
                expected_opening_token=expected_opening_token,
                allowed_confidence_bands=allowed_confidence_bands,
                primary_source=normalized_primary_source,
                rationale=str(question["rationale"]),
            )
        )
    return tuple(expectations)


def _selected_questionnaire(question_ids: Sequence[str]) -> rag.RuntimeQuestionnaire:
    loaded = rag.load_runtime_questionnaire()
    rows_by_id = {str(row["question_id"]): dict(row) for row in loaded.rows}
    selected_rows = [rows_by_id[question_id] for question_id in question_ids]
    return rag.RuntimeQuestionnaire(
        workbook_path=loaded.workbook_path,
        visible_columns=loaded.visible_columns,
        rows=selected_rows,
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
        log_path=base_dir / LOG_FILE_NAME,
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
    """Patch runtime globals into one isolated temp tree for live smoke execution."""

    gdd_updates, rag_updates, paths = _runtime_overrides(base_dir)
    with ExitStack() as stack:
        for attribute_name, value in gdd_updates.items():
            stack.enter_context(patch.object(gdd, attribute_name, value))
        for attribute_name, value in rag_updates.items():
            stack.enter_context(patch.object(rag, attribute_name, value))
        yield paths


def _opening_token(answer: str) -> str:
    normalized_answer = answer.strip()
    if not normalized_answer:
        return ""
    return normalized_answer.split(maxsplit=1)[0]


def _question_run_id(question_id: str) -> str:
    return f"{SUITE_RUN_ID}-{question_id.lower()}"


def _ordered_sources(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _reviewer_note_present(result: rag.GeneratedAnswerResult) -> bool:
    """Return whether one result exposes a reviewer-visible note in the final row contract."""
    return (
        result.status == rag.STATUS_NEEDS_REVIEW
        and bool(result.reviewer_note.strip())
    )


def _run_live_smoke(
    *,
    question_ids: Sequence[str],
    model: str,
    logger: JsonlLogger,
) -> int:
    api_key = _configured_openai_api_key()
    if not api_key:
        logger.emit(
            event="live_smoke_skipped",
            status=rag.LOG_STATUS_SKIPPED,
            message="Skipping the live-provider smoke because OPENAI_API_KEY is not configured.",
            reason="missing_openai_api_key",
            required_env_vars=rag.REQUIRED_ENV_VARS,
        )
        return 0

    expectations = _expectations_for(question_ids)
    with TemporaryDirectory(prefix=f"{SCRIPT_NAME}-") as tmp_dir_name:
        artifact_root = Path(tmp_dir_name)
        with isolated_workspace(artifact_root) as paths:
            copied_assets = gdd.prepare_demo_workspace(reset_index=True)
            logger.emit(
                event="workspace_prepared",
                status=rag.LOG_STATUS_COMPLETED,
                message="Prepared one isolated runtime workspace for the live-provider smoke suite.",
                artifact_path=paths.isolated_data_dir,
                copied_assets_count=len(copied_assets),
            )

            index_status = rag.ensure_curated_evidence_index(
                on_log_event=logger.capture_rag_event,
            )
            _require(index_status.ready, f"Live smoke requires a ready index, received {index_status.reason!r}.")
            logger.emit(
                event="index_ready",
                status=rag.LOG_STATUS_COMPLETED,
                message="The isolated curated evidence index is ready for live-provider verification.",
                run_id=SUITE_RUN_ID,
                workspace_hash=index_status.workspace_hash,
                index_action=index_status.index_action,
                reason=index_status.reason,
            )

            questionnaire = _selected_questionnaire(tuple(expectation.question_id for expectation in expectations))
            rows_by_id = {
                str(row["question_id"]): dict(row)
                for row in questionnaire.rows
            }

            for expectation in expectations:
                row = rows_by_id[expectation.question_id]
                run_id = _question_run_id(expectation.question_id)
                logger.emit(
                    event="question_started",
                    status=rag.LOG_STATUS_STARTED,
                    message=f"Starting the live-provider smoke check for {expectation.question_id}.",
                    run_id=run_id,
                    question_id=expectation.question_id,
                    workspace_hash=index_status.workspace_hash,
                    index_action=index_status.index_action,
                    model=model,
                )

                retrieved_chunks = rag.retrieve_evidence_chunks_for_row(
                    row,
                    index_status=index_status,
                )
                retrieved_sources = _ordered_sources(
                    [chunk.source for chunk in retrieved_chunks]
                )
                _require(
                    bool(retrieved_sources),
                    f"{expectation.question_id} returned no retrieved source filenames.",
                )
                if expectation.primary_source is not None:
                    _require(
                        expectation.primary_source in retrieved_sources,
                        f"{expectation.question_id} retrieval did not include expected primary source {expectation.primary_source!r}.",
                    )

                result = rag.generate_answer_result(
                    expectation.question,
                    retrieved_chunks,
                    model=model,
                    question_id=expectation.question_id,
                    run_id=run_id,
                    on_log_event=logger.capture_rag_event,
                )
                cited_sources = _ordered_sources(
                    [citation.source for citation in result.citations]
                )
                opening_token = _opening_token(result.answer)

                _require(
                    result.answer_type == expectation.expected_answer_type,
                    f"{expectation.question_id} answer_type drifted to {result.answer_type!r}.",
                )
                _require(
                    result.status == expectation.expected_status,
                    f"{expectation.question_id} status drifted to {result.status!r}.",
                )
                _require(
                    result.confidence_band in expectation.allowed_confidence_bands,
                    f"{expectation.question_id} confidence band {result.confidence_band!r} was outside {expectation.allowed_confidence_bands!r}.",
                )
                _require(
                    opening_token == expectation.expected_opening_token,
                    f"{expectation.question_id} answer opening token drifted to {opening_token!r}.",
                )
                if expectation.primary_source is None:
                    _require(
                        not cited_sources,
                        f"{expectation.question_id} cited unsupported sources {cited_sources!r}.",
                    )
                else:
                    _require(
                        expectation.primary_source in cited_sources,
                        f"{expectation.question_id} citations did not include expected primary source {expectation.primary_source!r}.",
                    )

                logger.emit(
                    event="question_completed",
                    status=rag.LOG_STATUS_COMPLETED,
                    message=(
                        f"Validated live-provider behavior for {expectation.question_id} "
                        f"as {result.answer_type} with {result.status}."
                    ),
                    run_id=run_id,
                    question_id=expectation.question_id,
                    workspace_hash=index_status.workspace_hash,
                    index_action=index_status.index_action,
                    valid_citation_count=len(result.citations),
                    answer_type=result.answer_type,
                    confidence_band=result.confidence_band,
                    review_status=result.status,
                    model=model,
                    expected_primary_source=expectation.primary_source,
                    expected_opening_token=expectation.expected_opening_token,
                    opening_token=opening_token,
                    retrieved_sources=retrieved_sources,
                    cited_sources=cited_sources,
                    reviewer_note_present=_reviewer_note_present(result),
                    failed_closed=result.failed_closed,
                )

            logger.emit(
                event="live_smoke_completed",
                status=rag.LOG_STATUS_COMPLETED,
                message="Completed the canonical live-provider smoke trio without transcript leaks.",
                model=model,
                artifact_path=logger.log_path,
            )
            return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the optional live-provider smoke suite for one supported, one partial, "
            "and one unsupported questionnaire row."
        )
    )
    parser.add_argument(
        "--question-ids",
        nargs="+",
        default=list(DEFAULT_QUESTION_IDS),
        help="Question ids to verify through the real retrieval + provider path.",
    )
    parser.add_argument(
        "--model",
        default=rag.DEFAULT_OPENAI_ANSWER_MODEL,
        help="OpenAI model to use for the live-provider smoke checks.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(rag.LIVE_SMOKE_LOGS_DIR),
        help="Directory for the JSONL live-smoke log.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each structured verification record to stdout.",
    )
    args = parser.parse_args(argv)

    log_dir = Path(args.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = JsonlLogger(log_dir / LOG_FILE_NAME, verbose=args.verbose)
    try:
        return _run_live_smoke(
            question_ids=tuple(args.question_ids),
            model=str(args.model),
            logger=logger,
        )
    except Exception as exc:
        logger.emit(
            event="live_smoke_failed",
            status=rag.LOG_STATUS_FAILED,
            level="ERROR",
            message=f"Live-provider smoke failed because {type(exc).__name__}: {exc}",
            reason=type(exc).__name__.lower(),
            artifact_path=logger.log_path,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
