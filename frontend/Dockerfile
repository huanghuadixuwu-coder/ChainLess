FROM node:22-alpine

WORKDIR /app

# Copy package files first for better caching
COPY package*.json ./

RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
