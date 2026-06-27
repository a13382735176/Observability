FROM golang:1.24-alpine AS build
WORKDIR /src
COPY src/ .
RUN go mod tidy && CGO_ENABLED=0 go build -o /out/app ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /out/app /app/app
EXPOSE 8080
CMD ["/app/app"]
