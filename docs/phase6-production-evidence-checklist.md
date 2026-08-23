# Phase 6 production identity and TLS evidence checklist

Status: preparation only. This checklist does not approve publication or source collection.

## Evidence boundary

Complete the template only after an identity-aware edge and trusted production certificate are
actually deployed. Store identifiers, dates, bounded control settings and SHA-256 fingerprints
only. Do not paste passwords, cookies, tokens, HMAC values, assertions, private keys, certificate
PEM bodies, authorization headers, DSNs containing passwords, request subjects or source URLs.

## Identity review

- name the reviewed proxy product and an opaque deployment reference;
- bind the configured proxy ID and confirm direct API access is blocked;
- confirm secret delivery is a runtime read-only file, without recording its value;
- set rotation to at most 90 days and assertion age to at most 60 seconds;
- confirm health monitoring and record only the production smoke report SHA-256.

## TLS review

- record the real production DNS hostname and reviewed certificate authority;
- record the leaf certificate SHA-256, not the certificate or private key;
- ensure the certificate remains valid through the evidence expiry;
- require TLS 1.2 or 1.3, runtime secret storage, automated renewal, renewal monitoring and HSTS;
- record only the production TLS smoke report SHA-256.

## Accountable review

Set a non-placeholder accountable owner and reviewer, use timezone-aware timestamps, and limit the
review lifetime to 90 days. Change `status` from `draft` to `reviewed` only after every statement is
supported by actual production evidence.

Run `scripts/run-production-evidence-review.ps1`. A draft, expired review, placeholder, loopback
certificate, zero hash, unknown field or secret-shaped key/value must produce `status=blocked`.

## Publication boundary

A reviewed identity/TLS report satisfies only the production transport evidence control. External
publication still requires the separate publication manifest and approval review. Neither report
authorizes Pixiv access or any real-source collection.
