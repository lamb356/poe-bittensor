use crate::blake3_field::hash_response_to_field;
use crate::normalize::normalize_scores;
use crate::types::{EvaluationData, WitnessData, NUM_MINERS};

/// Generate witness data from raw evaluation data.
/// Commitments are initially set to "0" -- they must be computed
/// by calling compute_commitments() afterwards.
pub fn generate_witness(data: &EvaluationData) -> WitnessData {
    assert_eq!(data.miner_uids.len(), NUM_MINERS);
    assert_eq!(data.responses.len(), NUM_MINERS);
    assert_eq!(data.scores.len(), NUM_MINERS);

    // BLAKE3 hash each response and reduce to BN254 field
    let response_hashes: Vec<String> = data
        .responses
        .iter()
        .map(|r| hash_response_to_field(r))
        .collect();

    // Normalize scores to u16 weights
    let weights = normalize_scores(&data.scores);

    WitnessData {
        input_commitment: "0".to_string(),
        weight_commitment: "0".to_string(),
        epoch: data.epoch.to_string(),
        validator_id: data.validator_id.to_string(),
        challenge_nonce: data.challenge_nonce.to_string(),
        miner_uids: data.miner_uids.iter().map(|u| u.to_string()).collect(),
        response_hashes,
        scores: data.scores.iter().map(|s| s.to_string()).collect(),
        weights: weights.iter().map(|w| w.to_string()).collect(),
        salt: data.salt.to_string(),
    }
}

/// Format witness data as Prover.toml for the commitment_helper circuit.
/// The helper has NO public inputs — all inputs are private.
pub fn to_commitment_helper_toml(w: &WitnessData) -> String {
    let mut lines = Vec::new();

    lines.push(format!("challenge_nonce = \"{}\"", w.challenge_nonce));
    lines.push(format!("epoch = \"{}\"", w.epoch));
    lines.push(format!("validator_id = \"{}\"", w.validator_id));
    lines.push(format!("salt = \"{}\"", w.salt));
    lines.push(format!("miner_uids = [{}]", format_array(&w.miner_uids)));
    lines.push(format!("response_hashes = [{}]", format_array(&w.response_hashes)));
    lines.push(format!("scores = [{}]", format_array(&w.scores)));
    lines.push(format!("weights = [{}]", format_array(&w.weights)));

    lines.join("\n") + "\n"
}

/// Format witness data as Prover.toml for the main poe_circuit.
pub fn to_prover_toml(w: &WitnessData) -> String {
    let mut lines = Vec::new();

    lines.push(format!("input_commitment = \"{}\"", w.input_commitment));
    lines.push(format!("weight_commitment = \"{}\"", w.weight_commitment));
    lines.push(format!("epoch = \"{}\"", w.epoch));
    lines.push(format!("validator_id = \"{}\"", w.validator_id));
    lines.push(format!("challenge_nonce = \"{}\"", w.challenge_nonce));
    lines.push(format!("salt = \"{}\"", w.salt));
    lines.push(format!("miner_uids = [{}]", format_array(&w.miner_uids)));
    lines.push(format!("response_hashes = [{}]", format_array(&w.response_hashes)));
    lines.push(format!("scores = [{}]", format_array(&w.scores)));
    lines.push(format!("weights = [{}]", format_array(&w.weights)));

    lines.join("\n") + "\n"
}

fn format_array(items: &[String]) -> String {
    items
        .iter()
        .map(|s| format!("\"{}\"", s))
        .collect::<Vec<_>>()
        .join(", ")
}

/// Compute commitments by shelling out to nargo execute on the commitment helper.
/// Parses the println output to extract hex commitment values.
pub fn compute_commitments(
    witness: &mut WitnessData,
    commitment_helper_dir: &str,
    nargo_bin: &str,
) -> Result<(), String> {
    use std::process::Command;

    // Write Prover.toml for the commitment helper
    let prover_path = format!("{}/Prover.toml", commitment_helper_dir);
    let toml_content = to_commitment_helper_toml(witness);
    std::fs::write(&prover_path, &toml_content)
        .map_err(|e| format!("Failed to write Prover.toml: {}", e))?;

    // Run nargo execute
    let output = Command::new(nargo_bin)
        .args(["execute", "--program-dir", commitment_helper_dir])
        .output()
        .map_err(|e| format!("Failed to run nargo: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("nargo execute failed: {}", stderr));
    }

    // Parse commitment values from stdout
    // Format: "input_commitment=0x..." and "weight_commitment=0x..."
    let stdout = String::from_utf8_lossy(&output.stdout);
    for line in stdout.lines() {
        let line = line.trim();
        if let Some(val) = line.strip_prefix("input_commitment=") {
            witness.input_commitment = val.to_string();
        } else if let Some(val) = line.strip_prefix("weight_commitment=") {
            witness.weight_commitment = val.to_string();
        }
    }

    if witness.input_commitment == "0" || witness.weight_commitment == "0" {
        return Err(format!(
            "Failed to extract commitments. nargo stdout:\n{}",
            stdout
        ));
    }

    // Clean up Prover.toml
    let _ = std::fs::remove_file(&prover_path);

    Ok(())
}
