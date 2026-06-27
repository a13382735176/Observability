use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use redis::{AsyncCommands, Client};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{env, net::SocketAddr, sync::Arc, time::{Instant, SystemTime, UNIX_EPOCH}};
use tracing::{error, info, warn};

const APP_LABEL: &str = "heartbeat-monitor-skill";
const DEFAULT_CACHE_URL: &str = "redis://redis-cache:6379";
const DEFAULT_STREAM_URL: &str = "redis://redis-stream:6379";
const HEARTBEAT_TTL_SECONDS: u64 = 30;
const HB_DOWN_STREAM: &str = "events:hb_down";

#[derive(Clone)]
struct AppState {
    cache: Client,
    stream: Client,
}

#[derive(Debug, Deserialize)]
struct BeatRequest {
    service_id: String,
    status_code: i64,
}

#[derive(Debug, Serialize)]
struct BeatResponse {
    service_id: String,
    status_code: i64,
    recorded: bool,
    alarm: bool,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: &'static str,
    service: &'static str,
}

#[derive(Debug, Serialize)]
struct StatusResponse {
    service_id: String,
    status: &'static str,
    alive: bool,
    status_code: Option<i64>,
}

#[derive(Debug, Serialize)]
struct AliveResponse {
    service_ids: Vec<String>,
}

#[derive(Debug, Serialize)]
struct AlarmEntry {
    id: String,
    fields: Value,
}

#[derive(Debug, Serialize)]
struct AlarmsResponse {
    alarms: Vec<AlarmEntry>,
}

#[derive(Debug)]
enum ApiError {
    BadRequest(String),
    Redis { operation: &'static str, source: redis::RedisError },
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        match self {
            ApiError::BadRequest(message) => {
                (StatusCode::BAD_REQUEST, Json(json!({ "error": message }))).into_response()
            }
            ApiError::Redis { operation, source } => {
                error!(
                    service = APP_LABEL,
                    operation,
                    dependency = "redis",
                    error = %source,
                    "redis operation failed"
                );
                (
                    StatusCode::SERVICE_UNAVAILABLE,
                    Json(json!({ "error": "redis unavailable" })),
                )
                    .into_response()
            }
        }
    }
}

#[tokio::main]
async fn main() {
    init_logging();

    let cache_url = env::var("REDIS_CACHE_URL").unwrap_or_else(|_| DEFAULT_CACHE_URL.to_string());
    let stream_url = env::var("REDIS_STREAM_URL").unwrap_or_else(|_| DEFAULT_STREAM_URL.to_string());
    let app_name = env::var("APP_NAME").unwrap_or_else(|_| APP_LABEL.to_string());

    let cache = Client::open(cache_url.as_str()).expect("REDIS_CACHE_URL must be a valid Redis URL");
    let stream = Client::open(stream_url.as_str()).expect("REDIS_STREAM_URL must be a valid Redis URL");
    let state = Arc::new(AppState { cache, stream });

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/beat", post(beat))
        .route("/status/:service_id", get(status))
        .route("/alive", get(alive))
        .route("/alarms", get(alarms))
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 8080));
    info!(service = %app_name, address = %addr, "starting heartbeat monitor");

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("failed to bind port 8080");

    if let Err(err) = axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
    {
        error!(service = APP_LABEL, error = %err, "server exited with error");
    }

    info!(service = APP_LABEL, "heartbeat monitor stopped");
}

fn init_logging() {
    let filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(filter)
        .with_current_span(false)
        .with_span_list(false)
        .init();
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    info!(service = APP_LABEL, "shutdown signal received");
}

async fn healthz() -> Json<HealthResponse> {
    Json(HealthResponse { status: "ok", service: APP_LABEL })
}

async fn beat(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<BeatRequest>,
) -> Result<Json<BeatResponse>, ApiError> {
    let started = Instant::now();
    let service_id = sanitize_service_id(payload.service_id)?;
    let key = heartbeat_key(&service_id);

    let mut cache_conn = state
        .cache
        .get_multiplexed_async_connection()
        .await
        .map_err(|source| ApiError::Redis { operation: "cache_connect", source })?;

    let _: () = cache_conn
        .set_ex(&key, payload.status_code, HEARTBEAT_TTL_SECONDS)
        .await
        .map_err(|source| ApiError::Redis { operation: "heartbeat_set", source })?;

    let mut alarm = false;
    if payload.status_code != 200 {
        alarm = true;
        let mut stream_conn = state
            .stream
            .get_multiplexed_async_connection()
            .await
            .map_err(|source| ApiError::Redis { operation: "stream_connect", source })?;
        let timestamp_ms = current_timestamp_ms().to_string();
        let status_code = payload.status_code.to_string();
        let _: String = redis::cmd("XADD")
            .arg(HB_DOWN_STREAM)
            .arg("*")
            .arg("service_id")
            .arg(&service_id)
            .arg("status_code")
            .arg(&status_code)
            .arg("timestamp_ms")
            .arg(&timestamp_ms)
            .query_async(&mut stream_conn)
            .await
            .map_err(|source| ApiError::Redis { operation: "alarm_xadd", source })?;
        warn!(
            service = APP_LABEL,
            operation = "beat",
            monitored_service = %service_id,
            status_code = payload.status_code,
            latency_ms = started.elapsed().as_millis() as u64,
            "heartbeat down alarm recorded"
        );
    } else {
        info!(
            service = APP_LABEL,
            operation = "beat",
            monitored_service = %service_id,
            status_code = payload.status_code,
            latency_ms = started.elapsed().as_millis() as u64,
            "heartbeat recorded"
        );
    }

    Ok(Json(BeatResponse {
        service_id,
        status_code: payload.status_code,
        recorded: true,
        alarm,
    }))
}

async fn status(
    State(state): State<Arc<AppState>>,
    Path(service_id): Path<String>,
) -> Result<Json<StatusResponse>, ApiError> {
    let started = Instant::now();
    let service_id = sanitize_service_id(service_id)?;
    let key = heartbeat_key(&service_id);
    let mut conn = state
        .cache
        .get_multiplexed_async_connection()
        .await
        .map_err(|source| ApiError::Redis { operation: "cache_connect", source })?;

    let status_code: Option<i64> = conn
        .get(&key)
        .await
        .map_err(|source| ApiError::Redis { operation: "heartbeat_get", source })?;

    let alive = status_code.is_some();
    info!(
        service = APP_LABEL,
        operation = "status",
        monitored_service = %service_id,
        alive,
        latency_ms = started.elapsed().as_millis() as u64,
        "heartbeat status checked"
    );

    Ok(Json(StatusResponse {
        service_id,
        status: if alive { "alive" } else { "dead" },
        alive,
        status_code,
    }))
}

async fn alive(State(state): State<Arc<AppState>>) -> Result<Json<AliveResponse>, ApiError> {
    let started = Instant::now();
    let mut conn = state
        .cache
        .get_multiplexed_async_connection()
        .await
        .map_err(|source| ApiError::Redis { operation: "cache_connect", source })?;

    let mut keys = Vec::new();
    let mut cursor = 0_u64;
    loop {
        let (next_cursor, mut page): (u64, Vec<String>) = redis::cmd("SCAN")
            .arg(cursor)
            .arg("MATCH")
            .arg("hb:*")
            .arg("COUNT")
            .arg(1000)
            .query_async(&mut conn)
            .await
            .map_err(|source| ApiError::Redis { operation: "alive_scan", source })?;
        keys.append(&mut page);
        cursor = next_cursor;
        if cursor == 0 {
            break;
        }
    }

    let mut service_ids: Vec<String> = keys
        .into_iter()
        .filter_map(|key| key.strip_prefix("hb:").map(ToOwned::to_owned))
        .collect();
    service_ids.sort();

    info!(
        service = APP_LABEL,
        operation = "alive",
        alive_count = service_ids.len(),
        latency_ms = started.elapsed().as_millis() as u64,
        "alive services listed"
    );

    Ok(Json(AliveResponse { service_ids }))
}

async fn alarms(State(state): State<Arc<AppState>>) -> Result<Json<AlarmsResponse>, ApiError> {
    let started = Instant::now();
    let mut conn = state
        .stream
        .get_multiplexed_async_connection()
        .await
        .map_err(|source| ApiError::Redis { operation: "stream_connect", source })?;

    let raw: redis::streams::StreamRangeReply = redis::cmd("XREVRANGE")
        .arg(HB_DOWN_STREAM)
        .arg("+")
        .arg("-")
        .arg("COUNT")
        .arg(50)
        .query_async(&mut conn)
        .await
        .map_err(|source| ApiError::Redis { operation: "alarms_xrevrange", source })?;

    let alarms = raw
        .ids
        .into_iter()
        .map(|entry| AlarmEntry {
            id: entry.id,
            fields: stream_fields_to_json(entry.map),
        })
        .collect::<Vec<_>>();

    info!(
        service = APP_LABEL,
        operation = "alarms",
        alarm_count = alarms.len(),
        latency_ms = started.elapsed().as_millis() as u64,
        "alarms listed"
    );

    Ok(Json(AlarmsResponse { alarms }))
}

fn heartbeat_key(service_id: &str) -> String {
    format!("hb:{service_id}")
}

fn sanitize_service_id(service_id: String) -> Result<String, ApiError> {
    let trimmed = service_id.trim().to_string();
    if trimmed.is_empty() {
        return Err(ApiError::BadRequest("service_id is required".to_string()));
    }
    Ok(trimmed)
}

fn current_timestamp_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn stream_fields_to_json(fields: std::collections::HashMap<String, redis::Value>) -> Value {
    let mut obj = serde_json::Map::new();
    for (key, value) in fields {
        obj.insert(key, redis_value_to_json(value));
    }
    Value::Object(obj)
}

fn redis_value_to_json(value: redis::Value) -> Value {
    match value {
        redis::Value::Nil => Value::Null,
        redis::Value::Int(i) => Value::Number(i.into()),
        redis::Value::BulkString(bytes) => String::from_utf8(bytes).map(Value::String).unwrap_or(Value::Null),
        redis::Value::SimpleString(s) => Value::String(s),
        redis::Value::Okay => Value::String("OK".to_string()),
        redis::Value::Array(values) => Value::Array(values.into_iter().map(redis_value_to_json).collect()),
        redis::Value::Map(values) => {
            let mut obj = serde_json::Map::new();
            for (k, v) in values {
                obj.insert(redis_value_to_key(k), redis_value_to_json(v));
            }
            Value::Object(obj)
        }
        redis::Value::Attribute { data, attributes } => json!({
            "data": redis_value_to_json(*data),
            "attributes": redis_value_to_json(redis::Value::Map(attributes)),
        }),
        redis::Value::Set(values) => Value::Array(values.into_iter().map(redis_value_to_json).collect()),
        redis::Value::Double(f) => json!(f),
        redis::Value::Boolean(b) => Value::Bool(b),
        redis::Value::VerbatimString { format: _, text } => Value::String(text),
        redis::Value::BigNumber(n) => Value::String(n.to_string()),
        redis::Value::Push { kind: _, data } => Value::Array(data.into_iter().map(redis_value_to_json).collect()),
        redis::Value::ServerError(err) => Value::String(format!("{err:?}")),
    }
}

fn redis_value_to_key(value: redis::Value) -> String {
    match redis_value_to_json(value) {
        Value::String(s) => s,
        other => other.to_string(),
    }
}
