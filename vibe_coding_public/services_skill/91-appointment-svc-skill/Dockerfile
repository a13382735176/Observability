FROM node:20-alpine
WORKDIR /app
COPY src/package*.json ./
RUN npm install --no-audit --no-fund
COPY src/ ./src/
EXPOSE 8080
CMD ["npx", "ts-node", "src/index.ts"]
