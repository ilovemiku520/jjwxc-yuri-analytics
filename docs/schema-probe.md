# Offline Schema Probe Design

## Inputs

A strict manifest references local `.json` payloads. Paths are resolved relative to the manifest and cannot escape it. Each observation has an aware timestamp, entity type and synthetic source ID.

## Fingerprint

The SHA-256 schema fingerprint is computed from a canonical descriptor containing only:

- JSON object field names;
- JSON value types;
- nested object structure;
- unique array element structures.

Object key order, array item order and scalar values do not affect the fingerprint. Changing a value type or field structure does.

## Aggregate report

For each entity type, the report records:

- sample count;
- field JSON path;
- observed type set;
- sample availability;
- required/nullable inference;
- simple stability band;
- payload hash and per-sample schema fingerprint.

Examples are disabled by default. If explicitly enabled, values are truncated and keys shaped like credentials are redacted. Raw payloads are never embedded in the report.

## Diff

The diff reports fields added/removed, type changes, requiredness changes and material availability changes. Removal of a required field and any type change are high severity. The CLI returns status `3` when high-severity changes exist, allowing a future CI gate.

## Limitations

- A field absent from a small fixture set may still exist in the source.
- Empty arrays do not reveal an element schema.
- Availability describes only the fixture cohort, not the platform population.
- Inferred requiredness is evidence for review, not an automatic database `NOT NULL` decision.

