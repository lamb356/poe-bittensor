//! Types for zkVerify Relayer API interaction.

use serde::{Deserialize, Serialize};
use std::fmt;

/// Configuration for the zkVerify bridge.
#[derive(Debug, Clone)]
pub struct ZkVerifyConfig {
    /// Relayer API base URL.
    pub relayer_url: String,
    /// API key for the Relayer.
    pub api_key: String,
    /// UltraHonk variant (Plain or Zk).
    pub variant: UltrahonkVariant,
    /// Tempo window in seconds (default: 72 minutes = 4320s).
    pub tempo_seconds: u64,
}

impl ZkVerifyConfig {
    pub fn testnet(api_key: String) -> Self {
        Self {
            relayer_url: "https://relayer-api-testnet.horizenlabs.io/api/v1".into(),
            api_key,
            variant: UltrahonkVariant::Plain,
            tempo_seconds: 4320,
        }
    }

    pub fn mainnet(api_key: String) -> Self {
        Self {
            relayer_url: "https://relayer-api-mainnet.horizenlabs.io/api/v1".into(),
            api_key,
            variant: UltrahonkVariant::Plain,
            tempo_seconds: 4320,
        }
    }
}

/// UltraHonk proof variant.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum UltrahonkVariant {
    Plain,
    Zk,
}

impl fmt::Display for UltrahonkVariant {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Plain => write!(f, "plain"),
            Self::Zk => write!(f, "zk"),
        }
    }
}

/// Request body for POST /submit-proof/{api_key}.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SubmitProofRequest {
    pub proof_type: String,
    pub vk_registered: bool,
    pub proof_data: ProofData,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub proof_options: Option<ProofOptions>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProofData {
    pub proof: String,
    pub public_signals: String,
    pub vk: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProofOptions {
    pub variant: UltrahonkVariant,
}

/// Response from POST /submit-proof.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SubmitProofResponse {
    pub job_id: String,
    #[serde(default)]
    pub optimistic_verification: bool,
}

/// Job status from the Relayer API.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum JobStatus {
    Pending,
    Verified,
    Failed,
    #[serde(other)]
    Unknown,
}

/// Response from GET /job-status/{job_id}.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct JobStatusResponse {
    pub status: JobStatus,
    #[serde(default)]
    pub attestation_id: Option<u64>,
    #[serde(default)]
    pub leaf_digest: Option<String>,
}

/// Attestation event data.
#[derive(Debug, Clone)]
pub struct AttestationEvent {
    pub attestation_id: u64,
    pub leaf_digest: String,
}

/// Merkle path for on-chain verification.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MerklePath {
    pub root: String,
    pub path: Vec<String>,
    pub leaf_index: u64,
}

/// Bridge errors.
#[derive(Debug, thiserror::Error)]
pub enum ZkVerifyError {
    #[error("HTTP request failed: {0}")]
    Http(#[from] reqwest::Error),

    #[error("API error ({status}): {message}")]
    Api { status: u16, message: String },

    #[error("Proof submission timed out after {elapsed_secs}s (tempo: {tempo_secs}s)")]
    TempoTimeout { elapsed_secs: u64, tempo_secs: u64 },

    #[error("Attestation not found for job {job_id}")]
    AttestationNotFound { job_id: String },

    #[error("Invalid hex: {0}")]
    Hex(String),

    #[error("Job failed: {0}")]
    JobFailed(String),
}

pub type Result<T> = std::result::Result<T, ZkVerifyError>;
