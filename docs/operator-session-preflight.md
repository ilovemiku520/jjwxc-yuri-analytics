# Operator Runtime Session Preflight

Status: **dry-run gate passed; no production session used**

`OperatorSessionFactory` reads session material only through Python's no-echo terminal
reader. There is deliberately no command-line, environment-variable, configuration-file,
database, or log input path for session material.

## Runtime behavior

- TTL is explicit and restricted to 1–60 minutes;
- values larger than 8 KiB, empty values, and CR/LF are rejected;
- the session is held in a mutable bytearray;
- closure or expiry overwrites that bytearray and prevents reuse;
- `repr()` always displays `[REDACTED]`;
- Python may create short-lived immutable copies during terminal input/UTF-8 decoding,
  so physical memory zeroization cannot be guaranteed;
- the preflight CLI is dry-run only and performs no transport.

## CLI

The installed command exposes only non-secret options:

```powershell
pyuri-session-preflight --dry-run --session-ttl-minutes 15
```

It prompts locally with input hidden, prints only expiry and safety booleans, then clears
the mutable buffer. Session material must never be pasted into chat.

## Evidence

`scripts/run-session-preflight-smoke.cmd` passed eight cases using synthetic values and
wrote `var/reports/session_preflight_smoke.json`. The full suite passed 85/85; Ruff and
strict mypy also passed.
