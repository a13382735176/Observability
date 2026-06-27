using System.Text.Json;
using Npgsql;
using StackExchange.Redis;

const string SERVICE = "deployment-tracker";

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://0.0.0.0:8080");
builder.Logging.ClearProviders();
builder.Logging.AddConsole();

string pgHost = Environment.GetEnvironmentVariable("POSTGRES_HOST") ?? "postgres";
string pgPort = Environment.GetEnvironmentVariable("POSTGRES_PORT") ?? "5432";
string redisHost = Environment.GetEnvironmentVariable("REDIS_STREAM_HOST") ?? "redis-stream";
string redisPort = Environment.GetEnvironmentVariable("REDIS_STREAM_PORT") ?? "6379";

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

try
{
    await using var conn = new NpgsqlConnection(pgConn);
    await conn.OpenAsync();
    await using var cmd = new NpgsqlCommand(@"
        CREATE TABLE IF NOT EXISTS deployments (
            id bigserial PRIMARY KEY,
            service text NOT NULL,
            version text NOT NULL,
            environment text NOT NULL,
            deployed_by text,
            rollback boolean DEFAULT false,
            deployed_at timestamptz DEFAULT now()
        );", conn);
    await cmd.ExecuteNonQueryAsync();
}
catch (Exception e)
{
    logger.LogError("deployment-tracker: schema init: {Error}", e.Message);
}

app.MapGet("/healthz", () => Results.Json(new { status = "ok", service = SERVICE }));

app.MapPost("/deployments", async (HttpContext ctx, PgFactory pgf) =>
{
    try
    {
        var body = await JsonSerializer.DeserializeAsync<NewDeploymentReq>(ctx.Request.Body);
        if (body is null || string.IsNullOrEmpty(body.service) || string.IsNullOrEmpty(body.version) || string.IsNullOrEmpty(body.environment))
            return Results.BadRequest(new { error = "service, version, environment required" });

        long id; DateTime deployedAt;
        await using (var conn = await pgf.OpenAsync())
        await using (var cmd = new NpgsqlCommand(
            "INSERT INTO deployments(service, version, environment, deployed_by) VALUES (@s, @v, @e, @b) RETURNING id, deployed_at",
            conn))
        {
            cmd.Parameters.AddWithValue("@s", body.service);
            cmd.Parameters.AddWithValue("@v", body.version);
            cmd.Parameters.AddWithValue("@e", body.environment);
            cmd.Parameters.AddWithValue("@b", (object?)body.deployed_by ?? DBNull.Value);
            await using var rd = await cmd.ExecuteReaderAsync();
            await rd.ReadAsync();
            id = rd.GetInt64(0);
            deployedAt = rd.GetDateTime(1);
        }

        try
        {
            var db = redis.GetDatabase();
            await db.StreamAddAsync("events:deployments", new NameValueEntry[]
            {
                new("id", id.ToString()),
                new("service", body.service),
                new("version", body.version),
                new("environment", body.environment),
            });
        }
        catch (Exception e)
        {
            logger.LogError("deployment-tracker: XADD events:deployments: {Error}", e.Message);
        }

        return Results.Json(new
        {
            id,
            service = body.service,
            version = body.version,
            environment = body.environment,
            deployed_by = body.deployed_by,
            rollback = false,
            deployed_at = deployedAt,
        });
    }
    catch (Exception e)
    {
        logger.LogError("deployment-tracker: create: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/deployments/{service}", async (string service, PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT id, service, version, environment, deployed_by, rollback, deployed_at FROM deployments WHERE service = @s ORDER BY id DESC LIMIT 20",
            conn);
        cmd.Parameters.AddWithValue("@s", service);
        var list = new List<object>();
        await using var rd = await cmd.ExecuteReaderAsync();
        while (await rd.ReadAsync())
        {
            list.Add(new
            {
                id = rd.GetInt64(0),
                service = rd.GetString(1),
                version = rd.GetString(2),
                environment = rd.GetString(3),
                deployed_by = rd.IsDBNull(4) ? null : rd.GetString(4),
                rollback = rd.GetBoolean(5),
                deployed_at = rd.GetDateTime(6),
            });
        }
        return Results.Json(new { service, items = list });
    }
    catch (Exception e)
    {
        logger.LogError("deployment-tracker: by-service: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/deployments/active/{environment}", async (string environment, PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            SELECT DISTINCT ON (service) id, service, version, environment, deployed_by, rollback, deployed_at
            FROM deployments
            WHERE environment = @e
            ORDER BY service, id DESC", conn);
        cmd.Parameters.AddWithValue("@e", environment);
        var list = new List<object>();
        await using var rd = await cmd.ExecuteReaderAsync();
        while (await rd.ReadAsync())
        {
            list.Add(new
            {
                id = rd.GetInt64(0),
                service = rd.GetString(1),
                version = rd.GetString(2),
                environment = rd.GetString(3),
                deployed_by = rd.IsDBNull(4) ? null : rd.GetString(4),
                rollback = rd.GetBoolean(5),
                deployed_at = rd.GetDateTime(6),
            });
        }
        return Results.Json(new { environment, items = list });
    }
    catch (Exception e)
    {
        logger.LogError("deployment-tracker: active: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapPut("/deployments/{id:long}/rollback", async (long id, HttpContext ctx, PgFactory pgf) =>
{
    try
    {
        var body = await JsonSerializer.DeserializeAsync<RollbackReq>(ctx.Request.Body);
        if (body is null || string.IsNullOrEmpty(body.previous_version))
            return Results.BadRequest(new { error = "previous_version required" });

        await using var conn = await pgf.OpenAsync();

        string svc, env; string? deployedBy;
        await using (var look = new NpgsqlCommand(
            "SELECT service, environment, deployed_by FROM deployments WHERE id = @i", conn))
        {
            look.Parameters.AddWithValue("@i", id);
            await using var lrd = await look.ExecuteReaderAsync();
            if (!await lrd.ReadAsync())
                return Results.NotFound(new { error = "deployment not found" });
            svc = lrd.GetString(0);
            env = lrd.GetString(1);
            deployedBy = lrd.IsDBNull(2) ? null : lrd.GetString(2);
        }

        long newId; DateTime deployedAt;
        await using (var ins = new NpgsqlCommand(
            "INSERT INTO deployments(service, version, environment, deployed_by, rollback) VALUES (@s, @v, @e, @b, true) RETURNING id, deployed_at",
            conn))
        {
            ins.Parameters.AddWithValue("@s", svc);
            ins.Parameters.AddWithValue("@v", body.previous_version);
            ins.Parameters.AddWithValue("@e", env);
            ins.Parameters.AddWithValue("@b", (object?)deployedBy ?? DBNull.Value);
            await using var rd = await ins.ExecuteReaderAsync();
            await rd.ReadAsync();
            newId = rd.GetInt64(0);
            deployedAt = rd.GetDateTime(1);
        }

        try
        {
            var db = redis.GetDatabase();
            await db.StreamAddAsync("events:rollbacks", new NameValueEntry[]
            {
                new("id", newId.ToString()),
                new("from_id", id.ToString()),
                new("service", svc),
                new("version", body.previous_version),
                new("environment", env),
            });
        }
        catch (Exception e)
        {
            logger.LogError("deployment-tracker: XADD events:rollbacks: {Error}", e.Message);
        }

        return Results.Json(new
        {
            id = newId,
            service = svc,
            version = body.previous_version,
            environment = env,
            deployed_by = deployedBy,
            rollback = true,
            deployed_at = deployedAt,
        });
    }
    catch (Exception e)
    {
        logger.LogError("deployment-tracker: rollback: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/deployments", async (PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT id, service, version, environment, deployed_by, rollback, deployed_at FROM deployments ORDER BY id DESC LIMIT 50",
            conn);
        var list = new List<object>();
        await using var rd = await cmd.ExecuteReaderAsync();
        while (await rd.ReadAsync())
        {
            list.Add(new
            {
                id = rd.GetInt64(0),
                service = rd.GetString(1),
                version = rd.GetString(2),
                environment = rd.GetString(3),
                deployed_by = rd.IsDBNull(4) ? null : rd.GetString(4),
                rollback = rd.GetBoolean(5),
                deployed_at = rd.GetDateTime(6),
            });
        }
        return Results.Json(new { items = list });
    }
    catch (Exception e)
    {
        logger.LogError("deployment-tracker: list: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.Run();

record NewDeploymentReq(string service, string version, string environment, string? deployed_by);
record RollbackReq(string previous_version);

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
