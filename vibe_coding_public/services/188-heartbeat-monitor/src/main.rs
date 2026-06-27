use std::env;
use std::net::SocketAddr;
use std::time::Duration;

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
use tower_http::trace::{DefaultOnRequest, DefaultOnResponse, TraceLayer};
use tracing::{error, Level};

const SERVICE: &str = "heartbeat-monitor";

#[derive(Clone)]
struct AppState {
    cache: redis::Client,
    stream: redis::Client,
}

#[derive(Serialize)]
struct Health {
    status: &'static str,
    service: &'static str,
}

#[derive(Deserialize)]
struct BeatReq {
    service_id: String,
    status_code: i32,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();

    let cache_url =
        env::var("REDIS_CACHE_URL").unwrap_or_else(|_| "redis://redis-cache:6379".to_string());
    let stream_url =
        env::var("REDIS_STREAM_URL").unwrap_or_else(|_| "redis://redis-stream:6379".to_string());

    let cache = redis::Client::open(cache_url).expect("invalid redis-cache url");
    let stream = redis::Client::open(stream_url).expect("invalid redis-stream url");

    let state = AppState { cache, stream };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/beat", post(beat))
        .route("/status/:service_id", get(status))
        .route("/alive", get(alive))
        .route("/alarms", get(alarms))
        .with_state(state)
        .layer(
            TraceLayer::new_for_http()
                .on_request(DefaultOnRequest::new().level(Level::INFO))
                .on_response(DefaultOnResponse::new().level(Level::INFO)),
        );

    let addr: SocketAddr = "0.0.0.0:8080".parse().unwrap();
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    tracing::info!("{}: listening on {}", SERVICE, addr);
    axum::serve(listener, app).await.unwrap();
}

async fn healthz() -> Json<Health> {
    Json(Health {
        status: "ok",
        service: SERVICE,
    })
}

async fn beat(
    State(s): State<AppState>,
    Json(req): Json<BeatReq>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let key = format!("hb:{}", req.service_id);
    let set_fut = async {
        let mut conn = s.cache.get_async_connection().await?;
        let _: () = conn.set_ex(&key, req.status_code, 30).await?;
        Ok::<_, redis::RedisError>(())
    };
    match tokio::time::timeout(Duration::from_secs(2), set_fut).await {
        Ok(Ok(_)) => {}
        Ok(Err(e)) => {
            error!("{}: SETEX {}: {}", SERVICE, key, e);
            return Err((StatusCode::BAD_GATEWAY, format!("cache error: {}", e)));
        }
        Err(_) => {
            error!("{}: SETEX {}: timeout", SERVICE, key);
            return Err((StatusCode::GATEWAY_TIMEOUT, "cache timeout".into()));
        }
    }

    let mut emitted = false;
    if req.status_code != 200 {
        let stream_fut = async {
            let mut conn = s.stream.get_async_connection().await?;
            let _: String = conn
                .xadd(
                    "events:hb_down",
                    "*",
                    &[
                        ("service_id", req.service_id.clone()),
                        ("status_code", req.status_code.to_string()),
                    ],
                )
                .await?;
            Ok::<_, redis::RedisError>(())
        };
        match tokio::time::timeout(Duration::from_secs(2), stream_fut).await {
            Ok(Ok(_)) => emitted = true,
            Ok(Err(e)) => {
                error!("{}: XADD events:hb_down: {}", SERVICE, e);
            }
            Err(_) => {
                error!("{}: XADD events:hb_down: timeout", SERVICE);
            }
        }
    }

    Ok(Json(json!({
        "service_id": req.service_id,
        "status_code": req.status_code,
        "emitted": emitted,
    })))
}

async fn status(
    State(s): State<AppState>,
    Path(service_id): Path<String>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let key = format!("hb:{}", service_id);
    let fut = async {
        let mut conn = s.cache.get_async_connection().await?;
        let v: Option<i64> = conn.get(&key).await?;
        Ok::<_, redis::RedisError>(v)
    };
    match tokio::time::timeout(Duration::from_secs(2), fut).await {
        Ok(Ok(Some(code))) => Ok(Json(json!({
            "service_id": service_id,
            "status": "alive",
            "status_code": code,
        }))),
        Ok(Ok(None)) => Ok(Json(json!({
            "service_id": service_id,
            "status": "dead",
        }))),
        Ok(Err(e)) => {
            error!("{}: GET {}: {}", SERVICE, key, e);
            Err((StatusCode::BAD_GATEWAY, format!("cache error: {}", e)))
        }
        Err(_) => {
            error!("{}: GET {}: timeout", SERVICE, key);
            Err((StatusCode::GATEWAY_TIMEOUT, "cache timeout".into()))
        }
    }
}

async fn alive(
    State(s): State<AppState>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let fut = async {
        let mut conn = s.cache.get_async_connection().await?;
        let mut cursor: u64 = 0;
        let mut out: Vec<String> = Vec::new();
        loop {
            let (next, batch): (u64, Vec<String>) = redis::cmd("SCAN")
                .arg(cursor)
                .arg("MATCH")
                .arg("hb:*")
                .arg("COUNT")
                .arg(100)
                .query_async(&mut conn)
                .await?;
            for k in batch {
                if let Some(id) = k.strip_prefix("hb:") {
                    out.push(id.to_string());
                }
            }
            if next == 0 {
                break;
            }
            cursor = next;
        }
        Ok::<_, redis::RedisError>(out)
    };
    match tokio::time::timeout(Duration::from_secs(2), fut).await {
        Ok(Ok(ids)) => Ok(Json(json!({"alive": ids}))),
        Ok(Err(e)) => {
            error!("{}: SCAN hb:*: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("cache error: {}", e)))
        }
        Err(_) => {
            error!("{}: SCAN hb:*: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "cache timeout".into()))
        }
    }
}

async fn alarms(
    State(s): State<AppState>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let fut = async {
        let mut conn = s.stream.get_async_connection().await?;
        let reply: redis::streams::StreamRangeReply = redis::cmd("XREVRANGE")
            .arg("events:hb_down")
            .arg("+")
            .arg("-")
            .arg("COUNT")
            .arg(50)
            .query_async(&mut conn)
            .await?;
        Ok::<_, redis::RedisError>(reply.ids)
    };
    match tokio::time::timeout(Duration::from_secs(2), fut).await {
        Ok(Ok(msgs)) => {
            let out: Vec<Value> = msgs
                .into_iter()
                .map(|m| {
                    let mut fields = serde_json::Map::new();
                    for (k, v) in m.map.iter() {
                        let s = match v {
                            redis::Value::Data(b) => {
                                String::from_utf8_lossy(b).to_string()
                            }
                            other => format!("{:?}", other),
                        };
                        fields.insert(k.clone(), Value::String(s));
                    }
                    json!({"id": m.id, "values": Value::Object(fields)})
                })
                .collect();
            Ok(Json(json!(out)))
        }
        Ok(Err(e)) => {
            error!("{}: XREVRANGE events:hb_down: {}", SERVICE, e);
            Err((StatusCode::BAD_GATEWAY, format!("stream error: {}", e)))
        }
        Err(_) => {
            error!("{}: XREVRANGE events:hb_down: timeout", SERVICE);
            Err((StatusCode::GATEWAY_TIMEOUT, "stream timeout".into()))
        }
    }
}
