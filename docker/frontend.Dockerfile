ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${NODE_IMAGE} AS build
ARG NPM_REGISTRY=https://registry.npmjs.org/
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=${NPM_REGISTRY} --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${NGINX_IMAGE}
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
