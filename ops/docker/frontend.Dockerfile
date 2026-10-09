FROM node:22-bookworm AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache openssl
COPY --from=build /app/dist /usr/share/nginx/html
COPY ops/docker/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY ops/docker/nginx/server-common.conf /etc/nginx/lcit-sign/server-common.conf
COPY ops/docker/nginx/40-lcit-sign-tls.sh /docker-entrypoint.d/40-lcit-sign-tls.sh
RUN chmod +x /docker-entrypoint.d/40-lcit-sign-tls.sh
EXPOSE 80 443
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
