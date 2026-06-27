FROM rust:1.88-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /work
COPY src/Cargo.toml .
RUN mkdir -p src && echo 'fn main(){}' > src/main.rs && cargo build --release && rm -rf src target/release/deps/media_encoder*
COPY src/src/ src/
RUN touch src/main.rs && cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libssl3 && rm -rf /var/lib/apt/lists/*
COPY --from=build /work/target/release/media-encoder-svc /app
EXPOSE 8080
CMD ["/app"]
