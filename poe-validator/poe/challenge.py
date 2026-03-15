"""Deterministic challenge nonce derivation for PoE."""
from __future__ import annotations

import hashlib

import blake3


def get_challenge_nonce(epoch: int) -> int:
    """Canonical challenge nonce: BLAKE3(b"poe-challenge" || epoch) truncated to 253 bits.

    Globally deterministic from epoch alone. Every node computes the same
    nonce for the same epoch with zero network dependency.
    """
    h = blake3.blake3(b"poe-challenge" + epoch.to_bytes(8, "big")).digest()
    n = int.from_bytes(h, "big")
    n &= (1 << 253) - 1
    return n


def get_mock_nonce(epoch: int) -> int:
    """Deterministic mock nonce for testing (uses blake2b, distinct from canonical)."""
    h = hashlib.blake2b(b"poe-mock-nonce" + epoch.to_bytes(8, "big"), digest_size=8)
    return int.from_bytes(h.digest(), "big")
