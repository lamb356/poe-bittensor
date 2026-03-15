"""Tests for UID selection utilities."""
import numpy as np
from poe_subnet.mock import MockMetagraph
from poe_subnet.utils.uids import get_random_uids


def test_get_random_uids_basic():
    mg = MockMetagraph(n=256)
    uids = get_random_uids(mg, k=16)
    assert len(uids) == 16
    assert len(set(uids)) == 16  # All unique


def test_get_random_uids_exclude():
    mg = MockMetagraph(n=10)
    uids = get_random_uids(mg, k=5, exclude={0, 1, 2})
    assert all(uid not in {0, 1, 2} for uid in uids)


def test_get_random_uids_k_larger_than_available():
    mg = MockMetagraph(n=5)
    uids = get_random_uids(mg, k=100)
    assert len(uids) == 5


def test_get_random_uids_empty():
    mg = MockMetagraph(n=3)
    uids = get_random_uids(mg, k=5, exclude={0, 1, 2})
    assert len(uids) == 0
