--------------------------- MODULE PoE ---------------------------
(**************************************************************************)
(* Proof-of-Evaluation Protocol for Bittensor                             *)
(*                                                                        *)
(* Models the PoE protocol across multiple epochs with honest validators, *)
(* copier validators, and adversarial behaviors (replay, proof sharing).   *)
(* Verifies that ZK proof requirements prevent weight copying.            *)
(**************************************************************************)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    HonestValidators,   \* Set of honest validator IDs
    CopierValidators,   \* Set of copier validator IDs
    Miners,             \* Set of miner IDs
    MaxEpoch            \* Number of epochs to model

VARIABLES
    epoch,              \* Current epoch number (1..MaxEpoch)
    phase,              \* Current phase: "challenge", "evaluate", "prove", "submit", "verify", "done"
    challengeNonce,     \* Drand nonce for current epoch (modeled as epoch-dependent)
    \* Per-validator state (functions from validator ID -> value)
    hasResponses,       \* validator -> BOOLEAN: queried miners and got responses
    hasScores,          \* validator -> BOOLEAN: computed scores from responses
    hasProof,           \* validator -> BOOLEAN: generated valid ZK proof
    proofEpoch,         \* validator -> epoch the proof was generated for
    proofValidator,     \* validator -> validator ID bound to the proof
    submitted,          \* validator -> BOOLEAN: submitted weights + proof
    verified,           \* validator -> "pending" | "valid" | "invalid"
    \* Copier-specific: track what copiers attempt
    copierStrategy,     \* copier -> "copy_weights" | "replay_proof" | "share_proof" | "idle"
    \* Tracking
    acceptedWeights,    \* Set of (validator, epoch) pairs with accepted weights
    rejectedWeights     \* Set of (validator, epoch) pairs with rejected weights

AllValidators == HonestValidators \union CopierValidators

vars == <<epoch, phase, challengeNonce,
          hasResponses, hasScores, hasProof,
          proofEpoch, proofValidator,
          submitted, verified,
          copierStrategy,
          acceptedWeights, rejectedWeights>>

------------------------------------------------------------------------
(* Initial State *)
------------------------------------------------------------------------
Init ==
    /\ epoch = 1
    /\ phase = "challenge"
    /\ challengeNonce = 1  \* Nonce derived from epoch
    /\ hasResponses = [v \in AllValidators |-> FALSE]
    /\ hasScores = [v \in AllValidators |-> FALSE]
    /\ hasProof = [v \in AllValidators |-> FALSE]
    /\ proofEpoch = [v \in AllValidators |-> 0]
    /\ proofValidator = [v \in AllValidators |-> v]
    /\ submitted = [v \in AllValidators |-> FALSE]
    /\ verified = [v \in AllValidators |-> "pending"]
    /\ copierStrategy = [v \in CopierValidators |-> "idle"]
    /\ acceptedWeights = {}
    /\ rejectedWeights = {}

------------------------------------------------------------------------
(* Phase Transitions *)
------------------------------------------------------------------------

(* Chain publishes challenge nonce at epoch start *)
ChallengePhase ==
    /\ phase = "challenge"
    /\ phase' = "evaluate"
    /\ challengeNonce' = epoch  \* Nonce is unpredictable; model as epoch-derived
    /\ UNCHANGED <<epoch, hasResponses, hasScores, hasProof,
                   proofEpoch, proofValidator, submitted, verified,
                   copierStrategy, acceptedWeights, rejectedWeights>>

(* Honest validator queries miners and gets responses *)
HonestEvaluate(v) ==
    /\ phase = "evaluate"
    /\ v \in HonestValidators
    /\ ~hasResponses[v]
    /\ hasResponses' = [hasResponses EXCEPT ![v] = TRUE]
    /\ hasScores' = [hasScores EXCEPT ![v] = TRUE]
    /\ UNCHANGED <<epoch, phase, challengeNonce, hasProof,
                   proofEpoch, proofValidator, submitted, verified,
                   copierStrategy, acceptedWeights, rejectedWeights>>

(* Copier chooses a strategy — does NOT query miners *)
CopierChooseStrategy(v) ==
    /\ phase = "evaluate"
    /\ v \in CopierValidators
    /\ copierStrategy[v] = "idle"
    /\ \E strat \in {"copy_weights", "replay_proof", "share_proof"} :
        copierStrategy' = [copierStrategy EXCEPT ![v] = strat]
    \* Copier does NOT get responses or scores from miners
    /\ UNCHANGED <<epoch, phase, challengeNonce, hasResponses, hasScores,
                   hasProof, proofEpoch, proofValidator, submitted, verified,
                   acceptedWeights, rejectedWeights>>

(* Advance to prove phase once evaluation window closes *)
EvaluateToProve ==
    /\ phase = "evaluate"
    /\ phase' = "prove"
    /\ UNCHANGED <<epoch, challengeNonce, hasResponses, hasScores, hasProof,
                   proofEpoch, proofValidator, submitted, verified,
                   copierStrategy, acceptedWeights, rejectedWeights>>

(* Honest validator generates ZK proof *)
(* Requires: has responses, has scores, current epoch's nonce *)
HonestProve(v) ==
    /\ phase = "prove"
    /\ v \in HonestValidators
    /\ hasResponses[v]
    /\ hasScores[v]
    /\ ~hasProof[v]
    /\ hasProof' = [hasProof EXCEPT ![v] = TRUE]
    /\ proofEpoch' = [proofEpoch EXCEPT ![v] = epoch]
    /\ proofValidator' = [proofValidator EXCEPT ![v] = v]
    /\ UNCHANGED <<epoch, phase, challengeNonce, hasResponses, hasScores,
                   submitted, verified, copierStrategy,
                   acceptedWeights, rejectedWeights>>

(* Copier attempts to fabricate or reuse a proof *)
(* Key insight: copier has NO responses, so cannot create valid input commitment *)
CopierAttemptProof(v) ==
    /\ phase = "prove"
    /\ v \in CopierValidators
    /\ ~hasProof[v]
    /\ \/ (* Strategy: copy weights — no proof possible without responses *)
          /\ copierStrategy[v] = "copy_weights"
          /\ UNCHANGED <<hasProof, proofEpoch, proofValidator>>
       \/ (* Strategy: replay proof from previous epoch *)
          /\ copierStrategy[v] = "replay_proof"
          /\ epoch > 1  \* Can only replay if not first epoch
          /\ hasProof' = [hasProof EXCEPT ![v] = TRUE]
          /\ proofEpoch' = [proofEpoch EXCEPT ![v] = epoch - 1]  \* Stale epoch!
          /\ proofValidator' = [proofValidator EXCEPT ![v] = v]
       \/ (* Strategy: share proof from an honest validator *)
          /\ copierStrategy[v] = "share_proof"
          /\ \E h \in HonestValidators :
              /\ hasProof[h]
              /\ hasProof' = [hasProof EXCEPT ![v] = TRUE]
              /\ proofEpoch' = [proofEpoch EXCEPT ![v] = proofEpoch[h]]
              /\ proofValidator' = [proofValidator EXCEPT ![v] = h]  \* Wrong validator ID!
    /\ UNCHANGED <<epoch, phase, challengeNonce, hasResponses, hasScores,
                   submitted, verified, copierStrategy,
                   acceptedWeights, rejectedWeights>>

(* Advance to submit phase *)
ProveToSubmit ==
    /\ phase = "prove"
    /\ phase' = "submit"
    /\ UNCHANGED <<epoch, challengeNonce, hasResponses, hasScores, hasProof,
                   proofEpoch, proofValidator, submitted, verified,
                   copierStrategy, acceptedWeights, rejectedWeights>>

(* Validator submits weights + proof *)
Submit(v) ==
    /\ phase = "submit"
    /\ v \in AllValidators
    /\ ~submitted[v]
    /\ submitted' = [submitted EXCEPT ![v] = TRUE]
    /\ UNCHANGED <<epoch, phase, challengeNonce, hasResponses, hasScores,
                   hasProof, proofEpoch, proofValidator, verified,
                   copierStrategy, acceptedWeights, rejectedWeights>>

(* Advance to verify phase *)
SubmitToVerify ==
    /\ phase = "submit"
    /\ phase' = "verify"
    /\ UNCHANGED <<epoch, challengeNonce, hasResponses, hasScores, hasProof,
                   proofEpoch, proofValidator, submitted, verified,
                   copierStrategy, acceptedWeights, rejectedWeights>>

(* Verification: check proof validity *)
(* A proof is valid IFF:
   1. Validator has a proof (hasProof)
   2. Proof was generated for THIS epoch (proofEpoch == epoch)
   3. Proof is bound to THIS validator (proofValidator == v)
   4. Validator had actual miner responses (hasResponses) — embedded in input commitment *)
Verify(v) ==
    /\ phase = "verify"
    /\ v \in AllValidators
    /\ submitted[v]
    /\ verified[v] = "pending"
    /\ LET isValid ==
           /\ hasProof[v]
           /\ proofEpoch[v] = epoch
           /\ proofValidator[v] = v
           /\ hasResponses[v]
       IN
       /\ verified' = [verified EXCEPT ![v] = IF isValid THEN "valid" ELSE "invalid"]
       /\ IF isValid
          THEN /\ acceptedWeights' = acceptedWeights \union {<<v, epoch>>}
               /\ UNCHANGED rejectedWeights
          ELSE /\ rejectedWeights' = rejectedWeights \union {<<v, epoch>>}
               /\ UNCHANGED acceptedWeights
    /\ UNCHANGED <<epoch, phase, challengeNonce, hasResponses, hasScores,
                   hasProof, proofEpoch, proofValidator, submitted,
                   copierStrategy>>

(* Advance to next epoch or terminate *)
NextEpoch ==
    /\ phase = "verify"
    \* All submitted validators have been verified
    /\ \A v \in AllValidators : submitted[v] => verified[v] /= "pending"
    /\ IF epoch < MaxEpoch
       THEN
           /\ epoch' = epoch + 1
           /\ phase' = "challenge"
           \* Reset per-epoch state
           /\ hasResponses' = [v \in AllValidators |-> FALSE]
           /\ hasScores' = [v \in AllValidators |-> FALSE]
           /\ hasProof' = [v \in AllValidators |-> FALSE]
           /\ proofEpoch' = [v \in AllValidators |-> proofEpoch[v]]  \* Keep for replay attacks
           /\ proofValidator' = [v \in AllValidators |-> v]
           /\ submitted' = [v \in AllValidators |-> FALSE]
           /\ verified' = [v \in AllValidators |-> "pending"]
           /\ copierStrategy' = [v \in CopierValidators |-> "idle"]
           /\ UNCHANGED <<challengeNonce, acceptedWeights, rejectedWeights>>
       ELSE
           /\ phase' = "done"
           /\ UNCHANGED <<epoch, challengeNonce, hasResponses, hasScores,
                         hasProof, proofEpoch, proofValidator, submitted,
                         verified, copierStrategy,
                         acceptedWeights, rejectedWeights>>

------------------------------------------------------------------------
(* Next State Relation *)
------------------------------------------------------------------------
Done ==
    /\ phase = "done"
    /\ UNCHANGED vars

Next ==
    \/ ChallengePhase
    \/ \E v \in HonestValidators : HonestEvaluate(v)
    \/ \E v \in CopierValidators : CopierChooseStrategy(v)
    \/ EvaluateToProve
    \/ \E v \in HonestValidators : HonestProve(v)
    \/ \E v \in CopierValidators : CopierAttemptProof(v)
    \/ ProveToSubmit
    \/ \E v \in AllValidators : Submit(v)
    \/ SubmitToVerify
    \/ \E v \in AllValidators : Verify(v)
    \/ NextEpoch
    \/ Done

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

------------------------------------------------------------------------
(* SAFETY INVARIANTS *)
------------------------------------------------------------------------

(* INV1: Copier weights are NEVER accepted *)
(* A copier who didn't query miners cannot have accepted weights *)
CopierNeverAccepted ==
    \A v \in CopierValidators : <<v, epoch>> \notin acceptedWeights

(* INV2: Replayed proofs are rejected *)
(* Any proof with proofEpoch /= current epoch is invalid *)
ReplayAlwaysRejected ==
    \A v \in AllValidators :
        (verified[v] = "valid") => (proofEpoch[v] = epoch)

(* INV3: Shared proofs are rejected *)
(* A proof bound to validator H is invalid for validator C *)
SharedProofRejected ==
    \A v \in AllValidators :
        (verified[v] = "valid") => (proofValidator[v] = v)

(* INV4: Honest validator with proof is always accepted *)
(* If honest validator completed all steps, they must be accepted *)
HonestAlwaysAccepted ==
    \A v \in HonestValidators :
        (/\ verified[v] = "valid"
         /\ hasResponses[v]
         /\ hasProof[v]
         /\ proofEpoch[v] = epoch
         /\ proofValidator[v] = v)
        =>
        <<v, epoch>> \in acceptedWeights

(* INV5: No validator accepted without miner responses *)
(* The fundamental PoE guarantee *)
NoAcceptWithoutResponses ==
    \A v \in AllValidators :
        <<v, epoch>> \in acceptedWeights => hasResponses[v]

(* INV6: Phase ordering is always valid *)
ValidPhaseOrder ==
    phase \in {"challenge", "evaluate", "prove", "submit", "verify", "done"}

------------------------------------------------------------------------
(* LIVENESS PROPERTIES *)
------------------------------------------------------------------------

(* Every honest validator who evaluates, proves, AND submits is accepted *)
HonestEventuallyAccepted ==
    \A v \in HonestValidators :
        (submitted[v] /\ hasProof[v] /\ proofEpoch[v] = epoch /\ hasResponses[v])
        ~> (<<v, epoch>> \in acceptedWeights)

(* The protocol always terminates (reaches "done") *)
ProtocolTerminates ==
    <>(phase = "done")

========================================================================
