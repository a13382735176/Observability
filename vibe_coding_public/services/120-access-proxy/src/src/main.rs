use std::env;
use std::time::Duration;

use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{delete, get, post},
    Json, Router,
};
use redis::{AsyncCommands, Client};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

#[derive(Clone)]
struct AppState {
    client: Client,
}

#[derive(Deserialize)]
struct TokenReq {
    user_id: String,
    scopes: Vec<String>,
}

#[derive(Deserialize)]
struct ValidateReq {
    token: String,
}

#[derive(Serialize)]
struct TokenResp {
    token: String,
    user_id: String,
    scopes: Vec<String>,
    ttl: u64,
}

async fn healthz() -> impl IntoResponse {
    Json(json!({"status":"ok","service":"access-proxy"}))
}

async fn issue(State(st): State<AppState>, Json(req): Json<TokenReq>) -> impl IntoResponse {
    let token = Uuid::new_v4().to_string();
    let key = format!("token:{}", token);
    let scopes_str = req.scopes.join(",");

    match get_conn(&st.client).await {
        Ok(mut con) => {
            let h: Result<(), redis::RedisError> = redis::pipe()
                .hset(&key, "user_id", &req.user_id)
                .hset(&key, "scopes", &scopes_str)
                .expire(&key, 3600)
                .query_async(&mut con)
                .await;
            if let Err(e) = h {
                tracing::error!("access-proxy: redis hset: {}", e);
                return (StatusCode::BAD_GATEWAY, Json(json!({"error":"cache error"}))).into_response();
            }
        }
        Err(e) => {
            tracing::error!("access-proxy: redis connect: {}", e);
            return (StatusCode::BAD_GATEWAY, Json(json!({"error":"cache unavailable"}))).into_response();
        }
    }
    (
        StatusCode::CREATED,
        Json(json!({
            "token": token,
            "user_id": req.user_id,
            "scopes": req.scopes,
            "ttl": 3600
        })),
    )
        .into_response()
}

async fn validate(State(st): State<AppState>, Json(req): Json<ValidateReq>) -> impl IntoResponse {
    let key = format!("token:{}", req.token);
    let mut con = match get_conn(&st.client).await {
        Ok(c) => c,
        Err(e) => {
            tracing::error!("access-proxy: redis connect: {}", e);
            return (StatusCode::BAD_GATEWAY, Json(json!({"error":"cache unavailable"}))).into_response();
        }
    };
    let map: Result<std::collections::HashMap<String, String>, redis::RedisError> = con.hgetall(&key).await;
    match map {
        Ok(m) if !m.is_empty() => {
            let user_id = m.get("user_id").cloned().unwrap_or_default();
            let scopes: Vec<&str> = m.get("scopes").map(|s| s.split(',').collect()).unwrap_or_default();
            (
                StatusCode::OK,
                Json(json!({"valid": true, "user_id": user_id, "scopes": scopes})),
            )
                .into_response()
        }
        Ok(_) => (StatusCode::UNAUTHORIZED, Json(json!({"valid": false}))).into_response(),
        Err(e) => {
            tracing::error!("access-proxy: hgetall: {}", e);
            (StatusCode::BAD_GATEWAY, Json(json!({"error":"cache error"}))).into_response()
        }
    }
}

async fn revoke(State(st): State<AppState>, Path(token): Path<String>) -> impl IntoResponse {
    let key = format!("token:{}", token);
    match get_conn(&st.client).await {
        Ok(mut con) => {
            let n: Result<i64, redis::RedisError> = con.del(&key).await;
            match n {
                Ok(_) => (StatusCode::NO_CONTENT, Json(Value::Null)).into_response(),
                Err(e) => {
                    tracing::error!("access-proxy: del: {}", e);
                    (StatusCode::BAD_GATEWAY, Json(json!({"error":"cache error"}))).into_response()
                }
            }
        }
        Err(e) => {
            tracing::error!("access-proxy: redis connect: {}", e);
            (StatusCode::BAD_GATEWAY, Json(json!({"error":"cache unavailable"}))).into_response()
        }
    }
}

async fn get_conn(client: &Client) -> redis::RedisResult<redis::aio::Connection> {
    tokio::time::timeout(Duration::from_secs(2), client.get_async_connection())
        .await
        .map_err(|_| redis::RedisError::from((redis::ErrorKind::IoError, "connect timeout")))?
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    let host = env::var("REDIS_CACHE_HOST").unwrap_or_else(|_| "redis-cache".to_string());
    let port = env::var("REDIS_CACHE_PORT").unwrap_or_else(|_| "6379".to_string());
    let url = format!("redis://{}:{}/0", host, port);
    let client = Client::open(url).expect("redis url");
    let state = AppState { client };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/tokens", post(issue))
        .route("/validate", post(validate))
        .route("/tokens/:token", delete(revoke))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    tracing::info!("access-proxy: listening on 0.0.0.0:8080");
    axum::serve(listener, app).await.unwrap();
}
