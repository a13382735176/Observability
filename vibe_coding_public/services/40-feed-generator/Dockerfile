FROM rust:1.88-slim AS build
RUN apt-get update && apt-get install -y pkg-config libssl-dev libpq-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY src/ .
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y libssl3 libpq5 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/target/release/app .
EXPOSE 8080
CMD ["./app"]
