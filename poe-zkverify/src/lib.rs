//! zkVerify bridge for PoE proof submission and attestation.
//!
//! Submits UltraHonk proofs to zkVerify via the Relayer HTTP API.
//! Proofs are verified on-chain and aggregated into Merkle trees.
//! Attestation roots can be checked to confirm proof validity
//! without peer trust.

pub mod attestation;
pub mod bridge;
pub mod hex_utils;
pub mod types;

pub use attestation::AttestationReader;
pub use bridge::ZkVerifyBridge;
pub use types::{UltrahonkVariant, ZkVerifyConfig};
