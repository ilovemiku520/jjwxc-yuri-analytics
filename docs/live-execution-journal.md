# Live execution journal

Migration `20260822_0005` adds one durable journal per permanent first-request slot. It
associates the approval, run, slot, request binding and transport permit without storing
the source URL or payload.

The journal state is monotonic:

```text
claimed -> send_started -> settled -> completed
   |             |             |
   +-> failed    +-> indeterminate
                              +-> failed
```

Recovery never retries. A restart while `claimed` becomes `failed`; a restart after
`send_started` but before known settlement becomes `indeterminate`; a restart after
settlement becomes terminal `failed` pending reconciliation. Completed, failed and
indeterminate rows can never return to a sendable state.

This migration provides the persistence foundation only. The current live composition
does not yet bind the transport's permit and send-start marker to this journal, so no live
entry point is enabled.
