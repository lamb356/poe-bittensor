"""PoE verifier: verify proofs from peer validators."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from poe.config import PoEConfig

from dataclasses import dataclass


# UltraHonk proof layout (bb 0.82.2):
# bytes 0-3: circuit size (u32 BE)
# bytes 4-195: 6 public inputs, each 32 bytes BE
# bytes 196+: proof commitments and evaluations
PROOF_HEADER_SIZE = 4
PUBLIC_INPUT_SIZE = 32
NUM_PUBLIC_INPUTS = 6
PUBLIC_INPUTS_START = PROOF_HEADER_SIZE
PUBLIC_INPUTS_END = PUBLIC_INPUTS_START + NUM_PUBLIC_INPUTS * PUBLIC_INPUT_SIZE

# Public input field order (must match poe_circuit/src/main.nr)
PUBLIC_INPUT_NAMES = [
    "input_commitment",
    "weight_commitment",
    "score_commitment",
    "epoch",
    "validator_id",
    "challenge_nonce",
]


@dataclass
class AuthenticatedPublicInputs:
    """Public inputs extracted directly from verified proof bytes."""
    input_commitment: str
    weight_commitment: str
    score_commitment: str
    epoch: int
    validator_id: int
    challenge_nonce: int


@dataclass
class VerifyResult:
    """Result of proof verification with authenticated public inputs."""
    is_valid: bool
    public_inputs: AuthenticatedPublicInputs | None = None
    error: str | None = None


class PoEVerifier:
    """Verify PoE proofs using bb verify."""

    def __init__(self, config: PoEConfig):
        self.config = config
        self._vk_paths: dict[str, str] = {}

    def _ensure_vk(self, keccak_mode: bool = False) -> str:
        """Generate verification key, cache per mode."""
        mode = "keccak" if keccak_mode else "local"
        cached = self._vk_paths.get(mode)
        if cached and os.path.exists(cached):
            return cached

        circuit_json = os.path.join(self.config.circuit_dir, "target", "poe_circuit.json")
        vk_dir = os.path.join(self.config.storage_dir, f"vk_{mode}")
        os.makedirs(vk_dir, exist_ok=True)

        cmd = [
            self.config.bb_binary, "write_vk",
            "--scheme", "ultra_honk",
            "-b", circuit_json,
            "-o", vk_dir,
        ]
        if keccak_mode:
            cmd.extend(["--zk", "--oracle_hash", "keccak"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(
                f"bb write_vk failed (exit {result.returncode}):\n"
                f"stderr: {result.stderr}\nstdout: {result.stdout}"
            )
        self._vk_paths[mode] = os.path.join(vk_dir, "vk")
        return self._vk_paths[mode]

    def verify(self, proof_bytes: bytes, keccak_mode: bool = False) -> bool:
        """Verify a proof. Returns True if valid, False otherwise."""
        vk_path = self._ensure_vk(keccak_mode)

        with tempfile.TemporaryDirectory(prefix="poe-verify-") as tmpdir:
            proof_path = os.path.join(tmpdir, "proof")
            with open(proof_path, "wb") as f:
                f.write(proof_bytes)

            cmd = [
                self.config.bb_binary, "verify",
                "--scheme", "ultra_honk",
                "-p", proof_path,
                "-k", vk_path,
            ]
            if keccak_mode:
                cmd.extend(["--zk", "--oracle_hash", "keccak"])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return result.returncode == 0

    @staticmethod
    def extract_public_inputs(proof_bytes: bytes) -> AuthenticatedPublicInputs:
        """Extract public inputs directly from raw UltraHonk proof bytes.

        The proof format (bb 0.82.2) embeds public inputs at fixed offsets:
        bytes 0-3 = circuit size, bytes 4-195 = 6 x 32-byte public inputs.

        This is the SOLE trusted source of public input values.
        Do not trust sidecar JSON from miners.
        """
        min_size = PUBLIC_INPUTS_END
        if len(proof_bytes) < min_size:
            raise ValueError(
                f"Proof too small for public input extraction: "
                f"{len(proof_bytes)} bytes (need >= {min_size})"
            )

        fields = {}
        for i, name in enumerate(PUBLIC_INPUT_NAMES):
            start = PUBLIC_INPUTS_START + i * PUBLIC_INPUT_SIZE
            end = start + PUBLIC_INPUT_SIZE
            raw = proof_bytes[start:end]
            value = int.from_bytes(raw, "big")
            fields[name] = value

        return AuthenticatedPublicInputs(
            input_commitment=f"0x{fields['input_commitment']:064x}",
            weight_commitment=f"0x{fields['weight_commitment']:064x}",
            score_commitment=f"0x{fields['score_commitment']:064x}",
            epoch=fields["epoch"],
            validator_id=fields["validator_id"],
            challenge_nonce=fields["challenge_nonce"],
        )

    def verify_and_extract(
        self, proof_bytes: bytes, keccak_mode: bool = False
    ) -> VerifyResult:
        """Verify proof and extract authenticated public inputs.

        Returns a VerifyResult with is_valid=True and public_inputs only
        if the proof passes bb verify AND public inputs parse successfully.
        """
        # Step 1: Cryptographic verification
        is_valid = self.verify(proof_bytes, keccak_mode)
        if not is_valid:
            return VerifyResult(is_valid=False, error="Proof verification failed")

        # Step 2: Extract public inputs from the verified proof bytes
        try:
            pub_inputs = self.extract_public_inputs(proof_bytes)
            return VerifyResult(is_valid=True, public_inputs=pub_inputs)
        except Exception as e:
            return VerifyResult(
                is_valid=False,
                error=f"Public input extraction failed: {e}",
            )
