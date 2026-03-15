"""Challenge nonce derivation — Drand beacon + BLAKE3 mixing."""
from __future__ import annotations

import hashlib
import logging

import blake3

logger = logging.getLogger(__name__)

# Drand quicknet (3-second rounds, used by Bittensor CR4)
DRAND_CHAIN_HASH = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
DRAND_GENESIS = 1692803367
DRAND_PERIOD = 3  # seconds
DRAND_API = f"https://api.drand.sh/{DRAND_CHAIN_HASH}"

# Bittensor timing
BLOCK_TIME = 12  # seconds per block


def get_challenge_nonce(
    epoch: int,
    tempo: int = 360,
    genesis_block: int = 0,
) -> int:
    """Primary nonce: Drand randomness mixed with BLAKE3.

    Derives the Drand round deterministically from the epoch, fetches the
    beacon randomness, then mixes with BLAKE3 for the final nonce.

    Falls back to deterministic BLAKE3(epoch) if Drand is unreachable.

    Args:
        epoch: Current Bittensor epoch number.
        tempo: Blocks per epoch (default 360).
        genesis_block: Bittensor chain genesis block (default 0).

    Returns:
        Challenge nonce as int, truncated to 253 bits (fits BN254 Field).
    """
    try:
        randomness = _fetch_drand_randomness(epoch, tempo, genesis_block)
        h = blake3.blake3(randomness + epoch.to_bytes(8, "big")).digest()
    except Exception as e:
        logger.warning(
            "Drand beacon unreachable (%s), falling back to deterministic nonce",
            e,
        )
        h = blake3.blake3(b"poe-challenge" + epoch.to_bytes(8, "big")).digest()

    n = int.from_bytes(h, "big")
    n &= (1 << 253) - 1
    return n


def get_deterministic_nonce(epoch: int) -> int:
    """Fallback nonce: pure BLAKE3(epoch). No network dependency.

    Use when Drand is unavailable or for testing. Predictable but still
    prevents replay (epoch binding). Copiers cannot forge valid proofs
    even with a predictable nonce because the input commitment binds
    to actual miner responses.
    """
    h = blake3.blake3(b"poe-challenge" + epoch.to_bytes(8, "big")).digest()
    n = int.from_bytes(h, "big")
    n &= (1 << 253) - 1
    return n


def get_mock_nonce(epoch: int) -> int:
    """Deterministic mock nonce for testing."""
    h = hashlib.blake2b(b"poe-mock-nonce" + epoch.to_bytes(8, "big"), digest_size=8)
    return int.from_bytes(h.digest(), "big")


def _fetch_drand_randomness(
    epoch: int, tempo: int, genesis_block: int
) -> bytes:
    """Fetch Drand beacon randomness for the epoch's start block.

    Derives the Drand round deterministically:
        epoch_start_time = (genesis_block + epoch * tempo) * BLOCK_TIME
        drand_round = (epoch_start_time - DRAND_GENESIS) / DRAND_PERIOD + 1

    Then fetches GET /public/{round} from the Drand HTTP API.
    """
    import httpx

    epoch_start_block = genesis_block + epoch * tempo
    epoch_start_time = epoch_start_block * BLOCK_TIME
    drand_round = max(1, (epoch_start_time - DRAND_GENESIS) // DRAND_PERIOD + 1)

    url = f"{DRAND_API}/public/{drand_round}"
    resp = httpx.get(url, timeout=5.0)
    resp.raise_for_status()
    data = resp.json()
    return bytes.fromhex(data["randomness"])


def get_drand_nonce(epoch: int) -> int:
    """DEPRECATED: Use get_challenge_nonce() instead."""
    import warnings
    warnings.warn(
        "get_drand_nonce() is deprecated. Use get_challenge_nonce().",
        DeprecationWarning,
        stacklevel=2,
    )
    return get_challenge_nonce(epoch)
