# 176-retention-cohort
.NET 8 minimal API that records user signups and daily activity, then computes D1/D7/D30 cohort retention.
Stack: ASP.NET Core 8, Npgsql 8.0.4, Postgres tables user_signups (PK user_id) and user_activity (UNIQUE user_id, activity_date).
Endpoints: POST /signups, POST /activity, GET /retention/:signup_date, GET /signups/cohorts, GET /activity/user/:user_id, GET /healthz.
Retention math: cohort_size = signups on date D; dN = distinct users whose activity_date = D + N days, divided by cohort_size (0 if cohort empty).
