"""Validator forward pass: query miners for proofs, verify, score."""
from __future__ import annotations

import json
import time

import bittensor as bt
import numpy as np

from poe.challenge import get_challenge_nonce
from poe_subnet.config import PoESubnetConfig
from poe_subnet.protocol import ProofSubmission
from poe_subnet.reward import get_rewards
from poe_subnet.utils.uids import get_random_uids


async def forward(validator) -> None:
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
        result = _verify_response(validator, response, config)
        proof_results.append(result)
        status = "valid" if result["proof_valid"] else "invalid/missing"
        bt.logging.debug(f"  UID {uid}: {status}")

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
            f"Proof too small: {len(proof_data)} bytes"
        )
        return {"proof_valid": False, "proof_timestamp": time.time()}

    try:
        is_valid = validator.verifier.verify(proof_data)
    except Exception as e:
        bt.logging.warning(f"Proof verification error: {e}")
        is_valid = False

    # Require public_inputs_json — without it, epoch/nonce binding cannot be verified
    if is_valid and not response.public_inputs_json:
        bt.logging.warning("Valid proof rejected: missing public_inputs_json")
        is_valid = False

    # M-11: Validate public inputs match current challenge
    if is_valid and response.public_inputs_json:
        try:
            pub_inputs = json.loads(response.public_inputs_json)

            # Require all 6 public input fields
            required = {
                "input_commitment", "weight_commitment", "score_commitment",
                "epoch", "validator_id", "challenge_nonce",
            }
            missing = required - set(pub_inputs.keys())
            if missing:
                bt.logging.warning(f"Missing public input fields: {missing}")
                is_valid = False

            # Verify epoch matches
            if pub_inputs.get("epoch") != response.epoch:
                bt.logging.warning(
                    f"Epoch mismatch: proof={pub_inputs.get('epoch')}, expected={response.epoch}"
                )
                is_valid = False

            # Verify challenge_nonce matches (compare as int to handle str vs int)
            proof_nonce = pub_inputs.get("challenge_nonce")
            if proof_nonce is not None and int(proof_nonce) != int(response.challenge_nonce):
                bt.logging.warning(
                    f"Nonce mismatch: proof={proof_nonce}, expected={response.challenge_nonce}"
                )
                is_valid = False

        except (json.JSONDecodeError, TypeError, ValueError) as e:
            bt.logging.warning(f"Malformed public_inputs_json: {e}")
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
