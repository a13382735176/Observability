using System.Data;
using Npgsql;
using StackExchange.Redis;

const string SERVICE = "loyalty-mileage";

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://0.0.0.0:8080");
builder.Logging.ClearProviders();
builder.Logging.AddConsole();

string pgHost = Environment.GetEnvironmentVariable("POSTGRES_HOST") ?? "postgres";
string pgPort = Environment.GetEnvironmentVariable("POSTGRES_PORT") ?? "5432";
string redisHost = Environment.GetEnvironmentVariable("REDIS_CACHE_HOST") ?? "redis-cache";
string redisPort = Environment.GetEnvironmentVariable("REDIS_CACHE_PORT") ?? "6379";

string pgConn = $"Host={pgHost};Port={pgPort};Database=vibe;Username=vibe;Password=vibe;Timeout=2;Command Timeout=2;Pooling=true;Maximum Pool Size=8";

var redisCfg = new ConfigurationOptions
{
    EndPoints = { $"{redisHost}:{redisPort}" },
    ConnectTimeout = 2000,
    SyncTimeout = 2000,
    AbortOnConnectFail = false,
};
var redis = ConnectionMultiplexer.Connect(redisCfg);

builder.Services.AddSingleton<IConnectionMultiplexer>(redis);
builder.Services.AddSingleton(new PgFactory(pgConn));

var app = builder.Build();
var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger(SERVICE);

// init schema
try
{
    await using var conn = new NpgsqlConnection(pgConn);
    await conn.OpenAsync();
    await using var cmd = new NpgsqlCommand(@"
        CREATE TABLE IF NOT EXISTS mileage_history (
            id serial PRIMARY KEY,
            user_id text NOT NULL,
            miles int NOT NULL,
            source text,
            ts timestamptz NOT NULL DEFAULT now()
        )", conn);
    await cmd.ExecuteNonQueryAsync();
}
catch (Exception e)
{
    logger.LogError("loyalty-mileage: schema init: {Error}", e.Message);
}

app.MapGet("/healthz", () => Results.Json(new { status = "ok", service = SERVICE }));

app.MapPost("/miles/earn", async (HttpContext ctx, PgFactory pgf) =>
{
    try
    {
        var body = await System.Text.Json.JsonSerializer.DeserializeAsync<EarnReq>(ctx.Request.Body);
        if (body is null || string.IsNullOrEmpty(body.user_id) || body.miles <= 0)
            return Results.BadRequest(new { error = "user_id and positive miles required" });

        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "INSERT INTO mileage_history(user_id, miles, source) VALUES (@u, @m, @s) RETURNING id, ts", conn);
        cmd.Parameters.AddWithValue("@u", body.user_id);
        cmd.Parameters.AddWithValue("@m", body.miles);
        cmd.Parameters.AddWithValue("@s", (object?)body.source ?? DBNull.Value);
        await using var rd = await cmd.ExecuteReaderAsync();
        long id = 0; DateTime ts = DateTime.UtcNow;
        if (await rd.ReadAsync()) { id = rd.GetInt32(0); ts = rd.GetDateTime(1); }
        await rd.CloseAsync();

        try
        {
            var db = redis.GetDatabase();
            await db.StringIncrementAsync($"miles:{body.user_id}", body.miles);
        }
        catch (Exception e)
        {
            logger.LogError("loyalty-mileage: redis incr: {Error}", e.Message);
        }

        return Results.Json(new { id, user_id = body.user_id, miles = body.miles, source = body.source, ts });
    }
    catch (Exception e)
    {
        logger.LogError("loyalty-mileage: earn: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapPost("/miles/redeem", async (HttpContext ctx, PgFactory pgf) =>
{
    try
    {
        var body = await System.Text.Json.JsonSerializer.DeserializeAsync<RedeemReq>(ctx.Request.Body);
        if (body is null || string.IsNullOrEmpty(body.user_id) || body.miles <= 0)
            return Results.BadRequest(new { error = "user_id and positive miles required" });

        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "INSERT INTO mileage_history(user_id, miles, source) VALUES (@u, @m, @s) RETURNING id, ts", conn);
        cmd.Parameters.AddWithValue("@u", body.user_id);
        cmd.Parameters.AddWithValue("@m", -body.miles);
        cmd.Parameters.AddWithValue("@s", "redeem");
        await using var rd = await cmd.ExecuteReaderAsync();
        long id = 0; DateTime ts = DateTime.UtcNow;
        if (await rd.ReadAsync()) { id = rd.GetInt32(0); ts = rd.GetDateTime(1); }
        await rd.CloseAsync();

        try
        {
            var db = redis.GetDatabase();
            await db.StringDecrementAsync($"miles:{body.user_id}", body.miles);
        }
        catch (Exception e)
        {
            logger.LogError("loyalty-mileage: redis decr: {Error}", e.Message);
        }

        return Results.Json(new { id, user_id = body.user_id, miles = -body.miles, ts });
    }
    catch (Exception e)
    {
        logger.LogError("loyalty-mileage: redeem: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/miles/{userId}", async (string userId, PgFactory pgf) =>
{
    try
    {
        try
        {
            var db = redis.GetDatabase();
            var v = await db.StringGetAsync($"miles:{userId}");
            if (v.HasValue && long.TryParse(v.ToString(), out var balance))
                return Results.Json(new { user_id = userId, balance, source = "cache" });
        }
        catch (Exception e)
        {
            logger.LogError("loyalty-mileage: redis get: {Error}", e.Message);
        }

        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand("SELECT COALESCE(SUM(miles), 0) FROM mileage_history WHERE user_id = @u", conn);
        cmd.Parameters.AddWithValue("@u", userId);
        var sum = (long)Convert.ToInt64(await cmd.ExecuteScalarAsync() ?? 0L);
        try
        {
            var db = redis.GetDatabase();
            await db.StringSetAsync($"miles:{userId}", sum.ToString());
        }
        catch { /* best effort */ }
        return Results.Json(new { user_id = userId, balance = sum, source = "db" });
    }
    catch (Exception e)
    {
        logger.LogError("loyalty-mileage: miles get: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/history/{userId}", async (string userId, PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT id, user_id, miles, source, ts FROM mileage_history WHERE user_id = @u ORDER BY id DESC LIMIT 30", conn);
        cmd.Parameters.AddWithValue("@u", userId);
        var list = new List<object>();
        await using var rd = await cmd.ExecuteReaderAsync();
        while (await rd.ReadAsync())
        {
            list.Add(new
            {
                id = rd.GetInt32(0),
                user_id = rd.GetString(1),
                miles = rd.GetInt32(2),
                source = rd.IsDBNull(3) ? null : rd.GetString(3),
                ts = rd.GetDateTime(4),
            });
        }
        return Results.Json(new { user_id = userId, items = list });
    }
    catch (Exception e)
    {
        logger.LogError("loyalty-mileage: history: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.Run();

record EarnReq(string user_id, int miles, string? source);
record RedeemReq(string user_id, int miles);

public class PgFactory
{
    private readonly string _conn;
    public PgFactory(string conn) { _conn = conn; }
    public async Task<NpgsqlConnection> OpenAsync()
    {
        var c = new NpgsqlConnection(_conn);
        await c.OpenAsync();
        return c;
    }
}
