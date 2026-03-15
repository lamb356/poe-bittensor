use crate::types::{NUM_MINERS, MAX_WEIGHT, MIN_WEIGHT_SUM};

// ============================================================
// Optimized score-to-weight proportionality + weight sum verification
//
// Checks: weight[i] == floor(score[i] * 65535 / total_score)
// Via integer division identity:
//   weight[i] * total + remainder == score[i] * 65535
//   where 0 <= remainder < total
//
// OPTIMIZATION: Replaces Field.lt() (expensive ~140 gates each) with
// bounded range checks via assert_max_bit_size (cheap ~5 gates each
// with UltraHonk lookup tables). Also merges weight sum verification
// into the same loop to eliminate a second pass.
//
// Gate cost reduction:
//   - 64 Field.lt() calls -> 64 pairs of 70-bit range checks
//   - 2 Field.lt() calls for weight sum -> 2 small range checks
//   - Eliminates separate verify_weight_sum function
//
// NOTE on Bittensor weight format:
// - Commit-Reveal v4 uses SUM-NORMALIZATION (weights sum to ~65535)
// - PoE requires CR4, so we use sum-normalization.
// ============================================================

// Maximum bit width for total_score.
// Scores are bounded in practice. 48 bits allows total_score up to 2^48
// (= 281 trillion), sufficient for any realistic scoring function.
// This is checked once and enables cheaper range proofs on remainders.
global TOTAL_SCORE_BITS: u32 = 48;

pub fn verify_weight_proportionality_and_sum(
    scores: [Field; NUM_MINERS],
    weights: [Field; NUM_MINERS],
) {
    // Compute total score
    let mut total_score: Field = 0;
    for i in 0..NUM_MINERS {
        total_score += scores[i];
    }
    assert(total_score != 0, "Total score must be nonzero");

    // Constrain total_score to 70 bits.
    // This enables remainder range checks below.
    // If a malicious prover passes scores that sum to > 2^70,
    // this assertion fails.
    total_score.assert_max_bit_size::<TOTAL_SCORE_BITS>();

    // Verify proportionality and accumulate weight sum in one pass
    let mut weight_sum: Field = 0;
    for i in 0..NUM_MINERS {
        let expected_numerator = scores[i] * MAX_WEIGHT;
        let remainder = expected_numerator - weights[i] * total_score;

        // Prove 0 <= remainder < total_score:
        // 1. remainder fits in 70 bits (proves it's small, not a wrapped negative)
        remainder.assert_max_bit_size::<TOTAL_SCORE_BITS>();
        // 2. (total_score - remainder - 1) fits in 70 bits (proves remainder < total_score)
        (total_score - remainder - 1).assert_max_bit_size::<TOTAL_SCORE_BITS>();

        weight_sum += weights[i];
    }

    // Weight sum range check: must be in [MIN_WEIGHT_SUM, 65535]
    weight_sum.assert_max_bit_size::<16>();
    (weight_sum - MIN_WEIGHT_SUM).assert_max_bit_size::<7>();
}

// Keep the old API for backwards compatibility during transition
pub fn verify_weight_proportionality(
    scores: [Field; NUM_MINERS],
    weights: [Field; NUM_MINERS],
) {
    verify_weight_proportionality_and_sum(scores, weights);
}

pub fn verify_weight_sum(_weights: [Field; NUM_MINERS]) {
    // Now handled inside verify_weight_proportionality_and_sum.
    // This function is a no-op kept for API compatibility.
}

// ============================================================
// Helper: compute weights from scores (for tests)
// ============================================================
pub fn compute_weights(scores: [Field; NUM_MINERS]) -> [Field; NUM_MINERS] {
    let mut total: Field = 0;
    for i in 0..NUM_MINERS {
        total += scores[i];
    }
    let mut weights: [Field; NUM_MINERS] = [0; NUM_MINERS];
    for i in 0..NUM_MINERS {
        weights[i] = (scores[i] * 65535) / total;
    }
    weights
}
