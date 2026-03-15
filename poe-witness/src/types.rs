use serde::{Deserialize, Serialize};

pub const NUM_MINERS: usize = 64;
pub const MAX_WEIGHT: u64 = 65535;

/// Raw evaluation data from the validator
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvaluationData {
    pub miner_uids: Vec<u16>,
    pub responses: Vec<Vec<u8>>,
    pub scores: Vec<u64>,
    pub epoch: u64,
    pub validator_id: u64,
    pub challenge_nonce: u64,
    pub salt: u64,
}

/// All values needed for Prover.toml
#[derive(Debug, Clone)]
pub struct WitnessData {
    // Public inputs
    pub input_commitment: String,
    pub weight_commitment: String,
    pub score_commitment: String,
    pub epoch: String,
    pub validator_id: String,
    pub challenge_nonce: String,
    // Private inputs
    pub miner_uids: Vec<String>,
    pub response_hashes: Vec<String>,
    pub scores: Vec<String>,
    pub weights: Vec<String>,
    pub salt: String,
}
