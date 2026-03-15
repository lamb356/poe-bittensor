use poseidon::poseidon2::Poseidon2;

// ============================================================
// Lite PoE Circuit -- Proof-of-Evaluation for Bittensor
// 8 miners, 5 constraints, ~10-20K gates expected
// ============================================================

global NUM_MINERS: u32 = 8;
global MAX_WEIGHT: Field = 65535;
global MIN_WEIGHT_SUM: Field = 65528; // 65535 - (NUM_MINERS - 1) floor rounding slack

// ---- main circuit ----
fn main(
    // Public inputs (visible to verifier)
    input_commitment: pub Field,
    weight_commitment: pub Field,
    epoch: pub Field,
    validator_id: pub Field,
    // Private inputs (known only to prover)
    miner_uids: [Field; NUM_MINERS],
    response_hashes: [Field; NUM_MINERS],
    scores: [Field; NUM_MINERS],
    weights: [Field; NUM_MINERS],
    salt: Field,
) {
    // -------------------------------------------------------
    // CONSTRAINT 1: Input commitment binding
    // Poseidon2 hash of (miner_uids || response_hashes || epoch || salt)
    // Proves the validator had access to specific miner responses
    // -------------------------------------------------------
    let mut input_preimage: [Field; 2 * NUM_MINERS + 2] = [0; 2 * NUM_MINERS + 2];
    for i in 0..NUM_MINERS {
        input_preimage[i] = miner_uids[i];
        input_preimage[NUM_MINERS + i] = response_hashes[i];
    }
    input_preimage[2 * NUM_MINERS] = epoch;
    input_preimage[2 * NUM_MINERS + 1] = salt;

    let computed_input_commitment = Poseidon2::hash(input_preimage, 2 * NUM_MINERS + 2);
    assert(computed_input_commitment == input_commitment, "Input commitment mismatch");

    // -------------------------------------------------------
    // CONSTRAINT 2: Score-to-weight proportionality
    // weight[i] == floor(score[i] * 65535 / total_score)
    // Verified via: weight[i] * total_score + remainder == score[i] * 65535
    //   where 0 <= remainder < total_score
    // -------------------------------------------------------
    let mut total_score: Field = 0;
    for i in 0..NUM_MINERS {
        total_score += scores[i];
    }
    // total_score must be nonzero
    assert(total_score != 0, "Total score must be nonzero");

    for i in 0..NUM_MINERS {
        let expected_numerator = scores[i] * MAX_WEIGHT;
        let remainder = expected_numerator - weights[i] * total_score;
        // remainder must be in [0, total_score)
        // In Noir, Field is unsigned mod p, so we check via lt
        assert(remainder.lt(total_score), "Weight proportionality: remainder >= total_score");
    }

    // -------------------------------------------------------
    // CONSTRAINT 3: Weight sum in [65528, 65535]
    // Floor division can lose up to NUM_MINERS-1 from rounding
    // -------------------------------------------------------
    let mut weight_sum: Field = 0;
    for i in 0..NUM_MINERS {
        weight_sum += weights[i];
    }
    assert(!weight_sum.lt(MIN_WEIGHT_SUM), "Weight sum too low");
    assert(
        weight_sum.lt(MAX_WEIGHT + 1),
        "Weight sum exceeds 65535",
    );

    // -------------------------------------------------------
    // CONSTRAINT 4: Weight commitment binding
    // Poseidon2 hash of (weights || validator_id || epoch)
    // Changing even one weight invalidates the proof
    // -------------------------------------------------------
    let mut weight_preimage: [Field; NUM_MINERS + 2] = [0; NUM_MINERS + 2];
    for i in 0..NUM_MINERS {
        weight_preimage[i] = weights[i];
    }
    weight_preimage[NUM_MINERS] = validator_id;
    weight_preimage[NUM_MINERS + 1] = epoch;

    let computed_weight_commitment = Poseidon2::hash(weight_preimage, NUM_MINERS + 2);
    assert(computed_weight_commitment == weight_commitment, "Weight commitment mismatch");

    // -------------------------------------------------------
    // CONSTRAINT 5: Validator identity binding
    // validator_id is a public input included in weight commitment
    // Different validator = different commitment = proof can't be reused
    // (Enforced structurally: validator_id is pub + hashed into weight_commitment)
    // -------------------------------------------------------
}

// ============================================================
// Helper: compute commitments for test data
// ============================================================
fn compute_input_commitment(
    miner_uids: [Field; NUM_MINERS],
    response_hashes: [Field; NUM_MINERS],
    epoch: Field,
    salt: Field,
) -> Field {
    let mut preimage: [Field; 2 * NUM_MINERS + 2] = [0; 2 * NUM_MINERS + 2];
    for i in 0..NUM_MINERS {
        preimage[i] = miner_uids[i];
        preimage[NUM_MINERS + i] = response_hashes[i];
    }
    preimage[2 * NUM_MINERS] = epoch;
    preimage[2 * NUM_MINERS + 1] = salt;
    Poseidon2::hash(preimage, 2 * NUM_MINERS + 2)
}

fn compute_weight_commitment(
    weights: [Field; NUM_MINERS],
    validator_id: Field,
    epoch: Field,
) -> Field {
    let mut preimage: [Field; NUM_MINERS + 2] = [0; NUM_MINERS + 2];
    for i in 0..NUM_MINERS {
        preimage[i] = weights[i];
    }
    preimage[NUM_MINERS] = validator_id;
    preimage[NUM_MINERS + 1] = epoch;
    Poseidon2::hash(preimage, NUM_MINERS + 2)
}

fn compute_weights(scores: [Field; NUM_MINERS]) -> [Field; NUM_MINERS] {
    let mut total: Field = 0;
    for i in 0..NUM_MINERS {
        total += scores[i];
    }
    let mut weights: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        // floor(score * 65535 / total) -- compute via integer division trick
        // We need to find w such that w * total + r = score * 65535, 0 <= r < total
        // In tests we use known small values so we can compute directly
        weights[i] = (scores[i] * 65535) / total;
    }
    weights
}

// ============================================================
// Test fixtures
// ============================================================
fn test_miner_uids() -> [Field; NUM_MINERS] {
    [1, 2, 3, 4, 5, 6, 7, 8]
}

fn test_response_hashes() -> [Field; NUM_MINERS] {
    [101, 102, 103, 104, 105, 106, 107, 108]
}

fn test_scores() -> [Field; NUM_MINERS] {
    [100, 200, 150, 250, 300, 50, 175, 275]
}

fn test_salt() -> Field {
    999
}

fn test_epoch() -> Field {
    42
}

fn test_validator_id() -> Field {
    12345
}

// ============================================================
// TEST 1: Honest validator passes
// ============================================================
#[test]
fn test_honest_validator() {
    let miner_uids = test_miner_uids();
    let response_hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let validator_id = test_validator_id();
    let weights = compute_weights(scores);

    let ic = compute_input_commitment(miner_uids, response_hashes, epoch, salt);
    let wc = compute_weight_commitment(weights, validator_id, epoch);

    main(ic, wc, epoch, validator_id, miner_uids, response_hashes, scores, weights, salt);
}

// ============================================================
// TEST 2: Wrong weights rejected
// ============================================================
#[test(should_fail)]
fn test_wrong_weights_rejected() {
    let miner_uids = test_miner_uids();
    let response_hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let validator_id = test_validator_id();
    let mut weights = compute_weights(scores);

    // Tamper with one weight
    weights[0] = weights[0] + 1000;

    let ic = compute_input_commitment(miner_uids, response_hashes, epoch, salt);
    // Commitment uses tampered weights -- will pass commitment check
    // but weight proportionality (constraint 2) should fail
    let wc = compute_weight_commitment(weights, validator_id, epoch);

    main(ic, wc, epoch, validator_id, miner_uids, response_hashes, scores, weights, salt);
}

// ============================================================
// TEST 3: Wrong responses rejected
// ============================================================
#[test(should_fail)]
fn test_wrong_responses_rejected() {
    let miner_uids = test_miner_uids();
    let mut response_hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let validator_id = test_validator_id();
    let weights = compute_weights(scores);

    // Compute commitment with ORIGINAL responses
    let ic = compute_input_commitment(miner_uids, response_hashes, epoch, salt);
    let wc = compute_weight_commitment(weights, validator_id, epoch);

    // Fabricate response hashes -- input commitment will mismatch
    response_hashes[0] = 9999;

    main(ic, wc, epoch, validator_id, miner_uids, response_hashes, scores, weights, salt);
}

// ============================================================
// TEST 4: Epoch replay rejected
// ============================================================
#[test(should_fail)]
fn test_replay_different_epoch_rejected() {
    let miner_uids = test_miner_uids();
    let response_hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch(); // epoch 42
    let validator_id = test_validator_id();
    let weights = compute_weights(scores);

    // Commitments computed for epoch 42
    let ic = compute_input_commitment(miner_uids, response_hashes, epoch, salt);
    let wc = compute_weight_commitment(weights, validator_id, epoch);

    // Try to use proof in epoch 43 -- epoch is a public input so verifier
    // sets it to 43, but commitments were for 42 => mismatch
    let replayed_epoch: Field = 43;
    main(
        ic, wc, replayed_epoch, validator_id, miner_uids, response_hashes, scores, weights, salt,
    );
}
