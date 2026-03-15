"""PoE verifier: verify proofs from peer validators."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from poe.config import PoEConfig


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
