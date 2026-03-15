"""PoE Subnet Validator: verifies proofs from miners and sets weights.

Validators on the PoE subnet query miners (who are validators on other
subnets) for their PoE proofs, verify them, and reward honest validators.

Usage:
    python neurons/validator.py --netuid 1 --subtensor.network local \
        --wallet.name validator --wallet.hotkey default --poe_root ~/poe-bittensor
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time

import bittensor as bt
import numpy as np

import poe_subnet
from poe_subnet.config import PoESubnetConfig
from poe_subnet.validator.forward import forward

from poe.config import PoEConfig
from poe.verifier import PoEVerifier


def get_config() -> bt.Config:
    parser = argparse.ArgumentParser()
    parser.add_argument("--netuid", type=int, default=1)
    parser.add_argument("--poe_root", type=str, default=os.path.expanduser("~/poe-bittensor"))
    parser.add_argument("--sample_size", type=int, default=16)
    parser.add_argument("--log_dir", type=str, default="testnet/logs")
    bt.Subtensor.add_args(parser)
    bt.Wallet.add_args(parser)
    bt.logging.add_args(parser)
    return bt.Config(parser)


class Validator:
    """PoE proof verifier neuron."""

    def __init__(self, config: bt.Config | None = None):
        self.config = config or get_config()
        bt.logging(config=self.config)

        self.wallet = bt.Wallet(config=self.config)
        self.subtensor = bt.Subtensor(config=self.config)
        self.metagraph = bt.Metagraph(
            netuid=self.config.netuid,
            network=self.subtensor.network,
            sync=True,
            subtensor=self.subtensor,
        )

        # Find our UID
        self.uid = self._get_uid()

        # PoE verification infrastructure
        poe_root = self.config.poe_root
        self.poe_config = PoEConfig.from_poe_root(poe_root)
        self.verifier = PoEVerifier(self.poe_config)
        self.poe_subnet_config = PoESubnetConfig(
            netuid=self.config.netuid,
            sample_size=getattr(self.config, "sample_size", 16),
        )

        # Per-UID scores (exponential moving average)
        self.scores = np.zeros(self.metagraph.n, dtype=np.float32)

        # Dendrite for querying miners
        self.dendrite = bt.Dendrite(wallet=self.wallet)

        self._last_weights_block = 0

        # Telemetry for campaign monitoring
        from poe_subnet.telemetry import TelemetryLogger
        wallet_name = self.config.wallet.name if hasattr(self.config.wallet, 'name') else "unknown"
        log_dir = getattr(self.config, 'log_dir', 'testnet/logs')
        self.telemetry = TelemetryLogger(log_dir, f"validator_{wallet_name}")

        self.load_state()
        bt.logging.info(f"Validator initialized with UID {self.uid}")

    def _get_uid(self) -> int:
        hotkey = self.wallet.hotkey.ss58_address
        if hotkey in self.metagraph.hotkeys:
            return self.metagraph.hotkeys.index(hotkey)
        raise RuntimeError(f"Hotkey {hotkey} not registered on netuid {self.config.netuid}")

    @property
    def block(self) -> int:
        return self.subtensor.get_current_block()

    def update_scores(self, rewards: np.ndarray, uids: np.ndarray) -> None:
        """Update scores with exponential moving average."""
        alpha = self.poe_subnet_config.moving_average_alpha
        for i, uid in enumerate(uids):
            if uid < len(self.scores):
                self.scores[uid] = alpha * rewards[i] + (1 - alpha) * self.scores[uid]

    def set_weights(self) -> None:
        """Submit weights to the chain."""
        total = np.sum(self.scores)
        if total == 0:
            bt.logging.warning("All scores are zero, skipping weight set")
            return

        raw_weights = self.scores / total

        # Filter to non-zero
        mask = raw_weights > 0
        uids = np.where(mask)[0]
        weights = raw_weights[mask]

        # Normalize to uint16
        weights_u16 = (weights / weights.max() * 65535).astype(int)

        bt.logging.info(
            f"Setting weights for {len(uids)} UIDs, "
            f"max={weights_u16.max()}, min={weights_u16.min()}"
        )

        result = self.subtensor.set_weights(
            wallet=self.wallet,
            netuid=self.config.netuid,
            uids=uids.tolist(),
            weights=weights_u16.tolist(),
            version_key=poe_subnet.__spec_version__,
        )
        bt.logging.info(f"set_weights result: {result}")
        self._last_weights_block = self.block

    def save_state(self) -> None:
        state_dir = os.path.expanduser("~/.poe-subnet")
        os.makedirs(state_dir, exist_ok=True)
        np.save(os.path.join(state_dir, "scores.npy"), self.scores)

    def load_state(self) -> None:
        path = os.path.join(os.path.expanduser("~/.poe-subnet"), "scores.npy")
        if os.path.exists(path):
            loaded = np.load(path)
            if len(loaded) == len(self.scores):
                self.scores = loaded
                bt.logging.info("Loaded saved scores")

    def run(self):
        """Main validator loop."""
        bt.logging.info("Starting validator loop...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            while True:
                try:
                    loop.run_until_complete(forward(self, telemetry=self.telemetry))
                except Exception as e:
                    bt.logging.error(f"Forward pass failed: {e}")

                # Set weights every tempo blocks
                current_block = self.block
                blocks_since = current_block - self._last_weights_block
                if blocks_since >= self.poe_subnet_config.tempo:
                    self.set_weights()
                    self.save_state()

                # Resync metagraph
                self.metagraph.sync(subtensor=self.subtensor)
                time.sleep(12)
        except KeyboardInterrupt:
            bt.logging.info("Validator shutting down...")
        finally:
            loop.close()


if __name__ == "__main__":
    validator = Validator()
    validator.run()
