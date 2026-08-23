# Live one-request composition root

`run_live_one_request_composition` is an offline-tested, dependency-injected core for a
future single live metadata request. It is deliberately not exposed through a CLI or API.

The enforced order is:

1. validate G0, a fresh one-request Launch Review, SessionCapability and Provider binding;
2. show an explicit LIVE prompt and mint a process-local operator capability;
3. permanently claim the approval's first-request slot;
4. consume the short-lived readiness latch;
5. mint a second private, non-serializable capability bound to Provider/request/claim;
6. consume both capabilities before the Provider can be called;
7. mark the slot completed only for a matching 2xx response; otherwise mark it failed.

The Provider remains responsible for reserving and settling its transport permit; the
composition never reserves a second permit. Results contain no body, headers, URL,
credential, readiness receipt or capability. Because application code cannot prove that
a socket send occurred, results use `source_transport_attempted` and leave
`network_send_confirmed=None`.

The Composition now requires a canonical endpoint-aware request binding for its permanent
slot and exact object identity for the RuntimeSessionLease owned by the Provider stack.
Equal public session fields with a different lease are rejected before confirmation.

The current module is not production-reachable. An internal journal-bound attempt
coordinator proves atomic permit/send-intent/settlement ordering with an injected fake
sender; see `journal-bound-live-attempt.md`. It is not yet the only route from this
Composition to the HTTPS broker. Before enabling any entry point, Provider execution must
be split into plan/send/parse stages and direct `Provider.fetch` bypass must be removed.
