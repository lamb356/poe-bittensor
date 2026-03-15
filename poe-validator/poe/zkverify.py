"""Python wrapper for poe-zkverify CLI binary."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from poe.config import PoEConfig


@dataclass
class ZkVerifyConfig:
    """Configuration for zkVerify bridge."""
    zkverify_binary: str = ""
    api_key: str = ""
    relayer_url: str = "https://relayer-api-testnet.horizenlabs.io/api/v1"
    variant: str = "plain"
    tempo_seconds: int = 4320


@dataclass
class ZkVerifyResult:
    """Result from a zkVerify submission."""
    job_id: str
    optimistic_verification: bool = False


@dataclass
class AttestationResult:
    """Result from waiting for attestation."""
    attestation_id: int
    leaf_digest: str


class ZkVerifySubmitter:
    """Submit proofs to zkVerify via the poe-zkverify CLI binary."""

    def __init__(self, poe_config: PoEConfig, zkv_config: ZkVerifyConfig):
        self.poe_config = poe_config
        self.zkv_config = zkv_config

    def submit_proof(
        self,
        proof_bytes: bytes,
        vk_path: str | None = None,
        public_inputs_path: str | None = None,
    ) -> ZkVerifyResult:
        """Submit a proof to zkVerify. Handles retry internally."""
        with tempfile.TemporaryDirectory(prefix="poe-zkv-") as tmpdir:
            # Write proof to temp file
            proof_file = os.path.join(tmpdir, "proof")
            with open(proof_file, "wb") as f:
                f.write(proof_bytes)

            # VK path: use cached or generate
            if vk_path is None:
                vk_dir = os.path.join(tmpdir, "vk_out")
                os.makedirs(vk_dir)
                circuit_json = os.path.join(
                    self.poe_config.circuit_dir, "target", "poe_circuit.json"
                )
                subprocess.run(
                    [
                        self.poe_config.bb_binary, "write_vk",
                        "--scheme", "ultra_honk",
                        "--oracle_hash", "keccak",
                        "-b", circuit_json,
                        "-o", vk_dir,
                    ],
                    check=True, capture_output=True,
                )
                vk_path = os.path.join(vk_dir, "vk")

            # Public inputs: extract from Prover.toml if not provided
            if public_inputs_path is None:
                public_inputs_path = os.path.join(tmpdir, "pubs")
                pubs = self._extract_public_inputs()
                with open(public_inputs_path, "wb") as f:
                    f.write(pubs)

            cmd = [
                self.zkv_config.zkverify_binary, "submit",
                "--proof", proof_file,
                "--vk", vk_path,
                "--pubs", public_inputs_path,
                "--relayer-url", self.zkv_config.relayer_url,
                "--variant", self.zkv_config.variant,
                "--tempo", str(self.zkv_config.tempo_seconds),
            ]
            env = {**os.environ, "ZKVERIFY_API_KEY": self.zkv_config.api_key}

            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                raise RuntimeError(
                    f"poe-zkverify submit failed: {result.stderr}"
                )

            data = json.loads(result.stdout)
            return ZkVerifyResult(
                job_id=data["job_id"],
                optimistic_verification=data.get("optimistic_verification", False),
            )

    def _extract_public_inputs(self) -> bytes:
        """Extract 5 public inputs from Prover.toml as 32-byte big-endian fields.

        Public inputs: input_commitment, weight_commitment, epoch,
        validator_id, challenge_nonce.
        """
        prover_toml = os.path.join(
            self.poe_config.circuit_dir, "Prover.toml"
        )
        field_names = [
            "input_commitment", "weight_commitment",
            "epoch", "validator_id", "challenge_nonce",
        ]
        values = {}
        with open(prover_toml) as f:
            for line in f:
                for name in field_names:
                    if line.startswith(f"{name} = "):
                        val = line.split("=", 1)[1].strip().strip("'").strip('"')
                        if val.startswith("0x"):
                            values[name] = int(val, 16)
                        else:
                            values[name] = int(val)
        if len(values) != 5:
            raise RuntimeError(
                f"Expected 5 public inputs, found {len(values)} in {prover_toml}"
            )
        return b"".join(values[n].to_bytes(32, "big") for n in field_names)

    def wait_for_attestation(
        self, job_id: str, timeout: int = 300
    ) -> AttestationResult:
        """Wait for a proof to be attested on zkVerify."""
        cmd = [
            self.zkv_config.zkverify_binary, "attest",
            "--job-id", job_id,
            "--timeout", str(timeout),
            "--relayer-url", self.zkv_config.relayer_url,
        ]
        env = {**os.environ, "ZKVERIFY_API_KEY": self.zkv_config.api_key}

        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise RuntimeError(
                f"poe-zkverify attest failed: {result.stderr}"
            )

        data = json.loads(result.stdout)
        return AttestationResult(
            attestation_id=data["attestation_id"],
            leaf_digest=data["leaf_digest"],
        )
