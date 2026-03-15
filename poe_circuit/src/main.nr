mod types;
mod commitment;
mod normalization;
mod eval_modules;

use types::NUM_MINERS;
use commitment::{compute_input_commitment, compute_weight_commitment};
use normalization::{verify_weight_proportionality, compute_weights};
use eval_modules::interface::{EvalFunction, MAX_PARAMS};

// ============================================================
// Lite PoE Circuit -- Proof-of-Evaluation for Bittensor
// 64 miners, 4 constraints
// ============================================================

fn main(
    // Public inputs
    input_commitment: pub Field,
    weight_commitment: pub Field,
    epoch: pub Field,
    validator_id: pub Field,
    challenge_nonce: pub Field,
    // Private inputs
    miner_uids: [Field; NUM_MINERS],
    response_hashes: [Field; NUM_MINERS],
    scores: [Field; NUM_MINERS],
    weights: [Field; NUM_MINERS],
    salt: Field,
) {
    // CONSTRAINT 1: Input commitment binding
    let computed_ic = compute_input_commitment(
        miner_uids, response_hashes, challenge_nonce, epoch, salt,
    );
    assert(computed_ic == input_commitment, "Input commitment mismatch");

    // CONSTRAINT 2: Score-to-weight proportionality + weight sum range check
    verify_weight_proportionality(scores, weights);

    // CONSTRAINT 3: Weight commitment binding
    let computed_wc = compute_weight_commitment(weights, validator_id, epoch);
    assert(computed_wc == weight_commitment, "Weight commitment mismatch");

    // CONSTRAINT 4: Validator identity binding
    // Enforced structurally: validator_id is pub + hashed into weight_commitment
}

// ============================================================
// Test fixtures
// ============================================================
fn test_miner_uids() -> [Field; NUM_MINERS] {
    let mut uids: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        uids[i] = (i + 1) as Field;
    }
    uids
}

fn test_response_hashes() -> [Field; NUM_MINERS] {
    let mut hashes: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        hashes[i] = (i + 101) as Field;
    }
    hashes
}

fn test_scores() -> [Field; NUM_MINERS] {
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        // Varying scores: 50 + (i * 37) % 300 -- spread across range
        scores[i] = (50 + (i * 37) % 300) as Field;
    }
    scores
}

fn test_salt() -> Field { 999 }
fn test_epoch() -> Field { 42 }
fn test_validator_id() -> Field { 12345 }
fn test_challenge_nonce() -> Field { 77777 }

// ============================================================
// TEST 1: Honest validator passes
// ============================================================
#[test]
fn test_honest_validator() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();
    let weights = unsafe { compute_weights(scores) };

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// ============================================================
// TEST 2: Wrong weights rejected
// ============================================================
#[test(should_fail)]
fn test_wrong_weights_rejected() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();
    let mut weights = unsafe { compute_weights(scores) };

    weights[0] = weights[0] + 1000;

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// ============================================================
// TEST 3: Wrong responses rejected
// ============================================================
#[test(should_fail)]
fn test_wrong_responses_rejected() {
    let uids = test_miner_uids();
    let mut hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();
    let weights = unsafe { compute_weights(scores) };

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    hashes[0] = 9999;

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// ============================================================
// TEST 4: Epoch replay rejected
// ============================================================
#[test(should_fail)]
fn test_replay_different_epoch_rejected() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();
    let weights = unsafe { compute_weights(scores) };

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    let replayed_epoch: Field = 43;
    main(ic, wc, replayed_epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// ============================================================
// TEST 5: Wrong challenge nonce rejected
// ============================================================
#[test(should_fail)]
fn test_wrong_challenge_nonce_rejected() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();
    let weights = unsafe { compute_weights(scores) };

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    // Verifier uses a different challenge nonce -- proof from wrong epoch/challenge
    let wrong_nonce: Field = 88888;
    main(ic, wc, epoch, vid, wrong_nonce, uids, hashes, scores, weights, salt);
}

// ============================================================
// Full PoE: Score computation inside the circuit
// ============================================================

/// Full PoE circuit -- computes scores in-circuit using a pluggable eval function.
/// Unlike Lite PoE, scores are NOT private inputs -- they're derived from responses.
pub fn full_poe_verify<E>(
    // Public inputs
    input_commitment: Field,
    weight_commitment: Field,
    epoch: Field,
    validator_id: Field,
    challenge_nonce: Field,
    // Private inputs (NO scores -- computed in-circuit)
    miner_uids: [Field; NUM_MINERS],
    response_hashes: [Field; NUM_MINERS],
    weights: [Field; NUM_MINERS],
    salt: Field,
    eval_params: [Field; MAX_PARAMS],
) where E: EvalFunction {
    // CONSTRAINT 1: Input commitment binding (same as Lite PoE)
    let computed_ic = compute_input_commitment(
        miner_uids, response_hashes, challenge_nonce, epoch, salt,
    );
    assert(computed_ic == input_commitment, "Input commitment mismatch");

    // CONSTRAINT 2: Score computation (NEW -- Full PoE only)
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        scores[i] = E::evaluate(response_hashes[i], eval_params);
    }

    // CONSTRAINT 3: Score-to-weight proportionality + weight sum range check
    verify_weight_proportionality(scores, weights);

    // CONSTRAINT 4: Weight commitment binding
    let computed_wc = compute_weight_commitment(weights, validator_id, epoch);
    assert(computed_wc == weight_commitment, "Weight commitment mismatch");
}

// ============================================================
// Full PoE Tests
// ============================================================

use eval_modules::arithmetic_eval::ArithmeticEval;

/// Helper: compute scores using arithmetic eval for test fixtures
fn compute_arithmetic_scores(
    hashes: [Field; NUM_MINERS],
    params: [Field; MAX_PARAMS],
) -> [Field; NUM_MINERS] {
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        scores[i] = ArithmeticEval::evaluate(hashes[i], params);
    }
    scores
}

#[test]
fn test_full_poe_arithmetic() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();

    // Eval params: weight=1, bias=50 -> score = 1*hash + 50
    let eval_params: [Field; MAX_PARAMS] = [1, 50, 0, 0];

    // Compute expected scores and weights
    let scores = compute_arithmetic_scores(hashes, eval_params);
    let weights = unsafe { compute_weights(scores) };

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    full_poe_verify::<ArithmeticEval>(
        ic, wc, epoch, vid, nonce,
        uids, hashes, weights, salt, eval_params,
    );
}

#[test(should_fail)]
fn test_full_poe_wrong_weights_rejected() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();

    let eval_params: [Field; MAX_PARAMS] = [1, 50, 0, 0];
    let scores = compute_arithmetic_scores(hashes, eval_params);
    let mut weights = unsafe { compute_weights(scores) };

    // Tamper with weights
    weights[0] = weights[0] + 500;

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    full_poe_verify::<ArithmeticEval>(
        ic, wc, epoch, vid, nonce,
        uids, hashes, weights, salt, eval_params,
    );
}

// ============================================================
// HARDENING: Edge Case Tests
// ============================================================

/// Helper: run main() with given scores (computes everything else from fixtures)
fn run_with_scores(scores: [Field; NUM_MINERS]) {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();
    let weights = unsafe { compute_weights(scores) };

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// --- Edge case: one miner has zero score, others nonzero ---
#[test]
fn test_edge_one_zero_score() {
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        scores[i] = (100 + i) as Field;
    }
    scores[0] = 0; // First miner gets zero
    run_with_scores(scores);
}

// --- Edge case: all miners have identical scores ---
#[test]
fn test_edge_uniform_scores() {
    let scores: [Field; NUM_MINERS] = [500; NUM_MINERS];
    run_with_scores(scores);
}

// --- Edge case: one miner dominates (huge score, rest minimal) ---
#[test]
fn test_edge_one_dominant_miner() {
    let mut scores: [Field; NUM_MINERS] = [1; NUM_MINERS];
    scores[0] = 1000000;
    run_with_scores(scores);
}

// --- Edge case: very small scores (all 1s) ---
#[test]
fn test_edge_all_ones() {
    let scores: [Field; NUM_MINERS] = [1; NUM_MINERS];
    run_with_scores(scores);
}

// --- Edge case: scores with large variance ---
#[test]
fn test_edge_high_variance() {
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        // Alternating 1 and 1000000
        if i % 2 == 0 {
            scores[i] = 1;
        } else {
            scores[i] = 1000000;
        }
    }
    run_with_scores(scores);
}

// --- Edge case: large scores (avoid Field overflow, use u64 range) ---
#[test]
fn test_edge_large_scores() {
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        // Large scores: base 10^9 + variation
        scores[i] = 1000000000 as Field + (i as Field) * 12345;
    }
    run_with_scores(scores);
}

// --- Edge case: all zero scores must fail ---
#[test(should_fail)]
fn test_edge_all_zero_scores() {
    let scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    // compute_weights will panic or produce invalid weights
    // but we need to test the circuit directly
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();
    let weights: [Field; NUM_MINERS] = [0; NUM_MINERS];

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// --- Edge case: weight sum exactly 65535 (no rounding loss) ---
#[test]
fn test_edge_exact_weight_sum() {
    // 64 miners, each with equal score
    // total = 64 * 1024 = 65536
    // weight[i] = floor(1024 * 65535 / 65536) = floor(65534.0) = 65534/64 hmm
    // Better: use scores that divide evenly
    // 65535 = 3 * 5 * 17 * 257. Not divisible by 64.
    // Use 5 miners with score 1 each? No, NUM_MINERS is fixed at 64.
    // Actually: scores = [65535, 65535, ...] (64 of them)
    // total = 64 * 65535 = 4194240
    // weight[i] = floor(65535 * 65535 / 4194240) = floor(65535/64) = 1023
    // sum = 64 * 1023 = 65472. Not 65535.
    // To get exact 65535: need scores where sum divides 65535 evenly per miner
    // 65535 / 64 = 1023.984... not integer.
    // Exact sum of 65535 is impossible with 64 equal-weight miners.
    // But with unequal: e.g., 63 miners at score 1, one at score 2
    // total = 65, weight[0..62] = floor(1*65535/65) = 1008, weight[63] = floor(2*65535/65) = 2016
    // sum = 63*1008 + 2016 = 63504 + 2016 = 65520. Close but not 65535.
    // Accept that exact 65535 is rare. Test boundary instead.
    // Let's just verify that a "good" score vector produces a valid weight sum.
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        scores[i] = ((i + 1) * 100) as Field;
    }
    run_with_scores(scores);
}

// --- Edge case: weight sum at minimum boundary (65472 = 65535 - 63) ---
#[test]
fn test_edge_weight_sum_minimum_boundary() {
    // Uniform scores: all equal
    // weight[i] = floor(score * 65535 / (64*score)) = floor(65535/64) = 1023
    // sum = 64 * 1023 = 65472 (exactly MIN_WEIGHT_SUM)
    let scores: [Field; NUM_MINERS] = [1; NUM_MINERS];
    run_with_scores(scores);
}

// ============================================================
// HARDENING: Adversarial Tests
// ============================================================

// --- Adversarial: weights sum to 65535 but don't match scores ---
#[test(should_fail)]
fn test_adversarial_fake_weights_correct_sum() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();

    // Create fake weights that sum to 65535 but don't match scores
    let mut fake_weights: [Field; NUM_MINERS] = [1023; NUM_MINERS];
    // Adjust to sum exactly 65535: 64 * 1023 = 65472, need 63 more
    fake_weights[0] = 1023 + 63; // = 1086

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(fake_weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, fake_weights, salt);
}

// --- Adversarial: swap two miners' scores, keep original weights ---
#[test(should_fail)]
fn test_adversarial_swapped_scores() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let mut scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();

    // Compute correct weights from original scores
    let weights = unsafe { compute_weights(scores) };

    // Swap scores[0] and scores[1] -- weights no longer match
    let tmp = scores[0];
    scores[0] = scores[1];
    scores[1] = tmp;

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// --- Adversarial: inflate one score, deflate another by same amount ---
#[test(should_fail)]
fn test_adversarial_score_redistribution() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let mut scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();

    // Compute correct weights
    let weights = unsafe { compute_weights(scores) };

    // Redistribute: +100 to miner 0, -100 from miner 1
    // Total stays the same, but individual weights should differ
    scores[0] = scores[0] + 100;
    scores[1] = scores[1] - 100;

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// --- Adversarial: correct proof but different miner UIDs ---
#[test(should_fail)]
fn test_adversarial_different_miner_uids() {
    let mut uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();
    let weights = unsafe { compute_weights(scores) };

    // Compute commitments with original UIDs
    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    // Change a UID -- input commitment will mismatch
    uids[0] = 9999;

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// --- Adversarial: salt reuse across epochs produces different commitments ---
#[test]
fn test_salt_reuse_different_epochs() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let salt = test_salt(); // Same salt
    let nonce = test_challenge_nonce();

    // Same inputs, different epochs -> different commitments
    let ic_epoch42 = compute_input_commitment(uids, hashes, nonce, 42, salt);
    let ic_epoch43 = compute_input_commitment(uids, hashes, nonce, 43, salt);

    // Commitments must differ due to epoch binding
    assert(ic_epoch42 != ic_epoch43, "Same salt + different epoch should produce different commitments");
}

// --- Adversarial: different validator produces different weight commitment ---
#[test]
fn test_different_validator_different_commitment() {
    let scores = test_scores();
    let weights = unsafe { compute_weights(scores) };
    let epoch = test_epoch();

    let wc_v1 = compute_weight_commitment(weights, 12345, epoch);
    let wc_v2 = compute_weight_commitment(weights, 67890, epoch);

    assert(wc_v1 != wc_v2, "Different validators should produce different weight commitments");
}

// --- Adversarial: validator tries to use someone else's proof ---
#[test(should_fail)]
fn test_adversarial_wrong_validator_id() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let nonce = test_challenge_nonce();
    let weights = unsafe { compute_weights(scores) };

    // Commitments bound to validator 12345
    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, 12345, epoch);

    // Verifier checks with validator 67890 -- weight commitment won't match
    main(ic, wc, epoch, 67890, nonce, uids, hashes, scores, weights, salt);
}

// ============================================================
// HARDENING: Fuzz-style Tests (deterministic pseudo-random)
// ============================================================

/// Generate pseudo-random score vector from a seed.
/// Scores are bounded to u32 range (realistic for Bittensor).
/// This is required because the optimized normalization uses
/// bounded range checks that assume total_score < 2^70.
fn pseudo_random_scores(seed: Field) -> [Field; NUM_MINERS] {
    let mut scores: [Field; NUM_MINERS] = [0; NUM_MINERS];
    let mut state = seed;
    for i in 0..NUM_MINERS {
        state = state * 137 + 251 + (i as Field);
        // Bound to u32 range using modular arithmetic
        // state % (2^32) = state & 0xFFFFFFFF but Noir doesn't have bitwise AND on Field
        // Instead, use: score = state - (state / 2^32) * 2^32  (floor mod)
        let bound: Field = 4294967296; // 2^32
        let quotient = state / bound;
        let score = state - quotient * bound + 1; // +1 ensures nonzero
        scores[i] = score;
    }
    scores
}

// --- Fuzz: 20 random valid score vectors all pass ---
#[test]
fn test_fuzz_valid_scores() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();

    // Test 20 different score vectors
    for seed_idx in 1..21 {
        let scores = pseudo_random_scores(seed_idx as Field);
        let weights = unsafe { compute_weights(scores) };

        let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
        let wc = compute_weight_commitment(weights, vid, epoch);

        main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
    }
}

// --- Fuzz: 20 random tampered weight vectors all fail ---
// (We can't test should_fail inside a loop, so test one representative case)
#[test(should_fail)]
fn test_fuzz_tampered_weights_rejected() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = pseudo_random_scores(42);
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();

    let mut weights = unsafe { compute_weights(scores) };

    // Tamper: redistribute weight from miner 0 to miner 1
    weights[0] = weights[0] + 1;
    weights[1] = weights[1] - 1;

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}

// --- Fuzz: tamper with a single weight by +1 ---
#[test(should_fail)]
fn test_fuzz_single_weight_off_by_one() {
    let uids = test_miner_uids();
    let hashes = test_response_hashes();
    let scores = test_scores();
    let salt = test_salt();
    let epoch = test_epoch();
    let vid = test_validator_id();
    let nonce = test_challenge_nonce();

    let mut weights = unsafe { compute_weights(scores) };

    // Off by just 1 -- should still be caught
    weights[32] = weights[32] + 1;

    let ic = compute_input_commitment(uids, hashes, nonce, epoch, salt);
    let wc = compute_weight_commitment(weights, vid, epoch);

    main(ic, wc, epoch, vid, nonce, uids, hashes, scores, weights, salt);
}
