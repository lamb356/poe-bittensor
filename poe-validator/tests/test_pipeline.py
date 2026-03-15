"""Full end-to-end pipeline test: eval -> witness -> prove -> verify.

This test calls real nargo and bb binaries. It requires the Noir toolchain
to be installed and the circuit to be compiled.

Run with: pytest tests/test_pipeline.py -v -s
"""
import os
import pytest
from pathlib import Path

from poe.config import PoEConfig
from poe.prover import PoEProver
from poe.verifier import PoEVerifier
from poe.challenge import get_mock_nonce
from poe.storage import Storage

POE_ROOT = Path.home() / "poe-bittensor"


def _check_toolchain():
    """Skip if Noir toolchain not available."""
    config = PoEConfig.from_poe_root(str(POE_ROOT))
    for binary in [config.witness_binary, config.nargo_binary, config.bb_binary]:
        if not os.path.isfile(binary):
            pytest.skip(f"Binary not found: {binary}")
    circuit_json = os.path.join(config.circuit_dir, "target", "poe_circuit.json")
    if not os.path.isfile(circuit_json):
        pytest.skip("Circuit not compiled (run nargo compile first)")


@pytest.fixture
def config(tmp_path):
    cfg = PoEConfig.from_poe_root(str(POE_ROOT), storage_dir=str(tmp_path / "proofs"))
    return cfg


@pytest.mark.slow
class TestFullPipeline:
    """End-to-end: add evaluations -> prove -> verify."""

    def test_prove_and_verify(self, config):
        _check_toolchain()

        prover = PoEProver(config, validator_id=1)
        verifier = PoEVerifier(config)
        storage = Storage(config)

        # Add 64 miner evaluations
        for uid in range(64):
            response = f"miner-{uid}-response-data-epoch-1".encode()
            score = (uid + 1) * 100  # scores 100..6400
            prover.add_evaluation(uid, response, score)

        epoch = 1
        nonce = get_mock_nonce(epoch)

        # Generate proof (this calls poe-witness, nargo execute, bb prove)
        proof = prover.prove(epoch, nonce)

        assert proof.epoch == epoch
        assert proof.challenge_nonce == nonce
        assert len(proof.proof_bytes) > 0
        print(f"Proof size: {len(proof.proof_bytes)} bytes")

        # Store it
        path = storage.publish(proof, epoch)
        assert path.exists()

        # Retrieve and verify
        proof_data = storage.retrieve(validator_id=1, epoch=epoch)
        assert proof_data is not None
        assert verifier.verify(proof_data)
        print("Proof verified successfully!")

        # Verify that random garbage fails
        assert not verifier.verify(b"\x00" * len(proof_data))

    def test_prover_reset_between_epochs(self, config):
        _check_toolchain()

        prover = PoEProver(config, validator_id=2)

        # Epoch 1
        for uid in range(64):
            prover.add_evaluation(uid, f"e1-{uid}".encode(), uid * 10)
        proof1 = prover.prove(1, get_mock_nonce(1))
        prover.reset()
        assert prover.evaluation_count == 0

        # Epoch 2 with different data
        for uid in range(64):
            prover.add_evaluation(uid, f"e2-{uid}".encode(), uid * 20)
        proof2 = prover.prove(2, get_mock_nonce(2))

        # Both proofs should be valid but different
        assert proof1.proof_bytes != proof2.proof_bytes

        verifier = PoEVerifier(config)
        assert verifier.verify(proof1.proof_bytes)
        assert verifier.verify(proof2.proof_bytes)
