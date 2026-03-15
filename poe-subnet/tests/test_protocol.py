"""Tests for protocol synapse definitions."""
import base64
import json
import os
import pytest
import bittensor as bt

from poe_subnet.protocol import ProofSubmission, ProofChallenge


class TestProofSubmissionModel:
    def test_required_fields(self):
        s = ProofSubmission(epoch=1, challenge_nonce=12345, subnet_uid=8)
        assert s.epoch == 1
        assert s.challenge_nonce == 12345
        assert s.subnet_uid == 8

    def test_optional_fields_default_none(self):
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=0)
        assert s.proof_b64 is None
        assert s.public_inputs_json is None
        assert s.proof_timestamp is None

    def test_deserialize_none_when_no_proof(self):
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=0)
        assert s.deserialize() is None

    def test_deserialize_returns_dict(self):
        raw = b"\x00\x01\x02\x03" * 25
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=0)
        s.proof_b64 = ProofSubmission.encode_proof(raw)
        s.public_inputs_json = '{"test": true}'
        s.proof_timestamp = 1234567890.0
        result = s.deserialize()
        assert result is not None
        assert result["proof_bytes"] == raw
        assert result["public_inputs_json"] == '{"test": true}'
        assert result["proof_timestamp"] == 1234567890.0

    def test_proof_bytes_property(self):
        raw = os.urandom(100)
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=0)
        s.proof_b64 = ProofSubmission.encode_proof(raw)
        assert s.proof_bytes == raw

    def test_proof_bytes_property_none(self):
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=0)
        assert s.proof_bytes is None


class TestProofChallengeModel:
    def test_required_fields(self):
        s = ProofChallenge(epoch=5, challenged_miner_uid=42)
        assert s.epoch == 5
        assert s.challenged_miner_uid == 42

    def test_optional_fields_default_none(self):
        s = ProofChallenge(epoch=0, challenged_miner_uid=0)
        assert s.response_hash is None
        assert s.score is None
        assert s.weight is None

    def test_deserialize_with_data(self):
        s = ProofChallenge(epoch=1, challenged_miner_uid=10)
        s.response_hash = "0xabc123"
        s.score = 500
        s.weight = 32000
        result = s.deserialize()
        assert result["response_hash"] == "0xabc123"
        assert result["score"] == 500
        assert result["weight"] == 32000


class TestSynapseInheritance:
    def test_inherits_from_bt_synapse(self):
        assert issubclass(ProofSubmission, bt.Synapse)
        assert issubclass(ProofChallenge, bt.Synapse)

    def test_has_synapse_fields(self):
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=0)
        assert hasattr(s, "name")
        assert hasattr(s, "timeout")
        assert hasattr(s, "dendrite")
        assert hasattr(s, "axon")
        assert s.name == "ProofSubmission"

    def test_challenge_has_synapse_fields(self):
        s = ProofChallenge(epoch=0, challenged_miner_uid=0)
        assert s.name == "ProofChallenge"


class TestWireFormat:
    def test_json_roundtrip_empty(self):
        s = ProofSubmission(epoch=42, challenge_nonce=99, subnet_uid=8)
        json_str = s.model_dump_json()
        s2 = ProofSubmission.model_validate_json(json_str)
        assert s2.epoch == 42
        assert s2.challenge_nonce == 99
        assert s2.subnet_uid == 8
        assert s2.proof_b64 is None

    def test_json_roundtrip_with_proof(self):
        """Synapse with proof data roundtrips through JSON correctly."""
        proof_data = os.urandom(14244)  # Real proof size
        s = ProofSubmission(epoch=1, challenge_nonce=12345, subnet_uid=8)
        s.proof_b64 = ProofSubmission.encode_proof(proof_data)
        s.public_inputs_json = json.dumps({"miner_uids": list(range(64))})
        s.proof_timestamp = 1700000000.123

        json_str = s.model_dump_json()
        s2 = ProofSubmission.model_validate_json(json_str)

        assert s2.proof_bytes == proof_data
        assert s2.proof_timestamp == 1700000000.123
        parsed = json.loads(s2.public_inputs_json)
        assert len(parsed["miner_uids"]) == 64

    def test_headers_serialization(self):
        s = ProofSubmission(epoch=10, challenge_nonce=555, subnet_uid=3)
        headers = s.to_headers()
        assert "bt_header_input_obj_epoch" in headers
        assert "bt_header_input_obj_challenge_nonce" in headers
        assert "bt_header_input_obj_subnet_uid" in headers

    def test_required_fields_detection(self):
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=0)
        required = s.get_required_fields()
        assert "epoch" in required
        assert "challenge_nonce" in required
        assert "subnet_uid" in required
        assert "proof_b64" not in required
        assert "public_inputs_json" not in required
        assert "proof_timestamp" not in required

    def test_model_dump_excludes_none(self):
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=0)
        dumped = s.model_dump(exclude_none=True)
        assert "epoch" in dumped
        assert "proof_b64" not in dumped

    def test_large_proof_bytes(self):
        """Realistic proof size (~14KB) serializes correctly via base64."""
        proof = os.urandom(14244)
        s = ProofSubmission(epoch=1, challenge_nonce=0, subnet_uid=8)
        s.proof_b64 = ProofSubmission.encode_proof(proof)
        json_str = s.model_dump_json()
        s2 = ProofSubmission.model_validate_json(json_str)
        assert s2.proof_bytes == proof
        assert len(s2.proof_bytes) == 14244

    def test_challenge_json_roundtrip(self):
        s = ProofChallenge(epoch=5, challenged_miner_uid=42)
        s.response_hash = "0x" + "ab" * 32
        s.score = 12345
        s.weight = 50000
        json_str = s.model_dump_json()
        s2 = ProofChallenge.model_validate_json(json_str)
        assert s2.epoch == 5
        assert s2.challenged_miner_uid == 42
        assert s2.response_hash == "0x" + "ab" * 32
        assert s2.score == 12345
        assert s2.weight == 50000

    def test_encode_decode_roundtrip(self):
        """encode_proof/decode_proof are inverses."""
        raw = os.urandom(20000)
        encoded = ProofSubmission.encode_proof(raw)
        decoded = ProofSubmission.decode_proof(encoded)
        assert decoded == raw

    def test_base64_is_ascii_safe(self):
        """Encoded proof is pure ASCII — safe for JSON transport."""
        raw = bytes(range(256)) * 100
        encoded = ProofSubmission.encode_proof(raw)
        assert encoded.isascii()
        # Verify it parses as JSON string
        json.dumps(encoded)


class TestProofValidation:
    """Tests for proof decode/validate hardening."""

    def test_malformed_base64_returns_none_or_raises(self):
        """Malformed base64 should raise or return None."""
        synapse = ProofSubmission(
            epoch=1, challenge_nonce=12345, subnet_uid=0,
            proof_b64="not-valid-base64!!!"
        )
        # decode_and_validate_proof should raise on malformed base64
        with pytest.raises(Exception):
            synapse.decode_and_validate_proof()

    def test_oversized_proof_rejected(self):
        """Proof exceeding MAX_PROOF_BYTES should be rejected."""
        from poe_subnet.protocol import MAX_PROOF_BYTES
        big_proof = base64.b64encode(b"x" * (MAX_PROOF_BYTES + 1)).decode()
        synapse = ProofSubmission(
            epoch=1, challenge_nonce=12345, subnet_uid=0,
            proof_b64=big_proof
        )
        with pytest.raises(ValueError, match="too large"):
            synapse.decode_and_validate_proof()

    def test_valid_proof_decode_succeeds(self):
        """Valid base64 proof within size limit should decode."""
        proof_data = b"valid proof data" * 100
        synapse = ProofSubmission(
            epoch=1, challenge_nonce=12345, subnet_uid=0,
            proof_b64=base64.b64encode(proof_data).decode()
        )
        result = synapse.decode_and_validate_proof()
        assert result == proof_data

    def test_missing_proof_returns_none(self):
        """No proof_b64 should return None from decode_and_validate_proof."""
        synapse = ProofSubmission(
            epoch=1, challenge_nonce=12345, subnet_uid=0,
        )
        assert synapse.decode_and_validate_proof() is None
