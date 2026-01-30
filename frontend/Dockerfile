FROM node:25-slim AS base

ARG PORT=3000

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

# Dependencies
FROM base AS dependencies

COPY package.json package-lock.json ./
RUN npm ci

# Build
FROM base AS build

# Public build-time environment variables
ARG NEXT_PUBLIC_BACKEND_URL="https://was-sdse-spib-hail-api-dt.azurewebsites.net"

ENV NEXT_PUBLIC_BACKEND_URL=${NEXT_PUBLIC_BACKEND_URL}

COPY --from=dependencies /app/node_modules ./node_modules
COPY . .

RUN npm run build

# Run
FROM base AS run

ENV NODE_ENV=production
ENV PORT=$PORT

RUN addgroup --gid 1001 nodejs
RUN adduser --uid 1001 nextjs
RUN mkdir .next
RUN chown nextjs:nodejs .next

COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static

# copy sshd_config file
COPY sshd_config /etc/ssh/
COPY entrypoint.sh /entrypoint.sh

RUN apt-get update \
    && apt-get install -y --no-install-recommends dialog \
    && apt-get install -y --no-install-recommends openssh-server \
    && echo "root:Docker!" | chpasswd \
    && chmod u+x /entrypoint.sh

USER root

EXPOSE $PORT 2222

ENV HOSTNAME="0.0.0.0"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["node", "server.js"]