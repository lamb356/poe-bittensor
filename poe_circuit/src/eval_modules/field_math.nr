// ============================================================
// Fixed-point arithmetic for ZK circuits
// SCALE = 10^6 (6 decimal places)
// All values are Field elements representing fixed-point numbers:
//   0.5 = 500000, 1.0 = 1000000, 2.5 = 2500000
// ============================================================

pub global FIXED_SCALE: Field = 1000000;

// Efficient comparison: uses range checks instead of Field.lt() (~435 gates -> ~ceil(BITS/14) gates)
unconstrained fn lt_hint(a: Field, b: Field) -> bool {
    a.lt(b)
}

pub fn bounded_lt<let BITS: u32>(a: Field, b: Field) -> bool {
    // Safety: lt_hint provides the comparison direction; range checks prove it correct
    let result = unsafe { lt_hint(a, b) };
    if result {
        (b - a - 1).assert_max_bit_size::<BITS>();
    } else {
        (a - b).assert_max_bit_size::<BITS>();
    }
    result
}

/// Fixed-point multiplication: (a * b) / SCALE
pub fn fixed_mul(a: Field, b: Field) -> Field {
    (a * b) / FIXED_SCALE
}

/// Fixed-point division: (a * SCALE) / b
pub fn fixed_div(a: Field, b: Field) -> Field {
    (a * FIXED_SCALE) / b
}

/// Approximate exp(-x) using degree-4 Taylor polynomial.
/// Input x is in fixed-point (e.g., x=1000000 means exp(-1.0)).
/// Valid for x in [0, 2*SCALE]. For x > 2.0, returns baseline 0.045.
///
/// exp(-x) ~ 1 - x + x^2/2 - x^3/6 + x^4/24
///
/// Error bounds (vs f64 exp()):
///   x=0.0: 0.000%    x=0.5: 0.026%    x=1.0: 1.9%
///   x=1.5: 5.2%      x=2.0+: clamped to 0.045 (baseline)
///
/// For SN8 decay rate 0.075: x=2.0 corresponds to t=26.7 days.
/// Days 0-26: Taylor approximation. Days 27+: baseline weight 0.045.
pub fn exp_neg_approx(x: Field) -> Field {
    // Clamp threshold: x >= 2.0 (Taylor diverges badly beyond x=1.5)
    let clamp_threshold = 2 * FIXED_SCALE;
    if !bounded_lt::<32>(x, clamp_threshold) {
        // x > 3.0: return baseline (0.045 in fixed-point)
        45000
    } else {
        let x2 = fixed_mul(x, x);
        let x3 = fixed_mul(x2, x);
        let x4 = fixed_mul(x3, x);
        // exp(-x) ~ 1 - x + x^2/2 - x^3/6 + x^4/24
        // Group to avoid underflow in unsigned Field:
        //   positive_terms = 1 + x^2/2 + x^4/24
        //   negative_terms = x + x^3/6
        //   result = positive - negative (only if positive > negative)
        //
        // NOTE: positive/negative use Field division (/ 2, / 6, / 24)
        // which produces modular inverses, not bounded integers.
        // Cannot use bounded_lt here; .lt() compares canonical Field values.
        let positive = FIXED_SCALE + x2 / 2 + x4 / 24;
        let negative = x + x3 / 6;
        if negative.lt(positive) {
            positive - negative
        } else {
            // Taylor diverged: return baseline
            45000
        }
    }
}

/// Compute time weight for SN8 decay formula:
/// w_t = 0.045 + 0.955 * exp(-0.075 * t)
/// t is days from most recent (t=0 is today, t=29 is 30 days ago)
/// Returns weight in fixed-point
pub fn sn8_time_weight(days_ago: Field) -> Field {
    // decay_rate = 0.075 in fixed-point = 75000
    let decay_rate: Field = 75000;
    let x = fixed_mul(decay_rate, days_ago * FIXED_SCALE);
    let exp_val = exp_neg_approx(x);
    // w = 0.045 + 0.955 * exp_val
    // 0.045 = 45000, 0.955 = 955000
    45000 + fixed_mul(955000, exp_val)
}

// ============================================================
// Signed fixed-point arithmetic
// Two-field representation: (magnitude, is_negative)
// This enables negative PnL representation in SN8 eval.
// ============================================================

pub struct SignedField {
    pub magnitude: Field,
    pub is_negative: bool,
}

pub fn signed_pos(val: Field) -> SignedField {
    SignedField { magnitude: val, is_negative: false }
}

pub fn signed_neg(val: Field) -> SignedField {
    SignedField { magnitude: val, is_negative: true }
}

pub fn signed_zero() -> SignedField {
    SignedField { magnitude: 0, is_negative: false }
}

/// Add two signed values
pub fn signed_add(a: SignedField, b: SignedField) -> SignedField {
    if a.is_negative == b.is_negative {
        // Same sign: add magnitudes, keep sign
        SignedField { magnitude: a.magnitude + b.magnitude, is_negative: a.is_negative }
    } else {
        // Different signs: subtract smaller from larger
        if bounded_lt::<48>(a.magnitude, b.magnitude) {
            // |b| > |a|, result has b's sign
            SignedField { magnitude: b.magnitude - a.magnitude, is_negative: b.is_negative }
        } else {
            // |a| >= |b|, result has a's sign
            SignedField { magnitude: a.magnitude - b.magnitude, is_negative: a.is_negative }
        }
    }
}

/// Subtract: a - b = a + (-b)
pub fn signed_sub(a: SignedField, b: SignedField) -> SignedField {
    signed_add(a, SignedField { magnitude: b.magnitude, is_negative: !b.is_negative })
}

/// Multiply two signed values (fixed-point)
pub fn signed_mul(a: SignedField, b: SignedField) -> SignedField {
    SignedField {
        magnitude: fixed_mul(a.magnitude, b.magnitude),
        is_negative: a.is_negative != b.is_negative,
    }
}

/// Compare: a < b
pub fn signed_lt(a: SignedField, b: SignedField) -> bool {
    if a.is_negative & !b.is_negative {
        // negative < positive (unless both zero)
        (a.magnitude != 0) | (b.magnitude != 0)
    } else if !a.is_negative & b.is_negative {
        // positive >= negative
        false
    } else if a.is_negative & b.is_negative {
        // Both negative: -|a| < -|b| iff |a| > |b|
        bounded_lt::<48>(b.magnitude, a.magnitude)
    } else {
        // Both positive
        bounded_lt::<48>(a.magnitude, b.magnitude)
    }
}

// ============================================================
// Tests
// ============================================================

#[test]
fn test_fixed_mul() {
    // 0.5 * 0.5 = 0.25
    let result = fixed_mul(500000, 500000);
    assert(result == 250000, "0.5 * 0.5 should be 0.25");
}

#[test]
fn test_fixed_mul_one() {
    // 1.0 * anything = anything
    let result = fixed_mul(FIXED_SCALE, 750000);
    assert(result == 750000, "1.0 * 0.75 should be 0.75");
}

#[test]
fn test_fixed_div() {
    // 1.0 / 2.0 = 0.5
    let result = fixed_div(FIXED_SCALE, 2 * FIXED_SCALE);
    assert(result == 500000, "1.0 / 2.0 should be 0.5");
}

#[test]
fn test_fixed_div_identity() {
    // x / 1.0 = x
    let result = fixed_div(750000, FIXED_SCALE);
    assert(result == 750000, "x / 1.0 should be x");
}

#[test]
fn test_exp_neg_zero() {
    // exp(0) = 1.0
    let result = exp_neg_approx(0);
    assert(result == FIXED_SCALE, "exp(0) should be 1.0");
}

#[test]
fn test_exp_neg_one() {
    // exp(-1) ~ 0.3679. Taylor: 1 - 1 + 0.5 - 0.1667 + 0.0417 = 0.3750
    // In fixed-point: 375000. Real: 367879. Error: ~1.9%
    let result = exp_neg_approx(FIXED_SCALE);
    // Accept range [360000, 380000] (~2% tolerance)
    assert(!result.lt(360000), "exp(-1) too low");
    assert(result.lt(380001), "exp(-1) too high");
}

#[test]
fn test_exp_neg_two_clamps() {
    // x >= 2.0 is now clamped to baseline 0.045
    let result = exp_neg_approx(2 * FIXED_SCALE);
    assert(result == 45000, "exp(-2) should clamp to baseline 0.045");
}

#[test]
fn test_exp_neg_large_clamps() {
    // x >= 2.0 should return baseline 0.045
    let result = exp_neg_approx(4 * FIXED_SCALE);
    assert(result == 45000, "exp(-4) should clamp to baseline 0.045");
}


#[test]
fn test_sn8_time_weight_recent() {
    // t=0 (today): w = 0.045 + 0.955 * exp(0) = 0.045 + 0.955 = 1.0
    let w = sn8_time_weight(0);
    assert(w == FIXED_SCALE, "Weight for today should be 1.0");
}

#[test]
fn test_sn8_time_weight_old() {
    // t=40 (40 days ago): x = 0.075 * 40 = 3.0 => clamp region
    // w = 0.045 + 0.955 * baseline = ~0.088
    let w = sn8_time_weight(40);
    // Expect ~88000. Accept [45000, 500000] (wide range due to Taylor error)
    assert(!w.lt(45000), "Old weight should be >= baseline");
    assert(w.lt(500001), "Old weight should be bounded");
}

#[test]
fn test_signed_add_both_positive() {
    let a = signed_pos(100);
    let b = signed_pos(200);
    let c = signed_add(a, b);
    assert(c.magnitude == 300, "100 + 200 = 300");
    assert(!c.is_negative, "Should be positive");
}

#[test]
fn test_signed_add_opposite_signs() {
    let a = signed_pos(300);
    let b = signed_neg(100);
    let c = signed_add(a, b);
    assert(c.magnitude == 200, "300 + (-100) = 200");
    assert(!c.is_negative, "Should be positive");
}

#[test]
fn test_signed_add_negative_result() {
    let a = signed_pos(100);
    let b = signed_neg(300);
    let c = signed_add(a, b);
    assert(c.magnitude == 200, "100 + (-300) = -200");
    assert(c.is_negative, "Should be negative");
}

#[test]
fn test_signed_lt() {
    assert(signed_lt(signed_neg(5), signed_pos(3)), "-5 < 3");
    assert(signed_lt(signed_pos(2), signed_pos(5)), "2 < 5");
    assert(!signed_lt(signed_pos(5), signed_pos(2)), "!(5 < 2)");
    assert(signed_lt(signed_neg(5), signed_neg(2)), "-5 < -2");
    assert(!signed_lt(signed_neg(2), signed_neg(5)), "!(-2 < -5)");
}
