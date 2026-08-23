# Source endpoint human-review evidence template

This form must be completed by the accountable owner before code may create a
`SourceEndpointContract(status="reviewed")`. Do not paste a Cookie, Authorization value,
password, full response body, signed URL, private content, deleted content or media bytes.

## Exact request identity

- Exact HTTPS origin:
- Fixed GET path with one `{source_id}` placeholder:
- Query parameters required: **must be no**
- Redirect observed: **must be no**
- Authentication header name: `Cookie` (name only; never its value)

## Current policy review

- Reviewer role: `accountable-owner`
- Review timestamp with timezone:
- Current official terms/reference URL or internal legal record:
- Does this reference specifically cover the proposed access method?
- Contract expiry, no later than G0 expiry:

## Representative response-shape review

- Manually initiated sample count (1–3):
- Review timestamp with timezone:
- HTTP content type: **must be `application/json`**
- Maximum observed body size in bytes:
- Canonical field-name-only schema SHA-256:
- Exact observed top-level fields:
- Secret-shaped field observed: **must be no**
- Private/deleted content observed: **must be no**
- Media bytes observed: **must be no**

The observed field set must equal all 14 G0 fields exactly. A subset, superset, nested
object, unknown field, missing identity, redirect, query requirement or non-JSON response
keeps the review blocked. This evidence does not itself authorize a request; it only lets
the offline finalizer create another non-authorizing contract checked again by Composition.
