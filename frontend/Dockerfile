FROM node:22-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

# Copy package files first for better caching
COPY package*.json ./

RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "run", "start"]
