//! zkVerify proof submission bridge.
//!
//! Submits UltraHonk proofs to the zkVerify Relayer API.
//! Retries with exponential backoff on failure — no fallback to peer verification.

use std::time::Duration;

use reqwest::Client;
use tracing::{info, warn, error};

use crate::hex_utils::bytes_to_hex;
use crate::types::*;

/// Bridge client for submitting proofs to zkVerify.
pub struct ZkVerifyBridge {
    config: ZkVerifyConfig,
    client: Client,
}

impl ZkVerifyBridge {
    pub fn new(config: ZkVerifyConfig) -> Self {
        Self {
            config,
            client: Client::new(),
        }
    }

    /// Register a verification key (one-time per circuit). Returns VK hash.
    pub async fn register_vk(&self, vk_bytes: &[u8]) -> Result<String> {
        let url = format!("{}/register-vk", self.config.relayer_url);

        let body = serde_json::json!({
            "proofType": "ultrahonk",
            "proofOptions": {
                "variant": self.config.variant,
            },
            "vk": bytes_to_hex(vk_bytes),
        });

        let resp = self.client.post(&url)
            .header("Authorization", format!("Bearer {}", self.config.api_key))
            .json(&body)
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let message = resp.text().await.unwrap_or_default();
            return Err(ZkVerifyError::Api { status, message });
        }

        let result: serde_json::Value = resp.json().await?;
        let vk_hash = result["vkHash"]
            .as_str()
            .unwrap_or_default()
            .to_string();

        info!(vk_hash = %vk_hash, "VK registered");
        Ok(vk_hash)
    }

    /// Submit a proof for verification. Single attempt, no retry.
    pub async fn submit_proof(
        &self,
        proof_bytes: &[u8],
        vk_bytes: &[u8],
        public_inputs: &[u8],
    ) -> Result<SubmitProofResponse> {
        let url = format!("{}/submit-proof", self.config.relayer_url);

        let request = SubmitProofRequest {
            proof_type: "ultrahonk".into(),
            vk_registered: false,
            proof_data: ProofData {
                proof: bytes_to_hex(proof_bytes),
                public_signals: bytes_to_hex(public_inputs),
                vk: bytes_to_hex(vk_bytes),
            },
            proof_options: Some(ProofOptions {
                variant: self.config.variant,
            }),
        };

        let resp = self.client.post(&url)
            .header("Authorization", format!("Bearer {}", self.config.api_key))
            .json(&request)
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let message = resp.text().await.unwrap_or_default();
            return Err(ZkVerifyError::Api { status, message });
        }

        let result: SubmitProofResponse = resp.json().await?;
        info!(job_id = %result.job_id, "Proof submitted");
        Ok(result)
    }

    /// Submit a proof with exponential backoff retry within the tempo window.
    ///
    /// Retries on transient failures (network, 5xx) with backoff: 1s, 2s, 4s, ...
    /// capped at 60s. Returns error if the entire tempo_deadline passes without
    /// success. **Never falls back to peer verification.**
    pub async fn submit_with_retry(
        &self,
        proof_bytes: &[u8],
        vk_bytes: &[u8],
        public_inputs: &[u8],
        tempo_deadline: Duration,
    ) -> Result<SubmitProofResponse> {
        let start = tokio::time::Instant::now();
        let mut backoff = Duration::from_secs(1);
        let max_backoff = Duration::from_secs(60);
        let mut attempt = 0u32;

        loop {
            attempt += 1;
            let elapsed = start.elapsed();

            if elapsed >= tempo_deadline {
                error!(
                    attempts = attempt,
                    elapsed_secs = elapsed.as_secs(),
                    "Tempo deadline exceeded, proof submission failed"
                );
                return Err(ZkVerifyError::TempoTimeout {
                    elapsed_secs: elapsed.as_secs(),
                    tempo_secs: tempo_deadline.as_secs(),
                });
            }

            match self.submit_proof(proof_bytes, vk_bytes, public_inputs).await {
                Ok(resp) => return Ok(resp),
                Err(e) => {
                    // Don't retry on client errors (4xx) — those won't fix themselves
                    if let ZkVerifyError::Api { status, .. } = &e {
                        if *status >= 400 && *status < 500 {
                            error!(status, "Client error, not retrying");
                            return Err(e);
                        }
                    }

                    warn!(
                        attempt,
                        error = %e,
                        backoff_secs = backoff.as_secs(),
                        "Submission failed, retrying"
                    );

                    // Don't sleep past the deadline
                    let remaining = tempo_deadline.saturating_sub(elapsed);
                    let sleep_time = backoff.min(remaining);
                    tokio::time::sleep(sleep_time).await;

                    backoff = (backoff * 2).min(max_backoff);
                }
            }
        }
    }

    /// Check the status of a submitted proof job.
    pub async fn check_job_status(&self, job_id: &str) -> Result<JobStatusResponse> {
        let url = format!(
            "{}/job-status/{}",
            self.config.relayer_url, job_id
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

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::{MockServer, Mock, ResponseTemplate};
    use wiremock::matchers::{method, path, path_regex};

    fn test_config(server_url: &str) -> ZkVerifyConfig {
        ZkVerifyConfig {
            relayer_url: server_url.to_string(),
            api_key: "test-key".to_string(),
            variant: UltrahonkVariant::Plain,
            tempo_seconds: 4320,
        }
    }

    #[tokio::test]
    async fn test_submit_proof_success() {
        let server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/submit-proof"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "jobId": "job-123",
                "optimisticVerification": true,
            })))
            .mount(&server)
            .await;

        let bridge = ZkVerifyBridge::new(test_config(&server.uri()));
        let result = bridge
            .submit_proof(b"proof-data", b"vk-data", b"pub-inputs")
            .await
            .unwrap();

        assert_eq!(result.job_id, "job-123");
        assert!(result.optimistic_verification);
    }

    #[tokio::test]
    async fn test_submit_proof_api_error() {
        let server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/submit-proof"))
            .respond_with(ResponseTemplate::new(400).set_body_string("Bad proof format"))
            .mount(&server)
            .await;

        let bridge = ZkVerifyBridge::new(test_config(&server.uri()));
        let result = bridge
            .submit_proof(b"bad-proof", b"vk", b"pubs")
            .await;

        assert!(result.is_err());
        match result.unwrap_err() {
            ZkVerifyError::Api { status, message } => {
                assert_eq!(status, 400);
                assert_eq!(message, "Bad proof format");
            }
            e => panic!("Expected Api error, got: {e:?}"),
        }
    }

    #[tokio::test]
    async fn test_submit_with_retry_immediate_success() {
        let server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/submit-proof"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "jobId": "job-456",
            })))
            .mount(&server)
            .await;

        let bridge = ZkVerifyBridge::new(test_config(&server.uri()));
        let result = bridge
            .submit_with_retry(b"proof", b"vk", b"pubs", Duration::from_secs(10))
            .await
            .unwrap();

        assert_eq!(result.job_id, "job-456");
    }

    #[tokio::test]
    async fn test_submit_with_retry_client_error_no_retry() {
        let server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/submit-proof"))
            .respond_with(ResponseTemplate::new(422).set_body_string("Invalid proof"))
            .expect(1) // Should only be called once — no retry on 4xx
            .mount(&server)
            .await;

        let bridge = ZkVerifyBridge::new(test_config(&server.uri()));
        let result = bridge
            .submit_with_retry(b"bad", b"vk", b"pubs", Duration::from_secs(10))
            .await;

        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_submit_with_retry_timeout() {
        let server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/submit-proof"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Internal error"))
            .mount(&server)
            .await;

        let bridge = ZkVerifyBridge::new(test_config(&server.uri()));
        // Very short deadline to trigger timeout quickly
        let result = bridge
            .submit_with_retry(b"proof", b"vk", b"pubs", Duration::from_millis(100))
            .await;

        assert!(result.is_err());
        match result.unwrap_err() {
            ZkVerifyError::TempoTimeout { .. } => {}
            e => panic!("Expected TempoTimeout, got: {e:?}"),
        }
    }

    #[tokio::test]
    async fn test_check_job_status() {
        let server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path_regex("/job-status/.*"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "verified",
                "attestationId": 42,
                "leafDigest": "0xabcdef",
            })))
            .mount(&server)
            .await;

        let bridge = ZkVerifyBridge::new(test_config(&server.uri()));
        let status = bridge.check_job_status("job-123").await.unwrap();
        assert_eq!(status.status, JobStatus::Verified);
        assert_eq!(status.attestation_id, Some(42));
    }

    #[tokio::test]
    async fn test_register_vk() {
        let server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/register-vk"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "vkHash": "0x1234567890abcdef",
            })))
            .mount(&server)
            .await;

        let bridge = ZkVerifyBridge::new(test_config(&server.uri()));
        let vk_hash = bridge.register_vk(b"vk-data").await.unwrap();
        assert_eq!(vk_hash, "0x1234567890abcdef");
    }

    #[tokio::test]
    async fn test_submit_proof_request_serialization() {
        let req = SubmitProofRequest {
            proof_type: "ultrahonk".into(),
            vk_registered: false,
            proof_data: ProofData {
                proof: "0xaabb".into(),
                public_signals: "0xccdd".into(),
                vk: "0xeeff".into(),
            },
            proof_options: Some(ProofOptions {
                variant: UltrahonkVariant::Plain,
            }),
        };

        let json_str = serde_json::to_string(&req).unwrap();
        assert!(json_str.contains(r#""proofType":"ultrahonk""#));
        assert!(json_str.contains(r#""vkRegistered":false"#));
        assert!(json_str.contains(r#""proof":"0xaabb""#));
        assert!(json_str.contains(r#""variant":"plain""#));
    }
}
