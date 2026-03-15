"""Mock objects for testing without a live Bittensor network."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock
import numpy as np


@dataclass
class MockAxonInfo:
    hotkey: str = ""
    ip: str = "127.0.0.1"
    port: int = 8091


@dataclass
class MockMetagraph:
    n: int = 256
    block: int = 1000

    def __post_init__(self):
        self.S = np.ones(self.n, dtype=np.float32)  # Stakes
        self.uids = np.arange(self.n)
        self.axons = [MockAxonInfo(hotkey=f"hotkey_{i}") for i in range(self.n)]
        self.hotkeys = [f"hotkey_{i}" for i in range(self.n)]

    def sync(self, **kwargs):
        pass
