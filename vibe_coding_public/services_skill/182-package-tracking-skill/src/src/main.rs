use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    net::SocketAddr,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;
use tokio_postgres::{Client, NoTls, Row};
use tracing::{error, info, warn};

struct AppState {
    service: String,
    pg_dsn: String,
    redis_url: Option<String>,
    cache: Mutex<HashMap<String, CacheEntry>>,
}

#[derive(Clone)]
struct CacheEntry {
    package: PackageResponse,
    expires_at: Instant,
}

#[derive(Deserialize)]
struct CreatePackageRequest {
    tracking_number: String,
    origin: String,
    destination: String,
    weight_kg: f64,
}

#[derive(Deserialize)]
struct CheckpointRequest {
    location: String,
    status: String,
}

#[derive(Clone, Serialize)]
struct PackageResponse {
    id: i64,
    tracking_number: String,
    origin: String,
    destination: String,
    weight_kg: f64,
    current_status: String,
    created_at: DateTime<Utc>,
}

#[derive(Serialize)]
struct CheckpointResponse {
    id: i64,
    package_id: i64,
    location: String,
    status: String,
    recorded_at: DateTime<Utc>,
}

#[derive(Debug)]
struct AppError {
    status: StatusCode,
    message: String,
}

impl AppError {
    fn bad_request(message: &str) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: message.to_string(),
        }
    }

    fn not_found(message: &str) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            message: message.to_string(),
        }
    }

    fn conflict(message: &str) -> Self {
        Self {
            status: StatusCode::CONFLICT,
            message: message.to_string(),
        }
    }

    fn internal(message: &str) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message: message.to_string(),
        }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "error": self.message }))).into_response()
    }
}

type AppResult<T> = Result<T, AppError>;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let service =
        std::env::var("APP_NAME").unwrap_or_else(|_| "package-tracking-skill".to_string());
    let pg_dsn = std::env::var("PG_DSN")
        .unwrap_or_else(|_| "postgres://vibe:vibe@postgres:5432/vibe".to_string());
    let redis_url = std::env::var("REDIS_URL").ok();

    let state = Arc::new(AppState {
        service,
        pg_dsn,
        redis_url,
        cache: Mutex::new(HashMap::new()),
    });

    if let Err(err) = init_db(&state).await {
        warn!(service = %state.service, dependency = "postgres", error = %err.message, "database initialization deferred");
    }
    if state.redis_url.is_some() {
        info!(service = %state.service, dependency = "redis", ttl_seconds = 300, "cache configuration detected");
    }

    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/packages", post(create_package))
        .route("/packages/active", get(active_packages))
        .route("/packages/:tracking_number", get(get_package))
        .route(
            "/packages/:tracking_number/checkpoint",
            post(add_checkpoint),
        )
        .route("/packages/:tracking_number/history", get(package_history))
        .with_state(state.clone());

    let addr = SocketAddr::from(([0, 0, 0, 0], 8080));
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind 8080");
    info!(service = %state.service, port = 8080, "service started");

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal(state.service.clone()))
        .await
        .expect("server error");
}

async fn shutdown_signal(service: String) {
    let _ = tokio::signal::ctrl_c().await;
    info!(service = %service, "shutdown signal received");
}

async fn healthz(State(_state): State<Arc<AppState>>) -> Json<Value> {
    Json(json!({ "status": "ok", "service": "package-tracking" }))
}

async fn create_package(
    State(state): State<Arc<AppState>>,
    Json(req): Json<CreatePackageRequest>,
) -> AppResult<Json<PackageResponse>> {
    let start = Instant::now();
    validate_non_empty(&req.tracking_number, "tracking_number")?;
    validate_non_empty(&req.origin, "origin")?;
    validate_non_empty(&req.destination, "destination")?;
    if !req.weight_kg.is_finite() || req.weight_kg < 0.0 {
        return Err(AppError::bad_request(
            "weight_kg must be a non-negative number",
        ));
    }

    let client = db_client(&state).await?;
    let row = client
        .query_one(
            "INSERT INTO packages(tracking_number, origin, destination, weight_kg) VALUES($1,$2,$3,$4) RETURNING id, tracking_number, origin, destination, weight_kg, current_status, created_at",
            &[&req.tracking_number, &req.origin, &req.destination, &req.weight_kg],
        )
        .await
        .map_err(|e| {
            if e.as_db_error().map(|db| db.code().code() == "23505").unwrap_or(false) {
                AppError::conflict("package already exists")
            } else {
                error!(operation = "create_package", dependency = "postgres", error = %e, "insert failed");
                AppError::internal("database insert failed")
            }
        })?;

    info!(
        operation = "create_package",
        elapsed_ms = start.elapsed().as_millis() as u64,
        "package created"
    );
    Ok(Json(package_from_row(&row)))
}

async fn get_package(
    State(state): State<Arc<AppState>>,
    Path(tracking_number): Path<String>,
) -> AppResult<Json<PackageResponse>> {
    let start = Instant::now();
    validate_non_empty(&tracking_number, "tracking_number")?;
    if let Some(package) = cache_get(&state, &tracking_number).await {
        info!(
            operation = "get_package",
            cache = "hit",
            elapsed_ms = start.elapsed().as_millis() as u64,
            "package retrieved"
        );
        return Ok(Json(package));
    }

    let package = fetch_package(&state, &tracking_number).await?;
    cache_put(&state, &tracking_number, package.clone()).await;
    info!(
        operation = "get_package",
        cache = "miss",
        elapsed_ms = start.elapsed().as_millis() as u64,
        "package retrieved"
    );
    Ok(Json(package))
}

async fn add_checkpoint(
    State(state): State<Arc<AppState>>,
    Path(tracking_number): Path<String>,
    Json(req): Json<CheckpointRequest>,
) -> AppResult<Json<CheckpointResponse>> {
    let start = Instant::now();
    validate_non_empty(&tracking_number, "tracking_number")?;
    validate_non_empty(&req.location, "location")?;
    validate_non_empty(&req.status, "status")?;

    let mut client = db_client(&state).await?;
    let tx = client
        .transaction()
        .await
        .map_err(db_err("begin transaction"))?;
    let pkg = tx
        .query_opt(
            "SELECT id FROM packages WHERE tracking_number=$1",
            &[&tracking_number],
        )
        .await
        .map_err(db_err("select package"))?
        .ok_or_else(|| AppError::not_found("package not found"))?;
    let package_id: i64 = pkg.get(0);

    let row = tx
        .query_one(
            "INSERT INTO package_checkpoints(package_id, location, status) VALUES($1,$2,$3) RETURNING id, package_id, location, status, recorded_at",
            &[&package_id, &req.location, &req.status],
        )
        .await
        .map_err(db_err("insert checkpoint"))?;

    tx.execute(
        "UPDATE packages SET current_status=$1 WHERE id=$2",
        &[&req.status, &package_id],
    )
    .await
    .map_err(db_err("update package status"))?;
    tx.commit().await.map_err(db_err("commit transaction"))?;

    cache_invalidate(&state, &tracking_number).await;
    info!(
        operation = "add_checkpoint",
        elapsed_ms = start.elapsed().as_millis() as u64,
        "checkpoint appended and cache invalidated"
    );
    Ok(Json(checkpoint_from_row(&row)))
}

async fn package_history(
    State(state): State<Arc<AppState>>,
    Path(tracking_number): Path<String>,
) -> AppResult<Json<Vec<CheckpointResponse>>> {
    let start = Instant::now();
    validate_non_empty(&tracking_number, "tracking_number")?;
    let client = db_client(&state).await?;
    let pkg = client
        .query_opt(
            "SELECT id FROM packages WHERE tracking_number=$1",
            &[&tracking_number],
        )
        .await
        .map_err(db_err("select package"))?
        .ok_or_else(|| AppError::not_found("package not found"))?;
    let package_id: i64 = pkg.get(0);
    let rows = client
        .query(
            "SELECT id, package_id, location, status, recorded_at FROM package_checkpoints WHERE package_id=$1 ORDER BY recorded_at ASC, id ASC",
            &[&package_id],
        )
        .await
        .map_err(db_err("select checkpoints"))?;
    let checkpoints = rows.iter().map(checkpoint_from_row).collect::<Vec<_>>();
    info!(
        operation = "package_history",
        elapsed_ms = start.elapsed().as_millis() as u64,
        count = checkpoints.len(),
        "history retrieved"
    );
    Ok(Json(checkpoints))
}

async fn active_packages(
    State(state): State<Arc<AppState>>,
) -> AppResult<Json<Vec<PackageResponse>>> {
    let start = Instant::now();
    let client = db_client(&state).await?;
    let rows = client
        .query(
            "SELECT id, tracking_number, origin, destination, weight_kg, current_status, created_at FROM packages WHERE current_status <> 'delivered' ORDER BY created_at DESC, id DESC LIMIT 100",
            &[],
        )
        .await
        .map_err(db_err("select active packages"))?;
    let packages = rows.iter().map(package_from_row).collect::<Vec<_>>();
    info!(
        operation = "active_packages",
        elapsed_ms = start.elapsed().as_millis() as u64,
        count = packages.len(),
        "active packages retrieved"
    );
    Ok(Json(packages))
}

async fn fetch_package(state: &AppState, tracking_number: &str) -> AppResult<PackageResponse> {
    let client = db_client(state).await?;
    let row = client
        .query_opt(
            "SELECT id, tracking_number, origin, destination, weight_kg, current_status, created_at FROM packages WHERE tracking_number=$1",
            &[&tracking_number],
        )
        .await
        .map_err(db_err("select package"))?
        .ok_or_else(|| AppError::not_found("package not found"))?;
    Ok(package_from_row(&row))
}

async fn cache_get(state: &AppState, tracking_number: &str) -> Option<PackageResponse> {
    let mut cache = state.cache.lock().await;
    match cache.get(tracking_number) {
        Some(entry) if entry.expires_at > Instant::now() => Some(entry.package.clone()),
        Some(_) => {
            cache.remove(tracking_number);
            None
        }
        None => None,
    }
}

async fn cache_put(state: &AppState, tracking_number: &str, package: PackageResponse) {
    let mut cache = state.cache.lock().await;
    cache.insert(
        tracking_number.to_string(),
        CacheEntry {
            package,
            expires_at: Instant::now() + Duration::from_secs(300),
        },
    );
}

async fn cache_invalidate(state: &AppState, tracking_number: &str) {
    let mut cache = state.cache.lock().await;
    cache.remove(tracking_number);
}

async fn init_db(state: &AppState) -> AppResult<()> {
    let client = db_client(state).await?;
    ensure_schema(&client).await
}

async fn db_client(state: &AppState) -> AppResult<Client> {
    let (client, connection) = tokio_postgres::connect(&state.pg_dsn, NoTls).await.map_err(|e| {
        error!(operation = "db_connect", dependency = "postgres", error = %e, "postgres connection failed");
        AppError::internal("database connection failed")
    })?;
    tokio::spawn(async move {
        if let Err(e) = connection.await {
            error!(dependency = "postgres", error = %e, "postgres connection task failed");
        }
    });
    ensure_schema(&client).await?;
    Ok(client)
}

async fn ensure_schema(client: &Client) -> AppResult<()> {
    client.batch_execute(
        "CREATE TABLE IF NOT EXISTS packages( id bigserial PRIMARY KEY, tracking_number text UNIQUE, origin text, destination text, weight_kg double precision, current_status text DEFAULT 'created', created_at timestamptz DEFAULT now() );
         CREATE TABLE IF NOT EXISTS package_checkpoints( id bigserial PRIMARY KEY, package_id bigint, location text, status text, recorded_at timestamptz DEFAULT now() );"
    ).await.map_err(db_err("ensure schema"))?;
    Ok(())
}

fn package_from_row(row: &Row) -> PackageResponse {
    PackageResponse {
        id: row.get("id"),
        tracking_number: row.get("tracking_number"),
        origin: row.get("origin"),
        destination: row.get("destination"),
        weight_kg: row.get("weight_kg"),
        current_status: row.get("current_status"),
        created_at: row.get("created_at"),
    }
}

fn checkpoint_from_row(row: &Row) -> CheckpointResponse {
    CheckpointResponse {
        id: row.get("id"),
        package_id: row.get("package_id"),
        location: row.get("location"),
        status: row.get("status"),
        recorded_at: row.get("recorded_at"),
    }
}

fn validate_non_empty(value: &str, field: &str) -> AppResult<()> {
    if value.trim().is_empty() {
        Err(AppError::bad_request(&format!("{} is required", field)))
    } else {
        Ok(())
    }
}

fn db_err(context: &'static str) -> impl FnOnce(tokio_postgres::Error) -> AppError {
    move |e| {
        error!(operation = context, dependency = "postgres", error = %e, "database operation failed");
        AppError::internal("database operation failed")
    }
}
