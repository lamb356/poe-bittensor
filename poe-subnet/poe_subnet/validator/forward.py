"""Validator forward pass: query miners for proofs, verify, score."""
from __future__ import annotations

import time

import bittensor as bt
import numpy as np

from poe.challenge import get_challenge_nonce
from poe_subnet.config import PoESubnetConfig
from poe_subnet.protocol import ProofSubmission
from poe_subnet.reward import get_rewards
from poe_subnet.utils.uids import get_random_uids


async def forward(validator, telemetry=None) -> None:
    """Query miners for PoE proofs and score them.

    Called each step by the validator's main loop.
    """
    config: PoESubnetConfig = validator.poe_subnet_config
    current_block = validator.block

    # Determine current epoch
    epoch = current_block // config.tempo
    epoch_end_time = time.time()

    # Challenge nonce for this epoch
    challenge_nonce = get_challenge_nonce(epoch)

    # Select miners to query
    miner_uids = get_random_uids(
        validator.metagraph,
        k=config.sample_size,
        exclude={validator.uid},
    )

    if len(miner_uids) == 0:
        bt.logging.warning("No miners available to query")
        return

    bt.logging.info(
        f"Querying {len(miner_uids)} miners for epoch {epoch} proofs"
    )

    # Query miners for proof submissions
    synapse = ProofSubmission(
        epoch=epoch,
        challenge_nonce=challenge_nonce,
        subnet_uid=config.netuid,
    )

    responses = await validator.dendrite.forward(
        axons=[validator.metagraph.axons[uid] for uid in miner_uids],
        synapse=synapse,
        deserialize=False,
        timeout=config.proof_timeout,
    )

    # Verify each proof
    proof_results = []
    for uid, response in zip(miner_uids, responses):
        verify_start = time.time()
        result = _verify_response(validator, response, config)
        verify_elapsed_ms = (time.time() - verify_start) * 1000
        proof_results.append(result)
        status = "valid" if result["proof_valid"] else "invalid/missing"
        bt.logging.debug(f"  UID {uid}: {status}")

        if telemetry:
            # Get proof size from response
            proof_size = 0
            if response.proof_b64:
                try:
                    proof_size = len(response.decode_and_validate_proof() or b"")
                except Exception:
                    pass
            telemetry.log(
                tempo=epoch,
                uid=int(uid),
                has_valid_proof=result["proof_valid"],
                verify_time_ms=round(verify_elapsed_ms, 1),
                proof_size_bytes=proof_size,
            )

    # Score miners
    rewards = get_rewards(proof_results, epoch_end_time, config)
    bt.logging.info(
        f"Rewards: mean={rewards.mean():.3f}, "
        f"valid={np.sum(rewards > 0)}/{len(rewards)}"
    )

    validator.update_scores(rewards, miner_uids)


def _verify_response(
    validator,
    response: ProofSubmission,
    config: PoESubnetConfig,
) -> dict:
    """Verify a single miner's proof submission."""
    if response.proof_b64 is None:
        return {"proof_valid": False, "proof_timestamp": None}

    try:
        proof_data = response.decode_and_validate_proof()
    except (ValueError, Exception) as e:
        bt.logging.debug(f"Proof decode/validation failed: {e}")
        return {"proof_valid": False, "proof_timestamp": time.time()}

    if proof_data is None or len(proof_data) < config.min_proof_size:
        bt.logging.debug(
            f"Proof too small: {len(proof_data) if proof_data else 0} bytes"
        )
        return {"proof_valid": False, "proof_timestamp": time.time()}

    # Verify proof and extract authenticated public inputs
    try:
        result = validator.verifier.verify_and_extract(proof_data)
    except Exception as e:
        bt.logging.warning(f"Proof verification error: {e}")
        return {"proof_valid": False, "proof_timestamp": time.time()}

    is_valid = result.is_valid

    # Enforce epoch and challenge_nonce from authenticated proof contents
    if is_valid and result.public_inputs:
        pi = result.public_inputs
        if pi.epoch != response.epoch:
            bt.logging.warning(
                f"Epoch mismatch: proof={pi.epoch}, expected={response.epoch}"
            )
            is_valid = False
        if pi.challenge_nonce != int(response.challenge_nonce):
            bt.logging.warning(
                f"Nonce mismatch: proof={pi.challenge_nonce}, "
                f"expected={response.challenge_nonce}"
            )
            is_valid = False
    elif is_valid:
        # Extraction failed but proof was valid — fail closed
        bt.logging.warning(
            f"Valid proof but public input extraction failed: {result.error}"
        )
        is_valid = False

    # H-11: Log zkVerify attestation status (soft enforcement)
    if response.zkverify_job_id:
        bt.logging.debug(f"zkVerify job_id: {response.zkverify_job_id}")
    elif is_valid:
        bt.logging.trace(f"Valid proof without zkVerify attestation")

    return {
        "proof_valid": is_valid,
        "proof_timestamp": time.time(),
    }
