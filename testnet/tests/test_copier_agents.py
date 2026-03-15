"""Tests for copier agent strategies."""
import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from copier_agents import NaiveCopier, DelayedCopier, PartialCopier


class TestNaiveCopier:
    def test_first_epoch_uniform(self):
        c = NaiveCopier(num_miners=8)
        w, has_proof = c.compute_weights(None, 0)
        assert not has_proof
        assert len(w) == 8
        assert abs(w.sum() - 1.0) < 1e-6

    def test_copies_previous(self):
        c = NaiveCopier(num_miners=8)
        prev = np.array([0.5, 0.3, 0.1, 0.05, 0.02, 0.01, 0.01, 0.01])
        c.update_history(prev)
        w, has_proof = c.compute_weights(None, 1)
        assert not has_proof
        np.testing.assert_array_almost_equal(w, prev)

    def test_never_has_proof(self):
        c = NaiveCopier()
        for i in range(10):
            w, has_proof = c.compute_weights(None, i)
            assert not has_proof
            c.update_history(np.random.dirichlet(np.ones(64)))


class TestDelayedCopier:
    def test_adds_noise(self):
        c = DelayedCopier(num_miners=8, noise_std=0.05)
        prev = np.array([0.5, 0.3, 0.1, 0.05, 0.02, 0.01, 0.01, 0.01])
        c.update_history(prev)
        w, has_proof = c.compute_weights(None, 1)
        assert not has_proof
        # Should be different due to noise
        assert not np.allclose(w, prev, atol=1e-6)
        # But should sum to 1
        assert abs(w.sum() - 1.0) < 1e-6

    def test_non_negative(self):
        c = DelayedCopier(num_miners=8, noise_std=0.5)
        prev = np.array([0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.93])
        c.update_history(prev)
        for _ in range(20):
            w, _ = c.compute_weights(None, 1)
            assert np.all(w >= 0), "Weights must be non-negative"


class TestPartialCopier:
    def test_honest_fraction(self):
        c = PartialCopier(num_miners=64, honest_fraction=0.1)
        assert c.honest_count == 6  # floor(64 * 0.1)

    def test_never_has_proof(self):
        c = PartialCopier(num_miners=8, honest_fraction=0.5)
        prev = np.ones(8) / 8
        c.update_history(prev)
        w, has_proof = c.compute_weights(None, 1)
        assert not has_proof

    def test_weights_normalized(self):
        c = PartialCopier(num_miners=8, honest_fraction=0.25)
        prev = np.random.dirichlet(np.ones(8))
        c.update_history(prev)
        w, _ = c.compute_weights(None, 1)
        assert abs(w.sum() - 1.0) < 1e-6
        assert np.all(w >= 0)


class TestDetectionGuarantee:
    """Verify that copiers can never produce valid proofs."""

    def test_all_copiers_no_proof(self):
        strategies = [NaiveCopier(8), DelayedCopier(8), PartialCopier(8)]
        prev = np.random.dirichlet(np.ones(8))

        for copier in strategies:
            copier.update_history(prev)
            for epoch in range(20):
                w, has_proof = copier.compute_weights(None, epoch)
                assert not has_proof, (
                    f"{copier.name} claimed valid proof at epoch {epoch}"
                )
                copier.update_history(np.random.dirichlet(np.ones(8)))
