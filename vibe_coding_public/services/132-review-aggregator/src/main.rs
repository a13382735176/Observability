use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Utc};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::env;
use std::net::SocketAddr;
use std::time::Duration;
use tracing::error;

const SERVICE: &str = "review-aggregator";

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
struct NewReview {
    entity_id: String,
    entity_type: String,
    rating: i32,
    body: String,
    author_id: String,
}

#[derive(Serialize, sqlx::FromRow)]
struct Review {
    id: i32,
    entity_id: String,
    entity_type: String,
    rating: i32,
    body: String,
    author_id: String,
    created_at: DateTime<Utc>,
}

#[derive(Serialize, Deserialize)]
struct Aggregate {
    avg: f64,
    count: i64,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_target(false)
        .init();

    let pg_dsn = env::var("PG_DSN")
        .unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let redis_url = env::var("REDIS_URL")
        .unwrap_or_else(|_| "redis://redis-cache:6379".to_string());

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
        "CREATE TABLE IF NOT EXISTS aggregated_reviews(
            id serial PRIMARY KEY,
            entity_id text,
            entity_type text,
            rating int,
            body text,
            author_id text,
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
        .route("/reviews", post(create_review))
        .route("/reviews/:entity_id", get(list_reviews))
        .route("/aggregate/:entity_type/:entity_id", get(aggregate))
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

async fn create_review(
    State(s): State<AppState>,
    Json(r): Json<NewReview>,
) -> Result<Json<Review>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, Review>(
        "INSERT INTO aggregated_reviews(entity_id, entity_type, rating, body, author_id) \
         VALUES($1,$2,$3,$4,$5) RETURNING id, entity_id, entity_type, rating, body, author_id, created_at",
    )
    .bind(&r.entity_id)
    .bind(&r.entity_type)
    .bind(r.rating)
    .bind(&r.body)
    .bind(&r.author_id);

    let row = tokio::time::timeout(Duration::from_secs(2), q.fetch_one(&s.pg)).await;
    match row {
        Ok(Ok(rev)) => {
            let key = format!("agg:{}:{}", rev.entity_type, rev.entity_id);
            if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                let _: Result<(), _> = conn.del(&key).await;
            }
            Ok(Json(rev))
        }
        Ok(Err(e)) => {
            error!("{}: insert review: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: insert review: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn list_reviews(
    State(s): State<AppState>,
    Path(entity_id): Path<String>,
) -> Result<Json<Vec<Review>>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, Review>(
        "SELECT id, entity_id, entity_type, rating, body, author_id, created_at \
         FROM aggregated_reviews WHERE entity_id=$1 ORDER BY created_at DESC LIMIT 50",
    )
    .bind(&entity_id);
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rs)) => Ok(Json(rs)),
        Ok(Err(e)) => {
            error!("{}: list reviews: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: list reviews: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn aggregate(
    State(s): State<AppState>,
    Path((entity_type, entity_id)): Path<(String, String)>,
) -> impl IntoResponse {
    let key = format!("agg:{}:{}", entity_type, entity_id);

    // Try cache first
    match s.redis_client.get_async_connection().await {
        Ok(mut conn) => {
            let cached: Result<Option<String>, _> =
                tokio::time::timeout(Duration::from_secs(2), conn.get(&key))
                    .await
                    .unwrap_or(Ok(None));
            if let Ok(Some(v)) = cached {
                if let Ok(agg) = serde_json::from_str::<Aggregate>(&v) {
                    return Json(agg).into_response();
                }
            }
        }
        Err(e) => {
            error!("{}: redis conn: {}", SERVICE, e);
        }
    }

    // Compute from postgres
    let row: Result<(Option<f64>, i64), _> = tokio::time::timeout(
        Duration::from_secs(2),
        sqlx::query_as::<_, (Option<f64>, i64)>(
            "SELECT AVG(rating::float8), COUNT(*) FROM aggregated_reviews \
             WHERE entity_type=$1 AND entity_id=$2",
        )
        .bind(&entity_type)
        .bind(&entity_id)
        .fetch_one(&s.pg),
    )
    .await
    .unwrap_or(Err(sqlx::Error::PoolTimedOut));

    match row {
        Ok((avg, count)) => {
            let agg = Aggregate { avg: avg.unwrap_or(0.0), count };
            if let Ok(payload) = serde_json::to_string(&agg) {
                if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                    let _: Result<(), _> =
                        conn.set_ex(&key, payload, 300).await;
                }
            }
            Json(agg).into_response()
        }
        Err(e) => {
            error!("{}: aggregate: {}", SERVICE, e);
            (StatusCode::BAD_GATEWAY, format!("db error: {}", e)).into_response()
        }
    }
}
