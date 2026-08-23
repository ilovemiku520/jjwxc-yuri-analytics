# Catalog details, rankings and consumer authorization seam

Phase 2 adds minimized details for works, authors and tags, plus work and author rankings
for `likes`, `bookmarks`, or `views`. Ranking order is score descending and internal key
ascending. The opaque cursor binds endpoint kind, metric, score and key; changing the metric
or using a work cursor for an author ranking fails with `422 invalid_cursor`.

Migration `20260823_0008` adds direct identity lookup indexes and composite metric/key indexes.
All pages remain limited to 100 rows and privately cached. Rankings expose the selected score,
not internal identifiers, Observation provenance, profile fields or payload storage details.

The application now accepts an injected `ConsumerAuthorizer`. A verified identity must carry
`analytics:read`; known missing authentication returns fixed 401, missing scope fixed 403, and
adapter failure fixed 503 without exposing identity-provider details. Health endpoints bypass
consumer authorization. No OIDC/trusted-proxy adapter is selected or enabled yet, so the CLI
continues to prohibit LAN/public binding and the default Compose deployment remains private.

OpenAPI regression asserts that every `/api` operation is GET-only and that its schemas omit
source URLs, object keys, observation metadata/provenance IDs and credential-shaped fields.
