# Multi-stage: node builds, nginx serves. The runtime image has no node, no npm, and
# no source -- just static files and a web server, which is a much smaller thing to
# keep patched.
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
