FROM golang:1.24-alpine AS build
RUN apk add --no-cache git
WORKDIR /app
COPY src/ .
RUN go mod tidy && go build -o server .
FROM alpine:3.19
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /app/server .
EXPOSE 8080
CMD ["./server"]
