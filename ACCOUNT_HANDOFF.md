# Account handoff

Updated: 2026-08-23 16:40 Asia/Shanghai

## Active workspace

The active writable project is now:

`C:\Users\Easyai\Documents\ChatGPT\yuri`

It was copied from the previous account workspace:

`C:\Users\Easyai\Documents\Codex\2026-08-22\files-mentioned-by-the-user-3\outputs\pixiv-yuri-analytics`

The new workspace contains the Python services, migrations, Docker Compose files,
Next.js product website, fixtures, tests, documentation, governance artifacts and safe
reports. Generated environments and caches were deliberately not migrated: `.venv`,
`node_modules`, `build`, `.next`, test/type/lint caches, identity/TLS scratch material
and temporary Docker validation directories. No `.env` file was copied.

## Verified baseline

The local filesystem, not the shared chat snapshot, is the source of truth.

| Scope | Completion | State |
| --- | ---: | --- |
| Phase 0 - offline engineering foundation | 100% | Complete |
| Phase 1 - approved acquisition MVP | 99.5% | Offline chain complete; live source remains gated |
| Phase 2 - read-only data API | 100% | Complete within the private boundary |
| Phase 3 - private product website | 92% | Website exists; accountable production deployment remains |
| Phase 4 - author analytics | 100% | Complete with Fixture evidence |
| Phase 5 - tag discovery | 100% | Complete with Fixture evidence |
| Phase 6 - production deployment | 60% | Ten of twelve offline controls pass |
| Overall roadmap | about 97% | Live acquisition and public deployment remain separately gated |

The website lives under `apps/web`. It includes the private analytics surfaces and the
read-only browser-export/candidate-review operations surface. Product ownership and the
non-commercial research/source-attribution statements are already present in the project.

## Latest evidence

- `apps/browser-extension` is a first-party Manifest V3 current-page metadata companion. It has no
  Cookie/webRequest permission, performs no background crawl and exports only after a user click.
  A real user-driven export has now passed the network-disabled Docker importer: one record accepted,
  none rejected, with no credential, media or raw-payload persistence.
- `scripts/run-pyuri-browser-companion-import.cmd` is the drag-and-drop entry for that export. The
  generic importer remains `network_mode: none` and recognizes both companion and PPD JSON.
- `var/reports/browser-export-import.json` is currently `candidate_ready` for the real project-
  companion sample: one file, one accepted record and zero rejected. Its safety flags confirm no
  credentials, external network, media or raw payload were used or persisted. The candidate remains
  noncanonical and does not authorize live acquisition.
- `scripts/run-pyuri-browser-companion-batch-import.cmd` accepts a folder with at most 25 companion
  exports and 10 MB total. The network-disabled importer rejects mixed/invalid batches and performs
  cross-file work-ID deduplication without retaining source file names.
- `scripts/run-pixiv-app-api-collection.cmd` is the interactive high-volume candidate entry. It uses
  pinned PixivPy3 3.7.5, user-driven OAuth PKCE with no password/token persistence, 12 pages/minute, one network worker,
  at most 100 pages/3,000 candidates per run and eight local minimization workers. The adapter is
  installed and offline-tested. `scripts/run-pixiv-app-api-first-sample.cmd` is the one-page real
  verification entry; the user only completes login/CAPTCHA, then extension 0.5.0 forwards the exact
  OAuth callback to a one-use local memory receiver automatically.
- `scripts/run-powerful-pixiv-import.cmd` accepts one user-exported JSON by drag-and-drop and invokes
  the network-disabled Docker importer. `/operations/imports` reads only the value-free report.
- `var/reports/source_endpoint_review.json` is fail-closed with
  `status="blocked"` and `violations=["endpoint_evidence_invalid"]`.
- `var/reports/source_endpoint_review_run.txt` preserves the latest CLI output.
- `var/reports/phase6_readiness.json` reports ten of twelve controls passed and
  `estimated_completion_percent=60`.
- Phase 6 blockers are `production_identity_or_tls_not_reviewed` and
  `external_publication_not_approved`.
- No Pixiv work/detail endpoint was contacted, no real metadata was collected, no
  credential was requested, and no source network request was authorized by these reports.

## Safety boundary

Do not request or store a Pixiv password, Cookie, token, authorization header or browser
profile. Do not bypass login, CAPTCHA, access controls or rate limits. Do not store image
bytes, raw browser responses, private/deleted content or secret-shaped fields. Browser
exports remain noncanonical candidates until the separate visibility review gate passes.

The approved G0 scope permits only the fourteen metadata fields recorded in
`config/g0_approval.json`. G0 approval does not by itself authorize a real request.

## Resume order

1. Recreate local dependencies in this new path only when execution is required; do not
   copy the old `.venv` or `node_modules` because they may contain absolute old paths.
2. Do not fabricate `SourceEndpointReviewEvidence`. Obtain one exact supported HTTPS
   metadata origin/path, a current access-method terms assessment and one manually reviewed,
   payload-free representative response-shape fingerprint.
3. Re-run `pixiv_yuri.governance.source_endpoint_review` with that evidence. A ready report
   is still non-authorizing and must remain `authorizes_network=false`.
4. After the endpoint evidence gate is satisfied, refresh Launch Review and the offline
   finalizer before considering one bounded real request.
5. Independently complete production identity/TLS evidence and accountable publication
   approval before exposing the website beyond loopback/private access.

## Environment bootstrap

Python and Node dependencies were intentionally excluded from the handoff. When needed,
recreate them from `pyproject.toml` and `pnpm-lock.yaml`. Docker Desktop data and the old
workspace remain untouched. The original validation history is preserved under
`var/reports` and `VALIDATION.md`.
