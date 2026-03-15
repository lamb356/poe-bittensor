"""Tests for challenge nonce."""
from poe.challenge import get_challenge_nonce, get_mock_nonce


def test_canonical_nonce_deterministic():
    n1 = get_challenge_nonce(42)
    n2 = get_challenge_nonce(42)
    assert n1 == n2


def test_canonical_nonce_different_epochs():
    n1 = get_challenge_nonce(1)
    n2 = get_challenge_nonce(2)
    assert n1 != n2


def test_canonical_nonce_fits_253_bits():
    for epoch in (0, 1, 100, 999999):
        n = get_challenge_nonce(epoch)
        assert n < 2**253, f"epoch {epoch}: nonce {n} exceeds 253 bits"


def test_canonical_nonce_nonzero():
    for epoch in (1, 10, 100, 1000):
        assert get_challenge_nonce(epoch) > 0


def test_mock_nonce_deterministic():
    n1 = get_mock_nonce(42)
    n2 = get_mock_nonce(42)
    assert n1 == n2


def test_mock_nonce_different_epochs():
    n1 = get_mock_nonce(1)
    n2 = get_mock_nonce(2)
    assert n1 != n2
