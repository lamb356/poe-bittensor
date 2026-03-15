use crate::eval_modules::interface::{EvalFunction, MAX_PARAMS};

// ============================================================
// Arithmetic Evaluation (SN8-style portfolio return scoring)
// Score = params[0] * response_hash + params[1]
// ~20 gates per miner
// ============================================================

pub struct ArithmeticEval;

impl EvalFunction for ArithmeticEval {
    fn evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field {
        // Linear weighted scoring: weight * response + bias
        let weight = params[0];
        let bias = params[1];
        weight * response_hash + bias
    }
}

#[test]
fn test_arithmetic_eval_basic() {
    // weight=2, bias=10
    let params = [2, 10, 0, 0];
    let score = ArithmeticEval::evaluate(100, params);
    // 2 * 100 + 10 = 210
    assert(score == 210, "Arithmetic eval: expected 210");
}

#[test]
fn test_arithmetic_eval_zero_bias() {
    let params = [3, 0, 0, 0];
    let score = ArithmeticEval::evaluate(50, params);
    assert(score == 150, "Arithmetic eval: expected 150");
}

#[test]
fn test_arithmetic_eval_identity() {
    // weight=1, bias=0 should return response_hash unchanged
    let params = [1, 0, 0, 0];
    let score = ArithmeticEval::evaluate(42, params);
    assert(score == 42, "Arithmetic eval: identity failed");
}
