# Project Status

Updated: 2026-08-24

## Current source pivot — JJWXC yuri novels

The active product direction changed on 2026-08-23 from Pixiv illustration metadata to
JJWXC yuri novel and author analytics. The existing safety, ingest-ledger, read-only API,
PostgreSQL, Docker, and Next.js foundations are retained as migration infrastructure;
Pixiv-specific acquisition is now legacy and is not part of the active product path.

|JJWXC scope|Estimated completion|Status|
|-|-:|-|
|Public-page feasibility and field review|100%|Four unauthenticated endpoints tested; terms and robots recorded|
|JJWXC models, parser and bounded collector|99%|Ranking, work detail, chapter clicks and author-profile aggregates are implemented with bounded cache-aware collection|
|JJWXC read API|100%|Database-backed catalog, date-bounded timeline, log-standardized correlation, custom work cohorts, search and separate work/author rating endpoints implemented|
|Interactive JJWXC website|100%|Search-first index, CSV/TSV/TXT cohort import with failure reports, total/per-work timelines, n>=30 adjustable Pearson/Spearman comparison, ratings and radar charts implemented|
|Canonical PostgreSQL snapshots|97%|Migration 0014 deployed; real and synthetic sources are isolated; 59 real work snapshots and 10 real author profiles are stored|
|Scheduled cloud collection|95%|Private daily job is active at Asia/Shanghai 03:30; first cloud sample passed and second-day evidence remains|
|Public cloud release|100%|Public Web, private API/PostgreSQL, daily collection, backup, volumes and GitHub automatic deployment are live|
|New JJWXC roadmap overall|Approximately 98%|Cloud product landing is complete; historical depth will grow through daily backfill and authorized V-click data remains optional|

Current JJWXC API evidence is exported separately at `contracts/openapi-jjwxc-v1.json` and
`var/reports/jjwxc_openapi_contract.json`: the historical review covered 36 GET-only paths and no
prohibited response field. The new private cohort-import mutation only validates and queues bounded
novel IDs; it does not return source payloads or credentials.
The earlier 25-path Phase 2/5 reports remain immutable historical evidence rather than being
silently overwritten after the source pivot.

Docker PostgreSQL is now at migration `20260824_0014`. It contains separate minimized
`jjwxc_authors`, `jjwxc_novels`, append-only `jjwxc_novel_snapshots`, and immutable
`jjwxc_author_snapshots` tables. The store is
idempotent by minimized-candidate SHA-256 and rejects conflicting values for the same novel/time;
no synopsis text, source URL, HTML, chapter, comment, or credential column exists.
The database also has `jjwxc_ranking_snapshots`, unique by ranking/day/novel and ranking/day/position.
The first bounded real run stored 200 ranking rows from one public ranking request and hydrated the
top 10 public novel summaries. API projections exclude all synthetic Fixture rows whenever real
`public_candidate` snapshots exist, so demonstration and real observations cannot be blended.

The canonical database contains 64 real novel records across observation days; the deployed website's
latest-day analysis cohort currently contains 56 detailed real novels.
Ten authors have real public profile aggregates covering nonlocked works, author
favorites, observed-work favorites, nonlocked-work words and nonlocked-work points. Locked works
are excluded from the author work/word/point totals. Incomplete profiles are labeled with their
coverage and receive a matching score penalty rather than being treated as complete. The rating is
explicitly cohort-relative public-data performance, not literary quality.

Cross-sectional correlation now applies `log(1+x)` to nonnegative count variables, explicitly
Z-standardizes each pair and calculates pairwise-complete Pearson coefficients. The website exposes
the method, sample size and a blue-to-red signed scale; raw V-chapter clicks are excluded from this
matrix, while the derived V/non-V click-retention proxy is included only for pairwise-complete works.
The proxy is `average V chapter clicks / average non-V chapter clicks`, is not capped at 100%, and is
explicitly not labeled as unique-reader retention. The adjustable comparison only displays
coefficients with
at least 30 pairwise-complete observations and supplements Pearson with Spearman rank correlation,
first and second central moments, covariance and an approximate Fisher-z 95% interval while stating
that this floor is not a significance guarantee. Timeline totals
can also be converted to per-observed-work means without double-dividing chapter-click averages.
The current 56-work analysis cohort covers 49 novels for non-V clicks and zero for V clicks. For novel
7630015 specifically, all 12 non-V chapter clicks are visible and all 68 V chapter clicks are missing,
so its visible-click chapter coverage is 12/80 (15%). Missing V chapters remain in the coverage
denominator but are never filled with zero and do not alter the non-V mean. The parser preserves
V-click values found
inline in an authenticated page instead of overwriting them with missing public-response values; the
UI reports the exact V-click and retention-proxy coverage rather than implying that absent values are zero.

The former 98% figure below describes the completed Pixiv-oriented baseline, not the new
JJWXC product roadmap.

## Collaboration handoff

On 2026-08-23, the shared Codex chat snapshot was reviewed for a same-device
collaboration handoff. Its last visible implementation checkpoint is Phase 4 complete
and Phase 5 started (about 90% overall). This workspace contains newer, locally
verifiable artifacts after that snapshot: Phase 5 is complete, Phase 6 preparation is
at 60%, and the roadmap is approximately 98% complete. The newer workspace state
is therefore the active baseline; no completed work was downgraded or inferred solely
from chat text.

## Progress

|Scope|Estimated completion|Status|
|-|-:|-|
|Phase 0 — offline engineering foundation|100%|Complete|
|Phase 1 — approved acquisition MVP|99.5%|Final offline plan/send/settle/parse chain passed; live remains gated|
|Phase 2 — read-only data API|100%|Private-boundary exit review passed; publication remains separate|
|Phase 3 — private web interface|92%|Offline security and deployment-evidence gates pass; accountable production deployment remains|
|Phase 4 — author analytics|100%|Private Fixture-only exit review passed|
|Phase 5 — tag knowledge discovery|100%|Aggregate private Fixture-only exit review passed|
|Phase 6 — production deployment|60%|Local controls and production-evidence tooling pass; actual identity/TLS review and publication approval remain|
|Overall roadmap|Approximately 98%|Phases 0, 2, 4 and 5 are complete; no-password OAuth candidate acquisition is implemented while its first real one-page run, canonical ingest and production publication remain gated|

The legacy percentage is milestone-weighted, not a line-count estimate. Pixiv G0 is validated but
its direct source collection remains at zero. The active JJWXC roadmap above has a separately
bounded real public-metadata sample and does not inherit Pixiv acquisition authorization.

## Completed

- Python project, typed Provider contract, FixtureProvider, configuration and logging;
- deterministic offline Schema Probe, reports, diffs and CLI;
- PostgreSQL ingest-ledger SQLAlchemy models and Alembic migration;
- transactional/idempotent fixture ingestion and quarantine behavior;
- fixture-only Schema Policy, exact Parser routing and validation reports;
- 609 automated tests, Ruff, strict mypy across 122 source modules and offline migration SQL generation;
- Docker Compose definitions for internal-only PostgreSQL migration and fixture ingest;
- successful real PostgreSQL migration and Fixture ingest integration;
- minimal FastAPI liveness/readiness contract and loopback-only Compose service;
- validated request ID propagation into response headers and structured logs;
- updated CI gates and a one-command Phase 0 demonstration runner;
- machine-verifiable, expiring G0 approval contract, draft template, CLI and tests;
- transport-independent request permits, budget enforcement and circuit breakers;
- G0 v2 authenticated-public and all-ages/R-18/R-18G scope controls;
- credential-free session capabilities and an authenticated fixture-only Provider;
- PostgreSQL daily/run budget, one-use permit, and append-only stop-event models plus
  Alembic revisions through `20260823_0009`;
- validated local G0 v2 record with 14 allowed metadata fields and bounded authenticated scope;
- transaction-owning persistent permit reserve/consume service with rate, request,
  daily/monthly cost, concurrency and 403/429 circuit-breaker enforcement;
- PostgreSQL 17 migration and two-worker row-lock contention passed with one permit,
  one deferral, and no external network use;
- numeric-loopback authenticated transport passed via cmd.exe with synthetic session,
  redirect/external-host blocking, response redaction, timeout accounting and 403 stop;
- pinned Provider contract passed via cmd.exe with the exact 14-field allowlist,
  sensitive-field isolation, non-success body discard, and Schema Drift persistence;
- no-echo runtime session preflight passed via cmd.exe with TTL enforcement,
  best-effort mutable-buffer clearing, safe output and no secret CLI option;
- read-only launch review passed against PostgreSQL with current migration, active G0,
  25-request ceiling, zero active permits and zero stopped runs;
- bounded two-stage pipeline passed with one serialized acquisition lane, three-way
  verified local processing, deterministic output, duplicate rejection and backpressure;
- persistent permit request-key hashes and per-run unique constraints reject retries
  without storing request identifiers or consuming additional budget;
- approval-fingerprint PostgreSQL advisory locking passed two-run contention across a
  UTC day boundary with one authorization, one deferral, and no external network;
- external HTTPS transport contract passed with exact host pins, runtime-only
  credentials, redirect blocking, bounded bodies, response redaction and durable permits;
- external HTTPS authorization, session validation, immediate pre-send validation and
  settlement now use separate fresh clock reads; hostile transport/HTTP/response/settlement
  exceptions are reduced to fixed payload-free errors;
- one-use, short-TTL operator confirmation gate passed for exactly one planned request;
- ordered database pipeline passed with parallel local preparation, coordinator-only
  Session ownership, deterministic commits, and atomic rollback on commit failure;
- process-local non-serializable one-request capability passed forgery, reuse and
  two-thread consumption tests with exactly one Provider fetch;
- approval-scoped permanent first-request slot passed offline lifecycle tests and
  blocks retries across runs after completed or failed attempts;
- FakeOpener end-to-end first-sample rehearsal passed with one permit, synchronous
  field minimization, Schema Drift stop, and no external network;
- explicit real-request policy latch defaults disabled, burns on early/invalid/mismatched
  consumption, and is documented as readiness evidence rather than authorization;
- live-readiness binder passed G0, fresh one-request Launch Review, runtime capability,
  existing durable claim, provider/request identity and short-TTL binding tests without fetch;
- one-command live-one-request offline preflight passed with reviewed request cap 1,
  `authorizes_live_request=false`, no credentials requested and no Pixiv contact;
- final same-process one-request composition passed explicit LIVE confirmation, durable
  first-slot claiming, dual opaque capabilities and fail-closed exception tests;
- non-2xx Provider responses now permanently fail the first slot without retry, including
  tested 403 and 429 cases;
- exact HTTPS source-endpoint review contract rejects redirects, query strings, media,
  unapproved fields/ratings and contracts that outlive G0;
- append-only live execution journal and migration `20260822_0005` passed lifecycle and
  recovery tests; ambiguous `send_started` recovery becomes `indeterminate` and never resends;
- internal journal-bound attempt coordinator now proves that a matching permit and durable
  `send_started` marker exist before an injected one-shot sender can run; uncertain outcomes
  become `indeterminate` and a second execution is rejected;
- the HTTPS Provider is split into a network-free immutable request plan and a settled-response
  allowlist parser; its legacy `fetch()` rejects a real default network transport;
- a durable-marker sender rechecks slot, run budget, permit, journal, approval, canonical hash,
  send timestamp and exact RuntimeSession lease under database locks before one bounded send;
- the final internal Provider executor now composes canonical plan, atomic permit/send intent,
  durable one-shot sender, permit/journal settlement and minimized parsing; Schema Drift persists
  a run stop, fails the journal and never retries;
- the operator-facing composition no longer calls `provider.fetch()` directly and instead
  requires an injected journal-bound executor after consuming both opaque capabilities;
- an idempotent restart reconciler now maps every unfinished or terminal journal to a
  permanent slot terminal state without importing or invoking any sender;
- the PostgreSQL smoke now covers claimed, send-started, settled and completed crash
  boundaries; uncertain authorized permits are conservatively consumed and no case resends;
- a read-only `live-attempt-report` CLI emits bounded payload-free unresolved-attempt and
  orphan-slot evidence; the latest PostgreSQL report contains zero unresolved records;
- an official-source endpoint review was recorded and correctly remained blocked because
  no supported exact metadata schema was established without contacting a work endpoint;
- on 2026-08-23 the accountable owner authorized network use for a one-sample trial. A bounded
  official-source revalidation used no login session and contacted no work page/detail endpoint.
  Pixiv's official engineering material confirms API rate limiting, session restrictions and
  acquisition monitoring, but no supported public metadata contract was found; a third-party
  reverse-engineered Cookie-based interface was rejected. The saved network-research report keeps
  source collection blocked and records that no observation or media was collected;
- abrupt `os._exit` subprocess tests now crash after claimed, send-started, settled and
  completed commits, then recover in a new Python process without loading any sender module;
- endpoint evidence is now executable: only an accountable-owner review with an exact origin,
  fixed path, current terms reference, representative JSON field set, bounded size and
  payload-free schema SHA-256 can finalize a still-non-authorizing reviewed contract;
- Phase 2 now provides PostgreSQL-backed source-record, Schema summary and observation-history
  reads with versioned checksum-verified opaque cursors and minimized response models;
- deterministic private ETags support conditional `304` reads, while public caching is disabled;
- Docker API verification passed liveness, readiness, two-record source/Schema pages and a
  one-record observation page with no mutation routes, prohibited fields or collection network;
- the consumer-auth boundary explicitly blocks non-loopback publication until a real trusted
  identity proxy and production certificate chain are deployed and reviewed;
- the API CLI now rejects LAN, public and hostname bindings; wildcard binding requires the
  exact private-container deployment scope, and health/error responses default to no-store;
- normalized author, work, tag and work-tag tables retain only reviewed metadata and bind
  every author/work projection to an exact validated immutable observation;
- offline Fixture projection is transactional and idempotent: PostgreSQL verified 1 author,
  2 works, 2 tags and 3 ordered links after replay without storing unreviewed fields;
- work search supports literal title, author and tag filters with opaque pagination; tag and
  author aggregates expose counts and reviewed public metric sums only;
- immutable work metric snapshots are unique per validated observation and remain idempotent
  across Fixture replay; PostgreSQL verified exactly two snapshots for two work observations;
- metric history enforces timezone-aware bounds, daily trends use each work/day's last sample,
  and range width is capped at 366 inclusive days;
- freshness reports only the latest metric observation and bounded catalog row counts;
- work, author and tag details expose reviewed metadata/aggregates only; five PostgreSQL
  identity/ranking indexes support their bounded access paths;
- work and author rankings use metric-bound composite cursors, deterministic score/key order,
  and reject cursor reuse across endpoints or metrics;
- a provider-neutral consumer authorization seam enforces `analytics:read` with fixed
  payload-free 401/403/503 responses when injected; no identity adapter is enabled by default;
- OpenAPI regression proves the `/api` surface is GET-only and omits storage/provenance and
  credential-shaped response fields;
- every API response now carries a bounded Server-Timing value and query-budget result;
  observers receive route templates only, without path values or query parameters;
- a thread-safe bounded single-process consumer limiter and provider-neutral shared-backend
  seam enforce fixed 429/503 outcomes; minimized audit events hash consumer subjects;
- migration `20260823_0009` adds PostgreSQL fixed-window counters and append-only minimized
  access audits with explicit retention deadlines and bounded expired-row deletion;
- an eight-worker PostgreSQL contention smoke passed with exactly three allowed, five denied,
  a persisted count of three, eight audit events, one expired event purged and no raw identity;
- canonical OpenAPI v1 export now covers twenty-five GET operations and SHA-256
  `1d40ea77ba9fd98bfcd2b1f894a04e22e22c16b7b342d8fb18c3a08ea7ac733a`;
- the executable Phase 2 exit review passed for loopback/private-container deployment while
  explicitly keeping external publication unapproved and real-source collection at zero;
- Phase 3 now has a pinned pnpm workspace with Next.js 16, React 19, TypeScript, Tailwind,
  ECharts and a private-origin-only server API client;
- the responsive dashboard renders catalog scale, freshness, a bounded work ranking, a
  seven-day trend chart and a safe API-unavailable state;
- private work, author and tag lists/details support minimized navigation, literal filters
  and opaque cursor pagination without exposing the internal API origin;
- the Web container is non-root, serves seventeen routes through a private Compose API
  dependency, and passed Fixture rendering, security-header and prohibited-field checks;
- minimized GET-only run, task and quarantine summaries omit configurations, requesters,
  targets, source identities, free text and attempt linkage;
- the private operations console provides Schema, run, task and quarantine views with
  bounded filters, opaque pagination and keyboard-focusable responsive tables;
- an aggregate-only consumer security API/page reports shared backend, audit sink, retention
  and publication decision without exposing consumer digests, request IDs or route records;
- unit and container probes verify default-deny CORS: untrusted-origin GET responses receive
  no grant and preflight receives `405`, leaving no browser cross-origin access path;
- a default-disabled trusted-HMAC-proxy adapter verifies pinned proxy ID, method, path,
  subject, sorted scopes and a short-lived timestamp with fixed 401/403 failure bodies;
- its real-container smoke passed valid, unsigned, wrong-scope, expired and tampered cases;
  six durable events retained only three subject digests, with no raw subject or secret output;
- Uvicorn now accepts only a complete pair of distinct absolute TLS files; a one-day local
  certificate smoke negotiated TLS 1.3/AES-256-GCM, returned HTTPS 200 and rejected plaintext;
- both smoke runners delete their temporary secret/private-key files after verification;
- a versioned publication manifest rejects unknown/secret-shaped fields and requires exact
  proxy isolation, secret rotation, production DNS/certificate lifecycle, monitoring and approval;
- a non-secret evidence CLI now exports the pinned manifest JSON Schema and initializes a fresh
  draft without overwriting operator files by default;
- its one-command evidence bundle records Schema/draft SHA-256 values, rejects forbidden
  credential-shaped properties and proves that a generated draft remains fail-closed;
- the committed draft publication review correctly reports 16 unresolved deployment controls,
  `external_publication_approved=false` and `real_source_collection_authorized=false`;
- a consolidated Phase 3 security review verifies identity, TLS, CORS, shared controls and
  temporary-secret cleanup plus the versioned evidence bundle while requiring publication to
  remain blocked;
- Phase 4 now exposes one read-only author analytics profile with work/page totals, explicit
  metric coverage, complete-data-only engagement rates and ten stable top-tag affinities;
- author metric trends select each work/day's last immutable snapshot over at most 366 inclusive
  days, preserve per-metric coverage and do not mislabel changing cohorts as growth;
- stable-cohort growth reports start-only, end-only and matched work counts, and calculates each
  metric only where the same work has complete endpoint values;
- its offline gate verifies twenty-eight focused API cases, the 24-GET OpenAPI contract and continued zero
  source/network use without adding a database or background service;
- the responsive author detail page now renders explicit metric coverage, complete-data-only rates,
  top-tag affinities, nullable trends and stable-cohort growth with separate membership counts;
- each author analytics request degrades independently, so unavailable analysis never triggers an
  external fallback and does not hide the reviewed base catalog;
- the author index now switches between total likes, bookmarks and views through the existing
  metric-bound ranking cursor contract without mixing pagination state;
- author rankings now also cover work count, average likes and average bookmarks; averages use only
  works carrying that metric, return their coverage count and use integer centi-unit scores;
- a bounded quality map plots work count against complete-data average bookmarks with observed total
  likes as bubble size; its four quadrant thresholds are explicit medians of the returned sample;
- the Phase 4 checkpoint cross-validates API, Web, OpenAPI and Phase 2/3 evidence, reports the
  private slice ready, and keeps final exit blocked on three named remaining items;
- a dedicated four-author aggregate Fixture spans all quality quadrants without changing the
  acquisition manifest or introducing any unapproved source field;
- the configurable `allowed-metadata-v1` influence model uses complete average bookmark/like
  metrics plus production volume, exposes all normalized components and rejects weights not
  totaling exactly 10,000 basis points;
- PostgreSQL/API Docker verification covers all 25 GET paths, including author growth, quality
  map and influence ranking; a PostgreSQL DATE/VARCHAR portability defect found by this gate was
  corrected and the focused 14-test author analytics suite passed;
- the Phase 4 exit review is `passed_private_fixture_only` at 100%, backed by 28 focused API,
  10 Web unit and 12 desktop/mobile browser cases with current Docker API/Web evidence;
- fixed-clock operator-session tests now pass independently of wall-clock date while preserving
  one-use lease expiry and mutable-buffer clearing behavior;
- 10 Vitest and 12 Playwright tests, typecheck, ESLint, production build and axe WCAG
  desktop/mobile checks pass;
- canonical v1 JSON now binds approval, provider, entity/source and normalized exact HTTPS
  URL without delimiter collisions; Composition uses its hash for the permanent slot;
- runtime session scope is immutable and one exact opaque lease identity is required across
  Composition, Provider, HTTPS broker and the one-use RuntimeSession supplier;
- permit reservation, run/daily budget updates and journal `send_started` now commit in one
  transaction; PostgreSQL verified `send_started` and conservative no-send `indeterminate`
  recovery without contacting a source;
- aggregate offline composition smoke passed 108 safety tests with no real Provider,
  credentials, Pixiv contact or source network use;
- RTK 0.45.0 was installed workspace-locally from a checksum-verified official release;
  fixed quality profiles passed with telemetry/tee disabled and ephemeral tracking removed;
- a bounded multi-Agent workflow now documents the main Agent, `luna_worker` and `explorer`
  ownership boundaries, precise-search and no-repeat-read rules, RTK output compression with
  fail-open-to-original-command fallback, and concentrated non-critical testing. Credential,
  network, field-allowlist and publication safety gates remain immediate and fail-closed;
- reusable Docker/PostgreSQL and API integration verification scripts.
- Phase 5 now has a bounded deterministic tag-association and sensitivity core with explicit
  sampled counts, support, Jaccard and PMI metrics; 33 focused tests, Ruff and strict mypy pass
  without adding a
  classifier, external model, graph database, background worker or source request.
- its private GET-only API projects at most 5,000 catalog works, reports truncation and descriptive-
  only semantics, and passed 17 focused core/API tests plus a real PostgreSQL Docker probe;
- the private `/tags/graph` and `/tags/review` surfaces add bounded filters, an ECharts force graph,
  a threshold curve, truncation warnings and keyboard-accessible evidence tables; 11 Web unit and
  16 desktop/mobile browser checks, production build, Axe and the seventeen-route Docker Web probe
  pass;
- Phase 6 now has a deterministic offline deployment-readiness matrix, private operations
  runbook, a non-root API image, and read-only/capability-free/no-new-privileges API and Web
  runtimes. Ten of twelve controls pass; runtime-only database secret provisioning and an isolated
  backup/restore drill now pass. The remaining blockers are production identity/TLS review and
  external-publication approval. Eleven focused tests, Ruff and strict mypy pass, with real-source
  collection and external publication still disabled;
- the rebuilt API container passed the full PostgreSQL-backed read integration after hardening;
  runtime inspection confirmed `user=pyuri`, a read-only root filesystem, all Linux capabilities
  dropped, `no-new-privileges` enabled and `/tmp` supplied only as tmpfs;
- a cryptographically random runtime-only database password now replaces the placeholder during
  Phase 6 review without being written to reports or the repository. An isolated PostgreSQL custom-
  format backup crossed a host temporary-storage boundary, retained its SHA-256, restored migration
  `20260823_0009`, and matched all nine evidence-table counts (17 rows total); disposable containers,
  images, host backup and volume were then removed;
- production identity/TLS evidence now has a versioned non-secret JSON Schema, fail-closed draft,
  operator checklist and offline reviewer. It rejects unknown or secret-shaped fields and PEM,
  Bearer, JWT and credential-bearing DSN value shapes; six focused tests, Ruff and strict mypy pass.
  Phase 6 consumes the machine review rather than trusting standalone Phase 3 booleans;
- a read-only interactive deployment console at `/operations/readiness` renders the current local
  Phase 6 reports with a 60% overview, passed/blocked control filters and four evidence summaries.
  It passed TypeScript, ESLint, a clean production build and live browser interaction checks for
  the two blocked controls and all four evidence cards. Its actual private Docker deployment is
  healthy and included in the seventeen-route container probe; the UI remains local-only;
- the shared product shell now identifies `ilovemiku520@outlook.com` as project owner and author
  through a visible `mailto:` link on every public and operations page, with matching application
  metadata. Public/operations browser checks, TypeScript, ESLint, production build and the rebuilt
  seventeen-route Docker Web probe pass;
- the shared product shell, `/about/data-policy` and `/operations/imports` now state
  personal/non-commercial research use,
  prohibit commercial use, redistribution and mirroring, attribute future reviewed public metadata
  to Pixiv and its rights holders, disclaim affiliation, identify the personal developer at
  `ilovemiku520@outlook.com`, and distinguish current Fixture data from user-export candidates. The
  product is `noindex, nofollow`; the updated declaration page passed a production container build
  and a browser-visible local check, while the earlier full Docker route probe remains unchanged;
- an independent anonymous-public contract and request-plan gate now require reviewed current terms,
  an allowed robots decision and a sanitized representative JSON Schema before they can exist. The
  branch accepts no session or credential supplier, is all-ages metadata-only, forbids redirects,
  queries and media, and enforces one concurrency slot, one initial request, at least 20 seconds
  between plans and at most three per minute. It has no HTTP sender and explicitly reports
  `authorizes_network=false`. A reviewed source may be HTML or JSON, but only the normalized
  field-only Schema may leave a future parser and no raw body may be persisted; 17 focused tests,
  Ruff and strict mypy pass;
- the production/publication binding gate now cross-checks deployment ID, normalized hostname,
  certificate fingerprint, production-evidence SHA-256 and publication-manifest SHA-256. Eleven
  focused tests, Ruff and strict mypy pass; the generated draft binding remains blocked and never
  grants publication or real-source authority;
- the source-endpoint contract now has an offline CLI that accepts only payload-free local evidence,
  rejects secret-shaped keys and values, and emits a non-authorizing machine report. The current
  report rejects the structured network-research summary as `endpoint_evidence_invalid`, preserving
  its SHA-256 while keeping `contract_ready=false` and `authorizes_network=false`; 27 endpoint
  review/contract tests, Ruff and strict mypy previously passed without creating a source URL or
  using network access;
- a local-only browser-export adapter now supports Powerful Pixiv Downloader JSON as an optional
  user-driven interchange format. It rejects R-18/R-18G/unknown ratings, novel bodies, secret-shaped
  and unknown vendor fields; emits only the twelve normalized metadata properties; strips media URLs
  and browser state; and marks every result `visibility_verified=false` and
  `canonical_ingest_authorized=false`. Five focused tests, Ruff, strict mypy and a synthetic end-to-end
  CLI run pass with no credentials, media persistence, raw-payload persistence or external network;
- the adapter is now packaged as a one-command Docker workflow with a read-only export mount,
  `network_mode: none`, a read-only root filesystem, dropped Linux capabilities and gitignored
  candidate/report outputs. A drag-and-drop Windows launcher delegates to the same workflow. The
  latest synthetic Docker run accepted one record and rejected zero, and `/operations/imports`
  successfully rendered that value-free result while hiding the input hash, source path and work data;
- a first-party Manifest V3 Pixiv metadata companion now supports user-managed sessions without
  receiving passwords, Cookies, tokens or browser profiles. One explicit click exports only approved
  metadata for the already-open artwork and supports
  G0-approved all-ages/R-18/R-18G ratings without retaining the rating. Version `0.4.0` adds a
  main-world observer for Pixiv's current Next.js page: it observes the single-artwork response that
  the page already requested, immediately minimizes it, and retains the legacy preload parser as a
  fallback. If the initial response occurred before observation, one explicit export click may issue
  one same-origin, current-work-only GET to Pixiv's non-official Web `/ajax/illust/{work_id}` endpoint
  with redirects disabled. The response is minimized in the page's main world before crossing the
  extension boundary; the extension does not inspect Cookie contents. There is no automatic paging or
  background collection. It does not persist or forward the raw response. Five JavaScript tests,
  eleven web tests, manifest permission review, TypeScript, ESLint, production build and a network-disabled Docker
  end-to-end run pass; the latter accepted one synthetic R-18G record and emitted exactly twelve fields;
- a Windows remote-host access path now keeps Cloudflare WARP in local proxy mode and adds a
  loopback-only, Pixiv-only HTTP CONNECT bridge. The bridge resolves allowed hosts with Cloudflare
  DoH through WARP, connects upstream by verified IPv4 address, rejects non-Pixiv domains and
  non-TLS ports, and never decrypts traffic. The only non-Pixiv exceptions are the exact
  `www.recaptcha.net` and `www.gstatic.com` resource hosts required for the user's manual Pixiv
  login verification; no CAPTCHA is read, clicked or submitted by the project. Its launcher leaves the system proxy and default route
  unchanged, uses a dedicated Chrome profile, and loads the first-party companion without reading
  browser state. Five focused standard-library tests pass; a live connectivity probe returned 200
  and Chrome rendered the Pixiv home page without a certificate warning on 2026-08-23;
- a new read-only `/operations/imports` page exposes the candidate-import decision, four fixed
  safety controls and the four-step one-sample workflow without forms, file inputs or mutation
  buttons. The shared provenance statement now distinguishes Fixture display data from unverified
  user-export candidates. TypeScript, ESLint, production build, 22 desktop/mobile browser cases and
  WCAG serious/critical checks pass after correcting one definition-list structure defect;
- the first real user-driven browser-companion export completed the offline candidate path on
  2026-08-23: one record was accepted and none rejected. The importer used no external network,
  requested no credentials, and persisted neither media nor raw payload. The sanitized result is
  `candidate_ready`; visibility remains unverified and canonical ingestion remains blocked;
- the offline importer now accepts a bounded batch of at most 25 same-directory JSON exports and
  10 MB total, deduplicates work identifiers across files, hashes the batch without retaining file
  names, and blocks the entire output when any file is invalid or formats are mixed. A Docker smoke
  with two duplicate companion exports accepted one record and counted one duplicate; the real
  single-record candidate was restored afterward;
- the candidate-review evidence gate now recognizes the first-party companion format and its
  G0-approved all-ages/R-18/R-18G human-review scope, while the legacy third-party adapter remains
  all-ages only. The current real candidate reaches the next two explicit blockers—human visibility
  evidence and a reviewed source-endpoint contract—without being misclassified as invalid import
  evidence. The product page displays these bound stages separately;
- the accountable owner amended G0 on 2026-08-23 to allow a bounded unofficial Pixiv App API
  candidate method and explicitly accepted possible account enforcement for private research.
  PixivPy3 is pinned to 3.7.5 and exposes only tag/word search, author works and ranking pages;
  password input, access-control bypass, media, raw-payload persistence, automatic retries and
  canonical ingest remain prohibited. The policy permits 12 pages/minute, network concurrency 1,
  100 pages/run and 500 pages/day, yielding up to 3,000 minimized candidates per run;
- the App API collector now defaults to user-driven OAuth PKCE in the WARP-backed project Chrome:
  login/CAPTCHA stay in the browser, extension 0.5.0 automatically forwards only the exact Pixiv
  OAuth callback to a one-use `127.0.0.1:41180` memory receiver,
  the verifier is zeroized after one exchange, and only a maximum 60-minute access-token lease is
  passed to PixivPy3. No password or refresh token is requested or saved by the default path. A
  hidden runtime refresh-token fallback remains available without argument/environment/file input;
  the collector serializes network pages,
  minimizes each page into the existing twelve-field candidate shape with up to eight local workers,
  and deduplicates across pages. Twenty-eight focused backend tests, strict mypy, Ruff, G0 validation,
  CLI discovery and a pre-authentication over-limit smoke pass without contacting Pixiv;
- the existing candidate-review gate now accepts the strict value-free App API report and up to
  3,000 sanitized JSONL records. It reuses the same Schema, unique work-ID, file/report hash,
  human-visibility, G0-fingerprint and endpoint-contract binds instead of creating a parallel
  authorization path;
- a candidate-visibility review gate now binds a sanitized JSONL candidate file, its import report,
  a human-only expiring review artifact, the active G0 fingerprint and an independently reviewed
  endpoint contract before it can report `canonical_ingest_authorized=true`. It is local-only,
  rejects URL/secret-shaped review references, does not persist candidate values, and currently
  safely blocks because the Pixiv endpoint review remains incomplete. Four focused tests plus the
  browser-export tests, Ruff, strict mypy and a fail-closed CLI smoke run pass;

## Current state

Docker Desktop `4.87.0.236836`, Docker CLI `29.7.2`, and Compose `v5.4.0` are installed
in per-user mode under `C:\Users\Easyai\AppData\Local\Programs\DockerDesktop`.
Per-user mode intentionally has no `com.docker.service`; the Linux Engine is hosted by
the signed-in user's Docker Desktop processes.

The Engine is running. Hardware checks confirmed SLAT and firmware virtualization on
the physical `OEM X99-Turbo` system. On 2026-08-22, DISM enabled both
`Microsoft-Windows-Subsystem-Linux` and `VirtualMachinePlatform`; Windows was restarted,
WSL was updated, and Docker Desktop then started successfully. The earlier BCDEdit
boot-store warning did not prevent the hypervisor or WSL2 backend from loading.

`scripts/enable-docker-virtualization.cmd` was updated so a BCDEdit boot-store warning
does not abort WSL update/report generation. It self-elevates through UAC and
deliberately does not restart Windows.

After the restart, Docker Desktop confirmed that the installed inbox WSL version is
too old. `scripts/update-wsl.cmd` now provides a dedicated self-elevating updater that
tries both Microsoft's direct download and Store update channels, selects WSL 2 as the
default, and writes `var/reports/wsl_update.json`.

The PowerShell Docker runners locate Docker Desktop's CLI when PATH has not refreshed.
Offline tests remain green: 426 pytest tests, Ruff, and strict mypy across 142 source/test modules pass.

The first integration attempt reached Docker BuildKit but Docker Hub authorization
timed out. Host diagnostics showed polluted DNS answers for `auth.docker.io` and
`registry-1.docker.io`, including addresses belonging to unrelated services. The
integration runner now uses DaoCloud's digest-preserving Docker Hub prefix only for its
`postgres:17` and `python:3.12-slim` inputs. Compose defaults remain the upstream image
names, and no system DNS, hosts file, or global Docker setting was changed.

The corrected integration then passed against PostgreSQL 17: 3/3 fixture tasks
succeeded, with 1 crawl run, 3 raw observations, 3 schema definitions, and no
quarantine rows. The minimal FastAPI contract also passes its local and container
process smoke test, including request ID propagation. The container-level gate also
passed: PostgreSQL and API both became healthy, and the API healthcheck verified
database readiness. A Windows PowerShell 5.1-only parameter mismatch in the reporting
step was corrected and did not invalidate container health evidence.

On the latest API verification, Docker Desktop retained the requested loopback binding in
HostConfig but did not publish it in NetworkSettings. The bounded runner retried loopback,
then verified the same healthy API inside the container and recorded
`verification_access_mode=container_internal_fallback`. API/PostgreSQL correctness passed;
host-port publication remains a local Docker environment issue to recheck.

The Phase 3 web integration also passed through Docker's internal network. PostgreSQL, API
and web containers are healthy; all seventeen application routes returned 200 and rendered
Fixture data. Because Docker Desktop again omitted the requested host port from runtime
publication, the verifier used a bounded container-internal fallback. A temporary host-side
Next.js process is currently retained on loopback port 3000 for interactive user evaluation. The
repeatable Playwright runner now owns and cleans up its exact local mock/API process trees.

## Phase 0 exit decision

Phase 0 passed on 2026-08-22. Evidence is recorded in `VALIDATION.md`,
`docs/phase0-exit-review.md`, and `var/reports/phase0_demo.json`.

## Next gate

Phase 6 offline preparation is 60% complete. Its generated report is intentionally
`offline_preparation_blocked`: ten of twelve controls pass, no source network was used, no
real-source collection was authorized, and no external publication was approved. The production
identity/TLS Schema, draft and reviewer are ready, but the current draft has fifteen unresolved
controls because no actual production edge/certificate evidence was supplied. External-publication
approval remains a separate accountable gate and cannot be inferred from local Fixture evidence.
The one-request Launch Review and fake-opener preflight were refreshed against migration
`20260823_0009`; they pass as readiness evidence only and explicitly record `pixiv_contacted=false`,
`authorizes_live_request=false` and `atomic_execution_gate=false`. A real first request remains
blocked before transport construction because no reviewed exact source-endpoint contract,
representative response evidence, live Provider or user-managed runtime session channel exists.
`var/reports/source_endpoint_review.json` now exposes that first blocker directly to automation.
The browser-export adapter offers a safer candidate-data path but does not remove this blocker:
third-party exports cannot independently prove public visibility or authorize canonical ingestion.

Phase 4 is complete as `passed_private_fixture_only` at 100%. Its current evidence covers the
25-path Docker API contract, seventeen Web routes, 426-test regression, production build and
desktop/mobile browser checks. This does not require or authorize real-source access.

Phase 5 now has a Fixture-only tag co-occurrence core, private GET-only catalog projection and
inspectable graph UI: deterministic pair counts, bounded support/Jaccard/PMI metrics, explicit
sample/truncation metadata, accessible tabular evidence and Docker PostgreSQL/Web checks pass.
The threshold-sensitivity and candidate-review contract is exposed through a private GET-only API
and an accessible Web review surface without assigning or persisting semantic labels. A
reviewer-attributed, tamper-evident offline decision artifact now binds exact candidate and sample
evidence while keeping all decisions manual. The aggregate Phase 5 exit review revalidates the
artifact and cross-checks core, API, Web, Docker, accessibility and private-boundary evidence.
Embeddings, automated
classification, Neo4j, Elasticsearch and background workers remain deferred until the bounded
PostgreSQL/API baseline has evidence that they are necessary.

The local executable G0 v2 record was amended and passed machine validation on 2026-08-23; it expires
on 2026-09-21. It approves the browser-current-work and bounded Pixiv App API access methods plus
14 metadata fields for authenticated-public
`all_ages`/`r18`/`r18g` scope. Private/deleted content, access-control bypass, media
storage, password collection, and secret persistence/logging remain prohibited.

One anonymous public single-artwork response was read in memory on 2026-08-23 solely to verify the
current response-field shape after Pixiv removed its legacy preload element. No response payload or
candidate values were persisted, and no authenticated browser session, Cookie or credential was used
for that diagnostic request. This shape check does not authorize a live Provider or canonical ingest.
A separate user-managed Chrome window reached the Pixiv home and artwork pages during the network
recovery and extension-compatibility checks. It has now produced one real export; the offline importer
accepted its single record as a sanitized candidate without persisting raw input or media. This is not
evidence of public visibility and does not authorize canonical ingestion.
Revision `20260823_0009` and the transactional permit service passed real PostgreSQL migration, cross-day global
locking, request idempotency, concurrent contention and journal-table verification in
Docker Desktop.

1. Obtain accountable-owner evidence for one exact supported Pixiv metadata access method
   and separately review a representative response shape. Current review status is blocked.
2. Run the offline evidence finalizer and re-run Launch Review only after item 1 is complete.
3. Keep CLI/API reachability and all real-source requests disabled until gates 1–2 pass.
   Redis and later analytical stores remain deferred.

The Pixiv-specific endpoint adapter and any live call remain blocked until its exact
request/response field contract is reviewed and the operator supplies a runtime-only
session locally. No account password is required or accepted.

## Railway public deployment (2026-08-24)

The current JJWXC product is publicly reachable at
`https://web-production-99ad5.up.railway.app`. PostgreSQL, the private FastAPI service and
the Next.js Web service are healthy in Railway's Singapore region. Database migrations
reached `20260824_0014`; only the Web service has a public domain.

A bounded one-time collection completed inside Railway with 14 network requests: 407
channel discoveries, 20 ranking positions, 99 bookbase summaries, 5 hydrated novel
snapshots, 725 chapter rows and 2 author profiles, with zero failed novels. All six
representative public pages returned HTTP 200 and the temporary PostgreSQL TCP proxies
used during diagnostics were deleted. The fourth `daily` service is now deployed without
a public domain, with a 500MB `/data/cache` volume and the bounded collector scheduled at
UTC 19:30 (Asia/Shanghai 03:30). The workspace remains on the cardless Trial; the next
online evidence is the 2026-08-25 automatic run and second observation-day snapshot.

The fifth and final Trial service, `backup`, is deployed privately in Singapore with the
third 500MB Trial volume mounted at `/backups`. It creates a PostgreSQL custom-format dump
at Asia/Shanghai 04:30, validates the archive with `pg_restore --list`, writes SHA-256
evidence and retains seven dumps. The first verified archive
`jjwxc-20260824T104711Z.dump` is 136287 bytes. No database or backup TCP endpoint is public.

All four code services (`api`, `web`, `daily`, `backup`) are connected to the GitHub
`ilovemiku520/jjwxc-yuri-analytics` repository on `main`. Their Dockerfiles, path-based
automatic deployment rules, health checks, migration command, Singapore replicas, Cron
schedules, persistent volumes and secret-preservation boundary are declared in
`.railway/railway.ts`. The production release therefore no longer depends on a local CLI
upload or on this virtual machine remaining available.

### Local high-window collection validation (2026-08-24)

To validate the backfill path before changing the cloud schedule, a local run used a
larger but still rate-limited window: 20 bookbase pages, 50 hydrated novels and 20
author profiles at a two-second request interval. The run completed with 120 network
requests, 50 hydrated novel snapshots, 4,249 new chapter rows and 20 author profiles;
all 50 detail hydrations succeeded. The source bookbase returned an oversized response
on its first page, so the resumable bookbase cursor remains pending and no raw body was
persisted. The local database now contains 122 novels, 11,670 chapter snapshots and
120 authors. This confirms that the larger window increases local coverage without
weakening the public-data and cache-size controls.

Railway deliberately remains on the bounded 99-request command
(`--index-pages 10 --hydrate-limit 39 --author-limit 10`) because the acquisition
ledger caps a single run at 100 requests. Additional cloud coverage should therefore
come from the daily schedule and resumable backfill, not a single unbounded burst.
