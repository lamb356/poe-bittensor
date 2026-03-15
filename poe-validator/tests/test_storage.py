"""Tests for proof storage."""
import tempfile
import pytest
from pathlib import Path

from poe.config import PoEConfig
from poe.prover import PoEProof
from poe.storage import Storage


@pytest.fixture
def storage(tmp_path):
    config = PoEConfig(storage_dir=str(tmp_path / "proofs"))
    return Storage(config)


def _make_proof(epoch=1, validator_id=42, data=b"proof-data"):
    return PoEProof(
        epoch=epoch,
        challenge_nonce=12345,
        validator_id=validator_id,
        proof_bytes=data,
        public_inputs={},
    )


def test_publish_creates_file(storage, tmp_path):
    proof = _make_proof()
    path = storage.publish(proof, epoch=1)
    assert path.exists()
    assert path.read_bytes() == b"proof-data"


def test_retrieve_roundtrip(storage):
    proof = _make_proof(validator_id=7, data=b"roundtrip-test")
    storage.publish(proof, epoch=5)
    retrieved = storage.retrieve(validator_id=7, epoch=5)
    assert retrieved == b"roundtrip-test"


def test_retrieve_missing(storage):
    assert storage.retrieve(validator_id=999, epoch=999) is None


def test_multiple_epochs(storage):
    for e in range(3):
        proof = _make_proof(epoch=e, data=f"epoch-{e}".encode())
        storage.publish(proof, epoch=e)
    for e in range(3):
        assert storage.retrieve(42, e) == f"epoch-{e}".encode()
