# Build do painel e servidor de borda (Caddy: TLS automático, estáticos e proxy da API).
ARG NODE_IMAGE=node:22-alpine
ARG CADDY_IMAGE=caddy:2-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false sh -c '\
    if [ -f /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; npm ci'
COPY . .
RUN npm run build

FROM ${CADDY_IMAGE}
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
