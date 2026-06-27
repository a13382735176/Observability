FROM golang:1.24-alpine AS build
WORKDIR /src
COPY src/go.mod ./
RUN go mod download || true
COPY src/ ./
RUN go mod tidy && CGO_ENABLED=0 go build -o /out/svc ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/svc /usr/local/bin/svc
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/svc"]
