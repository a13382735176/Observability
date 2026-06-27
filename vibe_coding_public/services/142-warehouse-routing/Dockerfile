FROM rust:1.88-slim AS build
WORKDIR /work
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml .
RUN mkdir -p src && echo 'fn main(){}' > src/main.rs && cargo build --release && rm -rf src target/release/deps/warehouse_routing*
COPY src/ src/
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libssl3 && rm -rf /var/lib/apt/lists/*
COPY --from=build /work/target/release/warehouse-routing /app
EXPOSE 8080
CMD ["/app"]
