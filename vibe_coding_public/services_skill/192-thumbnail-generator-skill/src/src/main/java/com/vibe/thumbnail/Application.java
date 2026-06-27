package com.vibe.thumbnail;

import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public final class Application {
    private static final String SERVICE_ID = "192-thumbnail-generator-skill";
    private static final String APP_LABEL = "thumbnail-generator-skill";
    private static final int DEFAULT_PORT = 8080;

    private Application() {
    }

    public static void main(String[] args) throws Exception {
        int port = readPort();
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
        ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor();

        server.createContext("/healthz", new HealthHandler());
        server.createContext("/", new NotFoundHandler());
        server.setExecutor(executor);

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            log("info", "shutdown", "service_stopping", "stop requested", null, 0, null);
            server.stop(2);
            executor.shutdown();
            try {
                if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                    executor.shutdownNow();
                }
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                executor.shutdownNow();
            }
            log("info", "shutdown", "service_stopped", "stop completed", null, 0, null);
        }, "shutdown-hook"));

        server.start();
        log("info", "startup", "service_started", "listening", null, 0,
                "\"port\":" + port + ",\"app_label\":\"" + APP_LABEL + "\"");
    }

    private static int readPort() {
        String value = System.getenv("PORT");
        if (value == null || value.isBlank()) {
            return DEFAULT_PORT;
        }
        try {
            int port = Integer.parseInt(value.trim());
            if (port > 0 && port <= 65535) {
                return port;
            }
        } catch (NumberFormatException ignored) {
            // fall through to the contract default
        }
        log("warn", "startup", "invalid_port", "using default port", null, 0, null);
        return DEFAULT_PORT;
    }

    private static final class HealthHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            long started = System.nanoTime();
            String requestId = requestId(exchange);
            try {
                if (!"GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                    send(exchange, 405, "{\"error\":\"method_not_allowed\"}\n", requestId);
                    logRequest(exchange, requestId, started, 405, "healthz", null);
                    return;
                }
                send(exchange, 200, "{\"status\":\"ok\",\"service\":\"" + SERVICE_ID + "\"}\n", requestId);
                logRequest(exchange, requestId, started, 200, "healthz", null);
            } catch (Exception failure) {
                send(exchange, 500, "{\"error\":\"internal_server_error\"}\n", requestId);
                logRequest(exchange, requestId, started, 500, "healthz", failure);
            } finally {
                exchange.close();
            }
        }
    }

    private static final class NotFoundHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange exchange) throws IOException {
            long started = System.nanoTime();
            String requestId = requestId(exchange);
            try {
                send(exchange, 404, "{\"error\":\"not_found\"}\n", requestId);
                logRequest(exchange, requestId, started, 404, "not_found", null);
            } catch (Exception failure) {
                logRequest(exchange, requestId, started, 500, "not_found", failure);
            } finally {
                exchange.close();
            }
        }
    }

    private static String requestId(HttpExchange exchange) {
        String supplied = exchange.getRequestHeaders().getFirst("X-Request-Id");
        if (supplied == null || supplied.isBlank() || supplied.length() > 128) {
            return UUID.randomUUID().toString();
        }
        return supplied.replaceAll("[^A-Za-z0-9_.:-]", "_");
    }

    private static void send(HttpExchange exchange, int status, String body, String requestId) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        Headers headers = exchange.getResponseHeaders();
        headers.set("Content-Type", "application/json; charset=utf-8");
        headers.set("X-Request-Id", requestId);
        if (status == 405) {
            headers.set("Allow", "GET");
        }
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }

    private static void logRequest(HttpExchange exchange, String requestId, long started, int status,
                                   String operation, Exception failure) {
        long latencyMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);
        String level = status >= 500 ? "error" : "info";
        String errorFields = failure == null ? null : "\"error_type\":\"" + json(failure.getClass().getSimpleName()) + "\"";
        String details = "\"method\":\"" + json(exchange.getRequestMethod().toUpperCase(Locale.ROOT)) + "\"," +
                "\"path\":\"" + json(exchange.getRequestURI().getPath()) + "\"," +
                "\"status\":" + status +
                (errorFields == null ? "" : "," + errorFields);
        log(level, operation, "request_completed", "request handled", requestId, latencyMs, details);
    }

    private static void log(String level, String operation, String event, String message,
                            String requestId, long latencyMs, String details) {
        StringBuilder line = new StringBuilder(192);
        line.append('{')
                .append("\"ts\":\"").append(Instant.now()).append("\",")
                .append("\"level\":\"").append(json(level)).append("\",")
                .append("\"service\":\"").append(SERVICE_ID).append("\",")
                .append("\"operation\":\"").append(json(operation)).append("\",")
                .append("\"event\":\"").append(json(event)).append("\",")
                .append("\"message\":\"").append(json(message)).append("\"");
        if (requestId != null) {
            line.append(",\"request_id\":\"").append(json(requestId)).append("\"");
        }
        if (latencyMs > 0) {
            line.append(",\"latency_ms\":").append(latencyMs);
        }
        if (details != null && !details.isBlank()) {
            line.append(',').append(details);
        }
        line.append('}');
        System.out.println(line);
    }

    private static String json(String value) {
        return value == null ? "" : value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}
