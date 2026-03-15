"""Tests for authenticated proof verification in the validator forward path."""
import struct
import time
import base64
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from poe.verifier import PoEVerifier, AuthenticatedPublicInputs, VerifyResult
from poe_subnet.protocol import ProofSubmission
from poe_subnet.config import PoESubnetConfig


def _make_fake_proof(epoch=42, validator_id=12345, challenge_nonce=77777):
    """Build fake proof bytes with known public inputs."""
    header = struct.pack(">I", 446)
    pub_inputs = b""
    for val in [0x1234, 0x5678, 0x9abc, epoch, validator_id, challenge_nonce]:
        pub_inputs += val.to_bytes(32, "big")
    return header + pub_inputs + b"\x00" * 14000


class TestAuthenticatedVerification:
    def _make_validator(self, verify_result):
        """Create a mock validator with a verify_and_extract that returns the given result."""
        validator = MagicMock()
        validator.verifier.verify_and_extract.return_value = verify_result
        return validator

    def _make_response(self, proof_bytes, epoch=42, challenge_nonce=77777):
        """Create a ProofSubmission with encoded proof."""
        return ProofSubmission(
            epoch=epoch,
            challenge_nonce=challenge_nonce,
            subnet_uid=0,
            proof_b64=base64.b64encode(proof_bytes).decode(),
        )

    def test_matching_epoch_and_nonce_accepted(self):
        """Proof with matching epoch and nonce is accepted."""
        from poe_subnet.validator.forward import _verify_response

        pi = AuthenticatedPublicInputs(
            input_commitment="0x1234",
            weight_commitment="0x5678",
            score_commitment="0x9abc",
            epoch=42,
            validator_id=12345,
            challenge_nonce=77777,
        )
        result = VerifyResult(is_valid=True, public_inputs=pi)
        validator = self._make_validator(result)
        response = self._make_response(_make_fake_proof(), epoch=42, challenge_nonce=77777)
        config = PoESubnetConfig()

        out = _verify_response(validator, response, config)
        assert out["proof_valid"] is True

    def test_epoch_mismatch_rejected(self):
        """Proof with wrong epoch is rejected."""
        from poe_subnet.validator.forward import _verify_response

        pi = AuthenticatedPublicInputs(
            input_commitment="0x1234",
            weight_commitment="0x5678",
            score_commitment="0x9abc",
            epoch=99,  # Different from response.epoch=42
            validator_id=12345,
            challenge_nonce=77777,
        )
        result = VerifyResult(is_valid=True, public_inputs=pi)
        validator = self._make_validator(result)
        response = self._make_response(_make_fake_proof(), epoch=42, challenge_nonce=77777)
        config = PoESubnetConfig()

        out = _verify_response(validator, response, config)
        assert out["proof_valid"] is False

    def test_nonce_mismatch_rejected(self):
        """Proof with wrong nonce is rejected."""
        from poe_subnet.validator.forward import _verify_response

        pi = AuthenticatedPublicInputs(
            input_commitment="0x1234",
            weight_commitment="0x5678",
            score_commitment="0x9abc",
            epoch=42,
            validator_id=12345,
            challenge_nonce=99999,  # Different from response.challenge_nonce=77777
        )
        result = VerifyResult(is_valid=True, public_inputs=pi)
        validator = self._make_validator(result)
        response = self._make_response(_make_fake_proof(), epoch=42, challenge_nonce=77777)
        config = PoESubnetConfig()

        out = _verify_response(validator, response, config)
        assert out["proof_valid"] is False

    def test_extraction_failure_rejects(self):
        """If extraction fails on valid proof, reject (fail closed)."""
        from poe_subnet.validator.forward import _verify_response

        result = VerifyResult(is_valid=True, public_inputs=None, error="extraction failed")
        validator = self._make_validator(result)
        response = self._make_response(_make_fake_proof())
        config = PoESubnetConfig()

        out = _verify_response(validator, response, config)
        assert out["proof_valid"] is False

    def test_invalid_proof_rejected(self):
        """Invalid proof is rejected without extraction."""
        from poe_subnet.validator.forward import _verify_response

        result = VerifyResult(is_valid=False, error="bb verify failed")
        validator = self._make_validator(result)
        response = self._make_response(_make_fake_proof())
        config = PoESubnetConfig()

        out = _verify_response(validator, response, config)
        assert out["proof_valid"] is False
