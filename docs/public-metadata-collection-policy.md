# Public metadata collection policy

## Scope

This personal project may analyze only metadata that an ordinary visitor can access without
signing in. It may not use a Cookie, token, account password, private session, reverse-engineered
mobile credential, access-control bypass or CAPTCHA workaround. R-18/R-18G, private, deleted and
URL-restricted works are outside this public route.

The data and analysis are for personal learning and non-commercial research only. Commercial use,
resale, redistribution, mirroring and publication of a reusable dataset are prohibited. Pixiv and
the respective creators retain all platform and work rights; this project is independent and is not
affiliated with, endorsed by or licensed by Pixiv.

## Data minimization

Only the normalized fields in `config/public_metadata_normalized.schema.json` may leave the parser.
Raw response bodies, source URLs, media URLs, image bytes, request headers and session material are
never persisted. Normalized metadata expires after seven days; payload-free audit evidence may be
retained for 365 days.

## Request controls

- exactly one concurrent request;
- at most three requests per minute with at least 20 seconds between requests;
- one request in the first real run and at most 25 requests per day;
- no redirect following, media fetching, query expansion or pagination in the first run;
- inspect and enforce the exact robots decision and current applicable terms before a request;
- stop on any login/challenge page, 403, 429, unexpected redirect, schema drift or complaint.

## Current decision

The route remains `blocked_pending_source_review`. Network permission and the absence of a formal API
license do not by themselves authorize scraping. Before the first request, the project still needs a
captured current terms assessment, the exact robots decision, one fixed public-page contract and a
manually reviewed payload-free representative schema. The saved normalized Schema is a destination
allowlist, not evidence that a Pixiv response matches it.
