using StackExchange.Redis;

const string SERVICE = "presence-tracker";

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://0.0.0.0:8080");
builder.Logging.ClearProviders();
builder.Logging.AddConsole();

string redisHost = Environment.GetEnvironmentVariable("REDIS_CACHE_HOST") ?? "redis-cache";
string redisPort = Environment.GetEnvironmentVariable("REDIS_CACHE_PORT") ?? "6379";

var redisCfg = new ConfigurationOptions
{
    EndPoints = { $"{redisHost}:{redisPort}" },
    ConnectTimeout = 2000,
    SyncTimeout = 2000,
    AbortOnConnectFail = false,
};
var redis = ConnectionMultiplexer.Connect(redisCfg);

builder.Services.AddSingleton<IConnectionMultiplexer>(redis);

var app = builder.Build();
var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger(SERVICE);

app.MapGet("/healthz", () => Results.Json(new { status = "ok", service = SERVICE }));

app.MapPost("/heartbeat", async (HttpContext ctx) =>
{
    try
    {
        var body = await System.Text.Json.JsonSerializer.DeserializeAsync<HeartbeatReq>(ctx.Request.Body);
        if (body is null || string.IsNullOrEmpty(body.user_id))
            return Results.BadRequest(new { error = "user_id required" });

        var db = redis.GetDatabase();
        await db.StringSetAsync($"presence:{body.user_id}", "online", TimeSpan.FromSeconds(60));
        await db.SetAddAsync("online_users", body.user_id);
        return Results.Json(new { user_id = body.user_id, status = "online", ttl_seconds = 60 });
    }
    catch (Exception e)
    {
        logger.LogError("presence-tracker: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/presence/{userId}", async (string userId) =>
{
    try
    {
        var db = redis.GetDatabase();
        var v = await db.StringGetAsync($"presence:{userId}");
        var status = v.HasValue ? "online" : "offline";
        return Results.Json(new { user_id = userId, status });
    }
    catch (Exception e)
    {
        logger.LogError("presence-tracker: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/online", async () =>
{
    try
    {
        var db = redis.GetDatabase();
        var members = await db.SetMembersAsync("online_users");
        var alive = new List<string>();
        var stale = new List<RedisValue>();
        foreach (var m in members)
        {
            var userId = m.ToString();
            var v = await db.StringGetAsync($"presence:{userId}");
            if (v.HasValue) alive.Add(userId);
            else stale.Add(m);
        }
        if (stale.Count > 0)
        {
            try { await db.SetRemoveAsync("online_users", stale.ToArray()); }
            catch (Exception e) { logger.LogError("presence-tracker: SREM stale: {Error}", e.Message); }
        }
        return Results.Json(new { count = alive.Count, users = alive });
    }
    catch (Exception e)
    {
        logger.LogError("presence-tracker: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapDelete("/heartbeat/{userId}", async (string userId) =>
{
    try
    {
        var db = redis.GetDatabase();
        await db.KeyDeleteAsync($"presence:{userId}");
        await db.SetRemoveAsync("online_users", userId);
        return Results.Json(new { user_id = userId, removed = true });
    }
    catch (Exception e)
    {
        logger.LogError("presence-tracker: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.Run();

record HeartbeatReq(string user_id);
