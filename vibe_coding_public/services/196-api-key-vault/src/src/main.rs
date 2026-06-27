use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Utc};
use rand::Rng;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::env;
use std::net::SocketAddr;
use std::time::Duration;
use tracing::error;

const SERVICE: &str = "api-key-vault";

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
struct NewKey {
    name: String,
    scopes: Vec<String>,
    owner_id: String,
}

#[derive(Serialize)]
struct CreatedKey {
    key: String,
    name: String,
    scopes: Vec<String>,
    owner_id: String,
}

#[derive(Deserialize)]
struct VerifyReq {
    key: String,
}

#[derive(Serialize)]
struct VerifyResp {
    valid: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    owner_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    scopes: Option<Vec<String>>,
}

#[derive(Serialize, sqlx::FromRow)]
struct PublicKey {
    id: i64,
    name: String,
    scopes: serde_json::Value,
    owner_id: String,
    revoked: bool,
    created_at: DateTime<Utc>,
}

fn random_key() -> String {
    let mut rng = rand::thread_rng();
    let mut s = String::with_capacity(35);
    s.push_str("vk_");
    for _ in 0..32 {
        let n: u8 = rng.gen_range(0..16);
        s.push(match n {
            0..=9 => (b'0' + n) as char,
            _ => (b'a' + (n - 10)) as char,
        });
    }
    s
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();

    let pg_dsn = env::var("PG_DSN")
        .unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let redis_url = env::var("REDIS_URL")
        .unwrap_or_else(|_| "redis://redis-cache:6379".to_string());

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
        "CREATE TABLE IF NOT EXISTS api_keys(
            id bigserial PRIMARY KEY,
            name text,
            key text UNIQUE,
            scopes jsonb DEFAULT '[]'::jsonb,
            owner_id text,
            revoked boolean DEFAULT false,
            created_at timestamptz DEFAULT now()
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
        .route("/keys", post(create_key).get(list_active))
        .route("/verify", post(verify))
        .route("/keys/:id/revoke", post(revoke))
        .route("/keys/owner/:owner_id", get(list_by_owner))
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

async fn create_key(
    State(s): State<AppState>,
    Json(req): Json<NewKey>,
) -> Result<Json<CreatedKey>, (StatusCode, String)> {
    let key = random_key();
    let scopes_json = serde_json::to_value(&req.scopes).unwrap_or(json!([]));

    let q = sqlx::query(
        "INSERT INTO api_keys(name, key, scopes, owner_id) VALUES($1, $2, $3, $4)",
    )
    .bind(&req.name)
    .bind(&key)
    .bind(&scopes_json)
    .bind(&req.owner_id);

    match tokio::time::timeout(Duration::from_secs(2), q.execute(&s.pg)).await {
        Ok(Ok(_)) => {
            let cache_key = format!("vk:{}", key);
            let payload = json!({"owner_id": req.owner_id, "scopes": req.scopes}).to_string();
            if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                let _: Result<(), _> = conn.set_ex(&cache_key, payload, 600).await;
            }
            Ok(Json(CreatedKey {
                key,
                name: req.name,
                scopes: req.scopes,
                owner_id: req.owner_id,
            }))
        }
        Ok(Err(e)) => {
            error!("{}: insert key: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: insert key: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn verify(
    State(s): State<AppState>,
    Json(req): Json<VerifyReq>,
) -> impl IntoResponse {
    let cache_key = format!("vk:{}", req.key);

    // Try redis first.
    if let Ok(mut conn) = s.redis_client.get_async_connection().await {
        let cached: Result<Option<String>, _> =
            tokio::time::timeout(Duration::from_secs(2), conn.get(&cache_key))
                .await
                .unwrap_or(Ok(None));
        if let Ok(Some(v)) = cached {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&v) {
                let owner_id = val.get("owner_id").and_then(|x| x.as_str()).map(String::from);
                let scopes = val.get("scopes").and_then(|x| x.as_array()).map(|a| {
                    a.iter()
                        .filter_map(|x| x.as_str().map(String::from))
                        .collect::<Vec<_>>()
                });
                return Json(VerifyResp { valid: true, owner_id, scopes }).into_response();
            }
        }
    }

    // Miss → consult postgres.
    let row: Result<(String, serde_json::Value), _> = tokio::time::timeout(
        Duration::from_secs(2),
        sqlx::query_as::<_, (String, serde_json::Value)>(
            "SELECT owner_id, scopes FROM api_keys WHERE key=$1 AND revoked=false",
        )
        .bind(&req.key)
        .fetch_one(&s.pg),
    )
    .await
    .unwrap_or(Err(sqlx::Error::PoolTimedOut));

    match row {
        Ok((owner_id, scopes_v)) => {
            let scopes: Vec<String> = scopes_v
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|x| x.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default();
            let payload = json!({"owner_id": owner_id, "scopes": scopes}).to_string();
            if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                let _: Result<(), _> = conn.set_ex(&cache_key, payload, 600).await;
            }
            Json(VerifyResp {
                valid: true,
                owner_id: Some(owner_id),
                scopes: Some(scopes),
            })
            .into_response()
        }
        Err(sqlx::Error::RowNotFound) => {
            Json(VerifyResp { valid: false, owner_id: None, scopes: None }).into_response()
        }
        Err(e) => {
            error!("{}: verify: {}", SERVICE, e);
            (StatusCode::BAD_GATEWAY, format!("db error: {}", e)).into_response()
        }
    }
}

async fn revoke(
    State(s): State<AppState>,
    Path(id): Path<i64>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    // Fetch key first to invalidate redis.
    let key_row: Result<(String,), _> = tokio::time::timeout(
        Duration::from_secs(2),
        sqlx::query_as::<_, (String,)>("SELECT key FROM api_keys WHERE id=$1")
            .bind(id)
            .fetch_one(&s.pg),
    )
    .await
    .unwrap_or(Err(sqlx::Error::PoolTimedOut));

    let key = match key_row {
        Ok((k,)) => k,
        Err(sqlx::Error::RowNotFound) => {
            return Err((StatusCode::NOT_FOUND, "not found".into()));
        }
        Err(e) => {
            error!("{}: revoke select: {}", SERVICE, e);
            return Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)));
        }
    };

    let upd = sqlx::query("UPDATE api_keys SET revoked=true WHERE id=$1").bind(id);
    match tokio::time::timeout(Duration::from_secs(2), upd.execute(&s.pg)).await {
        Ok(Ok(_)) => {
            if let Ok(mut conn) = s.redis_client.get_async_connection().await {
                let cache_key = format!("vk:{}", key);
                let _: Result<(), _> = conn.del(&cache_key).await;
            }
            Ok(Json(json!({"id": id, "revoked": true})))
        }
        Ok(Err(e)) => {
            error!("{}: revoke update: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: revoke update: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn list_by_owner(
    State(s): State<AppState>,
    Path(owner_id): Path<String>,
) -> Result<Json<Vec<serde_json::Value>>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, (i64, String, serde_json::Value)>(
        "SELECT id, name, scopes FROM api_keys WHERE owner_id=$1 AND revoked=false ORDER BY id DESC",
    )
    .bind(&owner_id);

    match tokio::time::timeout(Duration::from_secs(2), q.fetch_all(&s.pg)).await {
        Ok(Ok(rows)) => {
            let out: Vec<serde_json::Value> = rows
                .into_iter()
                .map(|(id, name, scopes)| json!({"id": id, "name": name, "scopes": scopes}))
                .collect();
            Ok(Json(out))
        }
        Ok(Err(e)) => {
            error!("{}: list by owner: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: list by owner: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

async fn list_active(
    State(s): State<AppState>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let q = sqlx::query_as::<_, (i64,)>("SELECT COUNT(*) FROM api_keys WHERE revoked=false");
    match tokio::time::timeout(Duration::from_secs(2), q.fetch_one(&s.pg)).await {
        Ok(Ok((c,))) => Ok(Json(json!({"active": c}))),
        Ok(Err(e)) => {
            error!("{}: list active: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("db error: {}", e)))
        }
        Err(_) => {
            error!("{}: list active: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "db timeout".into()))
        }
    }
}

#[allow(dead_code)]
fn _suppress_unused_publickey() {
    let _ = std::mem::size_of::<PublicKey>();
}
