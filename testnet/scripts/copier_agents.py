"""Simulated copier validators for testnet detection testing.

Three copier strategies with varying sophistication:
- NaiveCopier: copies previous epoch's consensus weights verbatim
- DelayedCopier: copies with 1-tempo delay + small random perturbations
- PartialCopier: evaluates 10% of miners honestly, copies the rest

Each runs as a Bittensor validator but generates invalid/no PoE proofs,
which the PoE verification system should detect and penalize.

Usage:
    python testnet/scripts/copier_agents.py \
        --strategy naive --wallet-name copier-1 \
        --netuid 1 --network test --poe-root ~/poe-bittensor
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import typing

import numpy as np

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from poe_subnet.config import PoESubnetConfig


class CopierStrategy:
    """Base class for copier strategies."""

    name: str = "base"

    def __init__(self, num_miners: int = 64):
        self.num_miners = num_miners
        self._prev_weights: np.ndarray | None = None
        self._epoch_count = 0

    def compute_weights(
        self,
        metagraph_weights: np.ndarray | None,
        epoch: int,
    ) -> tuple[np.ndarray, bool]:
        """Compute weights for this epoch.

        Returns:
            (weights, has_valid_proof): weights array and whether a valid
            proof was generated (always False for copiers).
        """
        raise NotImplementedError

    def update_history(self, consensus_weights: np.ndarray) -> None:
        """Called after each epoch with the consensus weights."""
        self._prev_weights = consensus_weights.copy()
        self._epoch_count += 1


class NaiveCopier(CopierStrategy):
    """Copies previous epoch's consensus weights verbatim.

    The simplest attack: just submit whatever the network agreed on
    last time. PoE catches this because the copier has no miner
    responses to commit to — the input_commitment will be invalid.
    """

    name = "naive"

    def compute_weights(self, metagraph_weights, epoch):
        if self._prev_weights is None:
            # First epoch: uniform weights
            w = np.ones(self.num_miners) / self.num_miners
            return w, False

        return self._prev_weights.copy(), False


class DelayedCopier(CopierStrategy):
    """Copies weights from 1 tempo ago with small random perturbations.

    More sophisticated: adds noise to avoid exact-match detection.
    PoE still catches this because the copier doesn't have the actual
    miner responses — the BLAKE3 hashes in the proof won't match.
    """

    name = "delayed"

    def __init__(self, num_miners: int = 64, noise_std: float = 0.02):
        super().__init__(num_miners)
        self.noise_std = noise_std

    def compute_weights(self, metagraph_weights, epoch):
        if self._prev_weights is None:
            w = np.ones(self.num_miners) / self.num_miners
            return w, False

        # Add Gaussian noise
        noise = np.random.normal(0, self.noise_std, self.num_miners)
        perturbed = self._prev_weights + noise

        # Clamp to non-negative and renormalize
        perturbed = np.maximum(perturbed, 0)
        total = perturbed.sum()
        if total > 0:
            perturbed /= total
        else:
            perturbed = np.ones(self.num_miners) / self.num_miners

        return perturbed, False


class PartialCopier(CopierStrategy):
    """Evaluates a fraction of miners honestly, copies the rest.

    The most sophisticated attack: actually queries some miners to
    build partial credibility, but copies weights for miners it didn't
    evaluate. PoE catches this because the proof must cover ALL miners —
    the input_commitment includes all 64 response hashes, and the
    copier doesn't have valid hashes for the unevaluated miners.
    """

    name = "partial"

    def __init__(self, num_miners: int = 64, honest_fraction: float = 0.1):
        super().__init__(num_miners)
        self.honest_fraction = honest_fraction
        self.honest_count = max(1, int(num_miners * honest_fraction))

    def compute_weights(self, metagraph_weights, epoch):
        if self._prev_weights is None:
            w = np.ones(self.num_miners) / self.num_miners
            return w, False

        # Pick which miners to evaluate honestly
        honest_uids = set(random.sample(range(self.num_miners), self.honest_count))

        # Generate "honest" scores for evaluated miners
        honest_scores = {}
        for uid in honest_uids:
            # Simulate honest evaluation: random score
            honest_scores[uid] = random.uniform(0.1, 1.0)

        # Build weights: honest for evaluated, copied for the rest
        weights = np.zeros(self.num_miners)
        for uid in range(self.num_miners):
            if uid in honest_uids:
                weights[uid] = honest_scores[uid]
            else:
                weights[uid] = self._prev_weights[uid]

        # Normalize
        total = weights.sum()
        if total > 0:
            weights /= total

        # This copier CANNOT generate a valid proof because it doesn't
        # have response hashes for the unevaluated miners
        return weights, False


STRATEGIES: dict[str, type[CopierStrategy]] = {
    "naive": NaiveCopier,
    "delayed": DelayedCopier,
    "partial": PartialCopier,
}


def get_args():
    parser = argparse.ArgumentParser(description="Copier agent for PoE testnet")
    parser.add_argument("--strategy", choices=STRATEGIES.keys(), required=True)
    parser.add_argument("--wallet-name", required=True)
    parser.add_argument("--netuid", type=int, default=1)
    parser.add_argument("--network", default="test")
    parser.add_argument("--poe-root", default=os.path.expanduser("~/poe-bittensor"))
    parser.add_argument("--num-tempos", type=int, default=100)
    parser.add_argument("--tempo-seconds", type=int, default=4320, help="Seconds per tempo")
    parser.add_argument("--noise-std", type=float, default=0.02, help="Noise for delayed copier")
    parser.add_argument("--honest-fraction", type=float, default=0.1, help="Fraction for partial copier")
    parser.add_argument("--log-dir", default="testnet/logs")
    return parser.parse_args()


def run_copier(args):
    """Run a copier agent for the specified number of tempos."""
    strategy_cls = STRATEGIES[args.strategy]
    kwargs = {}
    if args.strategy == "delayed":
        kwargs["noise_std"] = args.noise_std
    elif args.strategy == "partial":
        kwargs["honest_fraction"] = args.honest_fraction

    copier = strategy_cls(num_miners=64, **kwargs)

    os.makedirs(args.log_dir, exist_ok=True)
    log_file = os.path.join(args.log_dir, f"copier_{args.strategy}_{args.wallet_name}.jsonl")

    print(f"Copier agent: {args.strategy}")
    print(f"Wallet: {args.wallet_name}")
    print(f"Logging to: {log_file}")

    for tempo in range(args.num_tempos):
        start = time.time()

        # In a real deployment, we'd query the metagraph for consensus weights.
        # For simulation, generate synthetic "consensus" weights.
        if copier._prev_weights is None:
            # First tempo: simulate consensus
            consensus = np.random.dirichlet(np.ones(64))
        else:
            # Subsequent tempos: consensus shifts slightly
            noise = np.random.normal(0, 0.01, 64)
            consensus = copier._prev_weights + noise
            consensus = np.maximum(consensus, 0)
            consensus /= consensus.sum()

        weights, has_proof = copier.compute_weights(consensus, tempo)
        copier.update_history(consensus)

        elapsed = time.time() - start

        # Log
        entry = {
            "tempo": tempo,
            "strategy": args.strategy,
            "wallet": args.wallet_name,
            "has_valid_proof": has_proof,
            "weight_entropy": float(-np.sum(weights * np.log(weights + 1e-10))),
            "weight_diff_from_consensus": float(np.linalg.norm(weights - consensus)),
            "elapsed_seconds": elapsed,
            "timestamp": time.time(),
        }

        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

        if tempo % 10 == 0:
            print(
                f"  Tempo {tempo}: proof={has_proof}, "
                f"diff={entry['weight_diff_from_consensus']:.4f}, "
                f"entropy={entry['weight_entropy']:.2f}"
            )

    print(f"\nCopier {args.strategy} finished {args.num_tempos} tempos")
    print(f"Logs: {log_file}")


if __name__ == "__main__":
    args = get_args()
    run_copier(args)
