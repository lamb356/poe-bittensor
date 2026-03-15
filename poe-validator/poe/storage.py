"""Local proof storage."""
from __future__ import annotations

import os
from pathlib import Path

from poe.config import PoEConfig
from poe.prover import PoEProof


class Storage:
    """Store and retrieve proofs on the local filesystem."""

    def __init__(self, config: PoEConfig):
        self.base_dir = Path(config.storage_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, proof: PoEProof, epoch: int) -> Path:
        """Save a proof to local storage. Returns the proof file path."""
        epoch_dir = self.base_dir / f"epoch_{epoch}"
        epoch_dir.mkdir(parents=True, exist_ok=True)
        proof_path = epoch_dir / f"proof_{proof.validator_id}"
        proof_path.write_bytes(proof.proof_bytes)
        return proof_path

    def retrieve(self, validator_id: int, epoch: int) -> bytes | None:
        """Load a proof from local storage. Returns None if not found."""
        proof_path = self.base_dir / f"epoch_{epoch}" / f"proof_{validator_id}"
        if not proof_path.exists():
            return None
        return proof_path.read_bytes()
