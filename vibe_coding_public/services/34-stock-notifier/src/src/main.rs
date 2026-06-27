use actix_web::{web, App, HttpServer, HttpResponse, Responder};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{env, sync::Arc};
use tokio::sync::Mutex;
use tokio_postgres::NoTls;
use tracing::{error, info};

const SVC: &str = "stock-notifier";

#[derive(Clone)]
struct AppState {
    pg: Arc<Mutex<tokio_postgres::Client>>,
    stream: Arc<Mutex<redis::aio::MultiplexedConnection>>,
}

#[derive(Deserialize)]
struct SubBody { user_id: String, sku: String }

#[derive(Deserialize)]
struct NotifyBody { sku: String, qty_available: i32 }

async fn healthz() -> impl Responder {
    HttpResponse::Ok().json(json!({"status":"ok","service":SVC}))
}

async fn subscribe(data: web::Data<AppState>, body: web::Json<SubBody>) -> impl Responder {
    let pg = data.pg.lock().await;
    match pg.execute(
        "INSERT INTO stock_subscriptions(user_id,sku) VALUES($1,$2) ON CONFLICT DO NOTHING",
        &[&body.user_id, &body.sku]
    ).await {
        Ok(_) => HttpResponse::Created().json(json!({"user_id": body.user_id, "sku": body.sku})),
        Err(e) => { error!("{}: subscribe insert: {}", SVC, e); HttpResponse::InternalServerError().json(json!({"error":"db error"})) }
    }
}

async fn get_subscriptions(data: web::Data<AppState>, path: web::Path<String>) -> impl Responder {
    let sku = path.into_inner();
    let pg = data.pg.lock().await;
    match pg.query("SELECT id,user_id,sku,created_at FROM stock_subscriptions WHERE sku=$1", &[&sku]).await {
        Ok(rows) => {
            let subs: Vec<serde_json::Value> = rows.iter().map(|r| {
                json!({"id": r.get::<_,i32>(0), "user_id": r.get::<_,String>(1), "sku": r.get::<_,String>(2)})
            }).collect();
            HttpResponse::Ok().json(subs)
        }
        Err(e) => { error!("{}: get_subscriptions {}: {}", SVC, sku, e); HttpResponse::InternalServerError().json(json!({"error":"db error"})) }
    }
}

async fn notify(data: web::Data<AppState>, body: web::Json<NotifyBody>) -> impl Responder {
    let mut stream = data.stream.lock().await;
    match stream.xadd::<_, _, _, ()>(
        "stock:updates", "*",
        &[("sku", &body.sku), ("qty_available", &body.qty_available.to_string())]
    ).await {
        Ok(_) => HttpResponse::Created().json(json!({"sku": body.sku, "qty_available": body.qty_available, "published": true})),
        Err(e) => { error!("{}: stream xadd: {}", SVC, e); HttpResponse::InternalServerError().json(json!({"error":"stream error"})) }
    }
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    tracing_subscriber::fmt::init();
    let dsn = env::var("PG_DSN").unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".into());
    let redis_host = env::var("REDIS_STREAM_HOST").unwrap_or_else(|_| "redis-stream".into());
    let redis_port = env::var("REDIS_STREAM_PORT").unwrap_or_else(|_| "6379".into());

    let (pg_client, conn) = tokio::time::timeout(
        std::time::Duration::from_secs(2),
        tokio_postgres::connect(&dsn, NoTls)
    ).await.expect("pg timeout").expect("pg connect");
    tokio::spawn(async move { if let Err(e) = conn.await { error!("{}: pg conn: {}", SVC, e); } });

    pg_client.execute(
        "CREATE TABLE IF NOT EXISTS stock_subscriptions (id SERIAL PRIMARY KEY, user_id TEXT NOT NULL, sku TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(user_id,sku))",
        &[]
    ).await.map_err(|e| error!("{}: table init: {}", SVC, e)).ok();
    info!("{}: postgres ready", SVC);

    let redis_url = format!("redis://{}:{}", redis_host, redis_port);
    let rclient = redis::Client::open(redis_url.as_str()).expect("redis client");
    let rconn = tokio::time::timeout(
        std::time::Duration::from_secs(2),
        rclient.get_multiplexed_async_connection()
    ).await.expect("redis timeout").expect("redis conn");
    info!("{}: redis-stream connected", SVC);

    let state = web::Data::new(AppState {
        pg: Arc::new(Mutex::new(pg_client)),
        stream: Arc::new(Mutex::new(rconn)),
    });

    info!("{}: listening on :8080", SVC);
    HttpServer::new(move || {
        App::new()
            .app_data(state.clone())
            .route("/healthz", web::get().to(healthz))
            .route("/subscribe", web::post().to(subscribe))
            .route("/subscriptions/{sku}", web::get().to(get_subscriptions))
            .route("/notify", web::post().to(notify))
    })
    .bind("0.0.0.0:8080")?
    .run()
    .await
}
