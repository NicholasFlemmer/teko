# ---- Build stage ----
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_URL
ARG VITE_GOOGLE_MAPS_API_KEY
RUN if [ -z "$VITE_API_URL" ]; then \
      echo "ERROR: VITE_API_URL build arg is required (e.g. --build-arg VITE_API_URL=https://teko-backend-xxx.run.app). Refusing to build a bundle that would silently fall back to localhost." >&2; \
      exit 1; \
    fi; \
    if [ -z "$VITE_GOOGLE_MAPS_API_KEY" ]; then \
      echo "ERROR: VITE_GOOGLE_MAPS_API_KEY build arg is required." >&2; \
      exit 1; \
    fi

ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_GOOGLE_MAPS_API_KEY=${VITE_GOOGLE_MAPS_API_KEY}

RUN npm run build

# ---- Serve stage ----
FROM nginx:alpine
COPY --from=build /app/dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
