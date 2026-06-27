use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::process;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const SERVICE_ID: &str = "191-media-encoder-svc-skill";
const APP_LABEL: &str = "media-encoder-svc-skill";
const PORT: u16 = 8080;

static REQUEST_COUNTER: AtomicU64 = AtomicU64::new(1);

fn main() {
    let bind_addr = format!("0.0.0.0:{}", PORT);
    log_event(
        "startup",
        "initializing",
        &[("app", APP_LABEL), ("bind", bind_addr.as_str())],
    );

    let listener = match TcpListener::bind(&bind_addr) {
        Ok(listener) => listener,
        Err(err) => {
            let error = err.to_string();
            log_event("startup", "bind_failed", &[("error", error.as_str())]);
            process::exit(1);
        }
    };

    log_event("startup", "listening", &[("bind", bind_addr.as_str())]);

    for incoming in listener.incoming() {
        match incoming {
            Ok(stream) => handle_connection(stream),
            Err(err) => {
                let error = err.to_string();
                log_event("server", "accept_failed", &[("error", error.as_str())]);
            }
        }
    }
}

fn handle_connection(mut stream: TcpStream) {
    let request_id = REQUEST_COUNTER.fetch_add(1, Ordering::Relaxed).to_string();
    let started = Instant::now();

    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));

    let mut buffer = [0_u8; 4096];
    let read = match stream.read(&mut buffer) {
        Ok(0) => return,
        Ok(n) => n,
        Err(err) => {
            let error = err.to_string();
            log_event(
                "request",
                "read_failed",
                &[
                    ("request_id", request_id.as_str()),
                    ("error", error.as_str()),
                ],
            );
            let _ = stream.shutdown(Shutdown::Both);
            return;
        }
    };

    let request_text = String::from_utf8_lossy(&buffer[..read]);
    let (method, path) = parse_request_line(&request_text);

    log_event(
        "request",
        "received",
        &[
            ("request_id", request_id.as_str()),
            ("method", method),
            ("path", path),
        ],
    );

    let (status, reason, content_type, body) = route(method, path);
    let response = build_response(status, reason, content_type, body);

    if let Err(err) = stream.write_all(response.as_bytes()) {
        let error = err.to_string();
        log_event(
            "request",
            "write_failed",
            &[
                ("request_id", request_id.as_str()),
                ("status", status_code(status)),
                ("error", error.as_str()),
            ],
        );
        let _ = stream.shutdown(Shutdown::Both);
        return;
    }

    let _ = stream.flush();
    let _ = stream.shutdown(Shutdown::Both);

    let elapsed_ms = started.elapsed().as_millis().to_string();
    log_event(
        "request",
        "completed",
        &[
            ("request_id", request_id.as_str()),
            ("method", method),
            ("path", path),
            ("status", status_code(status)),
            ("latency_ms", elapsed_ms.as_str()),
        ],
    );
}

fn parse_request_line(request: &str) -> (&str, &str) {
    let mut parts = request
        .lines()
        .next()
        .unwrap_or_default()
        .split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("").split('?').next().unwrap_or("");
    (method, path)
}

fn route(method: &str, path: &str) -> (u16, &'static str, &'static str, &'static str) {
    match (method, path) {
        ("GET", "/healthz") | ("HEAD", "/healthz") => (
            200,
            "OK",
            "application/json",
            "{\"status\":\"ok\",\"service\":\"191-media-encoder-svc-skill\"}\n",
        ),
        _ => (
            404,
            "Not Found",
            "application/json",
            "{\"error\":\"not_found\"}\n",
        ),
    }
}

fn build_response(status: u16, reason: &str, content_type: &str, body: &str) -> String {
    format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        status,
        reason,
        content_type,
        body.as_bytes().len(),
        body
    )
}

fn status_code(status: u16) -> &'static str {
    match status {
        200 => "200",
        404 => "404",
        _ => "unknown",
    }
}

fn log_event(operation: &str, event: &str, fields: &[(&str, &str)]) {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_secs()
        .to_string();

    let mut line = format!(
        "ts={} service={} operation={} event={}",
        timestamp, SERVICE_ID, operation, event
    );

    for (key, value) in fields {
        line.push(' ');
        line.push_str(key);
        line.push('=');
        line.push_str(&sanitize_log_value(value));
    }

    eprintln!("{}", line);
}

fn sanitize_log_value(value: &str) -> String {
    value
        .chars()
        .map(|ch| match ch {
            'a'..='z' | 'A'..='Z' | '0'..='9' | '-' | '_' | '.' | '/' | ':' => ch,
            _ => '_',
        })
        .collect()
}
