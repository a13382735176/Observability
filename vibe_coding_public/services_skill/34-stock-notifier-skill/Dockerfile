FROM rust:1.88-slim AS build
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY src/ .
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/target/release/stock-notifier-skill /app
EXPOSE 8080
CMD ["/app"]
