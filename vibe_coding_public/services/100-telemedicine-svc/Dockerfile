FROM elixir:1.16-alpine AS build
RUN apk add --no-cache build-base git
WORKDIR /app
COPY src/ .
RUN mix local.hex --force && mix local.rebar --force && mix deps.get --only prod && MIX_ENV=prod mix deps.compile && MIX_ENV=prod mix compile
FROM elixir:1.16-alpine
WORKDIR /app
ENV MIX_ENV=prod
RUN mix local.hex --force && mix local.rebar --force
COPY --from=build /app ./
EXPOSE 8080
CMD ["mix", "run", "--no-halt"]
