use clap::Parser;
use std::path::PathBuf;

use poe_witness::types::EvaluationData;
use poe_witness::witness::{compute_commitments, generate_witness, to_prover_toml};

#[derive(Parser)]
#[command(name = "poe-witness")]
#[command(about = "Generate Noir witness from validator evaluation data")]
struct Cli {
    /// Path to evaluation data JSON
    #[arg(short, long)]
    input: PathBuf,

    /// Output path for Prover.toml
    #[arg(short, long)]
    output: PathBuf,

    /// Path to commitment helper Noir project
    #[arg(short, long, default_value = "../commitment_helper")]
    commitment_helper: PathBuf,

    /// Path to nargo binary
    #[arg(long, default_value = "nargo")]
    nargo: String,

    /// Skip commitment computation (output placeholder zeros)
    #[arg(long)]
    skip_commitments: bool,
}

fn main() {
    let cli = Cli::parse();

    let json = std::fs::read_to_string(&cli.input).expect("Failed to read input JSON");
    let data: EvaluationData = serde_json::from_str(&json).expect("Failed to parse JSON");

    let mut witness = generate_witness(&data);

    if !cli.skip_commitments {
        let helper_dir = cli.commitment_helper.to_str().unwrap();
        compute_commitments(&mut witness, helper_dir, &cli.nargo)
            .expect("Failed to compute commitments");
        eprintln!(
            "Commitments: ic={}, wc={}",
            witness.input_commitment, witness.weight_commitment
        );
    }

    let toml = to_prover_toml(&witness);
    std::fs::write(&cli.output, &toml).expect("Failed to write output");
    eprintln!("Witness written to {}", cli.output.display());
}
