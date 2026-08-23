# Phase 4 author analytics foundation

Updated: 2026-08-23

Phase 4 starts with one bounded read-only author profile derived from the existing normalized
catalog. It does not add a database, background job, source request or materialized score.

`GET /api/v1/analytics/authors/{author_id}/profile` returns reviewed author identity, work and
page counts, first/latest work timestamps, optional public metric totals, per-metric coverage,
and at most ten public tags ordered by work count and stable tag name. Tag affinity is descriptive
co-occurrence only; it is not a Yuri classification.

`GET /api/v1/analytics/authors/{author_id}/metric-trends` returns at most 366 inclusive days.
For each work/day it selects the latest immutable snapshot before aggregating totals. Every metric
has a separate coverage count, and a total remains `null` when no work supplied that metric. The
endpoint deliberately does not label cross-day total changes as growth because the observed work
cohort can differ between days.

`GET /api/v1/analytics/authors/{author_id}/growth` compares two distinct endpoint days. It reports
start-only, end-only and matched work counts, then calculates each metric only from matched works
where that metric exists at both endpoints. Absolute changes and signed basis-point growth remain
`null` when no complete matched work exists; a zero starting total permits an absolute change but
not a percentage growth value.

Views missing from every Fixture work remain `null`, not zero. Bookmark/view and like/view rates
are emitted in integer basis points only when every analyzed work contains both required metrics
and total views are positive. This prevents partial data from producing a misleading rate.

Run the offline acceptance gate with:

```powershell
scripts\run-phase4-author-analytics.cmd
```

The gate runs twenty-eight focused API tests, regenerates the canonical 24-GET OpenAPI contract, verifies
that no mutation or prohibited field appears, and asserts that external publication, real-source
authorization, source count and external network use all remain disabled.

The private author page now consumes all three endpoints independently. A profile failure leaves
the reviewed catalog usable, while a trend or growth failure affects only that panel. The page
shows per-metric coverage, complete-data-only rates, stable tag affinities, nullable trend points,
and start-only/end-only/matched cohort membership next to signed growth values.

`GET /api/v1/rankings/authors` additionally accepts `works`, `average_likes` and
`average_bookmarks`. Average rankings divide only by works carrying that metric, expose the exact
coverage count, use deterministic integer centi-unit scores and keep every cursor bound to its
metric namespace. Authors with no observation for the requested metric are excluded instead of
being assigned a false zero.

`GET /api/v1/analytics/authors/quality-map` returns at most 200 authors with a complete bookmark
axis. It plots work count against average bookmarks, exposes optional observed-like totals for
bubble size and classifies four quadrants against medians calculated from the returned sample.
The response says whether that sample was truncated; the labels are descriptive, not quality facts.

`GET /api/v1/analytics/authors/influence-ranking` implements the versioned
`allowed-metadata-v1` model. Its default weights are 43.75% average bookmarks, 37.5% average likes
and 18.75% production volume; callers may change the three bounded integer weights only when they
still total exactly 10,000 basis points. Only authors whose works have complete bookmark and like
coverage participate. Every normalized component, effective weights, sample size and truncation
decision remains visible, so the score is an inspectable sample-relative index rather than a fact.

`fixtures/analytics/author_influence.json` is a dedicated four-author aggregate Fixture spanning
core, boutique, volume and ordinary quadrants. It contains only synthetic approved-field
derivatives and is intentionally separate from the acquisition manifest.

Run its local Web acceptance gate with:

```powershell
scripts\run-phase4-author-web.cmd
```

This gate runs ten Vitest checks, strict TypeScript, ESLint, a production Next.js build and twelve
Playwright checks across desktop and mobile projects. The browser suite includes six metric-bound
author rankings, the author page, safe API failure behavior and Axe WCAG checks, and uses only a
process-owned loopback mock API.

Run the non-promotional Phase 4 checkpoint with:

```powershell
scripts\run-phase4-exit-review.cmd
```

It cross-checks the API, Web, OpenAPI, Phase 2 and Phase 3 evidence hashes and safety decisions.
The current result is `passed_private_fixture_only` at 100%. The influence model, multi-author
Fixture, full Python regression, production build, desktop/mobile browser evidence and fresh
25-path Docker API/Web evidence all pass. Real-source collection and external publication remain
separately disabled.

The Docker gate also exposed a PostgreSQL-only date comparison defect in stable-cohort growth:
the query compared a SQL `DATE` expression with an ISO string. The comparison now binds Python
`date` values, and both the 14-case focused suite and PostgreSQL container probe pass.

During development, repeated broad checks were deferred and recorded in
`var/reports/phase4_validation_deferred.json`. That deferral has now been superseded by one
consolidated run: 426 Python tests, Ruff, strict mypy, ten Web unit tests, typecheck, ESLint,
production build and twelve Playwright desktop/mobile checks pass.
