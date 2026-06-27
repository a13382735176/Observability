FROM rust:1.88-slim AS build
WORKDIR /work
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*
COPY src/ ./
RUN cargo build --release

FROM debian:bookworm-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /work/target/release/access-proxy-skill /app/access-proxy-skill
EXPOSE 8080
ENTRYPOINT ["/app/access-proxy-skill"]
