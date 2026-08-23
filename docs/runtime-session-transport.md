# Runtime Session Transport

Status: **numeric-loopback stage and offline external transport contract passed; live use disabled**

`LoopbackSessionBroker` exercises authenticated request handling without accepting a
password or contacting an external host. Its cookie supplier is called only after URL,
session-window, and timeout checks pass. The broker does not serialize the supplied
value and strips cookie/authorization/token-shaped response headers.

## Enforced boundary

- only `http://127.0.0.1:<port>` and `http://[::1]:<port>` are accepted;
- hostnames, HTTPS external URLs, URL credentials, fragments, and redirects are denied;
- every call first commits a PostgreSQL-compatible one-use permit;
- timeout/transport failures consume the permit without refund;
- HTTP 403/429 responses update the persistent circuit breaker;
- response bodies are bounded to 1 MB by default;
- tests use a synthetic cookie value and never access Pixiv.

## Evidence

The `cmd.exe` entry point `scripts/run-local-transport-smoke.cmd` passed five focused
tests and wrote `var/reports/local_transport_smoke.json`. The full suite now contains
72 passing tests.

## External HTTPS hardening

The separate exact-DNS HTTPS contract remains FakeOpener-only. Its successful path now
reads a fresh trusted time for permit authorization, session validation, the check
immediately before the injected opener, and permit settlement. Session expiry between
credential retrieval and the opener therefore blocks the call. Supplier, opener,
HTTPError, response header/body/close and settlement exceptions are converted to fixed
payload-free errors without retaining URL, query, header, payload or session text.

## Remaining live-transport gate

No Pixiv URL, endpoint mapping, or live Provider entry point exists. RuntimeSession now
owns a one-use opaque lease; Composition rejects a different equal-scope lease, and the
HTTPS broker exposes the exact lease owned by its RuntimeSession supplier. Before an
external request is possible, this broker must be reachable only through the journal-bound
coordinator and reviewed endpoint contract. A user session value must be entered locally
at runtime and must never be sent through chat or stored.
