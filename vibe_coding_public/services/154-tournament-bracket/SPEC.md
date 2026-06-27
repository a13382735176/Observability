# 154-tournament-bracket

Single-elimination tournament bracket service. Tracks tournaments, player registration (capped at `max_players`), and round-by-round bracket matches in Postgres; auto-generates the next round once all current-round matches are resolved.

**Stack:** TypeScript / Fastify on `node:20-alpine`
**Deps:** postgres (2 s `connectionTimeoutMillis` + `statement_timeout`)

Endpoints: `GET /healthz`, `POST /tournaments`, `POST /tournaments/:id/register`, `POST /tournaments/:id/bracket`, `POST /matches/:match_id/result`, `GET /tournaments/:id`. Errors logged as `tournament-bracket: ...` at ERROR level.
