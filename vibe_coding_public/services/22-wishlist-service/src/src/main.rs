use axum::{
    Router,
    extract::{Path, State},
    routing::{delete, get, post},
    Json,
};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{env, sync::Arc};
use tokio::sync::Mutex;
use tracing::{error, info};

const SVC: &str = "wishlist-service";

type RedisConn = Arc<Mutex<redis::aio::MultiplexedConnection>>;

#[derive(Deserialize)]
struct SkuBody { sku: String }

#[derive(Serialize)]
struct Wishlist { user_id: String, skus: Vec<String> }

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    let redis_host = env::var("REDIS_CACHE_HOST").unwrap_or_else(|_| "redis-cache".into());
    let redis_port = env::var("REDIS_CACHE_PORT").unwrap_or_else(|_| "6379".into());
    let redis_url = format!("redis://{}:{}", redis_host, redis_port);
    let client = redis::Client::open(redis_url.as_str()).expect("redis client");
    let conn = match tokio::time::timeout(
        std::time::Duration::from_secs(2),
        client.get_multiplexed_async_connection()
    ).await {
        Ok(Ok(c)) => { info!("{}: redis connected", SVC); c }
        Ok(Err(e)) => { error!("{}: redis connect failed: {}", SVC, e); panic!("redis unavailable") }
        Err(_) => { error!("{}: redis connect timeout", SVC); panic!("redis timeout") }
    };
    let state: RedisConn = Arc::new(Mutex::new(conn));
    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/wishlist/:user_id", get(get_wishlist))
        .route("/wishlist/:user_id/items", post(add_item))
        .route("/wishlist/:user_id", delete(del_wishlist))
        .with_state(state);
    info!("{}: listening on :8080", SVC);
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8080").await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

async fn healthz() -> Json<Value> {
    Json(json!({"status":"ok","service":SVC}))
}

async fn get_wishlist(Path(user_id): Path<String>, State(conn): State<RedisConn>) -> Json<Value> {
    let key = format!("wish:{}", user_id);
    let mut c = conn.lock().await;
    match c.smembers::<_, Vec<String>>(&key).await {
        Ok(skus) => Json(json!({"user_id": user_id, "skus": skus})),
        Err(e) => { error!("{}: smembers {}: {}", SVC, key, e); Json(json!({"error":"redis error"})) }
    }
}

async fn add_item(Path(user_id): Path<String>, State(conn): State<RedisConn>, Json(body): Json<SkuBody>) -> Json<Value> {
    let key = format!("wish:{}", user_id);
    let mut c = conn.lock().await;
    match c.sadd::<_, _, ()>(&key, &body.sku).await {
        Ok(_) => Json(json!({"user_id": user_id, "sku": body.sku, "added": true})),
        Err(e) => { error!("{}: sadd {} {}: {}", SVC, key, body.sku, e); Json(json!({"error":"redis error"})) }
    }
}

async fn del_wishlist(Path(user_id): Path<String>, State(conn): State<RedisConn>) -> Json<Value> {
    let key = format!("wish:{}", user_id);
    let mut c = conn.lock().await;
    match c.del::<_, ()>(&key).await {
        Ok(_) => Json(json!({"user_id": user_id, "deleted": true})),
        Err(e) => { error!("{}: del {}: {}", SVC, key, e); Json(json!({"error":"redis error"})) }
    }
}
