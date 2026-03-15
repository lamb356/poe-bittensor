use poe_witness::types::{EvaluationData, NUM_MINERS};
use poe_witness::witness::{generate_witness, to_prover_toml, compute_commitments};
use std::process::Command;

const NARGO: &str = "/home/burba/.nargo/bin/nargo";
const BB: &str = "/home/burba/.bb/bb";
const COMMITMENT_HELPER: &str = "/home/burba/poe-bittensor/commitment_helper";
const POE_CIRCUIT: &str = "/home/burba/poe-bittensor/poe_circuit";

fn test_evaluation_data() -> EvaluationData {
    let miner_uids: Vec<u16> = (1..=NUM_MINERS as u16).collect();
    let responses: Vec<Vec<u8>> = (0..NUM_MINERS)
        .map(|i| format!("miner_{}_response_epoch_42", i).into_bytes())
        .collect();
    let scores: Vec<u64> = (0..NUM_MINERS)
        .map(|i| 50 + ((i as u64) * 37) % 300)
        .collect();

    EvaluationData {
        miner_uids,
        responses,
        scores,
        epoch: 42,
        validator_id: 12345,
        challenge_nonce: 77777,
        salt: 999,
    }
}

#[test]
fn test_generate_witness_basic() {
    let data = test_evaluation_data();
    let witness = generate_witness(&data);

    assert_eq!(witness.miner_uids.len(), NUM_MINERS);
    assert_eq!(witness.response_hashes.len(), NUM_MINERS);
    assert_eq!(witness.weights.len(), NUM_MINERS);

    // Verify weight sum is in valid range
    let weight_sum: u64 = witness.weights.iter().map(|w| w.parse::<u64>().unwrap()).sum();
    assert!(weight_sum >= 65535 - 63, "Weight sum {} too low", weight_sum);
    assert!(weight_sum <= 65535, "Weight sum {} too high", weight_sum);
}

#[test]
fn test_commitment_computation() {
    let data = test_evaluation_data();
    let mut witness = generate_witness(&data);

    // Compute commitments via Noir helper
    compute_commitments(&mut witness, COMMITMENT_HELPER, NARGO)
        .expect("Commitment computation failed");

    assert_ne!(witness.input_commitment, "0", "Input commitment not computed");
    assert_ne!(witness.weight_commitment, "0", "Weight commitment not computed");
    assert!(
        witness.input_commitment.starts_with("0x"),
        "Input commitment should be hex"
    );
    assert!(
        witness.weight_commitment.starts_with("0x"),
        "Weight commitment should be hex"
    );
}

#[test]
fn test_full_roundtrip_prove_verify() {
    let data = test_evaluation_data();
    let mut witness = generate_witness(&data);

    // Step 1: Compute commitments
    compute_commitments(&mut witness, COMMITMENT_HELPER, NARGO)
        .expect("Commitment computation failed");

    // Step 2: Write Prover.toml to poe_circuit
    let prover_toml = to_prover_toml(&witness);
    let prover_path = format!("{}/Prover.toml", POE_CIRCUIT);
    std::fs::write(&prover_path, &prover_toml).expect("Failed to write Prover.toml");

    // Step 3: nargo execute (generate witness)
    let output = Command::new(NARGO)
        .args(["execute", "--program-dir", POE_CIRCUIT])
        .output()
        .expect("Failed to run nargo execute");
    assert!(
        output.status.success(),
        "nargo execute failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    // Step 4: bb prove
    let circuit_json = format!("{}/target/poe_circuit.json", POE_CIRCUIT);
    let witness_gz = format!("{}/target/poe_circuit.gz", POE_CIRCUIT);
    let proof_dir = "/tmp/poe_proof";
    let proof_path = "/tmp/poe_proof/proof";
    std::fs::create_dir_all(proof_dir).ok();
    let output = Command::new(BB)
        .args([
            "prove",
            "--scheme", "ultra_honk",
            "-b", &circuit_json,
            "-w", &witness_gz,
            "-o", proof_dir,
        ])
        .output()
        .expect("Failed to run bb prove");
    assert!(
        output.status.success(),
        "bb prove failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    // Step 5: bb write_vk + bb verify
    let vk_dir = "/tmp/poe_vk";
    let vk_path = "/tmp/poe_vk/vk";
    std::fs::create_dir_all(vk_dir).ok();
    let output = Command::new(BB)
        .args([
            "write_vk",
            "--scheme", "ultra_honk",
            "-b", &circuit_json,
            "-o", vk_dir,
        ])
        .output()
        .expect("Failed to run bb write_vk");
    assert!(
        output.status.success(),
        "bb write_vk failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    let output = Command::new(BB)
        .args([
            "verify",
            "--scheme", "ultra_honk",
            "-k", vk_path,
            "-p", proof_path,
        ])
        .output()
        .expect("Failed to run bb verify");
    assert!(
        output.status.success(),
        "bb verify failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    // Cleanup
    let _ = std::fs::remove_file(&prover_path);
    let _ = std::fs::remove_dir_all(proof_dir);
    let _ = std::fs::remove_dir_all(vk_dir);
}
