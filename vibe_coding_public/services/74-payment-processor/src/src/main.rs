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
use sqlx::postgres::PgPoolOptions;
use std::{env, sync::Arc};
use tokio::sync::Mutex;

#[derive(Clone)]
struct AppState {
    pool: sqlx::PgPool,
    stream: Arc<Mutex<redis::aio::MultiplexedConnection>>,
}

#[derive(Deserialize)]
struct PaymentReq {
    payer_id: String,
    payee_id: String,
    amount_cents: i64,
    currency: String,
}

#[derive(Serialize, sqlx::FromRow)]
struct Payment {
    id: i32,
    payer_id: String,
    payee_id: String,
    amount_cents: i64,
    currency: String,
    status: String,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let pg_dsn = env::var("PG_DSN").unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let stream_host = env::var("REDIS_STREAM_HOST").unwrap_or_else(|_| "redis-stream".to_string());

    let pool = PgPoolOptions::new()
        .max_connections(5)
        .acquire_timeout(std::time::Duration::from_secs(2))
        .connect(&pg_dsn)
        .await
        .expect("pg connect");

    sqlx::query(r#"
        CREATE TABLE IF NOT EXISTS payments(
            id serial PRIMARY KEY,
            payer_id text,
            payee_id text,
            amount_cents bigint,
            currency text,
            status text DEFAULT 'completed',
            ts timestamptz DEFAULT now()
        )
    "#).execute(&pool).await.expect("create table");

    let stream_client = redis::Client::open(format!("redis://{}:6379", stream_host)).unwrap();
    let stream_conn = stream_client.get_multiplexed_async_connection().await.expect("stream connect");

    let state = AppState {
        pool,
        stream: Arc::new(Mutex::new(stream_conn)),
    };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/payments", post(create_payment))
        .route("/payments/:id", get(get_payment))
        .route("/payments/user/:user_id", get(user_payments))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    tracing::info!("payment-processor listening on 8080");
    axum::serve(listener, app).await.unwrap();
}

async fn healthz() -> Json<Value> {
    Json(json!({"status": "ok", "service": "payment-processor"}))
}

async fn create_payment(
    State(state): State<AppState>,
    Json(req): Json<PaymentReq>,
) -> Result<(StatusCode, Json<Value>), StatusCode> {
    let row = sqlx::query_scalar::<_, i32>(
        "INSERT INTO payments(payer_id,payee_id,amount_cents,currency) VALUES($1,$2,$3,$4) RETURNING id"
    )
    .bind(&req.payer_id).bind(&req.payee_id).bind(req.amount_cents).bind(&req.currency)
    .fetch_one(&state.pool)
    .await
    .map_err(|e| { tracing::error!("payment-processor: {}", e); StatusCode::SERVICE_UNAVAILABLE })?;

    {
        let mut stream = state.stream.lock().await;
        let _: Result<String, _> = stream.xadd("events:payments", "*", &[
            ("payment_id", row.to_string().as_str()),
            ("payer_id", req.payer_id.as_str()),
            ("amount_cents", req.amount_cents.to_string().as_str()),
        ]).await.map_err(|e| tracing::error!("payment-processor: {}", e));
    }

    Ok((StatusCode::CREATED, Json(json!({"id": row}))))
}

async fn get_payment(
    State(state): State<AppState>,
    Path(id): Path<i32>,
) -> Result<Json<Value>, StatusCode> {
    let row = sqlx::query_as::<_, Payment>(
        "SELECT id,payer_id,payee_id,amount_cents,currency,status FROM payments WHERE id=$1"
    )
    .bind(id)
    .fetch_optional(&state.pool)
    .await
    .map_err(|e| { tracing::error!("payment-processor: {}", e); StatusCode::SERVICE_UNAVAILABLE })?;
    match row {
        Some(p) => Ok(Json(json!({"id":p.id,"payer_id":p.payer_id,"payee_id":p.payee_id,"amount_cents":p.amount_cents,"currency":p.currency,"status":p.status}))),
        None => Err(StatusCode::NOT_FOUND),
    }
}

async fn user_payments(
    State(state): State<AppState>,
    Path(user_id): Path<String>,
) -> Result<Json<Value>, StatusCode> {
    let rows = sqlx::query_as::<_, Payment>(
        "SELECT id,payer_id,payee_id,amount_cents,currency,status FROM payments WHERE payer_id=$1 OR payee_id=$1 ORDER BY id DESC LIMIT 10"
    )
    .bind(&user_id)
    .fetch_all(&state.pool)
    .await
    .map_err(|e| { tracing::error!("payment-processor: {}", e); StatusCode::SERVICE_UNAVAILABLE })?;
    Ok(Json(json!(rows.iter().map(|p| json!({"id":p.id,"payer_id":p.payer_id,"payee_id":p.payee_id,"amount_cents":p.amount_cents,"currency":p.currency})).collect::<Vec<_>>())))
}
