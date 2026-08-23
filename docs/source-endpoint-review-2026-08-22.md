# Pixiv source endpoint review — 2026-08-22

## Decision

**Blocked; no endpoint was promoted to `SourceEndpointContract(status="reviewed")`.**

This review performed no Pixiv work-page request, login, browser automation, endpoint
probe, or response capture. It authorizes no network request.

## Evidence reviewed

- The project requirements describe work/search/author/tag page categories and desired
  fields, but do not identify one exact, supported metadata origin and path.
- Pixiv's official engineering article states that work-detail and search HTTP API access
  is rate-limited, that some endpoints reject unauthorized sessions, and that search and
  work-detail access is logged and analyzed for malicious-account detection:
  <https://inside.pixiv.blog/2023/05/17/102629>
- Pixiv's official Help Center points users to the current centralized Terms of Use and
  Guidelines rather than publishing a supported metadata API contract:
  <https://www.pixiv.help/hc/en-us/sections/360002400154-About-pixiv>
- Pixiv Inc.'s official policy migration notice identifies the centralized policy site and
  explains that service-specific terms take precedence where present:
  <https://www.pixiv.co.jp/news/information/article/9437/>

## Why the gate remains closed

The repository contains synthetic `/ajax/illust/42` test strings, but test strings and
community knowledge are not endpoint-review evidence. No official source found in this
review publishes a stable, supported response schema for the project's proposed metadata
request. The existing internal G0 record approves purpose, fields, visibility and traffic
limits; it does not prove that a particular undocumented endpoint is permitted or stable.

Required evidence before an endpoint can be marked reviewed:

1. one exact HTTPS origin and fixed path template approved by the accountable owner;
2. a current terms/reference assessment specifically covering that access method;
3. one representative, manually initiated response-shape review under the approved scope;
4. a payload-free schema fingerprint proving the response can be reduced to exactly the
   14 G0 fields, with no private/deleted content, media bytes or secret-shaped fields;
5. observed redirect, content type and maximum-body behavior;
6. a contract expiry no later than G0 expiry.

Until all six exist, the correct configuration is: no Pixiv adapter, no real origin in
runtime configuration, no CLI/API collection entry point, and `authorizes_network=false`.

## Network revalidation — 2026-08-23

The accountable owner authorized network use for a one-sample field trial. That authorization
was recorded as permission to perform the review; it did not replace the endpoint-contract gate.
The revalidation used search/index access and the official Pixiv corporate and engineering pages.
It did not request a Pixiv work page or work-detail endpoint and did not use a login session.

- Pixiv's current official engineering material still describes rate limits, session restrictions,
  request logging and countermeasures against automated content acquisition, but does not publish
  a supported metadata endpoint or response contract.
- The official policy migration notice still directs users to the centralized policy site. Direct
  access to that policy host timed out from this environment, so the current policy text could not
  be independently captured.
- The only concrete JSON endpoint documentation found was explicitly third-party and reverse-
  engineered; it instructed users to extract a login Cookie. It was rejected as unsupported and
  incompatible with the project's no-secret-extraction boundary.

Decision remains **Blocked**. No representative response exists, so no schema fingerprint or
`SourceEndpointContract(status="reviewed")` can be created. Network authorization remains recorded,
but no source request slot was claimed and Pixiv work metadata was not collected.
