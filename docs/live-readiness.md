# Live one-request readiness binding

`live_readiness.py` is a pure, non-transport composition check for the final gap between
offline validation and a future one-request executor. It validates, without performing
I/O:

- an active authenticated-public G0 approval with concurrency 1;
- a passing PostgreSQL Launch Review no more than five minutes old and planned cap 1;
- an active non-secret `SessionCapability` covering the approved age ratings;
- an already-created permanent `FirstRequestClaim` bound to G0, run and canonical
  Provider/request identity;
- a live-mode Provider bound to the same G0 fingerprint; and
- a 5–120 second in-memory policy latch bound to that existing claim.

Any mismatch makes the latch terminal. The binder never calls `list_requests`, `fetch`,
or a credential supplier, and never creates or changes a database claim.

`LiveReadinessEvidence`, `RealRequestEnablementConfig`, and its consumption receipt are
not authorization capabilities. They are serializable evidence and can be reconstructed.
The future execution composition must still revalidate state, create the permanent slot
claim, mint a process-local non-serializable operator capability in the same call stack,
consume it before transport, and permanently resolve the claim after the one attempt.
