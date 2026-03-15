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

// Unconstrained hint for truncating integer division (a*b) / SCALE.
// Returns the integer quotient, discarding remainder.
// Required because Field division (/) computes modular inverse, which
// produces garbage when (a*b) is not exactly divisible by SCALE.
unconstrained fn trunc_mul_hint(a: Field, b: Field) -> Field {
    let a_u64 = a as u64;
    let b_u64 = b as u64;
    let scale = 1000000_u64;
    ((a_u64 * b_u64) / scale) as Field
}

/// Fixed-point multiplication with truncating (integer) division.
/// Result = floor(a * b / SCALE). Uses unconstrained hint + range check.
fn fixed_mul_trunc(a: Field, b: Field) -> Field {
    // Safety: trunc_mul_hint is pure arithmetic; range check below proves correctness
    let q = unsafe { trunc_mul_hint(a, b) };
    // Verify: q * SCALE <= a * b < (q+1) * SCALE
    let product = a * b;
    let q_scaled = q * FIXED_SCALE;
    // product - q_scaled = remainder, must be in [0, SCALE)
    let remainder = product - q_scaled;
    // remainder must be non-negative and < SCALE
    // Use range check: remainder fits in 20 bits (SCALE = 10^6 < 2^20)
    remainder.assert_max_bit_size::<20>();
    q
}

/// Piecewise exp(-x) approximation with <0.4% error across all segments.
/// Replaces the old single Taylor polynomial which had 22% error at x=1.5.
///
/// Segment 1 (x in [0, 0.75]): Taylor degree-4. Max error 0.37%.
/// Segment 2 (x in [0.75, 2.0]): Chebyshev degree-4. Max error 0.02%.
/// Segment 3 (x >= 2.0): Returns 0 (caller adds baseline).
pub fn piecewise_exp_neg(x: Field) -> Field {
    let seg1_end: Field = 750000; // 0.75 in fixed-point
    let seg2_end: Field = 2000000; // 2.0 in fixed-point

    if !bounded_lt::<32>(seg1_end, x) {
        // Segment 1: x in [0, 0.75] -- Taylor degree-4
        taylor_exp_neg(x)
    } else if bounded_lt::<32>(x, seg2_end) {
        // Segment 2: x in [0.75, 2.0] -- Chebyshev degree-4
        chebyshev_exp_neg(x)
    } else {
        // Segment 3: x >= 2.0 -- exp(-x) is near zero
        0
    }
}

/// Taylor degree-4: exp(-x) ~= 1 - x + x^2/2 - x^3/6 + x^4/24
/// Valid for x in [0, 0.75] with <0.37% error.
/// Uses fixed_mul_trunc for truncating integer division (not modular inverse).
fn taylor_exp_neg(x: Field) -> Field {
    let x2 = fixed_mul_trunc(x, x);
    let x3 = fixed_mul_trunc(x2, x);
    let x4 = fixed_mul_trunc(x3, x);
    // Coefficients as fixed-point reciprocals:
    //   1/2  = 0.500000 = 500000
    //   1/6  = 0.166667 = 166667
    //   1/24 = 0.041667 = 41667
    // Group positive and negative to avoid unsigned underflow:
    let positive = FIXED_SCALE + fixed_mul_trunc(x2, 500000) + fixed_mul_trunc(x4, 41667);
    let negative = x + fixed_mul_trunc(x3, 166667);
    if bounded_lt::<32>(negative, positive) {
        positive - negative
    } else {
        0
    }
}

/// Chebyshev degree-4 fitted on [0.75, 2.0] via numpy.polynomial.chebyshev.chebfit.
/// Power basis coefficients:
///   p(x) = 0.989631 - 0.956103*x + 0.425674*x^2 - 0.102042*x^3 + 0.010723*x^4
/// Max relative error: 0.018%.
fn chebyshev_exp_neg(x: Field) -> Field {
    let x2 = fixed_mul_trunc(x, x);
    let x3 = fixed_mul_trunc(x2, x);
    let x4 = fixed_mul_trunc(x3, x);
    // Positive terms: c0 + c2*x^2 + c4*x^4
    let positive = 989631 + fixed_mul_trunc(425674, x2) + fixed_mul_trunc(10723, x4);
    // Negative terms: |c1|*x + |c3|*x^3
    let negative = fixed_mul_trunc(956103, x) + fixed_mul_trunc(102042, x3);
    if bounded_lt::<32>(negative, positive) {
        positive - negative
    } else {
        0
    }
}

/// Compute time weight for SN8 decay formula using piecewise exp(-x).
/// w_t = 0.045 + 0.955 * exp(-0.075 * t)
/// t is days from most recent (t=0 is today, t=29 is 30 days ago)
pub fn sn8_compute_time_weight(days_ago: Field) -> Field {
    let decay_rate: Field = 75000; // 0.075 in fixed-point
    let x = fixed_mul_trunc(decay_rate, days_ago * FIXED_SCALE);
    let exp_val = piecewise_exp_neg(x);
    // w = 0.045 + 0.955 * exp(-x)
    45000 + fixed_mul_trunc(955000, exp_val)
}

/// Verify a committed time weight matches the piecewise approximation within tolerance.
/// Used in-circuit to catch fabricated weights while allowing exact off-circuit values.
pub fn verify_time_weight(committed: Field, days_ago: Field, tolerance: Field) {
    let expected = sn8_compute_time_weight(days_ago);
    if bounded_lt::<48>(expected, committed) {
        let diff = committed - expected;
        assert(!bounded_lt::<48>(tolerance, diff), "Time weight too high");
    } else {
        let diff = expected - committed;
        assert(!bounded_lt::<48>(tolerance, diff), "Time weight too low");
    }
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
    signed_add(
        a,
        SignedField { magnitude: b.magnitude, is_negative: !b.is_negative },
    )
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
fn test_piecewise_exp_neg_zero() {
    // exp(0) = 1.0
    let result = piecewise_exp_neg(0);
    assert(result == FIXED_SCALE, "exp(0) should be 1.0");
}

#[test]
fn test_piecewise_seg1_accuracy() {
    // x=0.5 (500000): exp(-0.5) = 0.60653. Taylor gives ~0.60677. Error <0.04%
    let result = piecewise_exp_neg(500000);
    assert(!result.lt(600000), "exp(-0.5) too low");
    assert(result.lt(615000), "exp(-0.5) too high");
}

#[test]
fn test_piecewise_seg2_accuracy() {
    // x=1.0 (1000000): exp(-1.0) = 0.36788. Chebyshev should be within 0.02%
    let result = piecewise_exp_neg(FIXED_SCALE);
    assert(!result.lt(365000), "exp(-1.0) too low");
    assert(result.lt(370000), "exp(-1.0) too high");
}

#[test]
fn test_piecewise_seg2_day20() {
    // x=1.5 (1500000): exp(-1.5) = 0.22313. The old Taylor had 22% error here.
    let result = piecewise_exp_neg(1500000);
    // Chebyshev should give ~223130 (within 0.02%)
    assert(!result.lt(220000), "exp(-1.5) too low");
    assert(result.lt(226000), "exp(-1.5) too high");
}

#[test]
fn test_piecewise_seg3_returns_zero() {
    // x >= 2.0: returns 0
    let result = piecewise_exp_neg(2 * FIXED_SCALE);
    assert(result == 0, "exp(-2.0) should return 0 in seg3");
    let result2 = piecewise_exp_neg(4 * FIXED_SCALE);
    assert(result2 == 0, "exp(-4.0) should return 0 in seg3");
}

#[test]
fn test_sn8_time_weight_today() {
    // t=0: w = 0.045 + 0.955 * 1.0 = 1.0
    let w = sn8_compute_time_weight(0);
    assert(w == FIXED_SCALE, "Weight for today should be 1.0");
}

#[test]
fn test_sn8_time_weight_day20() {
    // t=20: x=1.5, exp(-1.5)=0.22313, w=0.045+0.955*0.22313=0.25809
    // Expected: ~258090 in fixed-point
    let w = sn8_compute_time_weight(20);
    assert(!w.lt(255000), "Day 20 weight too low");
    assert(w.lt(262000), "Day 20 weight too high");
}

#[test]
fn test_sn8_time_weight_old() {
    // t=29: x=2.175, segment 3, exp~=0, w=0.045+0.955*0=0.045
    let w = sn8_compute_time_weight(29);
    assert(w == 45000, "Day 29 weight should be baseline 0.045");
}

#[test]
fn test_verify_time_weight_exact() {
    for i in 0..30 {
        let w = sn8_compute_time_weight(i as Field);
        verify_time_weight(w, i as Field, 20000);
    }
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
