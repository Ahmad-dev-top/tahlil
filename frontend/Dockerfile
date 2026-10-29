# Build the Next.js static export, then serve it with nginx (which also proxies /api to the backend).
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# .env.production sets NEXT_PUBLIC_API_BASE=/api
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /src/out /usr/share/nginx/html
# nginx's entrypoint renders *.template files with environment variables (TAHLIL_API_KEY)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
