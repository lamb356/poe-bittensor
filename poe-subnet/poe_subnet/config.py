"""PoE subnet configuration."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PoESubnetConfig:
    """Subnet-level configuration."""

    netuid: int = 0  # Set at registration time
    tempo: int = 360  # Blocks per epoch (~1 hour at 10s/block)
    proof_timeout: float = 30.0  # Seconds to wait for proof submission
    timeliness_window: int = 60  # Blocks after epoch end where full score applies
    timeliness_decay: float = 0.95  # Score multiplier per block past window
    min_proof_size: int = 1000  # Minimum valid proof size in bytes
    moving_average_alpha: float = 0.1  # EMA alpha for score updates
    sample_size: int = 16  # Miners to query per forward pass
