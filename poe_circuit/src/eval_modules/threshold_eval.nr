use crate::eval_modules::field_math::bounded_lt;
use crate::eval_modules::interface::{EvalFunction, MAX_PARAMS};

// ============================================================
// Threshold Evaluation (binary pass/fail scoring)
// Score = params[1] if response_hash > params[0], else 0
// params[0] = threshold, params[1] = pass_score
// ~10 gates per miner (one comparison)
// ============================================================

pub struct ThresholdEval;

impl EvalFunction for ThresholdEval {
    fn evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field {
        let threshold = params[0];
        let pass_score = params[1];
        // If response > threshold, score = pass_score, else 0
        if bounded_lt::<48>(threshold, response_hash) {
            pass_score
        } else {
            0
        }
    }
}

#[test]
fn test_threshold_above() {
    // threshold=50, pass_score=100
    let params = [50, 100, 0, 0];
    let score = ThresholdEval::evaluate(75, params);
    assert(score == 100, "Threshold: above should pass");
}

#[test]
fn test_threshold_below() {
    let params = [50, 100, 0, 0];
    let score = ThresholdEval::evaluate(25, params);
    assert(score == 0, "Threshold: below should fail");
}

#[test]
fn test_threshold_equal() {
    // Equal to threshold should fail (not strictly greater)
    let params = [50, 100, 0, 0];
    let score = ThresholdEval::evaluate(50, params);
    assert(score == 0, "Threshold: equal should fail");
}
