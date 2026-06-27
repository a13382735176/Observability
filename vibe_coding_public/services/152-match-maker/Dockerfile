FROM golang:1.24-alpine AS build
WORKDIR /work
COPY src/ ./
RUN go mod tidy && CGO_ENABLED=0 go build -o /out/app ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/app /app
EXPOSE 8080
CMD ["/app"]
