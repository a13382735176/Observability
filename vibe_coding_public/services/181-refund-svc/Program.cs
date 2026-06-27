using Npgsql;
using StackExchange.Redis;
using System.Text.Json;

const string SERVICE = "refund-svc";

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://0.0.0.0:8080");
builder.Logging.ClearProviders();
builder.Logging.AddConsole();

var pgHost = Environment.GetEnvironmentVariable("POSTGRES_HOST") ?? "postgres";
var pgPort = Environment.GetEnvironmentVariable("POSTGRES_PORT") ?? "5432";
var pgConn = $"Host={pgHost};Port={pgPort};Database=vibe;Username=vibe;Password=vibe;Timeout=2;Command Timeout=2;Pooling=true;Maximum Pool Size=8";

var redisHost = Environment.GetEnvironmentVariable("REDIS_STREAM_HOST") ?? "redis-stream";
var redisPort = int.Parse(Environment.GetEnvironmentVariable("REDIS_STREAM_PORT") ?? "6379");

var redisOpts = new ConfigurationOptions
{
    EndPoints = { { redisHost, redisPort } },
    ConnectTimeout = 2000,
    SyncTimeout = 2000,
    AbortOnConnectFail = false,
};
var redisLazy = new Lazy<ConnectionMultiplexer>(() => ConnectionMultiplexer.Connect(redisOpts));
IDatabase Db() => redisLazy.Value.GetDatabase();

builder.Services.AddSingleton<NpgsqlDataSource>(_ => NpgsqlDataSource.Create(pgConn));

var app = builder.Build();
var logger = app.Logger;

async Task InitDb(NpgsqlDataSource ds)
{
    try
    {
        await using var conn = await ds.OpenConnectionAsync();
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"
            CREATE TABLE IF NOT EXISTS refunds(
                id bigserial PRIMARY KEY,
                order_id bigint,
                amount_cents bigint,
                reason text,
                status text DEFAULT 'pending',
                denial_reason text,
                requested_at timestamptz DEFAULT now(),
                approved_at timestamptz
            )";
        await cmd.ExecuteNonQueryAsync();
        logger.LogInformation("refund-svc: db init ok");
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
    }
}

await InitDb(app.Services.GetRequiredService<NpgsqlDataSource>());

app.MapGet("/healthz", () => Results.Ok(new { status = "ok", service = SERVICE }));

app.MapPost("/refunds", async (HttpRequest req, NpgsqlDataSource ds) =>
{
    JsonElement body;
    try { body = await JsonSerializer.DeserializeAsync<JsonElement>(req.Body); }
    catch { return Results.BadRequest(new { error = "invalid json" }); }

    if (!body.TryGetProperty("order_id", out var orderIdEl) ||
        !body.TryGetProperty("amount_cents", out var amountEl))
    {
        return Results.BadRequest(new { error = "order_id, amount_cents required" });
    }
    long orderId = orderIdEl.GetInt64();
    long amount = amountEl.GetInt64();
    string reason = body.TryGetProperty("reason", out var rEl) && rEl.ValueKind == JsonValueKind.String
        ? rEl.GetString() ?? "" : "";

    long id;
    DateTime requestedAt;
    try
    {
        await using var conn = await ds.OpenConnectionAsync();
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"INSERT INTO refunds(order_id, amount_cents, reason, status)
                            VALUES(@oid, @amt, @reason, 'pending')
                            RETURNING id, requested_at";
        cmd.Parameters.AddWithValue("oid", orderId);
        cmd.Parameters.AddWithValue("amt", amount);
        cmd.Parameters.AddWithValue("reason", (object?)reason ?? DBNull.Value);
        await using var rd = await cmd.ExecuteReaderAsync();
        await rd.ReadAsync();
        id = rd.GetInt64(0);
        requestedAt = rd.GetDateTime(1);
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
        return Results.Json(new { error = "db error" }, statusCode: 503);
    }

    try
    {
        await Db().StreamAddAsync("events:refunds", new NameValueEntry[]
        {
            new("id", id),
            new("order_id", orderId),
            new("amount_cents", amount),
        });
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
    }

    return Results.Created($"/refunds/{id}", new
    {
        id,
        order_id = orderId,
        amount_cents = amount,
        reason,
        status = "pending",
        requested_at = requestedAt,
    });
});

app.MapGet("/refunds/{id:long}", async (long id, NpgsqlDataSource ds) =>
{
    try
    {
        await using var conn = await ds.OpenConnectionAsync();
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"SELECT id, order_id, amount_cents, reason, status, denial_reason,
                                   requested_at, approved_at
                            FROM refunds WHERE id=@id";
        cmd.Parameters.AddWithValue("id", id);
        await using var rd = await cmd.ExecuteReaderAsync();
        if (!await rd.ReadAsync())
            return Results.NotFound(new { error = "not found" });
        return Results.Ok(new
        {
            id = rd.GetInt64(0),
            order_id = rd.GetInt64(1),
            amount_cents = rd.GetInt64(2),
            reason = rd.IsDBNull(3) ? null : rd.GetString(3),
            status = rd.GetString(4),
            denial_reason = rd.IsDBNull(5) ? null : rd.GetString(5),
            requested_at = rd.GetDateTime(6),
            approved_at = rd.IsDBNull(7) ? (DateTime?)null : rd.GetDateTime(7),
        });
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
        return Results.Json(new { error = "db error" }, statusCode: 503);
    }
});

app.MapGet("/refunds/order/{orderId:long}", async (long orderId, NpgsqlDataSource ds) =>
{
    try
    {
        await using var conn = await ds.OpenConnectionAsync();
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"SELECT id, order_id, amount_cents, reason, status, denial_reason,
                                   requested_at, approved_at
                            FROM refunds WHERE order_id=@oid
                            ORDER BY requested_at DESC LIMIT 50";
        cmd.Parameters.AddWithValue("oid", orderId);
        var rows = new List<object>();
        await using var rd = await cmd.ExecuteReaderAsync();
        while (await rd.ReadAsync())
        {
            rows.Add(new
            {
                id = rd.GetInt64(0),
                order_id = rd.GetInt64(1),
                amount_cents = rd.GetInt64(2),
                reason = rd.IsDBNull(3) ? null : rd.GetString(3),
                status = rd.GetString(4),
                denial_reason = rd.IsDBNull(5) ? null : rd.GetString(5),
                requested_at = rd.GetDateTime(6),
                approved_at = rd.IsDBNull(7) ? (DateTime?)null : rd.GetDateTime(7),
            });
        }
        return Results.Ok(rows);
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
        return Results.Json(new { error = "db error" }, statusCode: 503);
    }
});

app.MapPut("/refunds/{id:long}/approve", async (long id, NpgsqlDataSource ds) =>
{
    long? orderId = null;
    long? amount = null;
    DateTime? approvedAt = null;
    try
    {
        await using var conn = await ds.OpenConnectionAsync();
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"UPDATE refunds
                            SET status='approved', approved_at=now()
                            WHERE id=@id AND status='pending'
                            RETURNING order_id, amount_cents, approved_at";
        cmd.Parameters.AddWithValue("id", id);
        await using var rd = await cmd.ExecuteReaderAsync();
        if (!await rd.ReadAsync())
            return Results.NotFound(new { error = "not found or not pending" });
        orderId = rd.GetInt64(0);
        amount = rd.GetInt64(1);
        approvedAt = rd.GetDateTime(2);
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
        return Results.Json(new { error = "db error" }, statusCode: 503);
    }

    try
    {
        await Db().StreamAddAsync("events:refund_approved", new NameValueEntry[]
        {
            new("id", id),
            new("order_id", orderId!.Value),
            new("amount_cents", amount!.Value),
        });
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
    }

    return Results.Ok(new
    {
        id,
        order_id = orderId,
        amount_cents = amount,
        status = "approved",
        approved_at = approvedAt,
    });
});

app.MapPut("/refunds/{id:long}/deny", async (long id, HttpRequest req, NpgsqlDataSource ds) =>
{
    string denialReason = "";
    try
    {
        var body = await JsonSerializer.DeserializeAsync<JsonElement>(req.Body);
        if (body.TryGetProperty("denial_reason", out var drEl) && drEl.ValueKind == JsonValueKind.String)
            denialReason = drEl.GetString() ?? "";
    }
    catch { /* allow empty body */ }

    long? orderId = null;
    try
    {
        await using var conn = await ds.OpenConnectionAsync();
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"UPDATE refunds
                            SET status='denied', denial_reason=@dr
                            WHERE id=@id AND status='pending'
                            RETURNING order_id";
        cmd.Parameters.AddWithValue("id", id);
        cmd.Parameters.AddWithValue("dr", (object?)denialReason ?? DBNull.Value);
        await using var rd = await cmd.ExecuteReaderAsync();
        if (!await rd.ReadAsync())
            return Results.NotFound(new { error = "not found or not pending" });
        orderId = rd.GetInt64(0);
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
        return Results.Json(new { error = "db error" }, statusCode: 503);
    }

    try
    {
        await Db().StreamAddAsync("events:refund_denied", new NameValueEntry[]
        {
            new("id", id),
            new("order_id", orderId!.Value),
            new("denial_reason", denialReason),
        });
    }
    catch (Exception e)
    {
        logger.LogError("refund-svc: {Error}", e.Message);
    }

    return Results.Ok(new
    {
        id,
        order_id = orderId,
        status = "denied",
        denial_reason = denialReason,
    });
});

app.Run();
