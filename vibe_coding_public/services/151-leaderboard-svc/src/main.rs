use std::env;
use std::net::SocketAddr;
use std::time::Duration;

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::Json,
    routing::{delete, get, post},
    Router,
};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tracing::error;

const SERVICE: &str = "leaderboard-svc";

#[derive(Clone)]
struct AppState {
    redis_client: redis::Client,
}

#[derive(Serialize)]
struct Health {
    status: &'static str,
    service: &'static str,
}

#[derive(Deserialize)]
struct ScoreReq {
    game_id: String,
    user_id: String,
    score: i64,
}

#[derive(Deserialize)]
struct TopQuery {
    top: Option<isize>,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().with_target(false).init();

    let redis_url =
        env::var("REDIS_URL").unwrap_or_else(|_| "redis://redis-cache:6379".to_string());

    let redis_client = redis::Client::open(redis_url).expect("invalid redis url");

    let state = AppState { redis_client };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/score", post(submit_score))
        .route("/leaderboard/:game_id", get(get_leaderboard))
        .route("/leaderboard/:game_id", delete(reset_leaderboard))
        .route("/rank/:game_id/:user_id", get(get_rank))
        .with_state(state);

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

async fn submit_score(
    State(s): State<AppState>,
    Json(req): Json<ScoreReq>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let key = format!("lb:{}", req.game_id);
    let fut = async {
        let mut conn = s.redis_client.get_async_connection().await?;
        let _: () = conn.zadd(&key, &req.user_id, req.score).await?;
        Ok::<_, redis::RedisError>(())
    };
    match tokio::time::timeout(Duration::from_secs(2), fut).await {
        Ok(Ok(_)) => Ok(Json(json!({
            "game_id": req.game_id,
            "user_id": req.user_id,
            "score": req.score,
        }))),
        Ok(Err(e)) => {
            error!("{}: ZADD {}: {}", SERVICE, key, e);
            Err((StatusCode::BAD_GATEWAY, format!("redis error: {}", e)))
        }
        Err(_) => {
            error!("{}: ZADD {}: timeout", SERVICE, key);
            Err((StatusCode::GATEWAY_TIMEOUT, "redis timeout".into()))
        }
    }
}

async fn get_leaderboard(
    State(s): State<AppState>,
    Path(game_id): Path<String>,
    Query(q): Query<TopQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let top = q.top.unwrap_or(10).max(1) - 1;
    let key = format!("lb:{}", game_id);
    let fut = async {
        let mut conn = s.redis_client.get_async_connection().await?;
        let entries: Vec<(String, i64)> = conn.zrevrange_withscores(&key, 0, top).await?;
        Ok::<_, redis::RedisError>(entries)
    };
    match tokio::time::timeout(Duration::from_secs(2), fut).await {
        Ok(Ok(entries)) => {
            let out: Vec<Value> = entries
                .into_iter()
                .enumerate()
                .map(|(i, (user_id, score))| {
                    json!({"user_id": user_id, "score": score, "rank": i + 1})
                })
                .collect();
            Ok(Json(json!({"game_id": game_id, "entries": out})))
        }
        Ok(Err(e)) => {
            error!("{}: ZREVRANGE {}: {}", SERVICE, key, e);
            Err((StatusCode::BAD_GATEWAY, format!("redis error: {}", e)))
        }
        Err(_) => {
            error!("{}: ZREVRANGE {}: timeout", SERVICE, key);
            Err((StatusCode::GATEWAY_TIMEOUT, "redis timeout".into()))
        }
    }
}

async fn get_rank(
    State(s): State<AppState>,
    Path((game_id, user_id)): Path<(String, String)>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let key = format!("lb:{}", game_id);
    let fut = async {
        let mut conn = s.redis_client.get_async_connection().await?;
        let rank: Option<isize> = conn.zrevrank(&key, &user_id).await?;
        let score: Option<i64> = conn.zscore(&key, &user_id).await?;
        Ok::<_, redis::RedisError>((rank, score))
    };
    match tokio::time::timeout(Duration::from_secs(2), fut).await {
        Ok(Ok((rank, score))) => {
            if rank.is_none() || score.is_none() {
                return Err((StatusCode::NOT_FOUND, "not found".into()));
            }
            Ok(Json(json!({
                "game_id": game_id,
                "user_id": user_id,
                "rank": rank.unwrap() + 1,
                "score": score.unwrap(),
            })))
        }
        Ok(Err(e)) => {
            error!("{}: ZREVRANK/ZSCORE {}: {}", SERVICE, key, e);
            Err((StatusCode::BAD_GATEWAY, format!("redis error: {}", e)))
        }
        Err(_) => {
            error!("{}: ZREVRANK/ZSCORE {}: timeout", SERVICE, key);
            Err((StatusCode::GATEWAY_TIMEOUT, "redis timeout".into()))
        }
    }
}

async fn reset_leaderboard(
    State(s): State<AppState>,
    Path(game_id): Path<String>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let key = format!("lb:{}", game_id);
    let fut = async {
        let mut conn = s.redis_client.get_async_connection().await?;
        let removed: i64 = conn.del(&key).await?;
        Ok::<_, redis::RedisError>(removed)
    };
    match tokio::time::timeout(Duration::from_secs(2), fut).await {
        Ok(Ok(removed)) => Ok(Json(json!({"game_id": game_id, "removed": removed}))),
        Ok(Err(e)) => {
            error!("{}: DEL {}: {}", SERVICE, key, e);
            Err((StatusCode::BAD_GATEWAY, format!("redis error: {}", e)))
        }
        Err(_) => {
            error!("{}: DEL {}: timeout", SERVICE, key);
            Err((StatusCode::GATEWAY_TIMEOUT, "redis timeout".into()))
        }
    }
}
