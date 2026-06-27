use axum::{
    extract::{Path, State},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::PgPool;
use std::{env, sync::Arc};
use redis::AsyncCommands;
use tracing::{error, info};

struct AppState {
    pg: PgPool,
    redis_stream: Arc<tokio::sync::Mutex<redis::aio::MultiplexedConnection>>,
}

#[derive(Serialize, Deserialize)]
struct TelemetryIn {
    device_id: String,
    metric: String,
    value: f32,
    unit: String,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let dsn = env::var("PG_DSN").unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".into());
    let pg = PgPool::connect(&dsn).await.expect("pg connect");
    sqlx::query("CREATE TABLE IF NOT EXISTS telemetry(id SERIAL PRIMARY KEY, device_id TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, recorded_at TIMESTAMPTZ DEFAULT NOW())")
        .execute(&pg).await.ok();

    let stream_host = env::var("REDIS_STREAM_HOST").unwrap_or_else(|_| "redis-stream".into());
    let stream_port = env::var("REDIS_STREAM_PORT").unwrap_or_else(|_| "6379".into());
    let stream_client = redis::Client::open(format!("redis://{}:{}/", stream_host, stream_port)).expect("stream client");
    let stream_conn = stream_client.get_multiplexed_async_connection().await.expect("stream conn");

    let state = Arc::new(AppState {
        pg,
        redis_stream: Arc::new(tokio::sync::Mutex::new(stream_conn)),
    });

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/telemetry", post(ingest_telemetry))
        .route("/telemetry/:device_id", get(get_telemetry))
        .with_state(state);

    info!("telemetry-ingest listening on :8080");
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

async fn healthz() -> Json<Value> {
    Json(json!({"status":"ok","service":"telemetry-ingest"}))
}

async fn ingest_telemetry(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<TelemetryIn>,
) -> Json<Value> {
    let result = sqlx::query_as::<_, (i32, String, String, f32, String, chrono::DateTime<chrono::Utc>)>(
        "INSERT INTO telemetry(device_id,metric,value,unit) VALUES($1,$2,$3,$4) RETURNING id,device_id,metric,value,unit,recorded_at")
        .bind(&payload.device_id).bind(&payload.metric).bind(payload.value).bind(&payload.unit)
        .fetch_one(&state.pg).await;

    let row = match result {
        Ok(r) => r,
        Err(e) => {
            error!("telemetry-ingest: pg insert: {}", e);
            return Json(json!({"error":"internal error"}));
        }
    };

    {
        let mut stream = state.redis_stream.lock().await;
        let fields = vec![
            ("event", "telemetry.received"),
            ("device_id", payload.device_id.as_str()),
            ("metric", payload.metric.as_str()),
        ];
        if let Err(e) = stream.xadd::<_, _, _, _, ()>("events:telemetry", "*", &fields).await {
            error!("telemetry-ingest: stream xadd: {}", e);
        }
    }

    Json(json!({"id":row.0,"device_id":row.1,"metric":row.2,"value":row.3,"unit":row.4,"recorded_at":row.5.to_rfc3339()}))
}

async fn get_telemetry(
    Path(device_id): Path<String>,
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    match sqlx::query_as::<_, (i32, String, String, f32, String)>(
        "SELECT id,device_id,metric,value,unit FROM telemetry WHERE device_id=$1 ORDER BY id DESC LIMIT 100")
        .bind(&device_id)
        .fetch_all(&state.pg).await {
        Ok(rows) => {
            let data: Vec<Value> = rows.iter().map(|r| json!({"id":r.0,"device_id":r.1.clone(),"metric":r.2.clone(),"value":r.3,"unit":r.4.clone()})).collect();
            Json(json!({"device_id":device_id,"count":data.len(),"data":data}))
        }
        Err(e) => {
            error!("telemetry-ingest: get telemetry {}: {}", device_id, e);
            Json(json!({"error":"internal error"}))
        }
    }
}
