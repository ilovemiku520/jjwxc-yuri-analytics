# G0 Decision Package

Status: **Executable G0 v2 amended for bounded unofficial App API candidates**  
Prepared: 2026-08-22; amended: 2026-08-23

G0 is an owner/legal/operational authorization gate, not an engineering test. This
document prepares the decision but does not grant permission to access Pixiv, Bright
Data, authenticated sessions, or any other live source.

## Required decisions

| Decision | Required evidence | Current status |
|-|-|-|
| Purpose and owner | Named accountable owner and approved research purpose | Recorded locally |
| Terms and law | Reviewed-reference and decision record | Internal reference recorded |
| Source boundary | Approved public pages; authentication explicitly included/excluded | Authenticated-public approved |
| Field scope | Allowed fields, prohibited fields, and minimization rationale | 14 metadata fields approved |
| Content scope | Age-restricted/private/deleted content handling | All-ages/R-18/R-18G; private/deleted/bypass prohibited |
| Retention | Raw metadata TTL, deletion process, and backup propagation | 7-day raw metadata, 365-day audit |
| Publication | Private-only versus public aggregates and export rules | Private research only |
| Traffic | Request rate, concurrency, daily/run caps, allowed schedule | 12/min, concurrency 1, 500/day, 100/run |
| Cost | Daily/monthly hard limits and alert thresholds | CNY 10/day, CNY 100/month |
| Stop conditions | 403/429/schema drift/cost/complaint kill switches | Required set recorded |
| Incident owner | Contact, response time, disable and recovery procedure | Accountable-owner role recorded |

## Minimum approval record

An approval must contain the approver, timestamp, reviewed source/version, explicit
answers to every row above, and an expiry/review date. Silence, successful fixtures,
Docker readiness, or Phase 0 completion are not approval.

## Engineering work unlocked only after approval

- a live Provider interface implementation for the specifically approved source;
- a tiny representative sample matrix within approved request and cost limits;
- G1 schema review based on that approved sample;
- Worker/retry/budget controls required by the approved acquisition path.

The 2026-08-23 amendment unlocks one candidate-only PixivPy3 App API adapter. It does
not unlock canonical ingestion, public distribution, media collection, password input,
automatic retry, private/deleted content, or access-control bypass.

## Recorded authenticated-scope intent

On 2026-08-22 the requester selected public works normally visible to the signed-in
account and explicitly allowed `r18` and `r18g`. This does not authorize private,
deleted, unavailable, or access-control-bypassed content. The detailed credential and
content boundary is in `docs/authenticated-acquisition-boundary.md`.

The example remains a reusable version 2 draft. The local, ignored
`config/g0_approval.json` is the executable record, originally validated on 2026-08-22
and amended on 2026-08-23 as `G0-2026-08-23-APP-API`. The accountable owner accepted
the possibility of account enforcement for private research and approved the
`pixiv_app_api` access method. It expires on 2026-09-21 and must be reviewed again
before that date.

## Machine validation

Complete `config/g0_approval.example.json` as `config/g0_approval.json`, set
`status` to `approved`, and run:

```powershell
pyuri-g0 config/g0_approval.json
```

A successful result contains an approval fingerprint, expiry, page types, field count,
and hard request caps. The example intentionally remains `draft` and returns exit code
2 until the missing decisions are supplied.
