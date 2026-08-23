# Authenticated Acquisition Boundary

Status: **scope intent recorded; live access remains disabled**  
Recorded: 2026-08-22

## Recorded scope

- Visibility: public works that the user's signed-in account can normally view.
- Age ratings: `all_ages`, `r18`, and `r18g` are allowed.
- Private, deleted, or otherwise unauthorized content remains prohibited.
- Access-control, age-gate, region, CAPTCHA, and anti-bot bypasses remain prohibited.
- Image and other media-byte storage remains prohibited; only separately approved
  metadata fields may enter the collection path.

Allowing `r18` and `r18g` is an explicit content-rating decision. It does not turn
private or unavailable content into an approved source.

## Credential boundary

The application must never request, persist, or log a Pixiv password, cookie,
Authorization header, session token, one-time code, or recovery code. None of those
values belong in chat, source control, `.env`, PostgreSQL, reports, or application
logs.

The offline `SessionBroker` boundary gives a Provider only a non-secret
`SessionCapability`: active time window, authenticated-public visibility, and approved
age ratings. `OfflineSessionBroker` accepts no secret material. A future live session
broker, if separately approved, must keep all secret handling on the user's machine and
must expose neither the secret nor a serializable equivalent to the Provider.

Python cannot guarantee physical memory zeroization. The current loopback-only design
therefore accepts only a synthetic runtime value in tests; no production prompt,
configuration field, or external authenticated transport exists.

## Current implementation

`AuthenticatedFixtureProvider` exercises approval, session-expiry, and rating-scope
checks using local fixtures only. It contains no URL, HTTP client, browser automation,
credential input, or live source integration.

`LoopbackSessionBroker` adds a separate HTTP safety exercise restricted to numeric
loopback addresses. It applies a synthetic runtime cookie, strips sensitive response
headers, blocks redirects/external hosts, and is always wrapped by a persistent permit.

## Remaining G0 evidence

This scope statement is not executable approval. The accountable owner, approver,
incident role, reviewed-terms reference, and final allowed-field confirmation are still
required. Persistent PostgreSQL budget/stop enforcement is also required before any
live transport can be considered.
