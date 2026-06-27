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

type RedisConn = redis::aio::MultiplexedConnection;

struct AppState {
    pg: PgPool,
    redis_cache: Arc<tokio::sync::Mutex<RedisConn>>,
    redis_stream: Arc<tokio::sync::Mutex<RedisConn>>,
}

#[derive(Serialize, Deserialize)]
struct FeedEvent {
    user_id: String,
    post_id: String,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let dsn = env::var("PG_DSN").unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".into());
    let pg = PgPool::connect(&dsn).await.expect("pg connect");
    sqlx::query("CREATE TABLE IF NOT EXISTS feed_events(id SERIAL PRIMARY KEY, user_id TEXT, post_id TEXT, created_at TIMESTAMPTZ DEFAULT NOW())")
        .execute(&pg).await.ok();

    let cache_host = env::var("REDIS_CACHE_HOST").unwrap_or_else(|_| "redis-cache".into());
    let cache_port = env::var("REDIS_CACHE_PORT").unwrap_or_else(|_| "6379".into());
    let stream_host = env::var("REDIS_STREAM_HOST").unwrap_or_else(|_| "redis-stream".into());
    let stream_port = env::var("REDIS_STREAM_PORT").unwrap_or_else(|_| "6379".into());

    let cache_client = redis::Client::open(format!("redis://{}:{}/", cache_host, cache_port)).expect("cache client");
    let stream_client = redis::Client::open(format!("redis://{}:{}/", stream_host, stream_port)).expect("stream client");

    let cache_conn = cache_client.get_multiplexed_async_connection().await.expect("cache conn");
    let stream_conn = stream_client.get_multiplexed_async_connection().await.expect("stream conn");

    let state = Arc::new(AppState {
        pg,
        redis_cache: Arc::new(tokio::sync::Mutex::new(cache_conn)),
        redis_stream: Arc::new(tokio::sync::Mutex::new(stream_conn)),
    });

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/feed/:user_id", get(get_feed))
        .route("/events", post(post_event))
        .with_state(state);

    info!("feed-generator listening on :8080");
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

async fn healthz() -> Json<Value> {
    Json(json!({"status":"ok","service":"feed-generator"}))
}

async fn get_feed(
    Path(user_id): Path<String>,
    State(state): State<Arc<AppState>>,
) -> Json<Value> {
    let key = format!("feed:{}", user_id);
    let mut cache = state.redis_cache.lock().await;
    match cache.lrange::<_, Vec<String>>(&key, 0, 49).await {
        Ok(items) => Json(json!({"user_id": user_id, "feed": items})),
        Err(e) => {
            error!("feed-generator: get_feed cache error: {}", e);
            Json(json!({"user_id": user_id, "feed": []}))
        }
    }
}

async fn post_event(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<FeedEvent>,
) -> Json<Value> {
    let event_str = serde_json::to_string(&payload).unwrap_or_default();
    let key = format!("feed:{}", payload.user_id);

    {
        let mut cache = state.redis_cache.lock().await;
        if let Err(e) = cache.lpush::<_, _, ()>(&key, &event_str).await {
            error!("feed-generator: cache lpush error: {}", e);
        }
        let _: Result<(), _> = cache.ltrim(&key, 0, 99).await;
    }
    {
        let mut stream = state.redis_stream.lock().await;
        let fields = vec![("event", "feed.update"), ("payload", event_str.as_str())];
        if let Err(e) = stream.xadd::<_, _, _, _, ()>("events:feed", "*", &fields).await {
            error!("feed-generator: stream xadd error: {}", e);
        }
    }
    if let Err(e) = sqlx::query("INSERT INTO feed_events(user_id,post_id) VALUES($1,$2)")
        .bind(&payload.user_id).bind(&payload.post_id)
        .execute(&state.pg).await {
        error!("feed-generator: pg insert error: {}", e);
    }
    Json(json!({"ok":true,"user_id":payload.user_id}))
}
