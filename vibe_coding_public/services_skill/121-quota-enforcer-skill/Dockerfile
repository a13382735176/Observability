FROM golang:1.24-alpine AS build
WORKDIR /work
COPY src/ ./
RUN go mod tidy && CGO_ENABLED=0 go build -o /app ./...

FROM alpine:3.20
WORKDIR /app
COPY --from=build /app /app/app
EXPOSE 8080
ENTRYPOINT ["/app/app"]
