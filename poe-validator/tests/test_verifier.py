"""Tests for PoEVerifier."""
import shutil
import pytest
from pathlib import Path

from poe.config import PoEConfig
from poe.verifier import PoEVerifier

POE_ROOT = Path.home() / "poe-bittensor"


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
