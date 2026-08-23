# Journal-bound live attempt

`JournalBoundLiveAttemptCoordinator` is an internal, dependency-injected proof of the
durable ordering required before one external send. It is not exported from the package,
registered in a CLI/API, or connected to an actual network client.

The enforced lifecycle is:

```text
existing permanent claim
  -> journal claimed
  -> persistent permit authorized
  -> journal send_started committed
  -> injected one-shot sender
  -> permit consumed / transport_failed
  -> journal settled
  -> completed / failed / indeterminate
```

The injected sender receives only the journal identifier, permit identifier, request
binding hash and send-start timestamp. Tests inspect the database at the call boundary to
prove that `send_started` and the authorized matching permit are already durable. A send
exception, invalid response status, permit-settlement uncertainty or journal-settlement
uncertainty becomes terminal `indeterminate`; a second execution is rejected.

Permit reservation, run/daily budget updates, and `send_started` now share one database
transaction. A marker-binding or constraint failure rolls the permit and every counter
back before the sender can receive a context. PostgreSQL integration verified committed
`send_started` and deliberately recovered the no-send rehearsal as conservative
`indeterminate`, with no source network use.

This remains an internal ordering proof, not production authorization. The next gate is
to split the live Provider into plan/send/parse stages and make this coordinator the only
route to the HTTPS broker; the current Composition still invokes `Provider.fetch` directly.
