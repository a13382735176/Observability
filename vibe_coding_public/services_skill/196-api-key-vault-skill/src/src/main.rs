use axum::{
    extract::State,
    http::{Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use serde_json::json;
use std::{
    env,
    net::SocketAddr,
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::{net::TcpListener, time::timeout};
use tokio_postgres::{Client, NoTls};

const DEFAULT_APP_NAME: &str = "api-key-vault-skill";
const DEFAULT_PG_DSN: &str = "postgres://vibe:vibe@postgres:5432/vibe";
const SCHEMA_SQL: &str = "CREATE TABLE IF NOT EXISTS api_keys( id bigserial PRIMARY KEY, name text, key text UNIQUE, scopes jsonb DEFAULT '[]'::jsonb, owner_id text, revoked boolean DEFAULT false, created_at timestamptz DEFAULT now() )";

#[derive(Clone)]
struct AppState {
    app_name: Arc<str>,
    pg: Arc<Client>,
}

#[tokio::main]
async fn main() {
    let app_name = env::var("APP_NAME").unwrap_or_else(|_| DEFAULT_APP_NAME.to_string());
    let pg_dsn = env::var("PG_DSN").unwrap_or_else(|_| DEFAULT_PG_DSN.to_string());
    let _redis_url =
        env::var("REDIS_URL").unwrap_or_else(|_| "redis://redis-cache:6379".to_string());

    log_event(&app_name, "startup", "starting", None);

    let (client, connection) = match tokio_postgres::connect(&pg_dsn, NoTls).await {
        Ok(parts) => parts,
        Err(err) => {
            log_event(
                &app_name,
                "postgres_connect",
                "failed",
                Some(err.to_string()),
            );
            std::process::exit(1);
        }
    };

    let app_name_for_connection = app_name.clone();
    tokio::spawn(async move {
        if let Err(err) = connection.await {
            log_event(
                &app_name_for_connection,
                "postgres_connection",
                "failed",
                Some(err.to_string()),
            );
        }
    });

    let schema_start = Instant::now();
    if let Err(err) = client.batch_execute(SCHEMA_SQL).await {
        log_event(
            &app_name,
            "postgres_schema",
            "failed",
            Some(err.to_string()),
        );
        std::process::exit(1);
    }
    log_event_with_latency(
        &app_name,
        "postgres_schema",
        "ready",
        schema_start.elapsed(),
        None,
    );

    let state = AppState {
        app_name: Arc::from(app_name.clone()),
        pg: Arc::new(client),
    };

    let app = Router::new()
        .route("/healthz", get(healthz))
        .fallback(not_found)
        .layer(middleware::from_fn_with_state(state.clone(), request_log))
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 8080));
    let listener = match TcpListener::bind(addr).await {
        Ok(listener) => listener,
        Err(err) => {
            log_event(&app_name, "listen", "failed", Some(err.to_string()));
            std::process::exit(1);
        }
    };

    log_event(&app_name, "listen", "ready", None);

    let server =
        axum::serve(listener, app).with_graceful_shutdown(shutdown_signal(app_name.clone()));
    if let Err(err) = server.await {
        log_event(&app_name, "server", "failed", Some(err.to_string()));
        std::process::exit(1);
    }
}

async fn healthz(State(state): State<AppState>) -> Response {
    let start = Instant::now();
    match timeout(Duration::from_secs(2), state.pg.query_one("SELECT 1", &[])).await {
        Ok(Ok(_)) => {
            log_event_with_latency(
                &state.app_name,
                "postgres_health",
                "ok",
                start.elapsed(),
                None,
            );
            (StatusCode::OK, Json(json!({ "status": "ok" }))).into_response()
        }
        Ok(Err(err)) => {
            log_event_with_latency(
                &state.app_name,
                "postgres_health",
                "failed",
                start.elapsed(),
                Some(err.to_string()),
            );
            (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({ "status": "unavailable" })),
            )
                .into_response()
        }
        Err(_) => {
            log_event_with_latency(
                &state.app_name,
                "postgres_health",
                "timeout",
                start.elapsed(),
                None,
            );
            (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({ "status": "unavailable" })),
            )
                .into_response()
        }
    }
}

async fn not_found() -> Response {
    (StatusCode::NOT_FOUND, Json(json!({ "error": "not_found" }))).into_response()
}

async fn request_log(
    State(state): State<AppState>,
    req: Request<axum::body::Body>,
    next: Next,
) -> Response {
    let method = req.method().as_str().to_string();
    let path = req.uri().path().to_string();
    let start = Instant::now();
    let response = next.run(req).await;
    let status = response.status().as_u16();
    let elapsed_ms = start.elapsed().as_millis();

    println!(
        "{}",
        json!({
            "ts": unix_millis(),
            "service": state.app_name.as_ref(),
            "operation": "http_request",
            "method": method,
            "path": path,
            "status": status,
            "latency_ms": elapsed_ms
        })
    );

    response
}

async fn shutdown_signal(app_name: String) {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };

    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut signal) => {
                signal.recv().await;
            }
            Err(_) => std::future::pending::<()>().await,
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }

    log_event(&app_name, "shutdown", "received", None);
}

fn log_event(service: &str, operation: &str, status: &str, error: Option<String>) {
    let mut event = json!({
        "ts": unix_millis(),
        "service": service,
        "operation": operation,
        "status": status
    });
    if let Some(error) = error {
        event["error"] = json!(error);
    }
    println!("{}", event);
}

fn log_event_with_latency(
    service: &str,
    operation: &str,
    status: &str,
    elapsed: Duration,
    error: Option<String>,
) {
    let mut event = json!({
        "ts": unix_millis(),
        "service": service,
        "operation": operation,
        "status": status,
        "latency_ms": elapsed.as_millis()
    });
    if let Some(error) = error {
        event["error"] = json!(error);
    }
    println!("{}", event);
}

fn unix_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}
