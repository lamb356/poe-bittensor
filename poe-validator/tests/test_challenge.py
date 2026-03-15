"""Tests for challenge nonce."""
from poe.challenge import get_mock_nonce


def test_mock_nonce_deterministic():
    n1 = get_mock_nonce(42)
    n2 = get_mock_nonce(42)
    assert n1 == n2


def test_mock_nonce_different_epochs():
    n1 = get_mock_nonce(1)
    n2 = get_mock_nonce(2)
    assert n1 != n2


def test_mock_nonce_is_u64():
    n = get_mock_nonce(100)
    assert 0 <= n < 2**64
