"""Compatibility test module for the canonical ``*_test.py`` discovery pattern."""

try:
    from tests.unit.test_verification_contract import VerificationContractTests
except ModuleNotFoundError:
    from test_verification_contract import VerificationContractTests

__all__ = ["VerificationContractTests"]
