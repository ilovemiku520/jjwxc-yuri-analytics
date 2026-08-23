ARG PYURI_NODE_BASE_IMAGE=node:22-alpine
FROM ${PYURI_NODE_BASE_IMAGE} AS dependencies

ENV COREPACK_HOME=/corepack \
    NEXT_TELEMETRY_DISABLED=1
ENV PATH=${COREPACK_HOME}:${PATH}

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --filter @pyuri/web --frozen-lockfile

FROM dependencies AS builder
COPY apps/web ./apps/web
ENV PYURI_WEB_STANDALONE=true
RUN pnpm --filter @pyuri/web build

FROM ${PYURI_NODE_BASE_IMAGE} AS runner

ENV HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    PORT=3000

WORKDIR /app
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static ./apps/web/.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
