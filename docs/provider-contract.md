# Pinned Metadata Provider Contract

Status: **local contract gate passed; external source disabled**

`PinnedMetadataProvider` validates the next acquisition boundary without contacting
Pixiv. It owns a deterministic request set, builds paths only below one exact numeric
loopback origin, requires a persistent permit, and applies the G0 field policy before a
payload can become a `RawResponse`.

## Data rules

- only the 14 fields in the executable G0 allowlist may pass;
- unknown top-level fields stop the run as Schema Drift;
- password/cookie/authorization/secret/token-shaped keys reject the whole payload;
- work, author, and tag payloads must contain their approved identity field;
- nested objects are rejected until G1 approves a structure;
- non-2xx response bodies are discarded and replaced with `{}`;
- exceptions contain only non-secret reason codes, never rejected keys or values.

## Verification

The first run detected and fixed a package-level circular import. A later full-suite
run correctly detected that the synthetic test approval still had the obsolete
three-field allowlist; the synthetic approval was updated to the same 14-field contract
as the executable G0 record.

After those fixes:

- five Provider contract tests passed through `cmd.exe`;
- the full suite passed 77/77;
- Ruff and strict mypy passed;
- `var/reports/provider_contract_smoke.json` records zero external network use.

No real endpoint, production session input, or Pixiv request exists in this stage.
