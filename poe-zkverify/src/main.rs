//! poe-zkverify CLI: submit proofs to zkVerify from the command line.
//!
//! Usage:
//!   poe-zkverify submit --proof proof_file --vk vk_file --pubs pubs_file \
//!       --api-key KEY [--relayer-url URL] [--tempo 4320]
//!   poe-zkverify status --job-id JOB_ID [--relayer-url URL]
//!   poe-zkverify attest --job-id JOB_ID --timeout 300 [--relayer-url URL]

use std::path::PathBuf;
use std::time::Duration;

use clap::{Parser, Subcommand};

use poe_zkverify::attestation::AttestationReader;
use poe_zkverify::bridge::ZkVerifyBridge;
use poe_zkverify::types::{UltrahonkVariant, ZkVerifyConfig};

#[derive(Parser)]
#[command(name = "poe-zkverify")]
#[command(about = "Submit PoE proofs to zkVerify for on-chain attestation")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Submit a proof to zkVerify with retry logic.
    Submit {
        /// Path to proof file (binary, from bb prove).
        #[arg(short, long)]
        proof: PathBuf,

        /// Path to verification key file (binary, from bb write_vk).
        #[arg(short, long)]
        vk: PathBuf,

        /// Path to public inputs file (binary).
        #[arg(long)]
        pubs: PathBuf,

        /// zkVerify Relayer API key.
        #[arg(long, env = "ZKVERIFY_API_KEY")]
        api_key: String,

        /// Relayer API URL.
        #[arg(long, default_value = "https://testnet.kurier.xyz/api/v1")]
        relayer_url: String,

        /// UltraHonk variant: plain or zk.
        #[arg(long, default_value = "plain")]
        variant: String,

        /// Tempo deadline in seconds for retry (default: 72 minutes).
        #[arg(long, default_value = "4320")]
        tempo: u64,
    },

    /// Check the status of a submitted proof job.
    Status {
        /// Job ID from a previous submit.
        #[arg(long)]
        job_id: String,

        /// Relayer API URL.
        #[arg(long, default_value = "https://testnet.kurier.xyz/api/v1")]
        relayer_url: String,
    },

    /// Wait for attestation and print Merkle path.
    Attest {
        /// Job ID from a previous submit.
        #[arg(long)]
        job_id: String,

        /// Timeout in seconds to wait for attestation.
        #[arg(long, default_value = "300")]
        timeout: u64,

        /// Relayer API URL.
        #[arg(long, default_value = "https://testnet.kurier.xyz/api/v1")]
        relayer_url: String,

        /// API key (needed for job status).
        #[arg(long, env = "ZKVERIFY_API_KEY")]
        api_key: String,
    },

    /// Register a verification key (one-time per circuit).
    RegisterVk {
        /// Path to verification key file.
        #[arg(short, long)]
        vk: PathBuf,

        /// zkVerify Relayer API key.
        #[arg(long, env = "ZKVERIFY_API_KEY")]
        api_key: String,

        /// Relayer API URL.
        #[arg(long, default_value = "https://testnet.kurier.xyz/api/v1")]
        relayer_url: String,

        /// UltraHonk variant: plain or zk.
        #[arg(long, default_value = "plain")]
        variant: String,
    },
}

fn parse_variant(s: &str) -> UltrahonkVariant {
    match s.to_lowercase().as_str() {
        "zk" => UltrahonkVariant::Zk,
        _ => UltrahonkVariant::Plain,
    }
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    match cli.command {
        Commands::Submit {
            proof,
            vk,
            pubs,
            api_key,
            relayer_url,
            variant,
            tempo,
        } => {
            let proof_bytes = std::fs::read(&proof)
                .unwrap_or_else(|e| panic!("Failed to read proof {}: {e}", proof.display()));
            let vk_bytes = std::fs::read(&vk)
                .unwrap_or_else(|e| panic!("Failed to read VK {}: {e}", vk.display()));
            let pubs_bytes = std::fs::read(&pubs)
                .unwrap_or_else(|e| panic!("Failed to read pubs {}: {e}", pubs.display()));

            let config = ZkVerifyConfig {
                relayer_url,
                api_key,
                variant: parse_variant(&variant),
                tempo_seconds: tempo,
            };

            let bridge = ZkVerifyBridge::new(config);
            let deadline = Duration::from_secs(tempo);

            match bridge
                .submit_with_retry(&proof_bytes, &vk_bytes, &pubs_bytes, deadline)
                .await
            {
                Ok(resp) => {
                    // Output JSON for Python to parse
                    let output = serde_json::json!({
                        "job_id": resp.job_id,
                        "optimistic_verification": resp.optimistic_verification,
                    });
                    println!("{}", serde_json::to_string(&output).unwrap());
                }
                Err(e) => {
                    eprintln!("ERROR: {e}");
                    std::process::exit(1);
                }
            }
        }

        Commands::Status {
            job_id,
            relayer_url,
        } => {
            let config = ZkVerifyConfig {
                relayer_url,
                api_key: String::new(), // Not needed for status check
                variant: UltrahonkVariant::Plain,
                tempo_seconds: 0,
            };

            let bridge = ZkVerifyBridge::new(config);
            match bridge.check_job_status(&job_id).await {
                Ok(status) => {
                    let output = serde_json::json!({
                        "status": format!("{:?}", status.status),
                        "attestation_id": status.attestation_id,
                        "leaf_digest": status.leaf_digest,
                    });
                    println!("{}", serde_json::to_string(&output).unwrap());
                }
                Err(e) => {
                    eprintln!("ERROR: {e}");
                    std::process::exit(1);
                }
            }
        }

        Commands::Attest {
            job_id,
            timeout,
            relayer_url,
            api_key,
        } => {
            let config = ZkVerifyConfig {
                relayer_url,
                api_key,
                variant: UltrahonkVariant::Plain,
                tempo_seconds: 0,
            };

            let reader = AttestationReader::new(config);
            match reader
                .wait_for_attestation(&job_id, Duration::from_secs(timeout))
                .await
            {
                Ok(event) => {
                    let output = serde_json::json!({
                        "attestation_id": event.attestation_id,
                        "leaf_digest": event.leaf_digest,
                    });
                    println!("{}", serde_json::to_string(&output).unwrap());
                }
                Err(e) => {
                    eprintln!("ERROR: {e}");
                    std::process::exit(1);
                }
            }
        }

        Commands::RegisterVk {
            vk,
            api_key,
            relayer_url,
            variant,
        } => {
            let vk_bytes = std::fs::read(&vk)
                .unwrap_or_else(|e| panic!("Failed to read VK {}: {e}", vk.display()));

            let config = ZkVerifyConfig {
                relayer_url,
                api_key,
                variant: parse_variant(&variant),
                tempo_seconds: 0,
            };

            let bridge = ZkVerifyBridge::new(config);
            match bridge.register_vk(&vk_bytes).await {
                Ok(vk_hash) => {
                    let output = serde_json::json!({
                        "vk_hash": vk_hash,
                    });
                    println!("{}", serde_json::to_string(&output).unwrap());
                }
                Err(e) => {
                    eprintln!("ERROR: {e}");
                    std::process::exit(1);
                }
            }
        }
    }
}
