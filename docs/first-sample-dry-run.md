# First-Sample Dry Run

The offline rehearsal binds the complete first-sample control path without enabling a
host network opener:

1. the Provider must contain exactly one immutable request and match the active G0;
2. an operator confirms a short-lived challenge in the same process;
3. a non-serializable capability is atomically consumed once;
4. PostgreSQL permanently claims one first-request slot per approval fingerprint;
5. a fake HTTPS opener exercises the exact-host transport and persistent permit;
6. the Provider synchronously applies the G0 field allowlist and Schema Drift stop.

The slot ends as `completed` or `failed` and is never automatically released. A crash
leaves it `claimed`, which blocks another first attempt until an operator reviews the
state. Current orchestration rejects a Provider backed by a real network opener before
showing the confirmation prompt.

Run `scripts\run-first-sample-dry-run-smoke.cmd`. Evidence is written to
`var/reports/first_sample_dry_run.json`.
