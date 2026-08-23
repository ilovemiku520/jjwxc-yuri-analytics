# Phase 5 tag knowledge discovery foundation

Updated: 2026-08-23

Phase 5 starts from descriptive, Fixture-only tag association evidence. It does not infer whether
a tag means Yuri, romance, BG, BL or a Yuri subcategory. Statistical association and semantic
classification remain separate review stages.

The first slice is implemented in `src/pixiv_yuri/analytics/tag_associations.py`. It accepts at
most 5,000 uniquely identified works and 64 reviewed public tags per work, deduplicates repeated
tags inside one work, and emits at most 200 deterministic edges. Every edge exposes:

- each tag's sampled work count;
- exact co-occurring work count;
- sample support in integer basis points;
- Jaccard similarity in integer basis points;
- pointwise mutual information in signed milli-bits.

The result also exposes sample size, observed tag count, eligible edge count, truncation,
minimum co-occurrence and an optional exact anchor tag. These fields prevent a bounded sample from
being presented as a complete graph. Empty samples return an explicit empty graph; duplicate work
identities, conflicting translations and unbounded inputs fail closed.

The first private API slice is now available at `GET /api/v1/analytics/tags/co-occurrence`.
It deterministically samples the latest 1,000 works by default, accepts a bounded limit up to 5,000,
supports an exact anchor tag and exposes catalog/sample truncation separately from edge truncation.
The response is private-cacheable, read-only and explicitly states
`semantic_classification_performed=false`.

Current acceptance evidence: 33 focused core/API pytest cases, Ruff and strict mypy pass. The
25-path OpenAPI contract and real PostgreSQL Docker probe also pass with synthetic Fixture
association and sensitivity evidence.
No external network, source request, embedding model, classifier, graph database, search cluster or
background worker was introduced.

The private `/tags/graph` explorer now consumes this contract. It preserves exact tag names,
exposes all sample caveats, supports bounded anchor/minimum/sample/edge controls, and pairs an
ECharts force graph with a keyboard-accessible tabular view. The private `/tags/review` page adds
a fixed-threshold curve, a complete threshold table, explicit truncation warnings and a
human-review-only candidate queue. Eleven Web unit and sixteen desktop/mobile Playwright checks
pass; Axe found no serious or critical issue, and the production Docker probe verifies all sixteen
routes.

The second offline slice is implemented in `src/pixiv_yuri/analytics/tag_sensitivity.py`. It runs
the same bounded graph over fixed minimum-co-occurrence thresholds of 1, 2, 3, 5 and 10, reports
eligible and returned edge counts, and measures each threshold's retention against the threshold-1
baseline in integer basis points. Empty baselines explicitly report zero retention rather than
claiming perfect stability. A truncated baseline or comparison is marked non-comparable.

This slice can rank at most 200 evidence records for accountable human review. Every candidate is
marked `pending_human_review`, records the thresholds it survives, and intentionally has no
semantic-label field or persistence operation. Threshold lists must start at 1, be unique and
strictly increasing, contain no more than eight values, and stay within the existing 5,000-work
bound. Automated labeling remains separately gated.

The same evidence is available through the private, GET-only
`/api/v1/analytics/tags/association-sensitivity` endpoint. Its thresholds are fixed rather than
caller-defined so reports remain comparable. Only `anchor_tag`, `candidate_limit` and
`sample_work_limit` are exposed as bounded query controls. The response is private-cacheable and
retains the explicit `semantic_classification_performed=false` contract.

Manual follow-up decisions use the offline `pyuri-tag-review` validator implemented in
`src/pixiv_yuri/analytics/tag_review.py`. Each finalized artifact records a bounded reviewer ID,
human-review role, timezone-aware creation/review times, one enumerated triage decision and a
required rationale. Its SHA-256 candidate fingerprint binds the exact tag pair, sampled work count,
fixed thresholds, metrics, truncation state and stability-comparability state.

The validator rejects stale fingerprints, future or reversed times, placeholders, extra fields,
secret-shaped rationale, scope-expanding booleans and attempts to retain truncated or
non-comparable evidence. The three available decisions only control offline follow-up:
`retain_for_followup`, `defer_insufficient_evidence` and `dismiss_statistical_artifact`. None is a
Yuri or other semantic label. The example at `config/tag_review_decision.fixture.json` is synthetic
and grants no source access or publication authority.

Phase 5 completion is determined by `src/pixiv_yuri/analytics/phase5_review.py`. The aggregate
review revalidates the canonical synthetic decision artifact instead of trusting its report,
cross-binds its candidate fingerprint to the core discovery evidence, verifies the shared OpenAPI
hash across Phase 2 and Phase 5, checks evidence timestamps, and requires the API, Web, Docker and
accessibility reports to preserve every private Fixture-only boundary. A pass explicitly defers
real collection, publication, embeddings, automated classification and additional data stores.
