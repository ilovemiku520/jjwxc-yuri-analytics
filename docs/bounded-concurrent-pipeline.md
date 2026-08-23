# Bounded Concurrent Pipeline

The acquisition pipeline accelerates only local work. Provider `fetch()` calls remain
serialized on the coordinator thread, so each permit-bearing request completes its
response recording and allowlist/Schema Drift checks before another request starts.

Already-minimized immutable `RawResponse` objects may be processed by 1–8 local worker
threads. Pending tasks are bounded between the worker count and 64, with a default of
twice the worker count. Results are returned in Provider request order rather than
thread completion order.

Safety properties:

- duplicate logical request keys fail before any Provider call;
- local worker exceptions are surfaced at scheduling boundaries and stop new work;
- queued local tasks are cancelled on failure when they have not started;
- acquisition concurrency is fixed at one and is reported in every `PipelineRun`;
- the pipeline performs no retries and does not itself initiate external transport.

Run `scripts\run-concurrent-pipeline-smoke.cmd` from cmd.exe. The offline evidence is
written to `var/reports/concurrent_pipeline_smoke.json`.

Before any real-source sample, persistent permits still need a per-run logical request
idempotency key and approval-level locking across UTC day boundaries. The first live
sample remains one request with a pending window of one.
