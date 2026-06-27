FROM golang:1.24-alpine AS build
WORKDIR /src
COPY src/ .
RUN go mod tidy && CGO_ENABLED=0 go build -o /app ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /app /app
EXPOSE 8080
CMD ["/app"]
