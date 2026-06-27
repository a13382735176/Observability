using System.Text.Json;
using Npgsql;
using StackExchange.Redis;

var pgDsn = Environment.GetEnvironmentVariable("PG_DSN") ?? "Host=postgres;Port=5432;Username=vibe;Password=vibe;Database=vibe";
var cacheHost = Environment.GetEnvironmentVariable("REDIS_CACHE_HOST") ?? "redis-cache";

NpgsqlDataSource? pgSource = null;
IDatabase? cache = null;

try {
    pgSource = NpgsqlDataSource.Create(pgDsn);
    await using var initConn = await pgSource.OpenConnectionAsync();
    await using var cmd = initConn.CreateCommand();
    cmd.CommandText = """
        CREATE TABLE IF NOT EXISTS device_configs(
            id serial PRIMARY KEY,
            device_id text UNIQUE,
            config text,
            pushed_at timestamptz,
            version int DEFAULT 1
        )
    """;
    await cmd.ExecuteNonQueryAsync();
} catch (Exception e) {
    Console.Error.WriteLine($"config-push: pg init: {e.Message}");
}

try {
    var mux = await ConnectionMultiplexer.ConnectAsync(new ConfigurationOptions {
        EndPoints = { { cacheHost, 6379 } },
        ConnectTimeout = 2000, SyncTimeout = 2000
    });
    cache = mux.GetDatabase();
} catch (Exception e) {
    Console.Error.WriteLine($"config-push: redis init: {e.Message}");
}

var app = WebApplication.CreateBuilder(args).Build();

app.MapGet("/healthz", () => Results.Ok(new { status = "ok", service = "config-push" }));

app.MapPost("/configs", async (HttpContext ctx) => {
    using var doc = await JsonDocument.ParseAsync(ctx.Request.Body);
    var deviceId = doc.RootElement.GetProperty("device_id").GetString()!;
    var config = doc.RootElement.GetProperty("config").ToString();
    try {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
        await using var conn = await pgSource!.OpenConnectionAsync(cts.Token);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = """
            INSERT INTO device_configs(device_id,config,version) VALUES(@d,@c,1)
            ON CONFLICT(device_id) DO UPDATE SET config=@c, version=device_configs.version+1
        """;
        cmd.Parameters.AddWithValue("d", deviceId);
        cmd.Parameters.AddWithValue("c", config);
        await cmd.ExecuteNonQueryAsync(cts.Token);
    } catch (Exception e) {
        Console.Error.WriteLine($"config-push: pg: {e.Message}");
        return Results.StatusCode(503);
    }
    try {
        cache?.HashSet("devcfg:" + deviceId, new HashEntry[] {
            new HashEntry("config", config),
            new HashEntry("device_id", deviceId)
        });
    } catch (Exception e) {
        Console.Error.WriteLine($"config-push: redis: {e.Message}");
    }
    return Results.Created("/configs/" + deviceId, new { ok = true });
});

app.MapGet("/configs/{deviceId}", async (string deviceId) => {
    try {
        var entries = cache?.HashGetAll("devcfg:" + deviceId);
        if (entries != null && entries.Length > 0) {
            return Results.Ok(new { device_id = deviceId, config = (string?)entries.FirstOrDefault(e => e.Name == "config").Value, source = "cache" });
        }
    } catch (Exception e) {
        Console.Error.WriteLine($"config-push: redis: {e.Message}");
    }
    try {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
        await using var conn = await pgSource!.OpenConnectionAsync(cts.Token);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT config, version FROM device_configs WHERE device_id=@d";
        cmd.Parameters.AddWithValue("d", deviceId);
        await using var reader = await cmd.ExecuteReaderAsync(cts.Token);
        if (await reader.ReadAsync(cts.Token)) {
            return Results.Ok(new { device_id = deviceId, config = reader.GetString(0), version = reader.GetInt32(1) });
        }
        return Results.NotFound(new { error = "not found" });
    } catch (Exception e) {
        Console.Error.WriteLine($"config-push: pg: {e.Message}");
        return Results.StatusCode(503);
    }
});

app.MapGet("/pending", async () => {
    try {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
        await using var conn = await pgSource!.OpenConnectionAsync(cts.Token);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT id,device_id,config,version FROM device_configs WHERE pushed_at IS NULL";
        await using var reader = await cmd.ExecuteReaderAsync(cts.Token);
        var rows = new List<object>();
        while (await reader.ReadAsync(cts.Token)) {
            rows.Add(new { id = reader.GetInt32(0), device_id = reader.GetString(1), config = reader.GetString(2), version = reader.GetInt32(3) });
        }
        return Results.Ok(rows);
    } catch (Exception e) {
        Console.Error.WriteLine($"config-push: pg: {e.Message}");
        return Results.StatusCode(503);
    }
});

app.Run("http://0.0.0.0:8080");
