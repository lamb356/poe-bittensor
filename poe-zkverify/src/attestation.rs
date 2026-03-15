//! Attestation reader for checking proof verification status.

use std::time::Duration;

use reqwest::Client;
use tracing::info;

use crate::types::*;

/// Reader for zkVerify attestation data.
pub struct AttestationReader {
    config: ZkVerifyConfig,
    client: Client,
}

impl AttestationReader {
    pub fn new(config: ZkVerifyConfig) -> Self {
        Self {
            config,
            client: Client::new(),
        }
    }

    /// Poll job status until attestation is available or timeout.
    pub async fn wait_for_attestation(
        &self,
        job_id: &str,
        timeout: Duration,
    ) -> Result<AttestationEvent> {
        let start = tokio::time::Instant::now();
        let poll_interval = Duration::from_secs(5);

        loop {
            if start.elapsed() >= timeout {
                return Err(ZkVerifyError::AttestationNotFound {
                    job_id: job_id.to_string(),
                });
            }

            let url = format!("{}/job-status/{}", self.config.relayer_url, job_id);
            let resp = self.client.get(&url).send().await?;

            if resp.status().is_success() {
                let status: JobStatusResponse = resp.json().await?;

                match status.status {
                    JobStatus::Verified => {
                        if let (Some(id), Some(digest)) =
                            (status.attestation_id, status.leaf_digest)
                        {
                            info!(attestation_id = id, "Attestation received");
                            return Ok(AttestationEvent {
                                attestation_id: id,
                                leaf_digest: digest,
                            });
                        }
                    }
                    JobStatus::Failed => {
                        return Err(ZkVerifyError::JobFailed(job_id.to_string()));
                    }
                    _ => {
                        // Still pending, wait and retry
                    }
                }
            }

            let remaining = timeout.saturating_sub(start.elapsed());
            tokio::time::sleep(poll_interval.min(remaining)).await;
        }
    }

    /// Check if a proof is included in an attestation's Merkle tree.
    pub async fn is_proof_attested(
        &self,
        attestation_id: u64,
        leaf_digest: &str,
    ) -> Result<bool> {
        match self.get_merkle_path(attestation_id, leaf_digest).await {
            Ok(_) => Ok(true),
            Err(ZkVerifyError::Api { status: 404, .. }) => Ok(false),
            Err(e) => Err(e),
        }
    }

    /// Get the Merkle path for a proof within an attestation.
    pub async fn get_merkle_path(
        &self,
        attestation_id: u64,
        leaf_digest: &str,
    ) -> Result<MerklePath> {
        let url = format!(
            "{}/merkle-proof/{}/{}",
            self.config.relayer_url, attestation_id, leaf_digest
        );

        let resp = self.client.get(&url).send().await?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let message = resp.text().await.unwrap_or_default();
            return Err(ZkVerifyError::Api { status, message });
        }

        Ok(resp.json().await?)
    }
}

/// Verify a Merkle path locally without trusting the relayer.
///
/// NOTE: This is a stub. Full implementation is blocked on zkVerify
/// documenting their exact Merkle hash function (Poseidon2 vs Keccak256
/// vs a domain-separated variant). Until then, we log a warning and
/// return the unverified result from is_proof_attested().
pub fn verify_merkle_path_local(
    merkle_path: &MerklePath,
    leaf_digest: &str,
) -> bool {
    tracing::warn!(
        root = %merkle_path.root,
        leaf = %leaf_digest,
        path_len = merkle_path.path.len(),
        "Merkle path verification not yet implemented - trusting relayer response"
    );
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::{MockServer, Mock, ResponseTemplate};
    use wiremock::matchers::{method, path_regex};

    fn test_config(server_url: &str) -> ZkVerifyConfig {
        ZkVerifyConfig {
            relayer_url: server_url.to_string(),
            api_key: "test-key".to_string(),
            variant: UltrahonkVariant::Plain,
            tempo_seconds: 4320,
        }
    }

    #[tokio::test]
    async fn test_wait_for_attestation_immediate() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path_regex("/job-status/.*"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "verified",
                "attestationId": 99,
                "leafDigest": "0xdeadbeef",
            })))
            .mount(&server)
            .await;

        let reader = AttestationReader::new(test_config(&server.uri()));
        let event = reader
            .wait_for_attestation("job-1", Duration::from_secs(5))
            .await
            .unwrap();

        assert_eq!(event.attestation_id, 99);
        assert_eq!(event.leaf_digest, "0xdeadbeef");
    }

    #[tokio::test]
    async fn test_wait_for_attestation_job_failed() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path_regex("/job-status/.*"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "failed",
            })))
            .mount(&server)
            .await;

        let reader = AttestationReader::new(test_config(&server.uri()));
        let result = reader
            .wait_for_attestation("job-fail", Duration::from_secs(5))
            .await;

        assert!(matches!(result, Err(ZkVerifyError::JobFailed(_))));
    }

    #[tokio::test]
    async fn test_is_proof_attested_true() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path_regex("/merkle-proof/.*"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "root": "0xaabb",
                "path": ["0x1111", "0x2222"],
                "leafIndex": 3,
            })))
            .mount(&server)
            .await;

        let reader = AttestationReader::new(test_config(&server.uri()));
        assert!(reader.is_proof_attested(1, "0xleaf").await.unwrap());
    }

    #[tokio::test]
    async fn test_is_proof_attested_false() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path_regex("/merkle-proof/.*"))
            .respond_with(ResponseTemplate::new(404).set_body_string("Not found"))
            .mount(&server)
            .await;

        let reader = AttestationReader::new(test_config(&server.uri()));
        assert!(!reader.is_proof_attested(1, "0xmissing").await.unwrap());
    }

    #[tokio::test]
    async fn test_get_merkle_path() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path_regex("/merkle-proof/.*"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "root": "0xroot",
                "path": ["0xa", "0xb", "0xc"],
                "leafIndex": 7,
            })))
            .mount(&server)
            .await;

        let reader = AttestationReader::new(test_config(&server.uri()));
        let path = reader.get_merkle_path(42, "0xleaf").await.unwrap();
        assert_eq!(path.root, "0xroot");
        assert_eq!(path.path.len(), 3);
        assert_eq!(path.leaf_index, 7);
    }
}
