FROM debian:bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ cmake ninja-build pkg-config ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN mkdir -p build && cd build && cmake -GNinja .. && ninja

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/app /usr/local/bin/app
EXPOSE 8080
CMD ["/usr/local/bin/app"]
