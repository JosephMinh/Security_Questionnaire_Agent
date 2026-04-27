"""Contract tests for the shared verification strategy definitions."""

from __future__ import annotations

import unittest

from rag import (
    CANONICAL_VERIFICATION_COMMANDS,
    CLOSEOUT_AUDIT_RULES,
    FULL_LOCAL_VALIDATION_COMMAND_NAMES,
    LOG_OPTIONAL_FIELDS,
    LOG_COMPONENTS,
    LOG_REQUIRED_FIELDS,
    OPTIONAL_LIVE_VALIDATION_COMMAND_NAMES,
    QUICK_CONFIDENCE_COMMAND_NAMES,
    TEST_SEAMS,
    build_structured_log_record,
    verification_command_by_name,
    verification_sequence_shell_commands,
)


class VerificationContractTests(unittest.TestCase):
    """Keep the shared verification contract stable as later beads build on it."""

    def test_command_names_cover_all_required_entrypoints(self) -> None:
        command_names = {command.name for command in CANONICAL_VERIFICATION_COMMANDS}
        self.assertEqual(
            command_names,
            {
                "quick_unit",
                "ui_suite",
                "deterministic_e2e",
                "failure_e2e",
                "live_smoke",
                "closeout_audit",
            },
        )

    def test_sequences_resolve_to_shell_commands(self) -> None:
        quick_commands = verification_sequence_shell_commands(
            QUICK_CONFIDENCE_COMMAND_NAMES
        )
        full_commands = verification_sequence_shell_commands(
            FULL_LOCAL_VALIDATION_COMMAND_NAMES
        )
        live_commands = verification_sequence_shell_commands(
            OPTIONAL_LIVE_VALIDATION_COMMAND_NAMES
        )
        self.assertEqual(len(quick_commands), 1)
        self.assertEqual(len(full_commands), 4)
        self.assertEqual(len(live_commands), 1)
        self.assertIn("tests/e2e/run_deterministic_demo.py", full_commands[2])
        self.assertIn("Q01 Q17 Q21", live_commands[0])

    def test_closeout_audit_command_and_rules_are_explicit(self) -> None:
        closeout_command = verification_command_by_name("closeout_audit")
        self.assertEqual(
            closeout_command.argv,
            ("br-closeout-audit", "--issue", "<issue-id>"),
        )
        self.assertEqual(len(CLOSEOUT_AUDIT_RULES), 2)
        self.assertIn("high-risk bead", CLOSEOUT_AUDIT_RULES[0])
        self.assertIn("verification-heavy work", CLOSEOUT_AUDIT_RULES[1])

    def test_logging_contract_has_required_fields_and_components(self) -> None:
        self.assertEqual(
            LOG_REQUIRED_FIELDS,
            ("ts", "level", "component", "event", "run_id", "status", "message"),
        )
        self.assertIn("answer_type", LOG_OPTIONAL_FIELDS)
        self.assertIn("confidence_band", LOG_OPTIONAL_FIELDS)
        self.assertIn("review_status", LOG_OPTIONAL_FIELDS)
        self.assertEqual(
            set(LOG_COMPONENTS),
            {"setup", "indexing", "pipeline", "ui", "export", "verification"},
        )

    def test_build_structured_log_record_includes_required_and_selected_optional_fields(self) -> None:
        record = build_structured_log_record(
            component="pipeline",
            event="row_completed",
            run_id="run-001",
            status="completed",
            message="Completed Q01 as supported with 2 valid citations.",
            question_id="Q01",
            workspace_hash="workspace-hash",
            manifest_hash="manifest-hash",
            index_action="reused",
            retrieved_chunk_count=5,
            valid_citation_count=2,
            answer_type="supported",
            confidence_band="High",
            review_status="Ready for Review",
            retry_attempt=1,
            artifact_path="data/outputs/Answered_Questionnaire.xlsx",
            reason="reused",
        )
        self.assertEqual(record["component"], "pipeline")
        self.assertEqual(record["event"], "row_completed")
        self.assertEqual(record["run_id"], "run-001")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["question_id"], "Q01")
        self.assertEqual(record["retrieved_chunk_count"], 5)
        self.assertEqual(record["valid_citation_count"], 2)
        self.assertEqual(record["answer_type"], "supported")
        self.assertEqual(record["confidence_band"], "High")
        self.assertEqual(record["review_status"], "Ready for Review")
        self.assertEqual(record["retry_attempt"], 1)
        self.assertEqual(
            record["artifact_path"],
            "data/outputs/Answered_Questionnaire.xlsx",
        )

    def test_test_seams_cover_the_expected_boundaries(self) -> None:
        seam_names = {seam.name for seam in TEST_SEAMS}
        self.assertEqual(
            seam_names,
            {
                "workspace_setup",
                "openai_embeddings",
                "openai_answers",
                "chroma_index",
                "result_shaping",
                "streamlit_orchestration",
            },
        )


if __name__ == "__main__":
    unittest.main()
