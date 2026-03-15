use crate::eval_modules::field_math::{
    bounded_lt, fixed_div, fixed_mul, signed_add, signed_lt, signed_neg, signed_pos, signed_sub,
    signed_zero, SignedField, sn8_compute_time_weight, verify_time_weight,
};
use crate::eval_modules::interface::{EvalFunction, MAX_PARAMS};

// ============================================================
// SN8 (Taoshi PTN) PnL Evaluation Module
//
// Proves: given committed PnL checkpoints and time weights,
// the validator's time-weighted PnL score is correctly computed.
//
// Formula: PnL_score = SUM(w_d * PnL_d) / SUM(w_d)
//          w_t = 0.045 + 0.955 * exp(-0.075 * (T - t))
//          If max_drawdown >= 10%, score = 0
//
// - Time weights verified in-circuit via piecewise polynomial (<0.4% error)
// - Time weights pre-computed in witness generator (committed via Poseidon2)
// - Only PnL metric (Sharpe/Sortino/Omega/Calmar all weight=0 in production)
// - Percentile ranking and cross-asset softmax deferred to v2
// - NUM_CHECKPOINTS=30 (daily aggregates from 12hr checkpoints)
// ============================================================

pub global NUM_CHECKPOINTS: u32 = 30;
// 10% drawdown threshold in fixed-point (0.10 * SCALE)
pub global DRAWDOWN_THRESHOLD: Field = 100000;

pub struct SN8PnlEval;

/// Simplified EvalFunction trait implementation.
/// For per-miner composability with the generic full_poe_verify framework.
/// params[0] = daily_pnl (fixed-point), params[1] = time_weight (fixed-point)
impl EvalFunction for SN8PnlEval {
    fn evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field {
        // Single-checkpoint weighted PnL contribution
        // Ignores response_hash (PnL comes from checkpoint data, not response content)
        let _rh = response_hash; // suppress unused warning
        let pnl = params[0];
        let weight = params[1];
        fixed_mul(pnl, weight)
    }
}

/// Compute time-weighted PnL score for a single miner.
/// daily_pnls: PnL per day as SignedField (positive = profit, negative = loss)
/// time_weights: pre-computed decay weights in fixed-point
/// Returns: score in fixed-point, or 0 if max drawdown >= 10%
pub fn sn8_pnl_score(
    daily_pnls: [SignedField; NUM_CHECKPOINTS],
    time_weights: [Field; NUM_CHECKPOINTS],
) -> Field {
    // Accumulate positive and negative weighted sums separately.
    // This avoids calling bounded_lt on non-integer Field values
    // that arise from fixed_mul with Taylor-approximated weights.
    let mut pos_sum: Field = 0;
    let mut neg_sum: Field = 0;
    let mut weight_sum: Field = 0;
    for i in 0..NUM_CHECKPOINTS {
        let weighted_mag = fixed_mul(daily_pnls[i].magnitude, time_weights[i]);
        if daily_pnls[i].is_negative {
            neg_sum += weighted_mag;
        } else {
            pos_sum += weighted_mag;
        }
        weight_sum += time_weights[i];
    }
    assert(weight_sum != 0, "Time weight sum must be nonzero");

    // Net PnL direction: compare pos_sum vs neg_sum using Field.lt()
    // (safe here because both are sums of non-negative Field products)
    if pos_sum.lt(neg_sum) | (pos_sum == neg_sum) {
        // Negative or zero overall PnL: score = 0
        0
    } else {
        let net = pos_sum - neg_sum;
        let score = fixed_div(net, weight_sum);

        // Check max drawdown
        let mdd = compute_max_drawdown(daily_pnls);
        if bounded_lt::<48>(DRAWDOWN_THRESHOLD, mdd.magnitude) & !mdd.is_negative {
            0
        } else {
            score
        }
    }
}

/// Compute maximum drawdown from daily PnL series.
/// Drawdown = (peak - current) as a fraction of initial capital (FIXED_SCALE = 100%).
/// Returns max drawdown as SignedField.
pub fn compute_max_drawdown(pnls: [SignedField; NUM_CHECKPOINTS]) -> SignedField {
    let mut cumulative = signed_zero();
    let mut peak = signed_zero();
    let mut max_dd = signed_zero();

    for i in 0..NUM_CHECKPOINTS {
        cumulative = signed_add(cumulative, pnls[i]);

        // Update peak if cumulative > peak
        if signed_lt(peak, cumulative) {
            peak = cumulative;
        }

        // Drawdown = peak - cumulative
        if signed_lt(cumulative, peak) {
            let dd = signed_sub(peak, cumulative);
            if signed_lt(max_dd, dd) {
                max_dd = dd;
            }
        }
    }

    max_dd
}

pub fn verify_time_weights(time_weights: [Field; NUM_CHECKPOINTS], tolerance: Field) {
    for i in 0..NUM_CHECKPOINTS {
        verify_time_weight(time_weights[i], i as Field, tolerance);
    }
}

// ============================================================
// Tests
// ============================================================

/// Helper: generate time weights from the decay formula
fn test_time_weights() -> [Field; NUM_CHECKPOINTS] {
    let mut weights: [Field; NUM_CHECKPOINTS] = [0; NUM_CHECKPOINTS];
    for i in 0..NUM_CHECKPOINTS {
        weights[i] = sn8_compute_time_weight(i as Field);
    }
    weights
}

#[test]
fn test_sn8_constant_pnl() {
    // All days have same PnL: score should equal that PnL
    let pnls: [SignedField; NUM_CHECKPOINTS] = [signed_pos(50000); NUM_CHECKPOINTS]; // 0.05 daily
    let weights = test_time_weights();
    let score = sn8_pnl_score(pnls, weights);
    // Score should be ~50000 (weighted average of identical values = that value)
    // Allow small rounding: [49000, 51000]
    assert(!score.lt(49000), "Constant PnL score too low");
    assert(score.lt(51001), "Constant PnL score too high");
}

#[test]
fn test_sn8_all_positive_no_drawdown() {
    // All positive PnL, no drawdown -> score > 0
    let mut pnls: [SignedField; NUM_CHECKPOINTS] = [signed_zero(); NUM_CHECKPOINTS];
    for i in 0..NUM_CHECKPOINTS {
        pnls[i] = signed_pos((10000 + i * 1000) as Field); // increasing daily PnL
    }
    let weights = test_time_weights();
    let score = sn8_pnl_score(pnls, weights);
    // Score should be positive (weighted average of positive values)
    assert(!score.lt(1), "All-positive PnL should give positive score");
}

#[test]
fn test_sn8_drawdown_kills_score() {
    // Start high, crash with negative PnL: drawdown > 10%
    let mut pnls: [SignedField; NUM_CHECKPOINTS] = [signed_zero(); NUM_CHECKPOINTS];
    // First 10 days: +50000 each (cumulative: 500000 = 50% gain)
    for i in 0..10 {
        pnls[i] = signed_pos(50000);
    }
    // Next 20 days: -30000 each (cumulative drop: 600000 from peak)
    // Drawdown = 600000 > DRAWDOWN_THRESHOLD (100000) => score = 0
    for i in 10..NUM_CHECKPOINTS {
        pnls[i] = signed_neg(30000);
    }
    let weights = test_time_weights();
    let score = sn8_pnl_score(pnls, weights);
    assert(score == 0, "Large drawdown should kill score");
}

#[test]
fn test_sn8_max_drawdown_zero_for_increasing() {
    // Monotonically increasing cumulative: drawdown = 0
    let mut pnls: [SignedField; NUM_CHECKPOINTS] = [signed_zero(); NUM_CHECKPOINTS];
    for i in 0..NUM_CHECKPOINTS {
        pnls[i] = signed_pos(10000); // constant positive
    }
    let mdd = compute_max_drawdown(pnls);
    assert(mdd.magnitude == 0, "No drawdown for increasing cumulative");
}

#[test]
fn test_sn8_max_drawdown_detected() {
    // Go up then down with negative PnL: real drawdown
    let mut pnls: [SignedField; NUM_CHECKPOINTS] = [signed_zero(); NUM_CHECKPOINTS];
    // First 15 days: +20000 each (cumulative: 300000)
    for i in 0..15 {
        pnls[i] = signed_pos(20000);
    }
    // Next 15 days: -10000 each (cumulative drops by 150000 from peak)
    for i in 15..NUM_CHECKPOINTS {
        pnls[i] = signed_neg(10000);
    }
    let mdd = compute_max_drawdown(pnls);
    // Drawdown should be 150000 (peak 300000, final 150000)
    assert(mdd.magnitude == 150000, "Drawdown should be 150000");
    assert(!mdd.is_negative, "Drawdown should be positive");
}

#[test]
fn test_sn8_time_weight_verification() {
    let weights = test_time_weights();
    // Tolerance: 20000 = 2% of SCALE
    verify_time_weights(weights, 20000);
}

#[test]
fn test_sn8_recent_weighted_higher() {
    // Recent days have higher weight -> if recent PnL is higher,
    // score should be above simple average
    let mut pnls: [SignedField; NUM_CHECKPOINTS] = [signed_zero(); NUM_CHECKPOINTS];
    // Old days (0-14): low PnL
    for i in 0..15 {
        pnls[i] = signed_pos(10000); // 0.01
    }
    // Recent days (15-29): high PnL
    for i in 15..NUM_CHECKPOINTS {
        pnls[i] = signed_pos(100000); // 0.10
    }
    let weights = test_time_weights();
    let score = sn8_pnl_score(pnls, weights);

    // Simple average would be (15*10000 + 15*100000)/30 = 55000
    // Time-weighted should be > 55000 since recent (high PnL) days weighted more
    assert(!score.lt(55001), "Time-weighted score should favor recent high PnL");
}

#[test]
fn test_sn8_negative_pnl_kills_score() {
    // All negative PnL: score should be 0
    let mut pnls: [SignedField; NUM_CHECKPOINTS] = [signed_zero(); NUM_CHECKPOINTS];
    for i in 0..NUM_CHECKPOINTS {
        pnls[i] = signed_neg(10000); // -0.01 daily
    }
    let weights = test_time_weights();
    let score = sn8_pnl_score(pnls, weights);
    assert(score == 0, "All-negative PnL should give zero score");
}

#[test]
fn test_sn8_drawdown_with_losses() {
    // Go up then crash: positive then negative PnL
    let mut pnls: [SignedField; NUM_CHECKPOINTS] = [signed_zero(); NUM_CHECKPOINTS];
    for i in 0..10 {
        pnls[i] = signed_pos(50000); // +5% daily for 10 days
    }
    for i in 10..NUM_CHECKPOINTS {
        pnls[i] = signed_neg(30000); // -3% daily for 20 days
    }
    let weights = test_time_weights();
    let score = sn8_pnl_score(pnls, weights);
    // Drawdown = peak(500000) - final(500000-600000=-100000) = 600000 > 100000 threshold
    assert(score == 0, "Large drawdown from losses should kill score");
}

#[test]
fn test_sn8_trait_impl() {
    // Test the EvalFunction trait implementation
    let params: [Field; MAX_PARAMS] = [50000, 800000, 0, 0]; // pnl=0.05, weight=0.8
    let score = SN8PnlEval::evaluate(0, params);
    // 0.05 * 0.8 = 0.04 = 40000
    assert(score == 40000, "Trait impl: 0.05 * 0.8 should be 0.04");
}

#[test(should_fail)]
fn test_fabricated_weights_rejected() {
    // Validator tries to commit uniform weights (not following decay curve)
    let fabricated: [Field; NUM_CHECKPOINTS] = [500000; NUM_CHECKPOINTS];
    // This should fail because uniform weights don't match the decay formula
    verify_time_weights(fabricated, 20000);
}

#[test]
fn test_exact_weights_accepted() {
    // Weights computed by sn8_compute_time_weight should always pass
    let weights = test_time_weights();
    verify_time_weights(weights, 20000); // 2% tolerance
}
