"""Test ProofSubmission synapse over real axon/dendrite connection."""
import asyncio
import json
import os
import time
import typing
import pytest

import bittensor as bt

from poe_subnet.protocol import ProofSubmission
from poe.config import PoEConfig
from poe.prover import PoEProver
from poe.verifier import PoEVerifier
from poe.challenge import get_mock_nonce

POE_ROOT = os.path.expanduser("~/poe-bittensor")


def _check_toolchain():
    config = PoEConfig.from_poe_root(POE_ROOT)
    for binary in [config.witness_binary, config.nargo_binary, config.bb_binary]:
        if not os.path.isfile(binary):
            pytest.skip(f"Binary not found: {binary}")


@pytest.fixture
def wallets(tmp_path):
    miner_wallet = bt.Wallet(
        name="test-miner",
        hotkey="default",
        path=str(tmp_path / "wallets"),
    )
    miner_wallet.create_if_non_existent(coldkey_use_password=False, hotkey_use_password=False)

    validator_wallet = bt.Wallet(
        name="test-validator",
        hotkey="default",
        path=str(tmp_path / "wallets"),
    )
    validator_wallet.create_if_non_existent(coldkey_use_password=False, hotkey_use_password=False)

    return miner_wallet, validator_wallet


@pytest.mark.slow
class TestAxonDendrite:
    def test_proof_roundtrip_over_network(self, wallets):
        """Full test: miner generates proof via axon, validator verifies via dendrite."""
        _check_toolchain()

        miner_wallet, validator_wallet = wallets
        poe_config = PoEConfig.from_poe_root(POE_ROOT)
        prover = PoEProver(poe_config, validator_id=0)
        verifier = PoEVerifier(poe_config)

        # Pre-load evaluations
        for uid in range(64):
            prover.add_evaluation(uid, f"axon-test-{uid}".encode(), (uid + 1) * 50)

        proof_generated = False

        async def miner_forward(synapse: ProofSubmission) -> ProofSubmission:
            nonlocal proof_generated
            proof = prover.prove(synapse.epoch, synapse.challenge_nonce)
            synapse.proof_b64 = ProofSubmission.encode_proof(proof.proof_bytes)
            synapse.public_inputs_json = json.dumps({"epoch": proof.epoch})
            synapse.proof_timestamp = time.time()
            proof_generated = True
            return synapse

        async def miner_blacklist(synapse: ProofSubmission) -> typing.Tuple[bool, str]:
            return False, ""

        async def miner_priority(synapse: ProofSubmission) -> float:
            return 1.0

        axon = bt.Axon(wallet=miner_wallet, port=18091)
        axon.attach(
            forward_fn=miner_forward,
            blacklist_fn=miner_blacklist,
            priority_fn=miner_priority,
        )
        axon.start()

        try:
            dendrite = bt.Dendrite(wallet=validator_wallet)
            synapse = ProofSubmission(
                epoch=42,
                challenge_nonce=get_mock_nonce(42),
                subnet_uid=1,
            )

            miner_axon_info = bt.AxonInfo(
                version=1,
                ip="127.0.0.1",
                port=18091,
                ip_type=4,
                hotkey=miner_wallet.hotkey.ss58_address,
                coldkey=miner_wallet.coldkeypub.ss58_address,
            )

            loop = asyncio.new_event_loop()

            # Use deserialize=False to get back ProofSubmission objects
            responses = loop.run_until_complete(
                dendrite.forward(
                    axons=[miner_axon_info],
                    synapse=synapse,
                    deserialize=False,
                    timeout=120.0,
                )
            )
            loop.close()

            assert proof_generated, "Miner forward was never called"

            response = responses[0]
            print(f"Response type: {type(response)}")
            print(f"Response: {response}")

            # Handle both ProofSubmission object and dict response
            if isinstance(response, ProofSubmission):
                proof_b64 = response.proof_b64
                proof_bytes = response.proof_bytes
                pi_json = response.public_inputs_json
            elif isinstance(response, dict):
                proof_b64 = response.get("proof_b64")
                if proof_b64:
                    proof_bytes = ProofSubmission.decode_proof(proof_b64)
                else:
                    proof_bytes = None
                pi_json = response.get("public_inputs_json")
            else:
                # Maybe it has attributes
                proof_b64 = getattr(response, "proof_b64", None)
                proof_bytes = getattr(response, "proof_bytes", None) if proof_b64 is None else ProofSubmission.decode_proof(proof_b64)
                pi_json = getattr(response, "public_inputs_json", None)

            assert proof_b64 is not None, (
                f"No proof in response. Type: {type(response)}, "
                f"Content: {str(response)[:200]}"
            )

            assert len(proof_bytes) > 1000, f"Proof too small: {len(proof_bytes)}"

            # Verify the ZK proof
            assert verifier.verify(proof_bytes), "Proof verification failed"

            # Check public inputs roundtrip
            pi = json.loads(pi_json)
            assert pi["epoch"] == 42
            print(f"SUCCESS: Proof verified ({len(proof_bytes)} bytes)")

        finally:
            axon.stop()
