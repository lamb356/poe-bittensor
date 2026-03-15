"""Synapse definitions for PoE proof submission and verification."""
from __future__ import annotations

import base64
import typing

try:
    import bittensor as bt
    _BaseSynapse = bt.Synapse
except ImportError:
    from pydantic import BaseModel

    class _BaseSynapse(BaseModel):
        def deserialize(self):
            return None


class ProofSubmission(_BaseSynapse):
    """Validator asks a miner to submit their PoE proof for a given epoch.

    Flow: Validator (dendrite) -> Miner (axon)
    - Validator sends: epoch, challenge_nonce, subnet_uid
    - Miner responds: proof_b64 (base64-encoded proof bytes), public_inputs_json

    proof_b64 uses base64 encoding because bittensor transports Synapse bodies
    as JSON, and raw bytes with arbitrary values can't be JSON-serialized.
    """

    # Required inputs — set by validator (dendrite caller)
    epoch: int
    challenge_nonce: int
    subnet_uid: int

    # Optional outputs — set by miner (axon receiver)
    proof_b64: typing.Optional[str] = None       # base64-encoded proof bytes
    public_inputs_json: typing.Optional[str] = None
    proof_timestamp: typing.Optional[float] = None
    zkverify_job_id: typing.Optional[str] = None

    def deserialize(self) -> typing.Optional[dict]:
        if self.proof_b64 is None:
            return None
        if len(self.proof_b64) > 25000:
            raise ValueError(
                f"proof_b64 too large: {len(self.proof_b64)} chars (max 25000)"
            )
        return {
            "proof_bytes": base64.b64decode(self.proof_b64),
            "public_inputs_json": self.public_inputs_json,
            "proof_timestamp": self.proof_timestamp,
        }

    @staticmethod
    def encode_proof(proof_bytes: bytes) -> str:
        """Encode raw proof bytes to base64 string for transport."""
        return base64.b64encode(proof_bytes).decode("ascii")

    @staticmethod
    def decode_proof(proof_b64: str) -> bytes:
        """Decode base64 proof string back to raw bytes."""
        return base64.b64decode(proof_b64)

    @property
    def proof_bytes(self) -> typing.Optional[bytes]:
        """Convenience: get decoded proof bytes."""
        if self.proof_b64 is None:
            return None
        return base64.b64decode(self.proof_b64)


class ProofChallenge(_BaseSynapse):
    """Validator challenges a miner to prove they evaluated a specific UID.

    Used for spot-checks: validator picks a random miner UID from the
    proof\'s public inputs and asks the prover to reveal the evaluation
    details for that UID.
    """

    # Required inputs
    epoch: int
    challenged_miner_uid: int

    # Optional outputs
    response_hash: typing.Optional[str] = None
    score: typing.Optional[int] = None
    weight: typing.Optional[int] = None

    def deserialize(self) -> typing.Optional[dict]:
        if self.response_hash is None:
            return None
        return {
            "response_hash": self.response_hash,
            "score": self.score,
            "weight": self.weight,
        }
