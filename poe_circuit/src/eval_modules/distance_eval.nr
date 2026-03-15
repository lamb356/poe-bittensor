use crate::eval_modules::interface::{EvalFunction, MAX_PARAMS};
use crate::eval_modules::field_math::bounded_lt;

// ============================================================
// Distance Evaluation (OCR-style inverted distance scoring)
// distance = |response_hash - expected|
// score = max_score - distance (clamped to 0)
// params[0] = expected value
// params[1] = max_score
// ~50 gates per miner (comparisons + subtraction)
// ============================================================

pub struct DistanceEval;

impl EvalFunction for DistanceEval {
    fn evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field {
        let expected = params[0];
        let max_score = params[1];

        // Absolute difference: |response_hash - expected|
        let distance = if bounded_lt::<48>(expected, response_hash) {
            response_hash - expected
        } else {
            expected - response_hash
        };

        // Inverted distance, clamped to 0
        if bounded_lt::<48>(distance, max_score) {
            max_score - distance
        } else {
            0
        }
    }
}

#[test]
fn test_distance_exact_match() {
    // expected=100, max_score=1000
    let params = [100, 1000, 0, 0];
    let score = DistanceEval::evaluate(100, params);
    assert(score == 1000, "Distance: exact match should get max score");
}

#[test]
fn test_distance_close() {
    let params = [100, 1000, 0, 0];
    let score = DistanceEval::evaluate(110, params);
    // distance = 10, score = 1000 - 10 = 990
    assert(score == 990, "Distance: close should score high");
}

#[test]
fn test_distance_far() {
    let params = [100, 1000, 0, 0];
    let score = DistanceEval::evaluate(50, params);
    // distance = 50, score = 1000 - 50 = 950
    assert(score == 950, "Distance: far should score lower");
}

#[test]
fn test_distance_beyond_max() {
    let params = [100, 50, 0, 0];
    let score = DistanceEval::evaluate(200, params);
    // distance = 100, max_score = 50, 100 > 50 => clamped to 0
    assert(score == 0, "Distance: beyond max should be 0");
}
