"""Tests for PoEVerifier."""
import shutil
import struct
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from poe.config import PoEConfig
from poe.verifier import PoEVerifier, AuthenticatedPublicInputs, VerifyResult

POE_ROOT = Path.home() / "poe-bittensor"


def _make_fake_proof(epoch=42, validator_id=12345, challenge_nonce=77777,
                     input_commit=0x1234, weight_commit=0x5678, score_commit=0x9abc):
    """Build minimal fake proof bytes with known public inputs at the correct offsets."""
    # 4-byte header (circuit size)
    header = struct.pack(">I", 446)
    # 6 public inputs, each 32 bytes big-endian
    pub_inputs = b""
    pub_inputs += input_commit.to_bytes(32, "big")
    pub_inputs += weight_commit.to_bytes(32, "big")
    pub_inputs += score_commit.to_bytes(32, "big")
    pub_inputs += epoch.to_bytes(32, "big")
    pub_inputs += validator_id.to_bytes(32, "big")
    pub_inputs += challenge_nonce.to_bytes(32, "big")
    # Pad with some fake proof data to reach a realistic size
    rest = b"\x00" * 14000
    return header + pub_inputs + rest


@pytest.fixture
def config():
    return PoEConfig.from_poe_root(str(POE_ROOT))


def test_verifier_init(config):
    v = PoEVerifier(config)
    assert v._vk_paths == {}


@pytest.mark.skipif(not shutil.which("bb"), reason="bb binary not on PATH")
def test_verify_invalid_proof(config):
    v = PoEVerifier(config)
    # Random bytes should not verify
    assert v.verify(b"definitely not a valid proof" * 100) is False


class TestPublicInputExtraction:
    def test_extract_valid_proof(self):
        """Extract public inputs from correctly formatted proof bytes."""
        proof = _make_fake_proof(epoch=42, validator_id=12345, challenge_nonce=77777)
        pi = PoEVerifier.extract_public_inputs(proof)
        assert pi.epoch == 42
        assert pi.validator_id == 12345
        assert pi.challenge_nonce == 77777
        assert pi.input_commitment.startswith("0x")
        assert pi.weight_commitment.startswith("0x")
        assert pi.score_commitment.startswith("0x")

    def test_extract_too_short_proof_raises(self):
        """Proof shorter than 196 bytes should raise ValueError."""
        with pytest.raises(ValueError, match="too small"):
            PoEVerifier.extract_public_inputs(b"\x00" * 100)

    def test_extract_exact_minimum_size(self):
        """Proof exactly 196 bytes should work (header + 6 inputs, no rest)."""
        proof = _make_fake_proof()[:196]
        pi = PoEVerifier.extract_public_inputs(proof)
        assert pi.epoch == 42

    def test_extract_field_order_matches_circuit(self):
        """Fields extracted in order: input_commit, weight_commit, score_commit, epoch, vid, nonce."""
        proof = _make_fake_proof(
            input_commit=1, weight_commit=2, score_commit=3,
            epoch=4, validator_id=5, challenge_nonce=6
        )
        pi = PoEVerifier.extract_public_inputs(proof)
        assert int(pi.input_commitment, 16) == 1
        assert int(pi.weight_commitment, 16) == 2
        assert int(pi.score_commitment, 16) == 3
        assert pi.epoch == 4
        assert pi.validator_id == 5
        assert pi.challenge_nonce == 6


class TestVerifyAndExtract:
    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_valid_proof_returns_inputs(self, mock_run, mock_exists):
        """verify_and_extract returns public inputs when bb verify succeeds."""
        mock_run.return_value = MagicMock(returncode=0)
        config = PoEConfig.from_poe_root(str(Path.home() / "poe-bittensor"))
        v = PoEVerifier(config)
        # Mock _ensure_vk to return a fake path
        v._vk_paths["local"] = "/tmp/fake_vk"

        proof = _make_fake_proof(epoch=42, validator_id=12345, challenge_nonce=77777)
        result = v.verify_and_extract(proof)
        assert result.is_valid is True
        assert result.public_inputs is not None
        assert result.public_inputs.epoch == 42
        assert result.public_inputs.validator_id == 12345
        assert result.public_inputs.challenge_nonce == 77777

    @patch("os.path.exists", return_value=True)
    @patch("subprocess.run")
    def test_invalid_proof_no_extraction(self, mock_run, mock_exists):
        """verify_and_extract skips extraction when bb verify fails."""
        mock_run.return_value = MagicMock(returncode=1)
        config = PoEConfig.from_poe_root(str(Path.home() / "poe-bittensor"))
        v = PoEVerifier(config)
        v._vk_paths["local"] = "/tmp/fake_vk"

        proof = _make_fake_proof()
        result = v.verify_and_extract(proof)
        assert result.is_valid is False
        assert result.public_inputs is None

    def test_too_short_proof_returns_error(self):
        """verify_and_extract with too-short proof returns error."""
        config = PoEConfig.from_poe_root(str(Path.home() / "poe-bittensor"))
        v = PoEVerifier(config)
        # verify() will fail on junk bytes, so verify_and_extract returns invalid
        # But we test extraction failure specifically
        proof = b"\x00" * 50
        pi_result = None
        try:
            pi_result = PoEVerifier.extract_public_inputs(proof)
        except ValueError:
            pass
        assert pi_result is None
