use axum::{
    Router,
    extract::{Path, State},
    routing::{get, post},
    Json,
};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{env, sync::Arc};
use tokio::sync::Mutex;
use tokio_postgres::NoTls;
use tracing::{error, info};

const SVC: &str = "loyalty-points";

#[derive(Clone)]
struct AppState {
    pg: Arc<Mutex<tokio_postgres::Client>>,
    redis: Arc<Mutex<redis::aio::MultiplexedConnection>>,
}

#[derive(Deserialize)]
struct EarnBody { user_id: String, order_total_cents: i64 }

#[derive(Deserialize)]
struct RedeemBody { user_id: String, points: i64 }

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    let dsn = env::var("PG_DSN").unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".into());
    let redis_host = env::var("REDIS_CACHE_HOST").unwrap_or_else(|_| "redis-cache".into());
    let redis_port = env::var("REDIS_CACHE_PORT").unwrap_or_else(|_| "6379".into());

    let (pg_client, conn) = tokio::time::timeout(
        std::time::Duration::from_secs(2),
        tokio_postgres::connect(&dsn, NoTls)
    ).await.expect("pg connect timeout").expect("pg connect");
    tokio::spawn(async move { if let Err(e) = conn.await { error!("{}: pg conn error: {}", SVC, e); } });

    pg_client.execute(
        "CREATE TABLE IF NOT EXISTS loyalty (id SERIAL PRIMARY KEY, user_id TEXT UNIQUE NOT NULL, points INT DEFAULT 0)",
        &[]
    ).await.map_err(|e| error!("{}: table init: {}", SVC, e)).ok();
    info!("{}: postgres ready", SVC);

    let redis_url = format!("redis://{}:{}", redis_host, redis_port);
    let rclient = redis::Client::open(redis_url.as_str()).expect("redis client");
    let rconn = tokio::time::timeout(
        std::time::Duration::from_secs(2),
        rclient.get_multiplexed_async_connection()
    ).await.expect("redis timeout").map_err(|e| { error!("{}: redis connect: {}", SVC, e); e }).expect("redis conn");
    info!("{}: redis connected", SVC);

    let state = AppState {
        pg: Arc::new(Mutex::new(pg_client)),
        redis: Arc::new(Mutex::new(rconn)),
    };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/points/:user_id", get(get_points))
        .route("/earn", post(earn))
        .route("/redeem", post(redeem))
        .with_state(state);

    info!("{}: listening on :8080", SVC);
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

async fn healthz() -> Json<Value> {
    Json(json!({"status":"ok","service":SVC}))
}

async fn get_points(Path(user_id): Path<String>, State(state): State<AppState>) -> Json<Value> {
    let cache_key = format!("loyalty:{}", user_id);
    {
        let mut r = state.redis.lock().await;
        if let Ok(v) = r.get::<_, Option<i64>>(&cache_key).await {
            if let Some(pts) = v {
                return Json(json!({"user_id": user_id, "points": pts}));
            }
        }
    }
    let pg = state.pg.lock().await;
    match pg.query_opt("SELECT points FROM loyalty WHERE user_id=$1", &[&user_id]).await {
        Ok(Some(row)) => {
            let pts: i32 = row.get(0);
            let mut r = state.redis.lock().await;
            let _: Result<(), _> = r.set_ex(&cache_key, pts as i64, 60).await;
            Json(json!({"user_id": user_id, "points": pts}))
        }
        Ok(None) => Json(json!({"user_id": user_id, "points": 0})),
        Err(e) => { error!("{}: get_points {}: {}", SVC, user_id, e); Json(json!({"error":"db error"})) }
    }
}

async fn earn(State(state): State<AppState>, Json(body): Json<EarnBody>) -> Json<Value> {
    let pts = body.order_total_cents / 100;
    let pg = state.pg.lock().await;
    match pg.execute(
        "INSERT INTO loyalty(user_id,points) VALUES($1,$2) ON CONFLICT(user_id) DO UPDATE SET points=loyalty.points+$2",
        &[&body.user_id, &(pts as i32)]
    ).await {
        Ok(_) => {
            let cache_key = format!("loyalty:{}", body.user_id);
            let mut r = state.redis.lock().await;
            let _: Result<(), _> = r.del(&cache_key).await;
            Json(json!({"user_id": body.user_id, "earned": pts}))
        }
        Err(e) => { error!("{}: earn {}: {}", SVC, body.user_id, e); Json(json!({"error":"db error"})) }
    }
}

async fn redeem(State(state): State<AppState>, Json(body): Json<RedeemBody>) -> Json<Value> {
    let pg = state.pg.lock().await;
    match pg.execute(
        "UPDATE loyalty SET points=GREATEST(0,points-$2) WHERE user_id=$1",
        &[&body.user_id, &(body.points as i32)]
    ).await {
        Ok(_) => {
            let cache_key = format!("loyalty:{}", body.user_id);
            let mut r = state.redis.lock().await;
            let _: Result<(), _> = r.del(&cache_key).await;
            Json(json!({"user_id": body.user_id, "redeemed": body.points}))
        }
        Err(e) => { error!("{}: redeem {}: {}", SVC, body.user_id, e); Json(json!({"error":"db error"})) }
    }
}
