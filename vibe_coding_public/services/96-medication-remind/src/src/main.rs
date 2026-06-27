
use axum::{
    extract::{Path, State},
    routing::{get, post},
    Json, Router,
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
    redis: Arc<Mutex<redis::aio::MultiplexedConnection>>,
}

#[derive(Deserialize)]
struct ReminderReq {
    patient_id: String,
    medication: String,
    times_per_day: i32,
    duration_days: i32,
}

#[derive(Deserialize)]
struct TakenReq {
    patient_id: String,
    medication_id: i32,
    ts_iso: String,
}

#[derive(Serialize, sqlx::FromRow)]
struct Reminder {
    id: i32,
    patient_id: String,
    medication: String,
    times_per_day: i32,
    start_date: Option<chrono::NaiveDate>,
    end_date: Option<chrono::NaiveDate>,
    active: bool,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    let pg_dsn = env::var("PG_DSN")
        .unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let stream_host = env::var("REDIS_STREAM_HOST").unwrap_or_else(|_| "redis-stream".to_string());

    let pool = PgPoolOptions::new()
        .max_connections(5)
        .acquire_timeout(std::time::Duration::from_secs(2))
        .connect(&pg_dsn)
        .await
        .expect("pg connect");

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS medication_reminders(\
         id serial PRIMARY KEY, patient_id text, medication text, \
         times_per_day int, start_date date, end_date date, active bool DEFAULT true)",
    )
    .execute(&pool)
    .await
    .expect("create table");

    let client = redis::Client::open(format!("redis://{}:6379", stream_host)).unwrap();
    let conn = client
        .get_multiplexed_async_connection()
        .await
        .expect("redis connect");

    let state = AppState {
        pool,
        redis: Arc::new(Mutex::new(conn)),
    };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/reminders", post(create_reminder))
        .route("/taken", post(mark_taken))
        .route("/reminders/:patient_id/active", get(active_reminders))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    tracing::info!("medication-remind listening on 8080");
    axum::serve(listener, app).await.unwrap();
}

async fn healthz() -> Json<Value> {
    Json(json!({"status":"ok","service":"medication-remind"}))
}

async fn create_reminder(
    State(s): State<AppState>,
    Json(body): Json<ReminderReq>,
) -> (axum::http::StatusCode, Json<Value>) {
    let today = chrono::Local::now().date_naive();
    let end_date = today + chrono::Duration::days(body.duration_days as i64);
    match sqlx::query_scalar::<_, i32>(
        "INSERT INTO medication_reminders(patient_id,medication,times_per_day,start_date,end_date) \
         VALUES($1,$2,$3,$4,$5) RETURNING id",
    )
    .bind(&body.patient_id)
    .bind(&body.medication)
    .bind(body.times_per_day)
    .bind(today)
    .bind(end_date)
    .fetch_one(&s.pool)
    .await
    {
        Ok(id) => (
            axum::http::StatusCode::CREATED,
            Json(json!({"id":id,"patient_id":body.patient_id,"medication":body.medication})),
        ),
        Err(e) => {
            tracing::error!("medication-remind: {}", e);
            (
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({"error":"db error"})),
            )
        }
    }
}

async fn mark_taken(
    State(s): State<AppState>,
    Json(body): Json<TakenReq>,
) -> (axum::http::StatusCode, Json<Value>) {
    let mut redis = s.redis.lock().await;
    match redis
        .xadd::<_, _, _, _, ()>(
            "events:medication_taken",
            "*",
            &[
                ("patient_id", body.patient_id.clone()),
                ("medication_id", body.medication_id.to_string()),
                ("ts", body.ts_iso.clone()),
            ],
        )
        .await
    {
        Ok(_) => (axum::http::StatusCode::CREATED, Json(json!({"ok":true}))),
        Err(e) => {
            tracing::error!("medication-remind: {}", e);
            (
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({"error":"stream error"})),
            )
        }
    }
}

async fn active_reminders(
    State(s): State<AppState>,
    Path(patient_id): Path<String>,
) -> (axum::http::StatusCode, Json<Value>) {
    match sqlx::query_as::<_, Reminder>(
        "SELECT id,patient_id,medication,times_per_day,start_date,end_date,active \
         FROM medication_reminders WHERE patient_id=$1 AND active=true",
    )
    .bind(&patient_id)
    .fetch_all(&s.pool)
    .await
    {
        Ok(rows) => (axum::http::StatusCode::OK, Json(json!(rows))),
        Err(e) => {
            tracing::error!("medication-remind: {}", e);
            (
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({"error":"db error"})),
            )
        }
    }
}
