FROM node:24-slim AS builder

WORKDIR /app/frontend

COPY package.json package-lock.json ./
COPY src/assets/kui-foundations-react-external-0.504.1.tgz ./src/assets/
RUN npm ci

COPY . .
RUN npm run build

FROM node:24-slim

ENV NODE_ENV=production \
    PORT=3000 \
    INGEST_API_URL=http://ingest-api:8000

WORKDIR /app/frontend

COPY --from=builder /app/frontend/dist ./dist
COPY --from=builder /app/frontend/server.mjs ./server.mjs

EXPOSE 3000

CMD ["node", "server.mjs"]
