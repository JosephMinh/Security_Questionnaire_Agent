"""Core contracts and RAG helpers for the Security Questionnaire Agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shlex import join as shell_join
from typing import Final, Mapping, Sequence

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent

APP_TITLE: Final[str] = "AI Security Questionnaire Copilot"
APP_SUBTITLE: Final[str] = (
    "Answer one curated security questionnaire from one bundled evidence pack."
)
DEMO_MODE_LABEL: Final[str] = (
    "Demo Mode: curated questionnaire + bundled evidence pack"
)

SEED_DATA_DIR: Final[Path] = REPO_ROOT / "seed_data"
SEED_QUESTIONNAIRE_DIR: Final[Path] = SEED_DATA_DIR / "questionnaire"
SEED_EVIDENCE_DIR: Final[Path] = SEED_DATA_DIR / "evidence"

DATA_DIR: Final[Path] = REPO_ROOT / "data"
RUNTIME_QUESTIONNAIRES_DIR: Final[Path] = DATA_DIR / "questionnaires"
RUNTIME_EVIDENCE_DIR: Final[Path] = DATA_DIR / "evidence"
OUTPUTS_DIR: Final[Path] = DATA_DIR / "outputs"
CHROMA_DIR: Final[Path] = DATA_DIR / "chroma"

QUESTIONNAIRE_FILE_NAME: Final[str] = "Demo_Security_Questionnaire.xlsx"
SOC2_SUMMARY_FILE_NAME: Final[str] = "AcmeCloud_SOC2_Summary.pdf"
ENCRYPTION_POLICY_FILE_NAME: Final[str] = "Encryption_Policy.md"
ACCESS_CONTROL_POLICY_FILE_NAME: Final[str] = "Access_Control_Policy.md"
INCIDENT_RESPONSE_POLICY_FILE_NAME: Final[str] = "Incident_Response_Policy.md"
BACKUP_RECOVERY_POLICY_FILE_NAME: Final[str] = "Backup_and_Recovery_Policy.md"
MANIFEST_FILE_NAME: Final[str] = "workspace_manifest.json"

ANSWERED_QUESTIONNAIRE_FILE_NAME: Final[str] = "Answered_Questionnaire.xlsx"
REVIEW_SUMMARY_FILE_NAME: Final[str] = "Review_Summary.md"
NEEDS_REVIEW_FILE_NAME: Final[str] = "Needs_Review.csv"

QUESTION_SHEET_NAME: Final[str] = "Questions"

SEED_QUESTION_COLUMNS: Final[tuple[str, ...]] = (
    "Question ID",
    "Category",
    "Question",
)
VISIBLE_OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "Answer",
    "Evidence",
    "Confidence",
    "Status",
    "Reviewer Notes",
)
VISIBLE_EXPORT_COLUMNS: Final[tuple[str, ...]] = (
    *SEED_QUESTION_COLUMNS,
    *VISIBLE_OUTPUT_COLUMNS,
)
MAIN_RESULTS_TABLE_COLUMNS: Final[tuple[str, ...]] = (
    "Question ID",
    "Category",
    "Answer",
    "Confidence",
    "Status",
)
REVIEW_QUEUE_COLUMNS: Final[tuple[str, ...]] = (
    "Question ID",
    "Category",
    "Question",
    "Answer",
    "Confidence",
    "Status",
    "Reviewer Notes",
)
SUMMARY_CARD_LABELS: Final[tuple[str, ...]] = (
    "Questions",
    "Ready for Review",
    "Needs Review",
    "Sources Indexed",
)

STATUS_READY_FOR_REVIEW: Final[str] = "Ready for Review"
STATUS_NEEDS_REVIEW: Final[str] = "Needs Review"

ANSWER_TYPE_SUPPORTED: Final[str] = "supported"
ANSWER_TYPE_PARTIAL: Final[str] = "partial"
ANSWER_TYPE_UNSUPPORTED: Final[str] = "unsupported"
ANSWER_TYPES: Final[tuple[str, ...]] = (
    ANSWER_TYPE_SUPPORTED,
    ANSWER_TYPE_PARTIAL,
    ANSWER_TYPE_UNSUPPORTED,
)

CONFIDENCE_BAND_HIGH: Final[str] = "High"
CONFIDENCE_BAND_MEDIUM: Final[str] = "Medium"
CONFIDENCE_BAND_LOW: Final[str] = "Low"

READY_STATUS_FILL: Final[str] = "light_green"
REVIEW_STATUS_FILL: Final[str] = "light_amber"

SUPPORTED_WITH_ONE_CITATION_SCORE: Final[float] = 0.78
SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE: Final[float] = 0.90
PARTIAL_SCORE: Final[float] = 0.55
UNSUPPORTED_SCORE: Final[float] = 0.30
FAIL_CLOSED_SCORE: Final[float] = 0.25
HIGH_CONFIDENCE_THRESHOLD: Final[float] = 0.85
MEDIUM_CONFIDENCE_THRESHOLD: Final[float] = 0.60
REVIEW_QUEUE_THRESHOLD: Final[float] = 0.75

COLLECTION_NAME: Final[str] = "security_questionnaire_demo"
CHUNK_SIZE_CHARS: Final[int] = 700
CHUNK_OVERLAP_CHARS: Final[int] = 100
RETRIEVAL_TOP_K: Final[int] = 5
MAX_VISIBLE_CITATIONS: Final[int] = 2
MODEL_RETRY_LIMIT: Final[int] = 1

INDEX_ACTION_CREATED: Final[str] = "created"
INDEX_ACTION_REUSED: Final[str] = "reused"
INDEX_ACTION_REBUILT_CONTENT_CHANGE: Final[str] = "rebuilt_content_change"
INDEX_ACTION_REBUILT_INTEGRITY: Final[str] = "rebuilt_integrity"
INDEX_ACTION_BLOCKED: Final[str] = "blocked"

REQUIRED_ENV_VARS: Final[tuple[str, ...]] = ("OPENAI_API_KEY",)

EXPECTED_EVIDENCE_FILE_NAMES: Final[tuple[str, ...]] = (
    SOC2_SUMMARY_FILE_NAME,
    ENCRYPTION_POLICY_FILE_NAME,
    ACCESS_CONTROL_POLICY_FILE_NAME,
    INCIDENT_RESPONSE_POLICY_FILE_NAME,
    BACKUP_RECOVERY_POLICY_FILE_NAME,
)
EXPECTED_QUESTION_IDS: Final[tuple[str, ...]] = tuple(
    f"Q{question_number:02d}" for question_number in range(1, 23)
)
ANSWER_OPENING_TOKENS: Final[tuple[str, ...]] = (
    "Yes.",
    "No.",
    "Partially.",
    "Not stated.",
)

RUNTIME_DIRECTORIES: Final[tuple[Path, ...]] = (
    RUNTIME_QUESTIONNAIRES_DIR,
    RUNTIME_EVIDENCE_DIR,
    OUTPUTS_DIR,
    CHROMA_DIR,
)
WORKSPACE_HASH_DIRECTORIES: Final[tuple[Path, ...]] = (
    RUNTIME_QUESTIONNAIRES_DIR,
    RUNTIME_EVIDENCE_DIR,
)

SEED_TO_RUNTIME_PATHS: Final[tuple[tuple[Path, Path], ...]] = (
    (
        SEED_QUESTIONNAIRE_DIR / QUESTIONNAIRE_FILE_NAME,
        RUNTIME_QUESTIONNAIRES_DIR / QUESTIONNAIRE_FILE_NAME,
    ),
    *tuple(
        (
            SEED_EVIDENCE_DIR / evidence_file_name,
            RUNTIME_EVIDENCE_DIR / evidence_file_name,
        )
        for evidence_file_name in EXPECTED_EVIDENCE_FILE_NAMES
    ),
)

TESTS_DIR: Final[Path] = REPO_ROOT / "tests"
UNIT_TESTS_DIR: Final[Path] = TESTS_DIR / "unit"
UI_TESTS_DIR: Final[Path] = TESTS_DIR / "ui"
E2E_TESTS_DIR: Final[Path] = TESTS_DIR / "e2e"

TEST_FIXTURES_DIR: Final[Path] = TESTS_DIR / "fixtures"
EXPECTED_OUTCOMES_FIXTURE_PATH: Final[Path] = (
    TEST_FIXTURES_DIR / "expected_outcomes.json"
)
STUBBED_OPENAI_FIXTURES_DIR: Final[Path] = TEST_FIXTURES_DIR / "stubbed_openai"
WORKSPACE_FIXTURES_DIR: Final[Path] = TEST_FIXTURES_DIR / "workspaces"
INDEX_FIXTURES_DIR: Final[Path] = TEST_FIXTURES_DIR / "indexes"

VERIFICATION_ARTIFACTS_DIR: Final[Path] = OUTPUTS_DIR / "verification"
UNIT_TEST_LOGS_DIR: Final[Path] = VERIFICATION_ARTIFACTS_DIR / "unit"
UI_TEST_LOGS_DIR: Final[Path] = VERIFICATION_ARTIFACTS_DIR / "ui"
E2E_TEST_LOGS_DIR: Final[Path] = VERIFICATION_ARTIFACTS_DIR / "e2e"
LIVE_SMOKE_LOGS_DIR: Final[Path] = VERIFICATION_ARTIFACTS_DIR / "live_smoke"

LOG_FORMAT_NAME: Final[str] = "jsonl"
LOG_FILE_EXTENSION: Final[str] = ".jsonl"

LOG_COMPONENT_SETUP: Final[str] = "setup"
LOG_COMPONENT_INDEXING: Final[str] = "indexing"
LOG_COMPONENT_PIPELINE: Final[str] = "pipeline"
LOG_COMPONENT_UI: Final[str] = "ui"
LOG_COMPONENT_EXPORT: Final[str] = "export"
LOG_COMPONENT_VERIFICATION: Final[str] = "verification"
LOG_COMPONENTS: Final[tuple[str, ...]] = (
    LOG_COMPONENT_SETUP,
    LOG_COMPONENT_INDEXING,
    LOG_COMPONENT_PIPELINE,
    LOG_COMPONENT_UI,
    LOG_COMPONENT_EXPORT,
    LOG_COMPONENT_VERIFICATION,
)

LOG_STATUS_STARTED: Final[str] = "started"
LOG_STATUS_COMPLETED: Final[str] = "completed"
LOG_STATUS_FAILED: Final[str] = "failed"
LOG_STATUS_BLOCKED: Final[str] = "blocked"
LOG_STATUS_SKIPPED: Final[str] = "skipped"
LOG_STATUS_RETRYING: Final[str] = "retrying"
LOG_STATUSES: Final[tuple[str, ...]] = (
    LOG_STATUS_STARTED,
    LOG_STATUS_COMPLETED,
    LOG_STATUS_FAILED,
    LOG_STATUS_BLOCKED,
    LOG_STATUS_SKIPPED,
    LOG_STATUS_RETRYING,
)

LOG_LEVELS: Final[tuple[str, ...]] = ("INFO", "WARNING", "ERROR")
LOG_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "ts",
    "level",
    "component",
    "event",
    "run_id",
    "status",
    "message",
)
LOG_OPTIONAL_FIELDS: Final[tuple[str, ...]] = (
    "question_id",
    "workspace_hash",
    "manifest_hash",
    "index_action",
    "retrieved_chunk_count",
    "valid_citation_count",
    "retry_attempt",
    "artifact_path",
    "reason",
)


@dataclass(frozen=True)
class VerificationCommand:
    """One canonical verification command and the conditions around it."""

    name: str
    argv: tuple[str, ...]
    purpose: str
    artifacts_dir: Path | None = None
    requires_openai_api_key: bool = False
    optional: bool = False

    def shell_command(self) -> str:
        """Return the canonical shell string for humans and README output."""
        return shell_join(self.argv)


@dataclass(frozen=True)
class TestSeam:
    """Describe a planned injection or isolation boundary for deterministic tests."""

    name: str
    planned_surface: str
    test_double_strategy: str
    why_it_exists: str


@dataclass(frozen=True)
class LogFieldSpec:
    """Describe one required or optional structured log field."""

    name: str
    required: bool
    example: str
    purpose: str


CANONICAL_VERIFICATION_COMMANDS: Final[tuple[VerificationCommand, ...]] = (
    VerificationCommand(
        name="quick_unit",
        argv=(
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests/unit",
            "-p",
            "test_*.py",
            "-v",
        ),
        purpose="Fast confidence check for pure unit-level contracts and helpers.",
        artifacts_dir=UNIT_TEST_LOGS_DIR,
    ),
    VerificationCommand(
        name="ui_suite",
        argv=(
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests/ui",
            "-p",
            "test_*.py",
            "-v",
        ),
        purpose="Page-level Streamlit checks for the golden-path operator workflow.",
        artifacts_dir=UI_TEST_LOGS_DIR,
    ),
    VerificationCommand(
        name="deterministic_e2e",
        argv=(
            "python",
            "tests/e2e/run_deterministic_demo.py",
            "--log-dir",
            str(E2E_TEST_LOGS_DIR),
            "--verbose",
        ),
        purpose=(
            "Full local golden-path validation with stubbed model responses and "
            "deterministic evidence expectations."
        ),
        artifacts_dir=E2E_TEST_LOGS_DIR,
    ),
    VerificationCommand(
        name="failure_e2e",
        argv=(
            "python",
            "tests/e2e/run_failure_paths.py",
            "--log-dir",
            str(E2E_TEST_LOGS_DIR),
            "--verbose",
        ),
        purpose=(
            "Failure, retry, review-routing, blocked-state, and index-reuse/rebuild "
            "coverage with deterministic fixtures."
        ),
        artifacts_dir=E2E_TEST_LOGS_DIR,
    ),
    VerificationCommand(
        name="live_smoke",
        argv=(
            "python",
            "tests/e2e/run_live_smoke.py",
            "--question-ids",
            "Q01",
            "Q17",
            "Q21",
            "--log-dir",
            str(LIVE_SMOKE_LOGS_DIR),
            "--verbose",
        ),
        purpose=(
            "Optional real-provider smoke pass for one supported, one partial, and "
            "one unsupported question when OPENAI_API_KEY is available."
        ),
        artifacts_dir=LIVE_SMOKE_LOGS_DIR,
        requires_openai_api_key=True,
        optional=True,
    ),
    VerificationCommand(
        name="closeout_audit",
        argv=("br-closeout-audit", "--issue", "<issue-id>"),
        purpose=(
            "Required audit before closing high-risk implementation beads and "
            "required again after verification-heavy test/logging changes."
        ),
        optional=False,
    ),
)

QUICK_CONFIDENCE_COMMAND_NAMES: Final[tuple[str, ...]] = ("quick_unit",)
FULL_LOCAL_VALIDATION_COMMAND_NAMES: Final[tuple[str, ...]] = (
    "quick_unit",
    "ui_suite",
    "deterministic_e2e",
    "failure_e2e",
)
OPTIONAL_LIVE_VALIDATION_COMMAND_NAMES: Final[tuple[str, ...]] = ("live_smoke",)

CLOSEOUT_AUDIT_RULES: Final[tuple[str, ...]] = (
    "Run br-closeout-audit before closing any high-risk bead that changes runtime, retrieval, scoring, or export behavior.",
    "Run br-closeout-audit again after closing verification-heavy work that adds or materially changes tests, e2e scripts, or diagnostic logging.",
)

TEST_SEAMS: Final[tuple[TestSeam, ...]] = (
    TestSeam(
        name="workspace_setup",
        planned_surface=(
            "generate_demo_data.py functions that create runtime directories, copy "
            "seed files, compute manifests, and reset outputs from explicit root paths"
        ),
        test_double_strategy=(
            "Use temporary directories and fixture trees rather than mutating the "
            "real repo workspace."
        ),
        why_it_exists=(
            "Workspace setup is filesystem-heavy and must be repeatable, idempotent, "
            "and safe to exercise in unit and e2e tests."
        ),
    ),
    TestSeam(
        name="openai_embeddings",
        planned_surface=(
            "rag.py adapter or factory that produces embeddings independently from "
            "answer generation"
        ),
        test_double_strategy=(
            "Inject deterministic fake embedding responses or fixed vectors without "
            "calling the network."
        ),
        why_it_exists=(
            "Indexing and retrieval tests must stay deterministic and must not depend "
            "on a live provider."
        ),
    ),
    TestSeam(
        name="openai_answers",
        planned_surface=(
            "rag.py adapter or factory that receives prompt payloads and returns the "
            "structured answer contract"
        ),
        test_double_strategy=(
            "Swap in scripted payload fixtures for supported, partial, unsupported, "
            "malformed, and retry-triggering responses."
        ),
        why_it_exists=(
            "Prompting, validation, scoring, and fail-closed behavior need exact, "
            "repeatable answer payloads."
        ),
    ),
    TestSeam(
        name="chroma_index",
        planned_surface=(
            "rag.py client or collection boundary that isolates persistence, reuse, "
            "rebuild, and integrity checks from chunk construction"
        ),
        test_double_strategy=(
            "Use temp persistence roots or fake collection objects to force reuse, "
            "stale-state, and rebuild scenarios deterministically."
        ),
        why_it_exists=(
            "The index lifecycle is central to correctness but should be testable "
            "without relying on implicit ambient state."
        ),
    ),
    TestSeam(
        name="result_shaping",
        planned_surface=(
            "Pure helpers in rag.py that assemble canonical result rows, evidence "
            "labels, reviewer notes, export values, and review ordering"
        ),
        test_double_strategy=(
            "Call helpers directly with small fixtures and assert exact field values, "
            "ordering, and fail-closed defaults."
        ),
        why_it_exists=(
            "Reviewer-facing outputs must stay stable across UI, exports, and tests."
        ),
    ),
    TestSeam(
        name="streamlit_orchestration",
        planned_surface=(
            "app.py event handlers that translate session state into explicit calls "
            "for setup, run, selection, review, and export actions"
        ),
        test_double_strategy=(
            "Drive UI tests through Streamlit's testing harness with fake workspace "
            "state and deterministic pipeline responses."
        ),
        why_it_exists=(
            "The UI should be testable without relying on manual clicks or a live "
            "provider session."
        ),
    ),
)

LOG_FIELD_SPECS: Final[tuple[LogFieldSpec, ...]] = (
    LogFieldSpec(
        name="ts",
        required=True,
        example="2026-04-27T19:00:00Z",
        purpose="UTC timestamp for stable event ordering across scripts and runs.",
    ),
    LogFieldSpec(
        name="level",
        required=True,
        example="INFO",
        purpose="Severity for filtering happy-path, warning, and failure events.",
    ),
    LogFieldSpec(
        name="component",
        required=True,
        example=LOG_COMPONENT_PIPELINE,
        purpose="High-level subsystem responsible for the event.",
    ),
    LogFieldSpec(
        name="event",
        required=True,
        example="row_completed",
        purpose="Stable machine-friendly event name for scripts and audits.",
    ),
    LogFieldSpec(
        name="run_id",
        required=True,
        example="demo-run-001",
        purpose="Correlation key spanning one setup or answer-generation run.",
    ),
    LogFieldSpec(
        name="status",
        required=True,
        example=LOG_STATUS_COMPLETED,
        purpose="Outcome marker for start, completion, failure, block, skip, or retry.",
    ),
    LogFieldSpec(
        name="message",
        required=True,
        example="Answered Q01 with 2 valid citations.",
        purpose="Human-readable summary of the event in one line.",
    ),
    LogFieldSpec(
        name="question_id",
        required=False,
        example="Q01",
        purpose="Question-level correlation for retrieval, scoring, and review events.",
    ),
    LogFieldSpec(
        name="workspace_hash",
        required=False,
        example="abc123workspacehash",
        purpose="Workspace identity for reuse, rebuild, and setup decisions.",
    ),
    LogFieldSpec(
        name="manifest_hash",
        required=False,
        example="def456manifesthash",
        purpose="Manifest identity when comparing persisted state to current files.",
    ),
    LogFieldSpec(
        name="index_action",
        required=False,
        example=INDEX_ACTION_REUSED,
        purpose="Explicit created/reused/rebuilt/blocked index decision outcome.",
    ),
    LogFieldSpec(
        name="retrieved_chunk_count",
        required=False,
        example="5",
        purpose="Retrieved evidence volume before answer validation.",
    ),
    LogFieldSpec(
        name="valid_citation_count",
        required=False,
        example="2",
        purpose="Valid citation count after payload validation and dedupe.",
    ),
    LogFieldSpec(
        name="retry_attempt",
        required=False,
        example="1",
        purpose="Retry counter for malformed or schema-invalid model responses.",
    ),
    LogFieldSpec(
        name="artifact_path",
        required=False,
        example="data/outputs/Answered_Questionnaire.xlsx",
        purpose="Published artifact path for exports and saved diagnostics.",
    ),
    LogFieldSpec(
        name="reason",
        required=False,
        example="missing_openai_api_key",
        purpose="Compact machine-friendly explanation for blocked or fail-closed states.",
    ),
)

LOGGING_CONVENTIONS: Final[tuple[str, ...]] = (
    "Emit one structured JSONL record per significant phase or question-level event.",
    "Always include the required fields and only include optional fields when they add real diagnostic value.",
    "Use question_id for row-level events, workspace_hash or manifest_hash for reuse decisions, and artifact_path for published outputs.",
    "Do not log API keys, raw secrets, or full provider transcripts by default.",
)


def question_order_index(question_id: str) -> int:
    """Return the canonical questionnaire order for a known question identifier."""
    return EXPECTED_QUESTION_IDS.index(question_id)


def confidence_band_for_score(confidence_score: float) -> str:
    """Map a numeric confidence score into the planned display band."""
    if confidence_score >= HIGH_CONFIDENCE_THRESHOLD:
        return CONFIDENCE_BAND_HIGH
    if confidence_score >= MEDIUM_CONFIDENCE_THRESHOLD:
        return CONFIDENCE_BAND_MEDIUM
    return CONFIDENCE_BAND_LOW


def build_evidence_display_value(display_labels: Sequence[str]) -> str:
    """Render reviewer-facing evidence labels for workbook export."""
    return "; ".join(label for label in display_labels if label)


def build_citation_display_label(
    source_file_name: str,
    section: str | None = None,
    page: int | None = None,
) -> str:
    """Create the reviewer-facing label for one citation."""
    base_label = source_file_name.replace("_", " ").rsplit(".", 1)[0]
    if section:
        return f"{base_label} — {section}"
    if page is not None:
        return f"{base_label} — Page {page}"
    return base_label


def make_result_row_defaults() -> dict[str, object]:
    """Return the canonical default shape for internal result-row fields."""
    return {
        "answer": "",
        "answer_type": "",
        "citation_ids": [],
        "citations": [],
        "confidence_score": 0.0,
        "confidence_band": "",
        "status": "",
        "reviewer_note": "",
        "evidence_labels": [],
        "index_action": "",
        "run_id": "",
    }


def review_priority_sort_key(row_like: Mapping[str, object]) -> tuple[float, int]:
    """Sort review rows by ascending confidence and then questionnaire order."""
    question_id = str(row_like["question_id"])
    return (float(row_like["confidence_score"]), question_order_index(question_id))


def verification_command_by_name(command_name: str) -> VerificationCommand:
    """Return one canonical verification command by its stable name."""
    for command in CANONICAL_VERIFICATION_COMMANDS:
        if command.name == command_name:
            return command
    raise KeyError(f"Unknown verification command: {command_name}")


def verification_sequence_shell_commands(
    command_names: Sequence[str],
) -> tuple[str, ...]:
    """Render one named verification sequence as shell-ready commands."""
    return tuple(
        verification_command_by_name(command_name).shell_command()
        for command_name in command_names
    )


__all__ = [
    "ACCESS_CONTROL_POLICY_FILE_NAME",
    "ANSWER_OPENING_TOKENS",
    "ANSWER_TYPE_PARTIAL",
    "ANSWER_TYPE_SUPPORTED",
    "ANSWER_TYPE_UNSUPPORTED",
    "ANSWER_TYPES",
    "ANSWERED_QUESTIONNAIRE_FILE_NAME",
    "APP_SUBTITLE",
    "APP_TITLE",
    "BACKUP_RECOVERY_POLICY_FILE_NAME",
    "CANONICAL_VERIFICATION_COMMANDS",
    "CHROMA_DIR",
    "CHUNK_OVERLAP_CHARS",
    "CHUNK_SIZE_CHARS",
    "COLLECTION_NAME",
    "CONFIDENCE_BAND_HIGH",
    "CONFIDENCE_BAND_LOW",
    "CONFIDENCE_BAND_MEDIUM",
    "CLOSEOUT_AUDIT_RULES",
    "DATA_DIR",
    "DEMO_MODE_LABEL",
    "E2E_TESTS_DIR",
    "E2E_TEST_LOGS_DIR",
    "ENCRYPTION_POLICY_FILE_NAME",
    "EXPECTED_OUTCOMES_FIXTURE_PATH",
    "EXPECTED_EVIDENCE_FILE_NAMES",
    "EXPECTED_QUESTION_IDS",
    "FAIL_CLOSED_SCORE",
    "FULL_LOCAL_VALIDATION_COMMAND_NAMES",
    "HIGH_CONFIDENCE_THRESHOLD",
    "INCIDENT_RESPONSE_POLICY_FILE_NAME",
    "INDEX_ACTION_BLOCKED",
    "INDEX_ACTION_CREATED",
    "INDEX_ACTION_REBUILT_CONTENT_CHANGE",
    "INDEX_ACTION_REBUILT_INTEGRITY",
    "INDEX_ACTION_REUSED",
    "INDEX_FIXTURES_DIR",
    "LIVE_SMOKE_LOGS_DIR",
    "LOGGING_CONVENTIONS",
    "LOG_COMPONENTS",
    "LOG_COMPONENT_EXPORT",
    "LOG_COMPONENT_INDEXING",
    "LOG_COMPONENT_PIPELINE",
    "LOG_COMPONENT_SETUP",
    "LOG_COMPONENT_UI",
    "LOG_COMPONENT_VERIFICATION",
    "LogFieldSpec",
    "LOG_FIELD_SPECS",
    "LOG_FILE_EXTENSION",
    "LOG_FORMAT_NAME",
    "LOG_LEVELS",
    "LOG_OPTIONAL_FIELDS",
    "LOG_REQUIRED_FIELDS",
    "LOG_STATUSES",
    "LOG_STATUS_BLOCKED",
    "LOG_STATUS_COMPLETED",
    "LOG_STATUS_FAILED",
    "LOG_STATUS_RETRYING",
    "LOG_STATUS_SKIPPED",
    "LOG_STATUS_STARTED",
    "MAIN_RESULTS_TABLE_COLUMNS",
    "MANIFEST_FILE_NAME",
    "MAX_VISIBLE_CITATIONS",
    "MEDIUM_CONFIDENCE_THRESHOLD",
    "MODEL_RETRY_LIMIT",
    "NEEDS_REVIEW_FILE_NAME",
    "OPTIONAL_LIVE_VALIDATION_COMMAND_NAMES",
    "OUTPUTS_DIR",
    "PARTIAL_SCORE",
    "QUESTIONNAIRE_FILE_NAME",
    "QUESTION_SHEET_NAME",
    "QUICK_CONFIDENCE_COMMAND_NAMES",
    "READY_STATUS_FILL",
    "REPO_ROOT",
    "REQUIRED_ENV_VARS",
    "RETRIEVAL_TOP_K",
    "REVIEW_QUEUE_COLUMNS",
    "REVIEW_QUEUE_THRESHOLD",
    "REVIEW_STATUS_FILL",
    "REVIEW_SUMMARY_FILE_NAME",
    "RUNTIME_DIRECTORIES",
    "RUNTIME_EVIDENCE_DIR",
    "RUNTIME_QUESTIONNAIRES_DIR",
    "SEED_DATA_DIR",
    "SEED_EVIDENCE_DIR",
    "SEED_QUESTIONNAIRE_DIR",
    "SEED_QUESTION_COLUMNS",
    "SEED_TO_RUNTIME_PATHS",
    "SOC2_SUMMARY_FILE_NAME",
    "STUBBED_OPENAI_FIXTURES_DIR",
    "STATUS_NEEDS_REVIEW",
    "STATUS_READY_FOR_REVIEW",
    "SUMMARY_CARD_LABELS",
    "SUPPORTED_WITH_ONE_CITATION_SCORE",
    "SUPPORTED_WITH_TWO_PLUS_CITATIONS_SCORE",
    "TESTS_DIR",
    "TEST_FIXTURES_DIR",
    "TestSeam",
    "TEST_SEAMS",
    "UI_TESTS_DIR",
    "UI_TEST_LOGS_DIR",
    "UNIT_TESTS_DIR",
    "UNIT_TEST_LOGS_DIR",
    "UNSUPPORTED_SCORE",
    "VERIFICATION_ARTIFACTS_DIR",
    "VerificationCommand",
    "VISIBLE_EXPORT_COLUMNS",
    "VISIBLE_OUTPUT_COLUMNS",
    "WORKSPACE_HASH_DIRECTORIES",
    "WORKSPACE_FIXTURES_DIR",
    "build_citation_display_label",
    "build_evidence_display_value",
    "confidence_band_for_score",
    "make_result_row_defaults",
    "question_order_index",
    "review_priority_sort_key",
    "verification_command_by_name",
    "verification_sequence_shell_commands",
]
