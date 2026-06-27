FROM node:20-alpine
WORKDIR /app
COPY src/package*.json src/tsconfig.json ./
RUN npm install
COPY src/ .
EXPOSE 8080
CMD ["npx", "ts-node", "index.ts"]
