# Live One-Request Offline Preflight

Run `scripts\run-live-one-request-preflight-smoke.cmd` before considering the separate
operator-authorized live step. The command composes two existing, non-source checks:

1. the read-only PostgreSQL launch review; and
2. the first-sample dry run backed by an injected fake HTTPS opener.

It forces `PYURI_ENABLE_NETWORK=false`, requires exactly one planned dry-run request,
executes Launch Review with `planned_request_cap=1`, checks that no active permit or
permanent first-request slot exists, and rejects any
component report that indicates external network use. It does not prompt for or read a
source credential and does not contact Pixiv.

The safe aggregate report is written to
`var/reports/live_one_request_preflight.json`. A passing smoke result establishes only
offline readiness. It is a non-atomic point-in-time report: it can become stale or be
edited, so `authorizes_live_request=false` and `atomic_execution_gate=false` are always
reported. A real execution path must revalidate G0 and the runtime session, claim the
PostgreSQL first-request slot, and consume a non-serializable operator capability in one
process immediately before transport.

`source_transport_used=false` and `pixiv_contacted=false` refer only to the source-data
transport. Docker build, registry, or package-index traffic is not measured by this
smoke and is reported separately as `infrastructure_network_activity="not_measured"`.
The report says `source_credentials_requested=false`; it does not claim to prove that
arbitrary inherited process environment was unreadable.
