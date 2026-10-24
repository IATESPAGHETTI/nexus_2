# Dashboard: build the React app, serve it with nginx, and reverse-proxy the API (see deploy/nginx.conf.template).
# Build context = repository root:  docker build -f dashboard/Dockerfile -t nexus-dashboard .
FROM node:20-alpine AS build
WORKDIR /web
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard ./
RUN npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache openssl
COPY --from=build /web/dist /usr/share/nginx/html
COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY deploy/40-auth.sh /docker-entrypoint.d/40-auth.sh
RUN chmod +x /docker-entrypoint.d/40-auth.sh
EXPOSE 80
