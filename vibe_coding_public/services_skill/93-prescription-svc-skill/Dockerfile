FROM golang:1.24-alpine AS build
RUN apk add --no-cache git
WORKDIR /app
COPY src/ .
RUN go mod tidy && CGO_ENABLED=0 go build -o /app/server .
FROM alpine:3.20
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /app/server .
EXPOSE 8080
CMD ["./server"]
