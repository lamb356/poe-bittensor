"""Incentive mechanism: score miners based on proof validity and timeliness."""
from __future__ import annotations

import time
import typing

import numpy as np

from poe_subnet.config import BLOCK_TIME_SECONDS, PoESubnetConfig


def reward(
    proof_valid: bool,
    proof_timestamp: typing.Optional[float],
    epoch_end_time: float,
    config: PoESubnetConfig,
) -> float:
    """Score a single miner's proof submission.

    Score = proof_valid (0 or 1) * timeliness_factor (0.0 to 1.0)

    Timeliness: full score if submitted within timeliness_window of epoch end.
    After that, score decays exponentially per block (10s each).
    Missing or invalid proofs always score 0.
    """
    if not proof_valid:
        return 0.0

    if proof_timestamp is None:
        return 0.0

    # How late is the proof?
    delay = proof_timestamp - epoch_end_time
    if delay <= 0:
        # Submitted before epoch ended — early, full score
        return 1.0

    # Convert delay to blocks
    delay_blocks = delay / BLOCK_TIME_SECONDS

    if delay_blocks <= config.timeliness_window:
        # Within grace window — full score
        return 1.0

    # Exponential decay past the window
    excess_blocks = delay_blocks - config.timeliness_window
    factor = config.timeliness_decay ** excess_blocks

    # Floor at 0.01 to avoid floating point noise
    return max(factor, 0.01)


def get_rewards(
    proof_results: list[dict],
    epoch_end_time: float,
    config: PoESubnetConfig,
) -> np.ndarray:
    """Batch reward across all queried miners.

    Args:
        proof_results: List of dicts with keys:
            - proof_valid: bool
            - proof_timestamp: Optional[float]
        epoch_end_time: When the epoch ended (unix timestamp)
        config: Subnet configuration

    Returns:
        np.ndarray of float rewards, one per miner.
    """
    rewards = []
    for result in proof_results:
        r = reward(
            proof_valid=result.get("proof_valid", False),
            proof_timestamp=result.get("proof_timestamp"),
            epoch_end_time=epoch_end_time,
            config=config,
        )
        rewards.append(r)
    return np.array(rewards, dtype=np.float32)
