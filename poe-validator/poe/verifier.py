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
        self._vk_path: str | None = None

    def _ensure_vk(self) -> str:
        """Generate verification key once, cache the path."""
        if self._vk_path and os.path.exists(self._vk_path):
            return self._vk_path

        circuit_json = os.path.join(self.config.circuit_dir, "target", "poe_circuit.json")
        vk_dir = os.path.join(self.config.storage_dir, "vk")
        os.makedirs(vk_dir, exist_ok=True)

        # bb write_vk -o takes a DIRECTORY; it creates a "vk" file inside it
        cmd = [
            self.config.bb_binary, "write_vk",
            "--scheme", "ultra_honk",
            "-b", circuit_json,
            "-o", vk_dir,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"bb write_vk failed (exit {result.returncode}):\n"
                f"stderr: {result.stderr}\nstdout: {result.stdout}"
            )
        self._vk_path = os.path.join(vk_dir, "vk")
        return self._vk_path

    def verify(self, proof_bytes: bytes) -> bool:
        """Verify a proof. Returns True if valid, False otherwise."""
        vk_path = self._ensure_vk()

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
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
