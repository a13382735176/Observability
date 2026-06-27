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

const SERVICE: &str = "feature-store";

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

#[derive(Deserialize, Clone)]
struct NewFeature {
    entity_id: String,
    feature_name: String,
    value: f64,
    #[serde(default = "default_version")]
    version: i32,
}

fn default_version() -> i32 {
    1
}

#[derive(Serialize, sqlx::FromRow)]
struct Feature {
    id: i64,
    entity_id: String,
    feature_name: String,
    value: f64,
    version: i32,
    created_at: DateTime<Utc>,
}

#[derive(Serialize)]
struct CachedValue {
    value: f64,
    cached: bool,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();

    let pg_dsn = env::var("PG_DSN")
        .unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let redis_url =
        env::var("REDIS_URL").unwrap_or_else(|_| "redis://redis-cache:6379".to_string());

    let pg = match PgPoolOptions::new()
        .max_connections(8)
        .acquire_timeout(Duration::from_secs(2))
        .connect(&pg_dsn)
        .await
    {
        Ok(p) => p,
        Err(e) => {
            error!("feature-store: pg connect: {}", e);
            std::process::exit(1);
        }
    };

    if let Err(e) = sqlx::query(
        "CREATE TABLE IF NOT EXISTS features(
            id bigserial PRIMARY KEY,
            entity_id text,
            feature_name text,
            value double precision,
            version int DEFAULT 1,
            created_at timestamptz DEFAULT now()
        )",
    )
    .execute(&pg)
    .await
    {
        error!("feature-store: create table: {}", e);
    }

    let redis_client = match redis::Client::open(redis_url) {
        Ok(c) => c,
        Err(e) => {
            error!("feature-store: redis open: {}", e);
            std::process::exit(1);
        }
    };

    let state = AppState { pg, redis_client };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/features", post(create_feature))
        .route("/features/batch", post(create_batch))
        .route("/features/entity/:entity_id", get(list_entity))
        .route("/features/:entity_id/:feature_name", get(get_feature))
        .with_state(state);

    let addr: SocketAddr = "0.0.0.0:8080".parse().unwrap();
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    println!("feature-store: listening on {}", addr);
    if let Err(e) = axum::serve(listener, app).await {
        error!("feature-store: server: {}", e);
    }
}

async fn healthz() -> Json<Health> {
    Json(Health { status: "ok", service: SERVICE })
}

async fn insert_one(pg: &PgPool, f: &NewFeature) -> Result<Feature, sqlx::Error> {
    sqlx::query_as::<_, Feature>(
        "INSERT INTO features(entity_id, feature_name, value, version) \
         VALUES($1,$2,$3,$4) RETURNING id, entity_id, feature_name, value, version, created_at",
    )
    .bind(&f.entity_id)
    .bind(&f.feature_name)
    .bind(f.value)
    .bind(f.version)
    .fetch_one(pg)
    .await
}

async fn cache_set(client: &redis::Client, key: &str, value: f64) {
    match client.get_async_connection().await {
        Ok(mut conn) => {
            let r: Result<(), _> = tokio::time::timeout(
                Duration::from_secs(2),
                conn.set_ex(key, value.to_string(), 600),
            )
            .await
            .unwrap_or(Ok(()));
            if let Err(e) = r {
                error!("feature-store: cache set: {}", e);
            }
        }
        Err(e) => {
            error!("feature-store: redis conn: {}", e);
        }
    }
}

async fn create_feature(
    State(s): State<AppState>,
    Json(f): Json<NewFeature>,
) -> Result<Json<Feature>, (StatusCode, String)> {
    let row = tokio::time::timeout(Duration::from_secs(2), insert_one(&s.pg, &f)).await;
    match row {
        Ok(Ok(row)) => {
            let key = format!("feat:{}:{}", row.entity_id, row.feature_name);
            cache_set(&s.redis_client, &key, row.value).await;
            Ok(Json(row))
        }
        Ok(Err(e)) => {
            error!("feature-store: insert: {}", e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("feature-store: insert: timeout");
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn create_batch(
    State(s): State<AppState>,
    Json(items): Json<Vec<NewFeature>>,
) -> Result<Json<Vec<Feature>>, (StatusCode, String)> {
    if items.is_empty() {
        return Ok(Json(vec![]));
    }
    let mut out: Vec<Feature> = Vec::with_capacity(items.len());
    for f in items.iter() {
        match tokio::time::timeout(Duration::from_secs(2), insert_one(&s.pg, f)).await {
            Ok(Ok(row)) => {
                let key = format!("feat:{}:{}", row.entity_id, row.feature_name);
                cache_set(&s.redis_client, &key, row.value).await;
                out.push(row);
            }
            Ok(Err(e)) => {
                error!("feature-store: batch insert: {}", e);
                return Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)));
            }
            Err(_) => {
                error!("feature-store: batch insert: timeout");
                return Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()));
            }
        }
    }
    Ok(Json(out))
}

async fn get_feature(
    State(s): State<AppState>,
    Path((entity_id, feature_name)): Path<(String, String)>,
) -> impl IntoResponse {
    let key = format!("feat:{}:{}", entity_id, feature_name);

    // Cache first
    if let Ok(mut conn) = s.redis_client.get_async_connection().await {
        let v: Result<Option<String>, _> =
            tokio::time::timeout(Duration::from_secs(2), conn.get(&key))
                .await
                .unwrap_or(Ok(None));
        if let Ok(Some(s_val)) = v {
            if let Ok(parsed) = s_val.parse::<f64>() {
                return Json(CachedValue { value: parsed, cached: true }).into_response();
            }
        }
    }

    // DB fallback
    let row = tokio::time::timeout(
        Duration::from_secs(2),
        sqlx::query_as::<_, Feature>(
            "SELECT id, entity_id, feature_name, value, version, created_at \
             FROM features WHERE entity_id=$1 AND feature_name=$2 \
             ORDER BY version DESC, id DESC LIMIT 1",
        )
        .bind(&entity_id)
        .bind(&feature_name)
        .fetch_optional(&s.pg),
    )
    .await;

    match row {
        Ok(Ok(Some(f))) => {
            cache_set(&s.redis_client, &key, f.value).await;
            Json(CachedValue { value: f.value, cached: false }).into_response()
        }
        Ok(Ok(None)) => (StatusCode::NOT_FOUND, "not found".to_string()).into_response(),
        Ok(Err(e)) => {
            error!("feature-store: get: {}", e);
            (StatusCode::BAD_GATEWAY, format!("db error: {}", e)).into_response()
        }
        Err(_) => {
            error!("feature-store: get: timeout");
            (StatusCode::GATEWAY_TIMEOUT, "db timeout".to_string()).into_response()
        }
    }
}

async fn list_entity(
    State(s): State<AppState>,
    Path(entity_id): Path<String>,
) -> Result<Json<Vec<Feature>>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, Feature>(
        "SELECT DISTINCT ON (feature_name) \
                id, entity_id, feature_name, value, version, created_at \
         FROM features WHERE entity_id=$1 \
         ORDER BY feature_name, version DESC, id DESC",
    )
    .bind(&entity_id);
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rs)) => Ok(Json(rs)),
        Ok(Err(e)) => {
            error!("feature-store: list_entity: {}", e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("feature-store: list_entity: timeout");
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}
