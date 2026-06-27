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

const SERVICE: &str = "warehouse-routing";

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
struct NewWarehouse {
    name: String,
    region: String,
    capacity: i32,
}

#[derive(Serialize, Deserialize, sqlx::FromRow, Clone)]
struct Warehouse {
    id: i64,
    name: String,
    region: String,
    capacity: i32,
    created_at: DateTime<Utc>,
}

#[derive(Deserialize)]
struct RouteReq {
    origin_zip: String,
    dest_zip: String,
}

#[derive(Serialize, Deserialize)]
struct RouteResp {
    warehouse_id: i64,
    distance: i32,
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
        "CREATE TABLE IF NOT EXISTS warehouses(
            id bigserial PRIMARY KEY,
            name text,
            region text,
            capacity int,
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
        .route("/warehouses", post(create_warehouse).get(list_warehouses))
        .route("/warehouses/:region", get(by_region))
        .route("/route", post(route))
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

async fn create_warehouse(
    State(s): State<AppState>,
    Json(w): Json<NewWarehouse>,
) -> Result<Json<Warehouse>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, Warehouse>(
        "INSERT INTO warehouses(name, region, capacity) VALUES($1,$2,$3) \
         RETURNING id, name, region, capacity, created_at",
    )
    .bind(&w.name)
    .bind(&w.region)
    .bind(w.capacity);

    match tokio::time::timeout(Duration::from_secs(2), q.fetch_one(&s.pg)).await {
        Ok(Ok(row)) => {
            let key = format!("wh:{}", row.region);
            if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                let _: Result<(), _> = conn.del(&key).await;
            }
            Ok(Json(row))
        }
        Ok(Err(e)) => {
            error!("{}: insert warehouse: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: insert warehouse: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn by_region(
    State(s): State<AppState>,
    Path(region): Path<String>,
) -> Result<Json<Vec<Warehouse>>, (StatusCode, String)> {
    let key = format!("wh:{}", region);

    if let Ok(mut conn) = s.redis_client.get_async_connection().await {
        let cached: Result<Option<String>, _> =
            tokio::time::timeout(Duration::from_secs(2), conn.get(&key))
                .await
                .unwrap_or(Ok(None));
        if let Ok(Some(v)) = cached {
            if let Ok(items) = serde_json::from_str::<Vec<Warehouse>>(&v) {
                return Ok(Json(items));
            }
        }
    }

    let q = sqlx::query_as::<_, Warehouse>(
        "SELECT id, name, region, capacity, created_at FROM warehouses \
         WHERE region=$1 ORDER BY id ASC",
    )
    .bind(&region);

    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rows)) => {
            if let Ok(payload) = serde_json::to_string(&rows) {
                if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                    let _: Result<(), _> = conn.set_ex(&key, payload, 300).await;
                }
            }
            Ok(Json(rows))
        }
        Ok(Err(e)) => {
            error!("{}: by_region: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: by_region: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn route(
    State(s): State<AppState>,
    Json(req): Json<RouteReq>,
) -> Result<Json<RouteResp>, (StatusCode, String)> {
    let prefix = if req.dest_zip.len() >= 2 {
        req.dest_zip[..2].to_string()
    } else {
        req.dest_zip.clone()
    };
    let cache_key = format!("route:{}:{}", req.origin_zip, req.dest_zip);

    if let Ok(mut conn) = s.redis_client.get_async_connection().await {
        let cached: Result<Option<String>, _> =
            tokio::time::timeout(Duration::from_secs(2), conn.get(&cache_key))
                .await
                .unwrap_or(Ok(None));
        if let Ok(Some(v)) = cached {
            if let Ok(r) = serde_json::from_str::<RouteResp>(&v) {
                return Ok(Json(r));
            }
        }
    }

    let pattern = format!("{}%", prefix);
    let q = sqlx::query_as::<_, (i64,)>(
        "SELECT id FROM warehouses WHERE region LIKE $1 ORDER BY id ASC LIMIT 1",
    )
    .bind(&pattern);

    match tokio::time::timeout(Duration::from_secs(2), q.fetch_optional(&s.pg)).await {
        Ok(Ok(Some((id,)))) => {
            let resp = RouteResp { warehouse_id: id, distance: 0 };
            if let Ok(payload) = serde_json::to_string(&resp) {
                if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                    let _: Result<(), _> = conn.set_ex(&cache_key, payload, 600).await;
                }
            }
            Ok(Json(resp))
        }
        Ok(Ok(None)) => Err((StatusCode::NOT_FOUND, "no warehouse for region".into())),
        Ok(Err(e)) => {
            error!("{}: route: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: route: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn list_warehouses(
    State(s): State<AppState>,
) -> Result<Json<Vec<Warehouse>>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, Warehouse>(
        "SELECT id, name, region, capacity, created_at FROM warehouses ORDER BY id ASC",
    );
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rows)) => Ok(Json(rows)),
        Ok(Err(e)) => {
            error!("{}: list_warehouses: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: list_warehouses: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}
