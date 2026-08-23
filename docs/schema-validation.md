# Fixture Schema Policy and Parser Gate

This increment closes the offline path between structural discovery and parsing:

```text
FixtureProvider
  -> payload hash and schema fingerprint
  -> exact offline_fixture policy decision
  -> exact parser ID/version lookup
  -> transient parser envelope
  -> valid status

unknown / rejected / missing parser / parser error
  -> quarantined status and review record
```

## Fail-closed rules

- Policy provider must exactly match the provider contract.
- Policy keys are `(entity_type, schema_fingerprint)`; no wildcard or closest-match
  fallback exists.
- Approved entries require an exact parser ID and version.
- Rejected entries cannot name a parser.
- Duplicate policy keys and unknown policy fields are rejected at load time.
- Parser output fingerprint must equal the fingerprint checked by the gate.
- Validation reports contain identifiers, hashes, decisions, and provenance—not raw
  payload fields or values.

The runtime contract is represented both by strict Pydantic models and
`contracts/jsonschema/schema-policy.schema.json`.

## Fixture-only parser

`fixture_object@0.1.0` accepts JSON objects and returns a transient envelope for
contract regression. It does not normalize works, authors, tags, or metrics and its
document is not persisted. Production parsers remain blocked until representative
authorized samples and G1 field approval exist.

## Commands

Generate a standalone validation report:

```powershell
pyuri-schema-probe validate `
  --manifest fixtures/manifest.json `
  --policy fixtures/schema_policy.json `
  --output var/reports
```

The command exits `0` when all records are valid and `4` when any record is
quarantined. It writes `schema_validation.json` and `schema_validation.md`.

Persist the same decision and parser provenance into the ingest ledger:

```powershell
pyuri-db ingest-fixtures `
  --manifest fixtures/manifest.json `
  --schema-policy fixtures/schema_policy.json
```

Without `--schema-policy`, fixture observations remain `pending`; this preserves the
previous discovery-only workflow.

## Approval boundary

The checked-in policy approves only synthetic regression fixtures under the literal
scope `offline_fixture`. It is not G0 source authorization, G1 production Schema
approval, or permission to write normalized `core` tables.
