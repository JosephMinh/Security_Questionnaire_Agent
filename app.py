"""Streamlit entrypoint for the Security Questionnaire Agent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st

from generate_demo_data import (
    WorkspaceValidationError,
    expected_runtime_evidence_paths,
    manifest_path,
    prepare_demo_workspace,
    questionnaire_path,
    validate_runtime_workspace,
)
from rag import (
    APP_SUBTITLE,
    APP_TITLE,
    CHROMA_DIR,
    DEMO_MODE_LABEL,
    INDEX_ACTION_BLOCKED,
    INDEX_ACTION_CREATED,
    INDEX_ACTION_REBUILT_CONTENT_CHANGE,
    INDEX_ACTION_REBUILT_INTEGRITY,
    INDEX_ACTION_REUSED,
    RuntimeQuestionnaire,
    STATUS_NEEDS_REVIEW,
    STATUS_READY_FOR_REVIEW,
    current_workspace_hash,
    ensure_curated_evidence_index,
    evaluate_chroma_reuse,
    load_runtime_questionnaire,
    run_questionnaire_answer_pipeline,
)


LAST_RUN_ID_KEY = "last_run_id"
LAST_RUN_QUESTIONNAIRE_KEY = "last_run_questionnaire"
RESULTS_QUESTIONNAIRE_KEY = "results_questionnaire"
RUN_ACTION_FEEDBACK_KEY = "run_action_feedback"
WORKSPACE_ACTION_FEEDBACK_KEY = "workspace_action_feedback"

INDEX_ACTION_LABELS = {
    INDEX_ACTION_CREATED: "Created a fresh local evidence index.",
    INDEX_ACTION_REUSED: "Reused the current local evidence index.",
    INDEX_ACTION_REBUILT_CONTENT_CHANGE: "Rebuilt the index because the workspace changed.",
    INDEX_ACTION_REBUILT_INTEGRITY: "Rebuilt the index after integrity checks found an unsafe cache.",
    INDEX_ACTION_BLOCKED: "The local evidence index is not ready yet.",
}

INDEX_REASON_LABELS = {
    "created": "No reusable collection existed yet.",
    "reused": "The manifest hash and stored chunk inventory still match.",
    "workspace_hash_changed": "The runtime workspace changed since the last index build.",
    "force_rebuild": "You explicitly requested a rebuild.",
    "collection_missing": "No local Chroma collection exists yet.",
    "manifest_unavailable": "The workspace manifest is missing or invalid.",
    "chunk_count_missing": "The cached collection is missing its chunk-count metadata.",
    "collection_empty": "The cached collection exists but contains no evidence rows.",
    "chunk_count_mismatch": "The cached collection count no longer matches its metadata.",
    "expected_chunks_unavailable": "The expected curated evidence inventory could not be loaded.",
    "expected_chunk_count_mismatch": "The cached collection count does not match the curated evidence set.",
    "collection_payload_mismatch": "The cached collection payload no longer matches the curated evidence set.",
    "metadata_missing": "The cached collection is missing stored metadata for one or more chunks.",
    "metadata_chunk_id_missing": "The cached collection is missing logical chunk ids.",
    "duplicate_logical_chunk_ids": "The cached collection contains duplicate logical chunk ids.",
    "logical_chunk_id_mismatch": "The cached collection contains an unexpected logical chunk inventory.",
    "source_coverage_mismatch": "The cached collection sources no longer match the curated evidence pack.",
}


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Current read-only view of workspace and index readiness."""

    questionnaire_exists: bool
    manifest_exists: bool
    evidence_present_count: int
    evidence_total_count: int
    validation_ok: bool
    validation_lines: tuple[str, ...]
    workspace_hash: str | None
    index_ready: bool
    index_action: str
    index_reason: str
    actual_chunk_count: int
    stored_chunk_count: int | None
    stored_workspace_hash: str | None
    index_error: str | None = None


@dataclass(frozen=True)
class ActionFeedback:
    """One persisted result message from the last workspace action."""

    level: str
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class RunSectionState:
    """Read-only view of whether the run controls can execute safely."""

    questionnaire: RuntimeQuestionnaire | None
    total_questions: int
    can_run: bool
    readiness_lines: tuple[str, ...]


def _friendly_index_action(index_action: str) -> str:
    """Return one user-facing index action label."""
    return INDEX_ACTION_LABELS.get(index_action, index_action.replace("_", " ").capitalize())


def _friendly_index_reason(reason: str) -> str:
    """Return one user-facing index reason label."""
    return INDEX_REASON_LABELS.get(reason, reason.replace("_", " ").capitalize())


def _render_feedback(feedback: ActionFeedback | None) -> None:
    """Display the last workspace action result."""
    if feedback is None:
        return

    body = "\n".join(feedback.lines)
    if feedback.level == "success":
        st.success(f"{feedback.title}\n\n{body}")
        return
    if feedback.level == "warning":
        st.warning(f"{feedback.title}\n\n{body}")
        return
    st.error(f"{feedback.title}\n\n{body}")


def _workspace_validation_snapshot() -> tuple[bool, tuple[str, ...]]:
    """Return whether the runtime workspace currently validates."""
    try:
        validate_runtime_workspace()
    except WorkspaceValidationError as exc:
        return False, tuple(issue.render() for issue in exc.issues)
    return True, ()


def _workspace_snapshot() -> WorkspaceSnapshot:
    """Collect the current workspace and index view for the UI."""
    evidence_paths = expected_runtime_evidence_paths()
    validation_ok, validation_lines = _workspace_validation_snapshot()

    workspace_hash: str | None = None
    if manifest_path().exists():
        try:
            workspace_hash = current_workspace_hash()
        except (FileNotFoundError, ValueError):
            workspace_hash = None

    try:
        reuse_status = evaluate_chroma_reuse()
    except Exception as exc:  # pragma: no cover - defensive UI resilience
        return WorkspaceSnapshot(
            questionnaire_exists=questionnaire_path().exists(),
            manifest_exists=manifest_path().exists(),
            evidence_present_count=sum(path.exists() for path in evidence_paths),
            evidence_total_count=len(evidence_paths),
            validation_ok=validation_ok,
            validation_lines=validation_lines,
            workspace_hash=workspace_hash,
            index_ready=False,
            index_action=INDEX_ACTION_BLOCKED,
            index_reason="index_unavailable",
            actual_chunk_count=0,
            stored_chunk_count=None,
            stored_workspace_hash=None,
            index_error=str(exc),
        )

    return WorkspaceSnapshot(
        questionnaire_exists=questionnaire_path().exists(),
        manifest_exists=manifest_path().exists(),
        evidence_present_count=sum(path.exists() for path in evidence_paths),
        evidence_total_count=len(evidence_paths),
        validation_ok=validation_ok,
        validation_lines=validation_lines,
        workspace_hash=workspace_hash,
        index_ready=reuse_status.reusable,
        index_action=reuse_status.index_action,
        index_reason=reuse_status.reason,
        actual_chunk_count=reuse_status.actual_chunk_count,
        stored_chunk_count=reuse_status.stored_chunk_count,
        stored_workspace_hash=reuse_status.stored_workspace_hash,
    )


def _index_status_lines(index_status: object) -> tuple[str, ...]:
    """Render the action result lines for one index status object."""
    lines = [
        f"Index action: {_friendly_index_action(index_status.index_action)}",
        f"Index detail: {_friendly_index_reason(index_status.reason)}",
    ]
    if index_status.workspace_hash:
        lines.append(f"Workspace hash: {index_status.workspace_hash}")
    if index_status.actual_chunk_count:
        lines.append(f"Indexed chunks: {index_status.actual_chunk_count}")
    return tuple(lines)


def _workspace_validation_error_feedback(exc: WorkspaceValidationError) -> ActionFeedback:
    """Build one actionable feedback block for workspace validation failures."""
    return ActionFeedback(
        level="error",
        title="Workspace validation failed.",
        lines=tuple(issue.render() for issue in exc.issues),
    )


def _generic_action_error_feedback(action_name: str, exc: Exception) -> ActionFeedback:
    """Build one fallback feedback block for unexpected workspace-action errors."""
    return ActionFeedback(
        level="error",
        title=f"{action_name} failed.",
        lines=(
            str(exc),
            "Check the repo dependencies and rerun the action once the underlying problem is fixed.",
        ),
    )


def _load_demo_workspace_feedback(*, reset_index: bool) -> ActionFeedback:
    """Run the setup path and return one user-facing result block."""
    try:
        copied_assets = prepare_demo_workspace(reset_index=reset_index)
        index_status = ensure_curated_evidence_index(force_rebuild=False)
    except WorkspaceValidationError as exc:
        return _workspace_validation_error_feedback(exc)
    except Exception as exc:  # pragma: no cover - defensive UI resilience
        return _generic_action_error_feedback("Workspace preparation", exc)

    action_name = "Demo reset" if reset_index else "Demo workspace"
    lines = [f"Copied {len(copied_assets)} curated runtime assets into `data/`."]
    if reset_index:
        lines.append(f"Cleared the local Chroma cache under `{CHROMA_DIR}` before rebuilding.")
    lines.extend(_index_status_lines(index_status))
    return ActionFeedback(
        level="success" if index_status.ready else "warning",
        title=(
            f"{action_name} is ready."
            if index_status.ready
            else f"{action_name} loaded, but the index is still blocked."
        ),
        lines=tuple(lines),
    )


def _rebuild_index_feedback() -> ActionFeedback:
    """Run the explicit rebuild-index path and return one user-facing result block."""
    try:
        validate_runtime_workspace()
        index_status = ensure_curated_evidence_index(force_rebuild=True)
    except WorkspaceValidationError as exc:
        return _workspace_validation_error_feedback(exc)
    except Exception as exc:  # pragma: no cover - defensive UI resilience
        return _generic_action_error_feedback("Index rebuild", exc)

    return ActionFeedback(
        level="success" if index_status.ready else "warning",
        title=(
            "Index rebuild finished."
            if index_status.ready
            else "Index rebuild was attempted, but the index is still blocked."
        ),
        lines=_index_status_lines(index_status),
    )


def _persist_feedback(feedback: ActionFeedback) -> None:
    """Store one workspace feedback block across reruns."""
    st.session_state[WORKSPACE_ACTION_FEEDBACK_KEY] = feedback


def _persist_run_feedback(feedback: ActionFeedback) -> None:
    """Store one run-feedback block across reruns."""
    st.session_state[RUN_ACTION_FEEDBACK_KEY] = feedback


def _clear_last_run() -> None:
    """Remove any persisted questionnaire results from a prior run."""
    st.session_state.pop(LAST_RUN_ID_KEY, None)
    st.session_state.pop(LAST_RUN_QUESTIONNAIRE_KEY, None)


def _persist_last_run(questionnaire: RuntimeQuestionnaire, *, run_id: str) -> None:
    """Store the most recent completed questionnaire run in session state."""
    st.session_state[LAST_RUN_ID_KEY] = run_id
    st.session_state[LAST_RUN_QUESTIONNAIRE_KEY] = questionnaire


def _clear_results_questionnaire() -> None:
    """Remove any persisted results-surface questionnaire snapshot."""
    st.session_state.pop(RESULTS_QUESTIONNAIRE_KEY, None)


def _persist_results_questionnaire(questionnaire: RuntimeQuestionnaire) -> None:
    """Store the most recent partial or completed questionnaire results snapshot."""
    st.session_state[RESULTS_QUESTIONNAIRE_KEY] = questionnaire


def _results_questionnaire() -> RuntimeQuestionnaire | None:
    """Return the most recent questionnaire snapshot for the results surface."""
    questionnaire = st.session_state.get(RESULTS_QUESTIONNAIRE_KEY)
    if isinstance(questionnaire, RuntimeQuestionnaire):
        return questionnaire
    return None


def _new_run_id() -> str:
    """Return one deterministic-enough run identifier for UI-triggered runs."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"demo-run-{timestamp}-{uuid4().hex[:8]}"


def _question_label(row_like: Mapping[str, object]) -> str:
    """Render one compact reviewer-facing question label."""
    return f"{row_like['question_id']} - {row_like['Question']}"


def _progress_summary_text(completed_count: int, total_questions: int) -> str:
    """Return one user-facing row-count summary."""
    return f"Completed {completed_count} of {total_questions} questions."


def _progress_bar_text(completed_count: int, total_questions: int) -> str:
    """Return one progress-bar label for the current run state."""
    return f"{completed_count}/{total_questions} questions completed"


def _set_run_progress(
    progress_bar: object,
    summary_placeholder: object,
    status_placeholder: object,
    *,
    completed_count: int,
    total_questions: int,
    status_text: str,
    status_level: str = "info",
) -> None:
    """Update the live run progress widgets in place."""
    progress_value = 0.0 if total_questions <= 0 else completed_count / total_questions
    progress_bar.progress(progress_value, text=_progress_bar_text(completed_count, total_questions))
    summary_placeholder.caption(_progress_summary_text(completed_count, total_questions))
    if status_level == "success":
        status_placeholder.success(status_text)
        return
    if status_level == "warning":
        status_placeholder.warning(status_text)
        return
    status_placeholder.info(status_text)


def _build_run_section_state(snapshot: WorkspaceSnapshot) -> RunSectionState:
    """Collect the current questionnaire/run readiness state for the UI."""
    readiness_lines: list[str] = []
    questionnaire: RuntimeQuestionnaire | None = None
    can_run = snapshot.validation_ok and snapshot.questionnaire_exists

    if not snapshot.questionnaire_exists:
        readiness_lines.append(
            "Load the demo workspace to materialize the curated questionnaire before running the copilot."
        )
    else:
        try:
            questionnaire = load_runtime_questionnaire()
        except (FileNotFoundError, ValueError) as exc:
            readiness_lines.append(str(exc))
            can_run = False

    if not snapshot.validation_ok:
        readiness_lines.append(
            "Fix the workspace validation issues above before starting the copilot run."
        )
        can_run = False

    total_questions = len(questionnaire.rows) if questionnaire is not None else 0
    if questionnaire is not None and total_questions == 0:
        readiness_lines.append("The runtime questionnaire does not contain any answerable rows.")
        can_run = False

    if questionnaire is not None and snapshot.validation_ok and not snapshot.index_ready:
        readiness_lines.append(
            "The local evidence index will be checked again when the run starts."
        )

    return RunSectionState(
        questionnaire=questionnaire,
        total_questions=total_questions,
        can_run=can_run,
        readiness_lines=tuple(readiness_lines),
    )


def _build_run_feedback(
    questionnaire: RuntimeQuestionnaire,
    *,
    run_id: str,
    index_action: str,
) -> ActionFeedback:
    """Return one compact post-run summary block."""
    ready_count = sum(
        str(row["Status"]) == STATUS_READY_FOR_REVIEW for row in questionnaire.rows
    )
    needs_review_count = sum(
        str(row["Status"]) == STATUS_NEEDS_REVIEW for row in questionnaire.rows
    )
    return ActionFeedback(
        level="success",
        title="Copilot run finished.",
        lines=(
            f"Run ID: {run_id}",
            f"Processed {len(questionnaire.rows)} questions.",
            f"Ready for Review: {ready_count}",
            f"Needs Review: {needs_review_count}",
            f"Index action: {_friendly_index_action(index_action)}",
        ),
    )


def _questionnaire_has_results(questionnaire: RuntimeQuestionnaire) -> bool:
    """Return whether any row currently contains visible result data."""
    return any(
        str(row["Status"]).strip() or str(row["Answer"]).strip()
        for row in questionnaire.rows
    )


def _render_results_surface(
    workspace_snapshot: WorkspaceSnapshot,
    *,
    questionnaire: RuntimeQuestionnaire | None,
    summary_placeholder: object,
    table_placeholder: object,
) -> None:
    """Render the results cards and the primary table when row output exists."""
    if questionnaire is None or not _questionnaire_has_results(questionnaire):
        summary_placeholder.empty()
        table_placeholder.info("Results will populate here as questions finish processing.")
        return

    ready_count = sum(
        str(row["Status"]) == STATUS_READY_FOR_REVIEW for row in questionnaire.rows
    )
    needs_review_count = sum(
        str(row["Status"]) == STATUS_NEEDS_REVIEW for row in questionnaire.rows
    )
    with summary_placeholder.container():
        st.markdown("**Results Overview**")
        question_column, ready_column, review_column, sources_column = st.columns(4)
        question_column.metric("Questions", len(questionnaire.rows))
        ready_column.metric("Ready for Review", ready_count)
        review_column.metric("Needs Review", needs_review_count)
        sources_column.metric("Sources Indexed", workspace_snapshot.evidence_present_count)

    table_rows = [
        {
            "Question ID": str(row["Question ID"]),
            "Category": str(row["Category"]),
            "Answer": str(row["Answer"]),
            "Confidence": str(row["Confidence"]),
            "Status": str(row["Status"]),
        }
        for row in questionnaire.rows
    ]
    table_placeholder.dataframe(table_rows, hide_index=True, width="stretch")


def _render_idle_run_state(
    run_state: RunSectionState,
    *,
    progress_bar: object,
    summary_placeholder: object,
    status_placeholder: object,
) -> None:
    """Render the resting progress state before or after a completed run."""
    last_questionnaire = st.session_state.get(LAST_RUN_QUESTIONNAIRE_KEY)
    last_run_id = st.session_state.get(LAST_RUN_ID_KEY)
    if isinstance(last_questionnaire, RuntimeQuestionnaire) and last_questionnaire.rows:
        total_questions = len(last_questionnaire.rows)
        _set_run_progress(
            progress_bar,
            summary_placeholder,
            status_placeholder,
            completed_count=total_questions,
            total_questions=total_questions,
            status_text=(
                f"Last completed run: {last_run_id}. "
                f"All {total_questions} questions now have row results."
            ),
            status_level="success",
        )
        return

    if run_state.total_questions > 0:
        _set_run_progress(
            progress_bar,
            summary_placeholder,
            status_placeholder,
            completed_count=0,
            total_questions=run_state.total_questions,
            status_text=(
                "Current question status will appear here once the run starts."
                if run_state.can_run
                else "Fix the workspace readiness issues above before starting the copilot run."
            ),
            status_level="info" if run_state.can_run else "warning",
        )
        return

    progress_bar.progress(
        0.0,
        text="Question progress will appear here once the curated workspace is ready.",
    )
    summary_placeholder.caption(
        "Total questions will appear once the runtime questionnaire is available."
    )
    status_placeholder.warning(
        "Load the curated workspace before starting the copilot run."
    )


def _run_copilot_feedback(
    run_state: RunSectionState,
    *,
    workspace_snapshot: WorkspaceSnapshot,
    progress_bar: object,
    progress_summary_placeholder: object,
    status_placeholder: object,
    results_summary_placeholder: object,
    results_table_placeholder: object,
) -> ActionFeedback:
    """Execute the run button path and return one persisted feedback block."""
    questionnaire = run_state.questionnaire
    if questionnaire is None:
        return ActionFeedback(
            level="warning",
            title="Copilot run is blocked.",
            lines=run_state.readiness_lines
            or ("Load the curated questionnaire before starting the run.",),
        )

    _clear_last_run()
    _clear_results_questionnaire()
    _render_results_surface(
        workspace_snapshot,
        questionnaire=None,
        summary_placeholder=results_summary_placeholder,
        table_placeholder=results_table_placeholder,
    )
    try:
        status_placeholder.info("Ensuring the local evidence index is ready for this run.")
        index_status = ensure_curated_evidence_index(force_rebuild=False)
        if not index_status.ready:
            return ActionFeedback(
                level="warning",
                title="Copilot run is blocked.",
                lines=(
                    "The local evidence index is not ready for question answering yet.",
                    *_index_status_lines(index_status),
                ),
            )

        total_questions = len(questionnaire.rows)
        if total_questions <= 0:
            return ActionFeedback(
                level="warning",
                title="Copilot run is blocked.",
                lines=("The runtime questionnaire does not contain any answerable rows.",),
            )

        run_id = _new_run_id()
        _set_run_progress(
            progress_bar,
            progress_summary_placeholder,
            status_placeholder,
            completed_count=0,
            total_questions=total_questions,
            status_text=f"Current question: {_question_label(questionnaire.rows[0])}",
            status_level="info",
        )

        def on_row_completed(
            run_questionnaire: RuntimeQuestionnaire,
            row_index: int,
        ) -> None:
            completed_row = run_questionnaire.rows[row_index]
            completed_label = _question_label(completed_row)
            completed_status = str(completed_row["Status"])
            completed_count = row_index + 1
            if completed_count < total_questions:
                next_label = _question_label(run_questionnaire.rows[completed_count])
                status_text = (
                    f"Completed {completed_label} ({completed_status}). "
                    f"Current question: {next_label}"
                )
                status_level = "info"
            else:
                status_text = (
                    f"Run finished after {completed_label} ({completed_status})."
                )
                status_level = "success"

            _persist_results_questionnaire(run_questionnaire)
            _set_run_progress(
                progress_bar,
                progress_summary_placeholder,
                status_placeholder,
                completed_count=completed_count,
                total_questions=total_questions,
                status_text=status_text,
                status_level=status_level,
            )
            _render_results_surface(
                workspace_snapshot,
                questionnaire=run_questionnaire,
                summary_placeholder=results_summary_placeholder,
                table_placeholder=results_table_placeholder,
            )

        completed_questionnaire = run_questionnaire_answer_pipeline(
            questionnaire,
            index_status=index_status,
            run_id=run_id,
            on_row_completed=on_row_completed,
        )
    except WorkspaceValidationError as exc:
        _clear_last_run()
        return _workspace_validation_error_feedback(exc)
    except Exception as exc:  # pragma: no cover - defensive UI resilience
        _clear_last_run()
        return _generic_action_error_feedback("Copilot run", exc)

    _persist_last_run(completed_questionnaire, run_id=run_id)
    _persist_results_questionnaire(completed_questionnaire)
    return _build_run_feedback(
        completed_questionnaire,
        run_id=run_id,
        index_action=index_status.index_action,
    )


def _render_workspace_files(snapshot: WorkspaceSnapshot) -> None:
    """Render the current workspace file and validation state."""
    st.markdown("**Workspace Files**")
    st.markdown(
        "\n".join(
            (
                f"- Questionnaire workbook: {'present' if snapshot.questionnaire_exists else 'missing'}",
                f"- Evidence pack files: {snapshot.evidence_present_count}/{snapshot.evidence_total_count} present",
                f"- Workspace manifest: {'present' if snapshot.manifest_exists else 'missing'}",
            )
        )
    )
    if snapshot.workspace_hash:
        st.caption(f"Workspace hash: {snapshot.workspace_hash}")

    if snapshot.validation_ok:
        st.success("Workspace validation passed.")
        return

    st.error("Workspace validation failed.")
    for line in snapshot.validation_lines:
        st.write(line)


def _render_index_status(snapshot: WorkspaceSnapshot) -> None:
    """Render the current index reuse/rebuild readiness state."""
    st.markdown("**Index Status**")
    if snapshot.index_error:
        st.error("Index status could not be inspected.")
        st.write(snapshot.index_error)
        return

    if snapshot.index_ready:
        st.success("Index ready for reuse.")
    else:
        st.warning("Index is not ready yet.")

    st.markdown(
        "\n".join(
            (
                f"- Action: {_friendly_index_action(snapshot.index_action)}",
                f"- Detail: {_friendly_index_reason(snapshot.index_reason)}",
                f"- Cached chunk count: {snapshot.actual_chunk_count}",
                f"- Stored chunk count: {snapshot.stored_chunk_count or 0}",
            )
        )
    )
    if snapshot.stored_workspace_hash:
        st.caption(f"Stored index workspace hash: {snapshot.stored_workspace_hash}")


def render_workspace_section() -> WorkspaceSnapshot:
    """Render the workspace preparation controls and live readiness state."""
    st.subheader("Workspace")
    st.write(
        "Prepare the curated runtime workspace, reuse the local evidence index when the "
        "manifest matches, and surface actionable recovery text when something drifts."
    )

    load_clicked = st.button(
        "Load Demo Workspace",
        type="primary",
        width="stretch",
    )
    with st.expander("Advanced"):
        st.caption(
            "Recovery-only controls. Use these when you need to rebuild the local index "
            "or reset the curated demo workspace."
        )
        rebuild_clicked = st.button("Rebuild Index", width="stretch")
        reset_clicked = st.button("Reset Demo", width="stretch")

    if load_clicked:
        with st.spinner("Preparing the demo workspace and ensuring the local index is ready..."):
            _persist_feedback(_load_demo_workspace_feedback(reset_index=False))
    elif rebuild_clicked:
        with st.spinner("Rebuilding the local evidence index..."):
            _persist_feedback(_rebuild_index_feedback())
    elif reset_clicked:
        with st.spinner("Resetting the demo workspace and rebuilding the local index..."):
            _persist_feedback(_load_demo_workspace_feedback(reset_index=True))

    _render_feedback(st.session_state.get(WORKSPACE_ACTION_FEEDBACK_KEY))
    snapshot = _workspace_snapshot()

    left_column, right_column = st.columns((1.1, 1.0))
    with left_column:
        _render_workspace_files(snapshot)
    with right_column:
        _render_index_status(snapshot)
    return snapshot


def render_run_section(workspace_snapshot: WorkspaceSnapshot) -> None:
    """Render the main run controls and visible row-by-row progress state."""
    st.subheader("Run Copilot")
    st.write(
        "Process the curated questionnaire one row at a time against the local evidence "
        "pack, with visible progress and current-question status throughout the run."
    )

    run_state = _build_run_section_state(workspace_snapshot)

    count_column, button_column = st.columns((0.9, 1.3))
    with count_column:
        st.metric("Total Questions", run_state.total_questions)
    with button_column:
        run_clicked = st.button(
            "Run Copilot",
            type="primary",
            width="stretch",
            disabled=not run_state.can_run,
        )

    for line in run_state.readiness_lines:
        st.caption(line)

    progress_bar = st.progress(
        0.0,
        text=(
            _progress_bar_text(0, run_state.total_questions)
            if run_state.total_questions > 0
            else "Question progress will appear here once the curated workspace is ready."
        ),
    )
    summary_placeholder = st.empty()
    status_placeholder = st.empty()
    _render_idle_run_state(
        run_state,
        progress_bar=progress_bar,
        summary_placeholder=summary_placeholder,
        status_placeholder=status_placeholder,
    )
    results_summary_placeholder = st.empty()
    results_table_placeholder = st.empty()
    _render_results_surface(
        workspace_snapshot,
        questionnaire=_results_questionnaire(),
        summary_placeholder=results_summary_placeholder,
        table_placeholder=results_table_placeholder,
    )

    if run_clicked:
        with st.spinner("Running the curated questionnaire one row at a time..."):
            _persist_run_feedback(
                _run_copilot_feedback(
                    run_state,
                    workspace_snapshot=workspace_snapshot,
                    progress_bar=progress_bar,
                    progress_summary_placeholder=summary_placeholder,
                    status_placeholder=status_placeholder,
                    results_summary_placeholder=results_summary_placeholder,
                    results_table_placeholder=results_table_placeholder,
                )
            )

    _render_feedback(st.session_state.get(RUN_ACTION_FEEDBACK_KEY))


def main() -> None:
    """Run the Streamlit app."""
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    st.markdown(f"`{DEMO_MODE_LABEL}`")
    st.write(
        "Single curated workspace demo: one prepared questionnaire, one bundled "
        "evidence pack, and one local review flow inside a single workspace. This app "
        "does not branch into generic uploads or multi-workspace intake."
    )
    workspace_snapshot = render_workspace_section()
    render_run_section(workspace_snapshot)


if __name__ == "__main__":
    main()


__all__ = [
    "APP_SUBTITLE",
    "APP_TITLE",
    "DEMO_MODE_LABEL",
    "main",
    "render_run_section",
    "render_workspace_section",
]
