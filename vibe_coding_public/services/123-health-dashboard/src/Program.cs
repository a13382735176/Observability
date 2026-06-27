using System.Text.Json;
using StackExchange.Redis;

string host = Environment.GetEnvironmentVariable("REDIS_CACHE_HOST") ?? "redis-cache";
string port = Environment.GetEnvironmentVariable("REDIS_CACHE_PORT") ?? "6379";
var options = ConfigurationOptions.Parse($"{host}:{port}");
options.AbortOnConnectFail = false;
options.AllowAdmin = true;
options.ConnectTimeout = 2000;
options.SyncTimeout = 2000;
options.AsyncTimeout = 2000;

var redis = await ConnectionMultiplexerAsync(options);

var builder = WebApplication.CreateBuilder(args);
builder.Logging.AddSimpleConsole(o => { o.SingleLine = true; });
var app = builder.Build();
var log = app.Logger;

app.MapGet("/healthz", () => Results.Json(new { status = "ok", service = "health-dashboard" }));

app.MapPost("/report", async (HttpRequest req) =>
{
    try
    {
        var doc = await JsonSerializer.DeserializeAsync<ReportReq>(req.Body);
        if (doc is null || string.IsNullOrWhiteSpace(doc.service_name) || string.IsNullOrWhiteSpace(doc.status))
            return Results.BadRequest(new { error = "service_name and status required" });
        var db = redis.GetDatabase();
        var key = $"health:{doc.service_name}";
        var ts = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
        await db.HashSetAsync(key, new HashEntry[]
        {
            new("status", doc.status),
            new("latency_ms", doc.latency_ms),
            new("ts", ts),
        });
        await db.KeyExpireAsync(key, TimeSpan.FromSeconds(300));
        return Results.Created($"/health/{doc.service_name}", new { ok = true });
    }
    catch (Exception e)
    {
        log.LogError(e, "health-dashboard: report: {Msg}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/health/summary", async () =>
{
    try
    {
        var db = redis.GetDatabase();
        var server = redis.GetServers().FirstOrDefault(s => s.IsConnected);
        if (server is null) return Results.StatusCode(502);
        var result = new Dictionary<string, Dictionary<string, string>>();
        await foreach (var key in server.KeysAsync(pattern: "health:*"))
        {
            var entries = await db.HashGetAllAsync(key);
            var inner = new Dictionary<string, string>();
            foreach (var e in entries) inner[e.Name!] = e.Value!;
            result[key.ToString().Substring("health:".Length)] = inner;
        }
        return Results.Json(result);
    }
    catch (Exception e)
    {
        log.LogError(e, "health-dashboard: summary: {Msg}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/health/{service_name}", async (string service_name) =>
{
    try
    {
        var db = redis.GetDatabase();
        var entries = await db.HashGetAllAsync($"health:{service_name}");
        if (entries.Length == 0) return Results.NotFound(new { error = "not found" });
        var dict = new Dictionary<string, string>();
        foreach (var e in entries) dict[e.Name!] = e.Value!;
        return Results.Json(dict);
    }
    catch (Exception e)
    {
        log.LogError(e, "health-dashboard: get: {Msg}", e.Message);
        return Results.StatusCode(502);
    }
});

app.Run("http://0.0.0.0:8080");

static async Task<ConnectionMultiplexer> ConnectionMultiplexerAsync(ConfigurationOptions options)
{
    return await ConnectionMultiplexer.ConnectAsync(options);
}

public record ReportReq(string service_name, string status, int latency_ms);
