"""Streamlit entrypoint for the Security Questionnaire Agent."""

from __future__ import annotations

from dataclasses import dataclass

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
    ensure_curated_evidence_index,
    evaluate_chroma_reuse,
    current_workspace_hash,
)


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


def render_workspace_section() -> None:
    """Render the workspace preparation controls and live readiness state."""
    st.subheader("Workspace")
    st.write(
        "Prepare the curated runtime workspace, reuse the local evidence index when the "
        "manifest matches, and surface actionable recovery text when something drifts."
    )

    load_clicked = st.button(
        "Load Demo Workspace",
        type="primary",
        use_container_width=True,
    )
    with st.expander("Advanced"):
        rebuild_clicked = st.button("Rebuild Index", use_container_width=True)
        reset_clicked = st.button("Reset Demo", use_container_width=True)

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


def main() -> None:
    """Run the Streamlit app."""
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    st.markdown(f"`{DEMO_MODE_LABEL}`")
    render_workspace_section()


if __name__ == "__main__":
    main()


__all__ = [
    "APP_SUBTITLE",
    "APP_TITLE",
    "DEMO_MODE_LABEL",
    "main",
    "render_workspace_section",
]
