"""UID selection utilities."""
from __future__ import annotations

import random
import typing

import numpy as np


def get_random_uids(
    metagraph,
    k: int,
    exclude: typing.Optional[set[int]] = None,
) -> np.ndarray:
    """Select k random UIDs from the metagraph, excluding specified UIDs."""
    exclude = exclude or set()
    available = [uid for uid in range(metagraph.n) if uid not in exclude]
    if len(available) == 0:
        return np.array([], dtype=np.int64)
    k = min(k, len(available))
    selected = random.sample(available, k)
    return np.array(selected, dtype=np.int64)
