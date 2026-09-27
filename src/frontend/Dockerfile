ARG NODE_BASE_IMAGE=node:24.21.0-alpine
ARG NGINX_BASE_IMAGE=nginx:1.29-alpine
FROM ${NODE_BASE_IMAGE} AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_GOOGLE_CLIENT_ID=REPLACE_WITH_GOOGLE_WEB_CLIENT_ID
ARG GOOGLE_CLIENT_ID_SHA256
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
RUN npm run build

FROM ${NGINX_BASE_IMAGE}
ARG GOOGLE_CLIENT_ID_SHA256
LABEL org.opencontainers.image.google-client-id-sha256=${GOOGLE_CLIENT_ID_SHA256}
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
