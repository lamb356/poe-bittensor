"""Bittensor validator lifecycle integration."""
from __future__ import annotations

from poe.challenge import get_challenge_nonce
from poe.config import PoEConfig
from poe.prover import PoEProver, PoEProof
from poe.storage import Storage


class PoEHooks:
    """Drop-in hooks for the Bittensor validator forward() loop."""

    def __init__(self, config: PoEConfig, validator_id: int):
        self.prover = PoEProver(config, validator_id)
        self.storage = Storage(config)

    def on_evaluation(self, uid: int, response: bytes, score: int) -> None:
        """Call after scoring each miner in forward()."""
        self.prover.add_evaluation(uid, response, score)

    def on_pre_set_weights(self, epoch: int) -> PoEProof:
        """Call before set_weights() to generate and store the proof."""
        nonce = get_challenge_nonce(epoch)
        proof = self.prover.prove(epoch, nonce)
        self.storage.publish(proof, epoch)
        self.prover.reset()
        return proof
