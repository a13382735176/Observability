FROM rust:1.88-slim AS build
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY src/Cargo.toml src/Cargo.lock* ./
RUN mkdir -p src && echo 'fn main(){}' > src/main.rs && cargo build --release 2>/dev/null || true
COPY src/src/ ./src/
RUN touch src/main.rs && cargo build --release
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/target/release/obd-parser /app
EXPOSE 8080
CMD ["/app"]
