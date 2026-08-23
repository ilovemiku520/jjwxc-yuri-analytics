# Source endpoint contract gate

Before any Pixiv-specific adapter is implemented, one exact metadata endpoint must be
recorded and reviewed offline using `SourceEndpointContract`. The contract permits only:

- one exact HTTPS DNS origin on port 443;
- one fixed path containing exactly one `{source_id}` placeholder;
- GET with `Accept: application/json`;
- one planned request, no query parameters and no redirects;
- no media download;
- a response cap of at most 1,000,000 bytes;
- the timeout, 14 metadata fields and age-rating scope already approved by G0; and
- only a credential header name, never its value.

The review result has `authorizes_network=false`. It contains no endpoint response,
Cookie, token, password, signed URL or account identifier. The reviewed contract must
expire no later than G0 and must be rechecked in the final same-process composition.

The repository intentionally contains no real Pixiv URL yet. Selecting that URL requires
a separate current terms/behavior review and a representative response-shape review;
neither step should use an account password or persist a runtime session.
