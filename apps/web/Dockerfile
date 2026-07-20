FROM node:22-alpine AS development

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV NEXT_TELEMETRY_DISABLED=1

RUN corepack enable

WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile

WORKDIR /workspace/apps/web

COPY apps/web/next-env.d.ts apps/web/next.config.ts apps/web/postcss.config.mjs apps/web/tsconfig.json ./

EXPOSE 3000

CMD ["pnpm", "dev", "--hostname", "0.0.0.0"]
