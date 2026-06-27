use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::Json,
    routing::{get, post},
    Router,
};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{env, sync::Arc};
use tokio::sync::Mutex;

#[derive(Clone)]
struct AppState {
    cache: Arc<Mutex<redis::aio::MultiplexedConnection>>,
    stream: Arc<Mutex<redis::aio::MultiplexedConnection>>,
}

#[derive(Deserialize)]
struct ParseReq {
    pid: String,
    raw_value: String,
}

#[derive(Serialize)]
struct ParseResp {
    pid: String,
    raw_value: String,
    decoded: f64,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let cache_host = env::var("REDIS_CACHE_HOST").unwrap_or_else(|_| "redis-cache".to_string());
    let stream_host = env::var("REDIS_STREAM_HOST").unwrap_or_else(|_| "redis-stream".to_string());

    let cache_client = redis::Client::open(format!("redis://{}:6379", cache_host)).unwrap();
    let stream_client = redis::Client::open(format!("redis://{}:6379", stream_host)).unwrap();

    let cache_conn = cache_client.get_multiplexed_async_connection().await
        .expect("cache connect");
    let stream_conn = stream_client.get_multiplexed_async_connection().await
        .expect("stream connect");

    let state = AppState {
        cache: Arc::new(Mutex::new(cache_conn)),
        stream: Arc::new(Mutex::new(stream_conn)),
    };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/parse", post(parse))
        .route("/cached/:pid", get(get_cached))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    tracing::info!("obd-parser listening on 8080");
    axum::serve(listener, app).await.unwrap();
}

async fn healthz() -> Json<Value> {
    Json(json!({"status": "ok", "service": "obd-parser"}))
}

async fn parse(
    State(state): State<AppState>,
    Json(req): Json<ParseReq>,
) -> Result<Json<Value>, StatusCode> {
    let raw = u64::from_str_radix(&req.raw_value, 16).unwrap_or(0);
    let decoded = raw as f64 * 0.0625;

    let key = format!("obd:{}", req.pid);
    let val = decoded.to_string();

    {
        let mut cache = state.cache.lock().await;
        let _: Result<(), _> = cache.set_ex::<_, _, ()>(&key, &val, 60).await;
    }

    {
        let mut stream = state.stream.lock().await;
        let _: Result<String, _> = stream.xadd("events:obd", "*", &[
            ("pid", req.pid.as_str()),
            ("raw", req.raw_value.as_str()),
            ("decoded", val.as_str()),
        ]).await.map_err(|e| {
            tracing::error!("obd-parser: {}", e);
            e
        });
    }

    Ok(Json(json!({"pid": req.pid, "raw_value": req.raw_value, "decoded": decoded})))
}

async fn get_cached(
    State(state): State<AppState>,
    Path(pid): Path<String>,
) -> Result<Json<Value>, StatusCode> {
    let key = format!("obd:{}", pid);
    let mut cache = state.cache.lock().await;
    let val: Option<String> = cache.get(&key).await.map_err(|e| {
        tracing::error!("obd-parser: {}", e);
        StatusCode::SERVICE_UNAVAILABLE
    })?;
    match val {
        Some(v) => Ok(Json(json!({"pid": pid, "decoded": v.parse::<f64>().unwrap_or(0.0)}))),
        None => Err(StatusCode::NOT_FOUND),
    }
}
