// ============================================================
// Pluggable Evaluation Interface
// Subnet developers implement this trait for Full PoE
// ============================================================

pub global MAX_PARAMS: u32 = 4;

/// Trait that subnet-specific evaluation functions implement.
/// Each subnet compiles a Full PoE circuit with their implementation.
pub trait EvalFunction {
    /// Evaluate a single miner's response and return a raw score.
    /// response_hash: BLAKE3 hash of the miner's response (as Field)
    /// params: subnet-specific configuration parameters
    fn evaluate(response_hash: Field, params: [Field; MAX_PARAMS]) -> Field;
}
