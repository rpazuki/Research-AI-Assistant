FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
# `configs/frontend.yaml` is read at RUNTIME, not baked in at build time — it is
# the single owner of "where is the backend, as seen by the frontend". Without it
# the config loader falls back to localhost:8000, which inside this container is
# nothing at all, and every server-side call fails with ECONNREFUSED.
COPY --from=builder /app/configs ./configs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Named explicitly rather than left to the loader's cwd-relative guess, which
# resolves to /app/frontend/configs here and does not exist.
ENV FRONTEND_CONFIG_FILE=/app/configs/frontend.yaml

USER nextjs
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
