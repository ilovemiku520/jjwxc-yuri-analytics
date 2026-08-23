# Phase 3 web foundation

Updated: 2026-08-23

The first private research interface is implemented under `apps/web` with Next.js 16,
React 19, TypeScript 5.9, Tailwind CSS 4 and an installed ECharts 6 dependency. pnpm uses
a committed lockfile and permits exactly one audited native postinstall package,
`unrs-resolver`, for ESLint module resolution.

The root dashboard reads only the internal v1 API. Its server-side client accepts three
exact private origins (`127.0.0.1`, `localhost`, or the Compose service name `api`), rejects
credentials/path/query fragments in the configured origin, accepts only relative
`/api/v1/` paths, uses a five-second timeout and never falls back to an external source.

The current private interface provides:

- data freshness and reviewed catalog scale cards;
- a likes-based work ranking from the bounded API;
- a bounded seven-day likes trend rendered with ECharts;
- work, author and tag indexes with literal filters and opaque cursor pagination;
- minimized work, author and tag detail pages linked through local route segments;
- a GET-only operations console for Schema, run, task, quarantine and consumer-security summaries;
- a fixed safe state when the private API is unavailable;
- explicit Fixture/private-boundary labeling;
- responsive desktop/mobile layout and semantic content regions;
- default no-referrer, no-sniff, frame-deny and restricted browser permissions headers.

The Docker image uses a multi-stage Node 22 Alpine build and runs the standalone Next.js
server as a non-root user. Compose exposes the web service only on loopback when the local
Docker engine publishes the requested binding; the browser never receives the private API
service origin. The integration runner now verifies all fourteen routes, Fixture rendering, security
headers, prohibited-field absence and disabled collection networking.

Validation:

```powershell
pnpm --filter @pyuri/web test
pnpm --filter @pyuri/web typecheck
pnpm --filter @pyuri/web lint
pnpm --filter @pyuri/web build
pnpm --filter @pyuri/web test:e2e
scripts\run-web-integration.cmd
```

All six gates pass. The Vitest suite contains seven component, formatting, boundary, URL
and trend tests. Eight Playwright checks cover desktop and 390x844 mobile catalog navigation,
filters, details, operations, safe fallback and axe WCAG scans. Scrollable operational tables
are keyboard focusable. PostgreSQL shared rate limiting, minimized durable access auditing and
retention cleanup are now contention-tested, and container probes prove default-deny CORS.
A trusted-proxy adapter and loopback TLS now pass offline/container matrices. Deploying the real
identity proxy and a trusted production certificate remains publication work; no external
publication is implied.
