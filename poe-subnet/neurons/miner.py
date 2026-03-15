"""PoE Subnet Miner: generates and submits PoE proofs.

A "miner" on the PoE subnet is actually a validator on another subnet.
When queried, it generates a ZK proof that it honestly evaluated miners
on its home subnet.

Usage:
    python neurons/miner.py --netuid 1 --subtensor.network local \
        --wallet.name miner --wallet.hotkey default --poe_root ~/poe-bittensor
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import typing

import bittensor as bt
import numpy as np

from poe_subnet.protocol import ProofSubmission
from poe_subnet.config import PoESubnetConfig

from poe.config import PoEConfig
from poe.prover import PoEProver


def get_config() -> bt.Config:
    parser = argparse.ArgumentParser()
    parser.add_argument("--netuid", type=int, default=1)
    parser.add_argument("--poe_root", type=str, default=os.path.expanduser("~/poe-bittensor"))
    bt.Subtensor.add_args(parser)
    bt.Wallet.add_args(parser)
    bt.Axon.add_args(parser)
    bt.logging.add_args(parser)
    return bt.Config(parser)


import os


class Miner:
    """PoE proof generator neuron."""

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

        # PoE proving infrastructure
        poe_root = self.config.poe_root
        self.poe_config = PoEConfig.from_poe_root(poe_root)
        self.prover = PoEProver(self.poe_config, validator_id=self.uid)
        self.poe_subnet_config = PoESubnetConfig()

        # Proof cache per epoch
        self._proof_cache: dict[int, dict] = {}

        # Set up axon
        self.axon = bt.Axon(wallet=self.wallet, config=self.config)
        self.axon.attach(
            forward_fn=self.forward,
            blacklist_fn=self.blacklist,
            priority_fn=self.priority,
        )

        bt.logging.info(f"Miner initialized with UID {self.uid}")

    def _get_uid(self) -> int:
        hotkey = self.wallet.hotkey.ss58_address
        if hotkey in self.metagraph.hotkeys:
            return self.metagraph.hotkeys.index(hotkey)
        raise RuntimeError(f"Hotkey {hotkey} not registered on netuid {self.config.netuid}")

    async def forward(
        self, synapse: ProofSubmission
    ) -> ProofSubmission:
        """Generate or return cached PoE proof for the requested epoch."""
        epoch = synapse.epoch

        if epoch in self._proof_cache:
            bt.logging.debug(f"Returning cached proof for epoch {epoch}")
            cached = self._proof_cache[epoch]
            synapse.proof_b64 = cached["proof_b64"]
            synapse.public_inputs_json = cached["public_inputs_json"]
            synapse.proof_timestamp = cached["proof_timestamp"]
            return synapse

        bt.logging.info(f"Generating proof for epoch {epoch}")

        if self.prover.evaluation_count == 0:
            bt.logging.warning("No evaluations accumulated, cannot prove")
            return synapse

        try:
            proof = self.prover.prove(epoch, synapse.challenge_nonce)
            synapse.proof_b64 = ProofSubmission.encode_proof(proof.proof_bytes)
            synapse.public_inputs_json = json.dumps(proof.public_inputs)
            synapse.proof_timestamp = time.time()

            self._proof_cache[epoch] = {
                "proof_b64": synapse.proof_b64,
                "public_inputs_json": synapse.public_inputs_json,
                "proof_timestamp": synapse.proof_timestamp,
            }

            self.prover.reset()
            bt.logging.info(f"Proof generated: {len(proof.proof_bytes)} bytes")
        except Exception as e:
            bt.logging.error(f"Proof generation failed: {e}")

        return synapse

    async def blacklist(
        self, synapse: ProofSubmission
    ) -> typing.Tuple[bool, str]:
        """Only allow registered validators to request proofs."""
        caller = synapse.dendrite.hotkey
        if caller not in self.metagraph.hotkeys:
            return True, f"Unrecognized hotkey: {caller}"
        return False, ""

    async def priority(
        self, synapse: ProofSubmission
    ) -> float:
        """Prioritize by caller's stake."""
        caller = synapse.dendrite.hotkey
        if caller in self.metagraph.hotkeys:
            uid = self.metagraph.hotkeys.index(caller)
            return float(self.metagraph.S[uid])
        return 0.0

    def run(self):
        """Main miner loop."""
        bt.logging.info("Starting miner axon...")
        self.axon.serve(netuid=self.config.netuid, subtensor=self.subtensor)
        self.axon.start()
        bt.logging.info(
            f"Miner serving on {self.axon.external_ip}:{self.axon.external_port}"
        )

        try:
            while True:
                # Resync metagraph periodically
                self.metagraph.sync(subtensor=self.subtensor)
                time.sleep(12)
        except KeyboardInterrupt:
            bt.logging.info("Miner shutting down...")
        finally:
            self.axon.stop()


if __name__ == "__main__":
    miner = Miner()
    miner.run()
