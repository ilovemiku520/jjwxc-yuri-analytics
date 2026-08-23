# Offline Foundation Boundary

## Allowed

- Read synthetic or separately approved local UTF-8 JSON fixtures.
- Calculate payload hashes and structure-only schema fingerprints.
- Generate local JSON/Markdown reports and diffs.
- Apply exact fixture-only schema decisions and route approved structures to a
  generic offline parser contract.
- Create the PostgreSQL ingest ledger and persist synthetic/approved fixture metadata.
- Store hashes, schema descriptors, task attempts and quarantine records; raw payload bytes remain outside PostgreSQL.
- Run unit, contract and CLI tests without network access.
- Build an offline schema-probe container with `network_mode: none`.
- Run fixture ingestion against PostgreSQL on an internal-only Compose network.
- Simulate authenticated-public and age-rating authorization with non-secret session
  capabilities and local fixtures only.

## Not allowed in this phase

- Pixiv HTTP requests, real login, cookies or browser automation.
- Bright Data CLI, SDK, proxy, Unlocker or Browser API calls.
- Storing or displaying Pixiv images.
- Real-source database ingestion, public API, web application or tag classification.
- Turning fixture fields into a final production database schema without G1 review.
- Treating `offline_fixture` policy approval as authorization for a live Provider or
  as approval of production catalog fields.

## G0 evidence needed before a live provider

1. Approved purpose and responsible owner.
2. Current target-platform terms, robots directives and applicable-law review.
3. Allowed page/content scope and authentication boundary.
4. Field minimization, retention, deletion and publication decisions.
5. Request, concurrency, traffic and monetary limits.
6. Stop conditions and incident contact.
