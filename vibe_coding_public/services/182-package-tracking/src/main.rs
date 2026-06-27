use axum::{
    extract::{Path, State},
    http::StatusCode,
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

const SERVICE: &str = "package-tracking";

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
struct NewPackage {
    tracking_number: String,
    origin: String,
    destination: String,
    weight_kg: f64,
}

#[derive(Serialize, Deserialize, sqlx::FromRow)]
struct Package {
    id: i64,
    tracking_number: String,
    origin: String,
    destination: String,
    weight_kg: f64,
    current_status: String,
    created_at: DateTime<Utc>,
}

#[derive(Deserialize)]
struct NewCheckpoint {
    location: String,
    status: String,
}

#[derive(Serialize, sqlx::FromRow)]
struct Checkpoint {
    id: i64,
    package_id: i64,
    location: String,
    status: String,
    recorded_at: DateTime<Utc>,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();

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
        "CREATE TABLE IF NOT EXISTS packages(
            id bigserial PRIMARY KEY,
            tracking_number text UNIQUE,
            origin text,
            destination text,
            weight_kg double precision,
            current_status text DEFAULT 'created',
            created_at timestamptz DEFAULT now()
        )",
    )
    .execute(&pg)
    .await
    {
        error!("{}: create packages: {}", SERVICE, e);
    }
    if let Err(e) = sqlx::query(
        "CREATE TABLE IF NOT EXISTS package_checkpoints(
            id bigserial PRIMARY KEY,
            package_id bigint,
            location text,
            status text,
            recorded_at timestamptz DEFAULT now()
        )",
    )
    .execute(&pg)
    .await
    {
        error!("{}: create package_checkpoints: {}", SERVICE, e);
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
        .route("/packages", post(create_package))
        .route("/packages/active", get(list_active))
        .route("/packages/:tracking_number", get(get_package))
        .route(
            "/packages/:tracking_number/checkpoint",
            post(add_checkpoint),
        )
        .route("/packages/:tracking_number/history", get(history))
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

async fn create_package(
    State(s): State<AppState>,
    Json(p): Json<NewPackage>,
) -> Result<Json<Package>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, Package>(
        "INSERT INTO packages(tracking_number, origin, destination, weight_kg) \
         VALUES($1,$2,$3,$4) \
         RETURNING id, tracking_number, origin, destination, weight_kg, current_status, created_at",
    )
    .bind(&p.tracking_number)
    .bind(&p.origin)
    .bind(&p.destination)
    .bind(p.weight_kg);

    match tokio::time::timeout(Duration::from_secs(2), q.fetch_one(&s.pg)).await {
        Ok(Ok(pkg)) => Ok(Json(pkg)),
        Ok(Err(e)) => {
            error!("{}: insert package: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: insert package: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn get_package(
    State(s): State<AppState>,
    Path(tn): Path<String>,
) -> Result<Json<Package>, (StatusCode, String)> {
    let key = format!("pkg:{}", tn);

    if let Ok(mut conn) = s.redis_client.get_async_connection().await {
        let cached: Result<Option<String>, _> =
            tokio::time::timeout(Duration::from_secs(2), conn.get(&key))
                .await
                .unwrap_or(Ok(None));
        if let Ok(Some(v)) = cached {
            if let Ok(pkg) = serde_json::from_str::<Package>(&v) {
                return Ok(Json(pkg));
            }
        }
    }

    let q = sqlx::query_as::<_, Package>(
        "SELECT id, tracking_number, origin, destination, weight_kg, current_status, created_at \
         FROM packages WHERE tracking_number=$1",
    )
    .bind(&tn);

    match tokio::time::timeout(Duration::from_secs(2), q.fetch_optional(&s.pg)).await {
        Ok(Ok(Some(pkg))) => {
            if let Ok(payload) = serde_json::to_string(&pkg) {
                if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                    let _: Result<(), _> = conn.set_ex(&key, payload, 300).await;
                }
            }
            Ok(Json(pkg))
        }
        Ok(Ok(None)) => Err((StatusCode::NOT_FOUND, "not found".into())),
        Ok(Err(e)) => {
            error!("{}: get package: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: get package: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn add_checkpoint(
    State(s): State<AppState>,
    Path(tn): Path<String>,
    Json(c): Json<NewCheckpoint>,
) -> Result<Json<Checkpoint>, (StatusCode, String)> {
    let pkg_id: Result<i64, _> = tokio::time::timeout(
        Duration::from_secs(2),
        sqlx::query_scalar::<_, i64>("SELECT id FROM packages WHERE tracking_number=$1")
            .bind(&tn)
            .fetch_one(&s.pg),
    )
    .await
    .unwrap_or(Err(sqlx::Error::PoolTimedOut));

    let pkg_id = match pkg_id {
        Ok(id) => id,
        Err(sqlx::Error::RowNotFound) => {
            return Err((StatusCode::NOT_FOUND, "package not found".into()));
        }
        Err(e) => {
            error!("{}: lookup package: {}", SERVICE, e);
            return Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)));
        }
    };

    let q = sqlx::query_as::<_, Checkpoint>(
        "INSERT INTO package_checkpoints(package_id, location, status) \
         VALUES($1,$2,$3) \
         RETURNING id, package_id, location, status, recorded_at",
    )
    .bind(pkg_id)
    .bind(&c.location)
    .bind(&c.status);

    let cp = match tokio::time::timeout(Duration::from_secs(2), q.fetch_one(&s.pg)).await {
        Ok(Ok(cp)) => cp,
        Ok(Err(e)) => {
            error!("{}: insert checkpoint: {}", SERVICE, e);
            return Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)));
        }
        Err(_) => {
            error!("{}: insert checkpoint: timeout", SERVICE);
            return Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()));
        }
    };

    let _ = tokio::time::timeout(
        Duration::from_secs(2),
        sqlx::query("UPDATE packages SET current_status=$1 WHERE id=$2")
            .bind(&c.status)
            .bind(pkg_id)
            .execute(&s.pg),
    )
    .await;

    if let Ok(mut conn) = s.redis_client.get_async_connection().await {
        let _: Result<(), _> = conn.del(format!("pkg:{}", tn)).await;
    }

    Ok(Json(cp))
}

async fn history(
    State(s): State<AppState>,
    Path(tn): Path<String>,
) -> Result<Json<Vec<Checkpoint>>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, Checkpoint>(
        "SELECT c.id, c.package_id, c.location, c.status, c.recorded_at \
         FROM package_checkpoints c \
         JOIN packages p ON p.id = c.package_id \
         WHERE p.tracking_number=$1 \
         ORDER BY c.recorded_at ASC",
    )
    .bind(&tn);

    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rs)) => Ok(Json(rs)),
        Ok(Err(e)) => {
            error!("{}: history: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: history: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn list_active(
    State(s): State<AppState>,
) -> Result<Json<Vec<Package>>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, Package>(
        "SELECT id, tracking_number, origin, destination, weight_kg, current_status, created_at \
         FROM packages WHERE current_status <> 'delivered' \
         ORDER BY created_at DESC LIMIT 100",
    );
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rs)) => Ok(Json(rs)),
        Ok(Err(e)) => {
            error!("{}: active: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: active: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}
