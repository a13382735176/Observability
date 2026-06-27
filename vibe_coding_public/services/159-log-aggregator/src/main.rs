use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Utc};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::collections::HashMap;
use std::env;
use std::net::SocketAddr;
use std::time::Duration;
use tracing::error;

const SERVICE: &str = "log-aggregator";

#[derive(Clone)]
struct AppState {
    pg: PgPool,
    redis_client: redis::Client,
}

#[derive(Serialize)]
struct Health {
    status: &'static str,
    service: &'static str,
}

#[derive(Deserialize)]
struct NewLog {
    service: String,
    level: String,
    message: String,
    #[serde(default)]
    fields: JsonValue,
}

#[derive(Serialize, sqlx::FromRow)]
struct LogEntry {
    id: i64,
    service: String,
    level: String,
    message: String,
    fields: JsonValue,
    created_at: DateTime<Utc>,
}

#[derive(Deserialize)]
struct LogQuery {
    service: Option<String>,
    level: Option<String>,
    limit: Option<i64>,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();

    let pg_dsn = env::var("PG_DSN")
        .unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let redis_url = env::var("REDIS_URL")
        .unwrap_or_else(|_| "redis://redis-stream:6379".to_string());

    let pg = match PgPoolOptions::new()
        .max_connections(8)
        .acquire_timeout(Duration::from_secs(2))
        .connect(&pg_dsn)
        .await
    {
        Ok(p) => p,
        Err(e) => {
            error!("{}: pg connect: {}", SERVICE, e);
            std::process::exit(1);
        }
    };

    if let Err(e) = sqlx::query(
        "CREATE TABLE IF NOT EXISTS log_entries(
            id bigserial PRIMARY KEY,
            service text NOT NULL,
            level text NOT NULL,
            message text NOT NULL,
            fields jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )",
    )
    .execute(&pg)
    .await
    {
        error!("{}: create table: {}", SERVICE, e);
    }

    let redis_client = match redis::Client::open(redis_url) {
        Ok(c) => c,
        Err(e) => {
            error!("{}: redis open: {}", SERVICE, e);
            std::process::exit(1);
        }
    };

    let state = AppState { pg, redis_client };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/logs", post(create_log).get(query_logs))
        .route("/logs/recent", get(recent_logs))
        .route("/errors/stream", get(error_stream))
        .with_state(state);

    let addr: SocketAddr = "0.0.0.0:8080".parse().unwrap();
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    println!("{}: listening on {}", SERVICE, addr);
    if let Err(e) = axum::serve(listener, app).await {
        error!("{}: server: {}", SERVICE, e);
    }
}

async fn healthz() -> Json<Health> {
    Json(Health { status: "ok", service: SERVICE })
}

async fn create_log(
    State(s): State<AppState>,
    Json(r): Json<NewLog>,
) -> Result<Json<LogEntry>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, LogEntry>(
        "INSERT INTO log_entries(service, level, message, fields) \
         VALUES($1,$2,$3,$4) RETURNING id, service, level, message, fields, created_at",
    )
    .bind(&r.service)
    .bind(&r.level)
    .bind(&r.message)
    .bind(&r.fields);

    let row = tokio::time::timeout(Duration::from_secs(2), q.fetch_one(&s.pg)).await;
    let entry = match row {
        Ok(Ok(e)) => e,
        Ok(Err(e)) => {
            error!("{}: insert log: {}", SERVICE, e);
            return Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)));
        }
        Err(_) => {
            error!("{}: insert log: timeout", SERVICE);
            return Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()));
        }
    };

    if entry.level.eq_ignore_ascii_case("error") {
        let svc = entry.service.clone();
        let msg = entry.message.clone();
        let id = entry.id;
        match tokio::time::timeout(Duration::from_secs(2), s.redis_client.get_async_connection()).await {
            Ok(Ok(mut conn)) => {
                let items: Vec<(&str, String)> = vec![
                    ("service", svc),
                    ("message", msg),
                    ("id", id.to_string()),
                ];
                let xadd = redis::cmd("XADD")
                    .arg("events:errors")
                    .arg("*")
                    .arg(&items)
                    .query_async::<_, String>(&mut conn);
                if let Err(e) = tokio::time::timeout(Duration::from_secs(2), xadd).await.unwrap_or_else(|_| Err(redis::RedisError::from((redis::ErrorKind::IoError, "timeout")))) {
                    error!("{}: redis xadd errors: {}", SERVICE, e);
                }
            }
            Ok(Err(e)) => error!("{}: redis conn: {}", SERVICE, e),
            Err(_) => error!("{}: redis conn: timeout", SERVICE),
        }
    }

    Ok(Json(entry))
}

async fn query_logs(
    State(s): State<AppState>,
    Query(q): Query<LogQuery>,
) -> Result<Json<Vec<LogEntry>>, (StatusCode, String)> {
    let limit = q.limit.unwrap_or(50).clamp(1, 200);
    let service = q.service.unwrap_or_default();
    let level = q.level.unwrap_or_default();

    let stmt = if !service.is_empty() && !level.is_empty() {
        sqlx::query_as::<_, LogEntry>(
            "SELECT id, service, level, message, fields, created_at FROM log_entries \
             WHERE service=$1 AND level=$2 ORDER BY id DESC LIMIT $3",
        )
        .bind(&service)
        .bind(&level)
        .bind(limit)
    } else if !service.is_empty() {
        sqlx::query_as::<_, LogEntry>(
            "SELECT id, service, level, message, fields, created_at FROM log_entries \
             WHERE service=$1 ORDER BY id DESC LIMIT $2",
        )
        .bind(&service)
        .bind(limit)
    } else if !level.is_empty() {
        sqlx::query_as::<_, LogEntry>(
            "SELECT id, service, level, message, fields, created_at FROM log_entries \
             WHERE level=$1 ORDER BY id DESC LIMIT $2",
        )
        .bind(&level)
        .bind(limit)
    } else {
        sqlx::query_as::<_, LogEntry>(
            "SELECT id, service, level, message, fields, created_at FROM log_entries \
             ORDER BY id DESC LIMIT $1",
        )
        .bind(limit)
    };

    match tokio::time::timeout(Duration::from_secs(2), stmt.fetch_all(&s.pg)).await {
        Ok(Ok(rs)) => Ok(Json(rs)),
        Ok(Err(e)) => {
            error!("{}: query logs: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: query logs: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn recent_logs(
    State(s): State<AppState>,
) -> Result<Json<Vec<LogEntry>>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, LogEntry>(
        "SELECT id, service, level, message, fields, created_at FROM log_entries \
         ORDER BY id DESC LIMIT 100",
    );
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rs)) => Ok(Json(rs)),
        Ok(Err(e)) => {
            error!("{}: recent logs: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: recent logs: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn error_stream(State(s): State<AppState>) -> impl IntoResponse {
    let mut conn = match tokio::time::timeout(Duration::from_secs(2), s.redis_client.get_async_connection()).await {
        Ok(Ok(c)) => c,
        Ok(Err(e)) => {
            error!("{}: redis conn: {}", SERVICE, e);
            return (StatusCode::BAD_GATEWAY, format!("redis error: {}", e)).into_response();
        }
        Err(_) => {
            error!("{}: redis conn: timeout", SERVICE);
            return (StatusCode::GATEWAY_TIMEOUT, "redis timeout".to_string()).into_response();
        }
    };

    let xrev = redis::cmd("XREVRANGE")
        .arg("events:errors")
        .arg("+")
        .arg("-")
        .arg("COUNT")
        .arg(50)
        .query_async::<_, redis::Value>(&mut conn);

    match tokio::time::timeout(Duration::from_secs(2), xrev).await {
        Ok(Ok(val)) => {
            let entries = decode_xrange(val);
            Json(entries).into_response()
        }
        Ok(Err(e)) => {
            error!("{}: redis xrevrange errors: {}", SERVICE, e);
            (StatusCode::BAD_GATEWAY, format!("redis error: {}", e)).into_response()
        }
        Err(_) => {
            error!("{}: redis xrevrange errors: timeout", SERVICE);
            (StatusCode::GATEWAY_TIMEOUT, "redis timeout".to_string()).into_response()
        }
    }
}

fn decode_xrange(v: redis::Value) -> Vec<HashMap<String, String>> {
    let mut out = Vec::new();
    if let redis::Value::Bulk(entries) = v {
        for entry in entries {
            if let redis::Value::Bulk(pair) = entry {
                if pair.len() != 2 {
                    continue;
                }
                let id = match &pair[0] {
                    redis::Value::Data(b) => String::from_utf8_lossy(b).to_string(),
                    redis::Value::Status(s) => s.clone(),
                    _ => String::new(),
                };
                let mut map = HashMap::new();
                map.insert("_id".to_string(), id);
                if let redis::Value::Bulk(fields) = &pair[1] {
                    let mut i = 0;
                    while i + 1 < fields.len() {
                        let k = match &fields[i] {
                            redis::Value::Data(b) => String::from_utf8_lossy(b).to_string(),
                            redis::Value::Status(s) => s.clone(),
                            _ => String::new(),
                        };
                        let val = match &fields[i + 1] {
                            redis::Value::Data(b) => String::from_utf8_lossy(b).to_string(),
                            redis::Value::Status(s) => s.clone(),
                            _ => String::new(),
                        };
                        map.insert(k, val);
                        i += 2;
                    }
                }
                out.push(map);
            }
        }
    }
    out
}
