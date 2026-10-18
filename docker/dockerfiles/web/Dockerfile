FROM node:24-alpine AS build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json yarn.lock ./
RUN corepack enable && yarn install --frozen-lockfile
COPY . .
ARG SERVER_DOMAIN=http://app:8000
ENV SERVER_DOMAIN=${SERVER_DOMAIN}
RUN yarn build

FROM node:24-alpine
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 SERVER_DOMAIN=http://app:8000
RUN corepack enable
COPY --from=build --chown=node:node /web ./
USER node
EXPOSE 5173
CMD ["node", "node_modules/next/dist/bin/next", "start", "-H", "0.0.0.0", "-p", "5173"]
