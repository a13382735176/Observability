use actix_web::{web, App, HttpServer, HttpResponse, middleware};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use std::{env, sync::Arc};
use tokio::sync::Mutex;

#[derive(Clone)]
struct AppState {
    pool: sqlx::PgPool,
    cache: Arc<Mutex<redis::aio::MultiplexedConnection>>,
}

#[derive(Deserialize)]
struct SplitItem { user_id: String, amount_cents: i64 }

#[derive(Deserialize)]
struct SplitReq { payer_id: String, participants: Vec<SplitItem>, description: Option<String> }

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    tracing_subscriber::fmt::init();
    let pg_dsn = env::var("PG_DSN").unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let cache_host = env::var("REDIS_CACHE_HOST").unwrap_or_else(|_| "redis-cache".to_string());

    let pool = PgPoolOptions::new()
        .max_connections(5)
        .acquire_timeout(std::time::Duration::from_secs(2))
        .connect(&pg_dsn).await.expect("pg connect");

    sqlx::query("CREATE TABLE IF NOT EXISTS splits(id serial PRIMARY KEY,payer_id text,total_cents bigint,description text,status text DEFAULT 'open',created_at timestamptz DEFAULT now())")
        .execute(&pool).await.expect("create splits");
    sqlx::query("CREATE TABLE IF NOT EXISTS split_items(id serial PRIMARY KEY,split_id int,user_id text,amount_cents bigint,settled bool DEFAULT false)")
        .execute(&pool).await.expect("create split_items");

    let cache_client = redis::Client::open(format!("redis://{}:6379", cache_host)).unwrap();
    let cache_conn = cache_client.get_multiplexed_async_connection().await.expect("cache connect");

    let state = AppState { pool, cache: Arc::new(Mutex::new(cache_conn)) };

    tracing::info!("split-pay listening on 8080");
    HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(state.clone()))
            .route("/healthz", web::get().to(healthz))
            .route("/split", web::post().to(create_split))
            .route("/splits/{id}", web::get().to(get_split))
            .route("/splits/user/{user_id}", web::get().to(user_splits))
    })
    .bind("0.0.0.0:8080")?.run().await
}

async fn healthz() -> HttpResponse {
    HttpResponse::Ok().json(json!({"status":"ok","service":"split-pay"}))
}

async fn create_split(state: web::Data<AppState>, body: web::Json<SplitReq>) -> HttpResponse {
    let total: i64 = body.participants.iter().map(|p| p.amount_cents).sum();
    let desc = body.description.clone().unwrap_or_default();
    let id: i32 = match sqlx::query_scalar(
        "INSERT INTO splits(payer_id,total_cents,description) VALUES($1,$2,$3) RETURNING id"
    ).bind(&body.payer_id).bind(total).bind(&desc).fetch_one(&state.pool).await {
        Ok(v) => v,
        Err(e) => { tracing::error!("split-pay: {}", e); return HttpResponse::ServiceUnavailable().json(json!({"error":"db error"})); }
    };
    for item in &body.participants {
        if let Err(e) = sqlx::query("INSERT INTO split_items(split_id,user_id,amount_cents) VALUES($1,$2,$3)")
            .bind(id).bind(&item.user_id).bind(item.amount_cents).execute(&state.pool).await {
            tracing::error!("split-pay: {}", e);
        }
    }
    use redis::AsyncCommands;
    let mut cache = state.cache.lock().await;
    let _: redis::RedisResult<()> = cache.set_ex(format!("split:{}", id), total.to_string(), 300).await;
    HttpResponse::Created().json(json!({"id": id, "payer_id": body.payer_id, "total_cents": total}))
}

async fn get_split(state: web::Data<AppState>, path: web::Path<i32>) -> HttpResponse {
    let id = path.into_inner();
    let row = match sqlx::query_as::<_, (i32,String,i64,String,String)>(
        "SELECT id,payer_id,total_cents,description,status FROM splits WHERE id=$1"
    ).bind(id).fetch_optional(&state.pool).await {
        Ok(Some(r)) => r,
        Ok(None) => return HttpResponse::NotFound().json(json!({"error":"not found"})),
        Err(e) => { tracing::error!("split-pay: {}", e); return HttpResponse::ServiceUnavailable().json(json!({"error":"db error"})); }
    };
    let items = match sqlx::query_as::<_, (i32,String,i64,bool)>(
        "SELECT id,user_id,amount_cents,settled FROM split_items WHERE split_id=$1"
    ).bind(id).fetch_all(&state.pool).await {
        Ok(v) => v.iter().map(|r| json!({"id":r.0,"user_id":r.1,"amount_cents":r.2,"settled":r.3})).collect::<Vec<_>>(),
        Err(e) => { tracing::error!("split-pay: {}", e); vec![] }
    };
    HttpResponse::Ok().json(json!({"id":row.0,"payer_id":row.1,"total_cents":row.2,"description":row.3,"status":row.4,"items":items}))
}

async fn user_splits(state: web::Data<AppState>, path: web::Path<String>) -> HttpResponse {
    let user_id = path.into_inner();
    let rows = match sqlx::query_as::<_, (i32,i64,bool)>(
        "SELECT split_id,amount_cents,settled FROM split_items WHERE user_id=$1"
    ).bind(&user_id).fetch_all(&state.pool).await {
        Ok(v) => v,
        Err(e) => { tracing::error!("split-pay: {}", e); return HttpResponse::ServiceUnavailable().json(json!({"error":"db error"})); }
    };
    let result: Vec<Value> = rows.iter().map(|r| json!({"split_id":r.0,"amount_cents":r.1,"settled":r.2})).collect();
    HttpResponse::Ok().json(result)
}
