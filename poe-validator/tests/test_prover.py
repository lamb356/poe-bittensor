"""Tests for PoEProver."""
import json
import pytest
from pathlib import Path

from poe.config import PoEConfig
from poe.prover import PoEProver

POE_ROOT = Path.home() / "poe-bittensor"


@pytest.fixture
def config():
    return PoEConfig.from_poe_root(str(POE_ROOT))


@pytest.fixture
def prover(config):
    return PoEProver(config, validator_id=42)


def test_add_evaluation(prover):
    prover.add_evaluation(0, b"hello", 100)
    assert prover.evaluation_count == 1


def test_add_evaluation_multiple(prover):
    for i in range(10):
        prover.add_evaluation(i, f"response_{i}".encode(), i * 100)
    assert prover.evaluation_count == 10


def test_add_evaluation_duplicate_raises(prover):
    prover.add_evaluation(5, b"first", 100)
    with pytest.raises(ValueError, match="Duplicate UID 5"):
        prover.add_evaluation(5, b"second", 200)


def test_add_evaluation_invalid_uid(prover):
    with pytest.raises(ValueError, match="uid must be u16"):
        prover.add_evaluation(-1, b"data", 100)
    with pytest.raises(ValueError, match="uid must be u16"):
        prover.add_evaluation(70000, b"data", 100)


def test_add_evaluation_invalid_score(prover):
    with pytest.raises(ValueError, match="score must be non-negative"):
        prover.add_evaluation(0, b"data", -1)


def test_build_eval_data(prover):
    for i in range(5):
        prover.add_evaluation(i, f"resp_{i}".encode(), (i + 1) * 1000)
    data = prover._build_eval_data(epoch=10, challenge_nonce=12345)
    assert len(data["miner_uids"]) == 64
    assert len(data["responses"]) == 64
    assert len(data["scores"]) == 64
    assert data["epoch"] == 10
    assert data["challenge_nonce"] == 12345
    assert data["validator_id"] == 42
    # First 5 should be real, rest padded
    assert data["miner_uids"][:5] == [0, 1, 2, 3, 4]
    assert data["scores"][:5] == [1000, 2000, 3000, 4000, 5000]


def test_reset(prover):
    prover.add_evaluation(0, b"data", 100)
    prover.reset()
    assert prover.evaluation_count == 0


def test_prove_empty_raises(prover):
    with pytest.raises(ValueError, match="No evaluations"):
        prover.prove(epoch=1, challenge_nonce=999)
