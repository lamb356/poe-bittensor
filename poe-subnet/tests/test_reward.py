"""Tests for the PoE reward mechanism."""
import time
import pytest
import numpy as np

from poe_subnet.config import PoESubnetConfig
from poe_subnet.reward import reward, get_rewards


@pytest.fixture
def config():
    return PoESubnetConfig()


class TestReward:
    def test_valid_proof_on_time(self, config):
        """Valid proof submitted before epoch end gets full score."""
        epoch_end = time.time()
        score = reward(
            proof_valid=True,
            proof_timestamp=epoch_end - 10,  # 10s before epoch end
            epoch_end_time=epoch_end,
            config=config,
        )
        assert score == 1.0

    def test_invalid_proof_scores_zero(self, config):
        """Invalid proof always scores 0 regardless of timeliness."""
        epoch_end = time.time()
        score = reward(
            proof_valid=False,
            proof_timestamp=epoch_end,
            epoch_end_time=epoch_end,
            config=config,
        )
        assert score == 0.0

    def test_missing_proof_scores_zero(self, config):
        """Missing proof (no timestamp) scores 0."""
        score = reward(
            proof_valid=True,
            proof_timestamp=None,
            epoch_end_time=time.time(),
            config=config,
        )
        assert score == 0.0

    def test_within_grace_window(self, config):
        """Proof within timeliness window gets full score."""
        epoch_end = time.time()
        # 30 blocks late = 360 seconds (at 12s/block), within default 60-block window
        score = reward(
            proof_valid=True,
            proof_timestamp=epoch_end + 360,
            epoch_end_time=epoch_end,
            config=config,
        )
        assert score == 1.0

    def test_past_grace_window_decays(self, config):
        """Proof past timeliness window gets decayed score."""
        epoch_end = time.time()
        # 80 blocks late = 960 seconds (at 12s/block), 20 blocks past the 60-block window
        score = reward(
            proof_valid=True,
            proof_timestamp=epoch_end + 960,
            epoch_end_time=epoch_end,
            config=config,
        )
        expected = config.timeliness_decay ** 20  # 0.95^20 ≈ 0.358
        assert 0.0 < score < 1.0
        assert abs(score - expected) < 0.01

    def test_very_late_floors_at_minimum(self, config):
        """Extremely late proof floors at 0.01."""
        epoch_end = time.time()
        # 1000 blocks late = 12000 seconds (at 12s/block)
        score = reward(
            proof_valid=True,
            proof_timestamp=epoch_end + 12000,
            epoch_end_time=epoch_end,
            config=config,
        )
        assert score >= 0.01

    def test_timeliness_monotonically_decreasing(self, config):
        """Later proofs always score less than earlier ones."""
        epoch_end = time.time()
        scores = []
        for delay in [0, 600, 700, 800, 1000, 2000, 5000]:
            s = reward(
                proof_valid=True,
                proof_timestamp=epoch_end + delay,
                epoch_end_time=epoch_end,
                config=config,
            )
            scores.append(s)
        # Should be non-increasing
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Score at delay index {i} ({scores[i]}) < "
                f"score at {i+1} ({scores[i+1]})"
            )


class TestGetRewards:
    def test_batch_rewards(self, config):
        """get_rewards processes a batch of results correctly."""
        epoch_end = time.time()
        results = [
            {"proof_valid": True, "proof_timestamp": epoch_end - 5},   # On time
            {"proof_valid": False, "proof_timestamp": epoch_end},       # Invalid
            {"proof_valid": True, "proof_timestamp": None},             # Missing
            {"proof_valid": True, "proof_timestamp": epoch_end + 100},  # Within window
        ]
        rewards = get_rewards(results, epoch_end, config)
        assert isinstance(rewards, np.ndarray)
        assert len(rewards) == 4
        assert rewards[0] == 1.0  # Valid, on time
        assert rewards[1] == 0.0  # Invalid
        assert rewards[2] == 0.0  # Missing timestamp
        assert rewards[3] == 1.0  # Within window

    def test_empty_batch(self, config):
        """Empty results list returns empty array."""
        rewards = get_rewards([], time.time(), config)
        assert len(rewards) == 0

    def test_all_invalid(self, config):
        """All invalid proofs score zero."""
        results = [{"proof_valid": False} for _ in range(10)]
        rewards = get_rewards(results, time.time(), config)
        assert np.all(rewards == 0.0)

    def test_all_valid_on_time(self, config):
        """All valid on-time proofs score 1.0."""
        epoch_end = time.time()
        results = [
            {"proof_valid": True, "proof_timestamp": epoch_end - 1}
            for _ in range(10)
        ]
        rewards = get_rewards(results, epoch_end, config)
        assert np.all(rewards == 1.0)
