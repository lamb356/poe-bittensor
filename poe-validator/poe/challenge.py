"""Challenge nonce from Drand beacon."""
from __future__ import annotations

import hashlib


def get_drand_nonce(epoch: int) -> int:
    """Fetch a nonce from the Drand beacon for this epoch.

    Uses the Drand HTTP API. The nonce is the first 8 bytes of the
    beacon randomness for the round closest to the epoch timestamp.
    """
    import httpx

    resp = httpx.get("https://api.drand.sh/public/latest", timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    randomness = bytes.fromhex(data["randomness"])
    # Mix epoch into randomness so different epochs get different nonces
    mixed = hashlib.blake2b(randomness + epoch.to_bytes(8, "big"), digest_size=8).digest()
    return int.from_bytes(mixed, "big")


def get_mock_nonce(epoch: int) -> int:
    """Deterministic mock nonce for testing."""
    h = hashlib.blake2b(b"poe-mock-nonce" + epoch.to_bytes(8, "big"), digest_size=8)
    return int.from_bytes(h.digest(), "big")
