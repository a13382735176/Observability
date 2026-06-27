# 175-funnel-analyzer
Kotlin/Ktor service that defines conversion funnels, ingests user events, and computes per-step conversion rates.
Stack: Ktor 2.3.12, Postgres (funnels, funnel_events), Jedis 5.1.3 redis-cache (60s conversion result cache).
Endpoints: POST /funnels, POST /funnels/:id/track, GET /funnels/:id/conversion, GET /funnels, GET /funnels/:id/users-completed, GET /healthz.
Conversion = ordered step traversal: each step counts distinct users whose first event ts is strictly after their previous step's ts.
