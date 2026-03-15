"""Challenge nonce derivation using BLAKE3."""
from __future__ import annotations

import hashlib
import warnings

import blake3


def get_challenge_nonce(epoch: int) -> int:
    """Deterministic challenge nonce: BLAKE3(b"poe-challenge" || epoch_be8) truncated to 253 bits.

    Fits in BN254 scalar field (< 2^254). Deterministic and consistent
    across validator and subnet code.
    """
    h = blake3.blake3(b"poe-challenge" + epoch.to_bytes(8, "big")).digest()
    n = int.from_bytes(h, "big")
    n &= (1 << 253) - 1
    return n


def get_drand_nonce(epoch: int) -> int:
    """DEPRECATED: Use get_challenge_nonce() instead.

    Non-deterministic — Drand returns different values per call.
    """
    warnings.warn(
        "get_drand_nonce() is non-deterministic and deprecated. "
        "Use get_challenge_nonce().",
        DeprecationWarning,
        stacklevel=2,
    )
    return get_challenge_nonce(epoch)


def get_mock_nonce(epoch: int) -> int:
    """Deterministic mock nonce for testing."""
    h = hashlib.blake2b(b"poe-mock-nonce" + epoch.to_bytes(8, "big"), digest_size=8)
    return int.from_bytes(h.digest(), "big")
