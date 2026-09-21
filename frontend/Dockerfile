# The UI is static files once it is built, so production has no Node process: this image builds
# them and hands them to Caddy, which serves them and proxies the API behind the same origin.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
