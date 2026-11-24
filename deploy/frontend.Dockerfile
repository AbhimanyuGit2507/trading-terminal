FROM node:22-alpine AS builder

WORKDIR /repo
RUN corepack enable && corepack prepare pnpm@latest --activate

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./frontend/
COPY shared/ ./shared/
WORKDIR /repo/frontend
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
ARG NEXT_PUBLIC_API_BASE_URL=https://terminal.example.com
ARG NEXT_PUBLIC_WS_URL=wss://terminal.example.com/api/v1/ws/stream
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}

RUN pnpm run build

FROM node:22-alpine AS runner
WORKDIR /repo/frontend
ENV NODE_ENV=production
RUN corepack enable && corepack prepare pnpm@latest --activate

COPY --from=builder /repo/frontend/package.json ./
COPY --from=builder /repo/frontend/.next ./.next
COPY --from=builder /repo/frontend/node_modules ./node_modules
COPY --from=builder /repo/frontend/next.config.ts ./

EXPOSE 3000
CMD ["pnpm", "start"]

