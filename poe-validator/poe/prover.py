"""PoE prover: accumulate evaluations, generate ZK proof."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from poe.config import PoEConfig


@dataclass
class PoEProof:
    """A completed PoE proof."""
    epoch: int
    challenge_nonce: int
    validator_id: int
    proof_bytes: bytes
    public_inputs: dict


class PoEProver:
    """Accumulate miner evaluations and generate a ZK proof."""

    def __init__(self, config: PoEConfig, validator_id: int):
        self.config = config
        self.validator_id = validator_id
        self._evaluations: dict[int, tuple[bytes, int]] = {}

    def add_evaluation(self, uid: int, response_bytes: bytes, score: int) -> None:
        """Record a single miner evaluation."""
        if not isinstance(uid, int) or uid < 0 or uid >= 65536:
            raise ValueError(f"uid must be u16, got {uid}")
        if not isinstance(score, int) or score < 0:
            raise ValueError(f"score must be non-negative int, got {score}")
        if uid in self._evaluations:
            raise ValueError(f"Duplicate UID {uid} in current epoch")
        if len(response_bytes) > self.config.max_response_bytes:
            raise ValueError(
                f"response_bytes too large: {len(response_bytes)} bytes "
                f"(max {self.config.max_response_bytes})"
            )
        self._evaluations[uid] = (response_bytes, score)

    @property
    def evaluation_count(self) -> int:
        return len(self._evaluations)

    def _build_eval_data(self, epoch: int, challenge_nonce: int) -> dict:
        """Build the EvaluationData JSON matching poe-witness types.rs."""
        n = self.config.num_miners

        # Sort by UID for determinism
        sorted_uids = sorted(self._evaluations.keys())

        # Pad to num_miners with dummy entries
        miner_uids: list[int] = []
        responses: list[list[int]] = []
        scores: list[int] = []

        for uid in sorted_uids:
            resp_bytes, score = self._evaluations[uid]
            miner_uids.append(uid)
            responses.append(list(resp_bytes))
            scores.append(score)

        # Pad remaining slots
        while len(miner_uids) < n:
            miner_uids.append(0)
            responses.append([0])
            scores.append(0)

        if len(miner_uids) > n:
            raise ValueError(
                f"Too many evaluations ({len(self._evaluations)}) for "
                f"num_miners={n}. Call reset() between epochs."
            )

        salt = secrets.randbelow(2**63)

        return {
            "miner_uids": miner_uids,
            "responses": responses,
            "scores": scores,
            "epoch": epoch,
            "validator_id": self.validator_id,
            "challenge_nonce": challenge_nonce,
            "salt": salt,
        }

    def prove(self, epoch: int, challenge_nonce: int, keccak_mode: bool = False) -> PoEProof:
        """Full proving pipeline: witness -> execute -> prove."""
        if not self._evaluations:
            raise ValueError("No evaluations accumulated")

        eval_data = self._build_eval_data(epoch, challenge_nonce)

        if sum(eval_data["scores"]) == 0:
            raise ValueError("All scores are zero — proving would fail in nargo")

        with tempfile.TemporaryDirectory(prefix="poe-") as tmpdir:
            # Step 1: Write evaluation data JSON
            eval_json = os.path.join(tmpdir, "eval_data.json")
            with open(eval_json, "w") as f:
                json.dump(eval_data, f)

            # Step 2: Run poe-witness to generate Prover.toml
            prover_toml = os.path.join(tmpdir, "Prover.toml")
            self._run_witness(eval_json, prover_toml)

            # Step 3: Copy Prover.toml with unique name to avoid concurrency races
            prover_name = f"poe_{epoch}_{int(time.time())}"
            circuit_prover = os.path.join(
                self.config.circuit_dir, f"{prover_name}.toml"
            )
            shutil.copy2(prover_toml, circuit_prover)

            try:
                # Step 4: nargo execute -> witness (unique name avoids races)
                self._run_nargo_execute(prover_name)

                # Step 5: bb prove -> proof
                proof_dir = os.path.join(tmpdir, "proof_out")
                proof_file = self._run_bb_prove(
                    proof_dir, keccak=keccak_mode, witness_name=prover_name,
                )
            finally:
                # Clean up unique prover TOML and witness
                for f in [
                    circuit_prover,
                    os.path.join(self.config.circuit_dir, "target", f"{prover_name}.gz"),
                ]:
                    try:
                        os.remove(f)
                    except FileNotFoundError:
                        pass

            # Read proof bytes
            with open(proof_file, "rb") as f:
                proof_bytes = f.read()

        return PoEProof(
            epoch=epoch,
            challenge_nonce=challenge_nonce,
            validator_id=self.validator_id,
            proof_bytes=proof_bytes,
            public_inputs=eval_data,
        )

    def _run_witness(self, input_json: str, output_toml: str) -> None:
        """Run poe-witness binary."""
        cmd = [
            self.config.witness_binary,
            "--input", input_json,
            "--output", output_toml,
            "--commitment-helper", self.config.commitment_helper_dir,
            "--nargo", self.config.nargo_binary,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"poe-witness failed (exit {result.returncode}):\n"
                f"stderr: {result.stderr}\nstdout: {result.stdout}"
            )

    def _run_nargo_execute(self, prover_name: str = "Prover") -> None:
        """Run nargo execute in the circuit directory."""
        cmd = [
            self.config.nargo_binary, "execute",
            "--prover-name", prover_name,
            "--program-dir", self.config.circuit_dir,
            prover_name,  # witness output name
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"nargo execute failed (exit {result.returncode}):\n"
                f"stderr: {result.stderr}\nstdout: {result.stdout}"
            )

    def _run_bb_prove(
        self, proof_output_dir: str, keccak: bool = False, witness_name: str = "poe_circuit",
    ) -> str:
        """Run bb prove with UltraHonk. Returns path to proof file."""
        circuit_json = os.path.join(self.config.circuit_dir, "target", "poe_circuit.json")
        witness_gz = os.path.join(self.config.circuit_dir, "target", f"{witness_name}.gz")
        os.makedirs(proof_output_dir, exist_ok=True)
        cmd = [
            self.config.bb_binary, "prove",
            "--scheme", "ultra_honk",
            "-b", circuit_json,
            "-w", witness_gz,
            "-o", proof_output_dir,
        ]
        if keccak:
            cmd.extend(["--zk", "--oracle_hash", "keccak"])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"bb prove failed (exit {result.returncode}):\n"
                f"stderr: {result.stderr}\nstdout: {result.stdout}"
            )
        return os.path.join(proof_output_dir, "proof")

    def reset(self) -> None:
        """Clear accumulated evaluations for next epoch."""
        self._evaluations.clear()
