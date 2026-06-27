use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post, put},
    Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::env;
use std::net::SocketAddr;
use std::time::Duration;
use tracing::error;

const SERVICE: &str = "media-encoder-svc";

#[derive(Clone)]
struct AppState {
    pg: PgPool,
    redis_client: redis::Client,
}

#[derive(Deserialize)]
struct NewJob {
    input_url: String,
    format: String,
    quality: String,
}

#[derive(Deserialize)]
struct CompleteJob {
    output_url: String,
    duration_sec: i32,
}

#[derive(Serialize, sqlx::FromRow)]
struct EncodingJob {
    id: i64,
    input_url: String,
    output_url: Option<String>,
    format: String,
    quality: String,
    status: String,
    duration_sec: Option<i32>,
    started_at: Option<DateTime<Utc>>,
    completed_at: Option<DateTime<Utc>>,
    created_at: DateTime<Utc>,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();

    let pg_dsn = env::var("PG_DSN")
        .unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let redis_url = env::var("REDIS_STREAM_URL")
        .unwrap_or_else(|_| "redis://redis-stream:6379".to_string());

    let pg = match PgPoolOptions::new()
        .max_connections(4)
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
        "CREATE TABLE IF NOT EXISTS encoding_jobs(
            id bigserial PRIMARY KEY,
            input_url text,
            output_url text,
            format text,
            quality text,
            status text default 'queued',
            duration_sec int,
            started_at timestamptz,
            completed_at timestamptz,
            created_at timestamptz default now()
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
        .route("/jobs", post(create_job))
        .route("/jobs/:id", get(get_job))
        .route("/jobs/:id/start", put(start_job))
        .route("/jobs/:id/complete", put(complete_job))
        .route("/jobs/queue", get(queue))
        .with_state(state);

    let addr: SocketAddr = "0.0.0.0:8080".parse().unwrap();
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    println!("{}: listening on {}", SERVICE, addr);
    if let Err(e) = axum::serve(listener, app).await {
        error!("{}: server: {}", SERVICE, e);
    }
}

async fn healthz() -> impl IntoResponse {
    Json(json!({"status": "ok", "service": SERVICE}))
}

async fn xadd(client: &redis::Client, stream: &str, fields: &[(&str, &str)]) {
    match client.get_async_connection().await {
        Ok(mut conn) => {
            let mut cmd = redis::cmd("XADD");
            cmd.arg(stream).arg("*");
            for (k, v) in fields {
                cmd.arg(*k).arg(*v);
            }
            let r: Result<redis::Value, _> =
                tokio::time::timeout(Duration::from_secs(2), cmd.query_async(&mut conn))
                    .await
                    .unwrap_or(Ok(redis::Value::Nil));
            if let Err(e) = r {
                error!("{}: xadd {}: {}", SERVICE, stream, e);
            }
        }
        Err(e) => error!("{}: redis conn: {}", SERVICE, e),
    }
}

async fn create_job(
    State(s): State<AppState>,
    Json(r): Json<NewJob>,
) -> Result<Json<EncodingJob>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, EncodingJob>(
        "INSERT INTO encoding_jobs(input_url, format, quality) VALUES($1,$2,$3) \
         RETURNING id, input_url, output_url, format, quality, status, duration_sec, \
                   started_at, completed_at, created_at",
    )
    .bind(&r.input_url)
    .bind(&r.format)
    .bind(&r.quality);

    match tokio::time::timeout(Duration::from_secs(2), q.fetch_one(&s.pg)).await {
        Ok(Ok(job)) => {
            let id_str = job.id.to_string();
            xadd(&s.redis_client, "events:enc_jobs",
                 &[("id", &id_str), ("format", &job.format)]).await;
            Ok(Json(job))
        }
        Ok(Err(e)) => {
            error!("{}: create job: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: create job: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn get_job(
    State(s): State<AppState>,
    Path(id): Path<i64>,
) -> Result<Json<EncodingJob>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, EncodingJob>(
        "SELECT id, input_url, output_url, format, quality, status, duration_sec, \
                started_at, completed_at, created_at FROM encoding_jobs WHERE id=$1",
    )
    .bind(id);
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_optional(&s.pg)).await {
        Ok(Ok(Some(job))) => Ok(Json(job)),
        Ok(Ok(None)) => Err((StatusCode::NOT_FOUND, "not found".into())),
        Ok(Err(e)) => {
            error!("{}: get job: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: get job: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn start_job(
    State(s): State<AppState>,
    Path(id): Path<i64>,
) -> Result<Json<EncodingJob>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, EncodingJob>(
        "UPDATE encoding_jobs SET status='running', started_at=now() WHERE id=$1 \
         RETURNING id, input_url, output_url, format, quality, status, duration_sec, \
                   started_at, completed_at, created_at",
    )
    .bind(id);
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_optional(&s.pg)).await {
        Ok(Ok(Some(job))) => {
            let id_str = job.id.to_string();
            xadd(&s.redis_client, "events:enc_started", &[("id", &id_str)]).await;
            Ok(Json(job))
        }
        Ok(Ok(None)) => Err((StatusCode::NOT_FOUND, "not found".into())),
        Ok(Err(e)) => {
            error!("{}: start job: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: start job: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn complete_job(
    State(s): State<AppState>,
    Path(id): Path<i64>,
    Json(r): Json<CompleteJob>,
) -> Result<Json<EncodingJob>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, EncodingJob>(
        "UPDATE encoding_jobs SET status='complete', completed_at=now(), \
                output_url=$2, duration_sec=$3 WHERE id=$1 \
         RETURNING id, input_url, output_url, format, quality, status, duration_sec, \
                   started_at, completed_at, created_at",
    )
    .bind(id)
    .bind(&r.output_url)
    .bind(r.duration_sec);
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_optional(&s.pg)).await {
        Ok(Ok(Some(job))) => {
            let id_str = job.id.to_string();
            xadd(&s.redis_client, "events:enc_complete", &[("id", &id_str)]).await;
            Ok(Json(job))
        }
        Ok(Ok(None)) => Err((StatusCode::NOT_FOUND, "not found".into())),
        Ok(Err(e)) => {
            error!("{}: complete job: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: complete job: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn queue(State(s): State<AppState>) -> Result<Json<Vec<EncodingJob>>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, EncodingJob>(
        "SELECT id, input_url, output_url, format, quality, status, duration_sec, \
                started_at, completed_at, created_at FROM encoding_jobs \
         WHERE status='queued' ORDER BY id LIMIT 50",
    );
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rs)) => Ok(Json(rs)),
        Ok(Err(e)) => {
            error!("{}: queue: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: queue: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}
