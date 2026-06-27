using System.Globalization;
using Npgsql;

const string SERVICE = "retention-cohort";

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://0.0.0.0:8080");
builder.Logging.ClearProviders();
builder.Logging.AddConsole();

string pgHost = Environment.GetEnvironmentVariable("POSTGRES_HOST") ?? "postgres";
string pgPort = Environment.GetEnvironmentVariable("POSTGRES_PORT") ?? "5432";

string pgConn = $"Host={pgHost};Port={pgPort};Database=vibe;Username=vibe;Password=vibe;Timeout=2;Command Timeout=2;Pooling=true;Maximum Pool Size=8";

builder.Services.AddSingleton(new PgFactory(pgConn));

var app = builder.Build();
var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger(SERVICE);

// init schema
try
{
    await using var conn = new NpgsqlConnection(pgConn);
    await conn.OpenAsync();
    await using (var c1 = new NpgsqlCommand(@"
        CREATE TABLE IF NOT EXISTS user_signups (
            user_id text PRIMARY KEY,
            signup_date date NOT NULL
        )", conn))
    {
        await c1.ExecuteNonQueryAsync();
    }
    await using (var c2 = new NpgsqlCommand(@"
        CREATE TABLE IF NOT EXISTS user_activity (
            id bigserial PRIMARY KEY,
            user_id text NOT NULL,
            activity_date date NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(user_id, activity_date)
        )", conn))
    {
        await c2.ExecuteNonQueryAsync();
    }
}
catch (Exception e)
{
    logger.LogError("retention-cohort: schema init: {Error}", e.Message);
}

app.MapGet("/healthz", () => Results.Ok(new { status = "ok", service = SERVICE }));

app.MapPost("/signups", async (HttpContext ctx, PgFactory pgf) =>
{
    try
    {
        var body = await System.Text.Json.JsonSerializer.DeserializeAsync<SignupReq>(ctx.Request.Body);
        if (body is null || string.IsNullOrEmpty(body.user_id) || string.IsNullOrEmpty(body.signup_date_iso))
            return Results.BadRequest(new { error = "user_id and signup_date_iso required" });
        if (!DateOnly.TryParseExact(body.signup_date_iso, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var sd))
            return Results.BadRequest(new { error = "signup_date_iso must be yyyy-MM-dd" });

        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            INSERT INTO user_signups(user_id, signup_date) VALUES (@u, @d)
            ON CONFLICT (user_id) DO UPDATE SET signup_date = EXCLUDED.signup_date
            RETURNING user_id, signup_date", conn);
        cmd.Parameters.AddWithValue("@u", body.user_id);
        cmd.Parameters.AddWithValue("@d", sd.ToDateTime(TimeOnly.MinValue));
        await using var rd = await cmd.ExecuteReaderAsync();
        if (await rd.ReadAsync())
        {
            return Results.Json(new
            {
                user_id = rd.GetString(0),
                signup_date = rd.GetDateTime(1).ToString("yyyy-MM-dd"),
            });
        }
        return Results.StatusCode(502);
    }
    catch (Exception e)
    {
        logger.LogError("retention-cohort: signups: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapPost("/activity", async (HttpContext ctx, PgFactory pgf) =>
{
    try
    {
        var body = await System.Text.Json.JsonSerializer.DeserializeAsync<ActivityReq>(ctx.Request.Body);
        if (body is null || string.IsNullOrEmpty(body.user_id) || string.IsNullOrEmpty(body.activity_date_iso))
            return Results.BadRequest(new { error = "user_id and activity_date_iso required" });
        if (!DateOnly.TryParseExact(body.activity_date_iso, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var ad))
            return Results.BadRequest(new { error = "activity_date_iso must be yyyy-MM-dd" });

        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(@"
            INSERT INTO user_activity(user_id, activity_date) VALUES (@u, @d)
            ON CONFLICT (user_id, activity_date) DO NOTHING", conn);
        cmd.Parameters.AddWithValue("@u", body.user_id);
        cmd.Parameters.AddWithValue("@d", ad.ToDateTime(TimeOnly.MinValue));
        var rows = await cmd.ExecuteNonQueryAsync();
        return Results.Json(new { user_id = body.user_id, activity_date = body.activity_date_iso, inserted = rows });
    }
    catch (Exception e)
    {
        logger.LogError("retention-cohort: activity: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/retention/{signup_date}", async (string signup_date, PgFactory pgf) =>
{
    try
    {
        if (!DateOnly.TryParseExact(signup_date, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var sd))
            return Results.BadRequest(new { error = "signup_date must be yyyy-MM-dd" });

        await using var conn = await pgf.OpenAsync();

        long cohortSize;
        await using (var c0 = new NpgsqlCommand("SELECT count(*) FROM user_signups WHERE signup_date = @d", conn))
        {
            c0.Parameters.AddWithValue("@d", sd.ToDateTime(TimeOnly.MinValue));
            cohortSize = Convert.ToInt64(await c0.ExecuteScalarAsync() ?? 0L);
        }

        async Task<long> Retained(int days)
        {
            await using var cmd = new NpgsqlCommand(
                $"SELECT count(DISTINCT s.user_id) FROM user_signups s JOIN user_activity a ON a.user_id = s.user_id WHERE s.signup_date = @d AND a.activity_date = s.signup_date + interval '{days} days'", conn);
            cmd.Parameters.AddWithValue("@d", sd.ToDateTime(TimeOnly.MinValue));
            return Convert.ToInt64(await cmd.ExecuteScalarAsync() ?? 0L);
        }

        long r1 = await Retained(1);
        long r7 = await Retained(7);
        long r30 = await Retained(30);

        double d1 = cohortSize == 0 ? 0.0 : (double)r1 / cohortSize;
        double d7 = cohortSize == 0 ? 0.0 : (double)r7 / cohortSize;
        double d30 = cohortSize == 0 ? 0.0 : (double)r30 / cohortSize;

        return Results.Json(new
        {
            signup_date,
            cohort_size = cohortSize,
            d1,
            d7,
            d30,
            d1_count = r1,
            d7_count = r7,
            d30_count = r30,
        });
    }
    catch (Exception e)
    {
        logger.LogError("retention-cohort: retention: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/signups/cohorts", async (PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT signup_date, count(*) FROM user_signups GROUP BY signup_date ORDER BY signup_date DESC LIMIT 30", conn);
        var list = new List<object>();
        await using var rd = await cmd.ExecuteReaderAsync();
        while (await rd.ReadAsync())
        {
            list.Add(new
            {
                signup_date = rd.GetDateTime(0).ToString("yyyy-MM-dd"),
                cohort_size = Convert.ToInt64(rd.GetValue(1)),
            });
        }
        return Results.Json(new { cohorts = list });
    }
    catch (Exception e)
    {
        logger.LogError("retention-cohort: cohorts: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/activity/user/{user_id}", async (string user_id, PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT activity_date FROM user_activity WHERE user_id = @u ORDER BY activity_date DESC LIMIT 30", conn);
        cmd.Parameters.AddWithValue("@u", user_id);
        var list = new List<string>();
        await using var rd = await cmd.ExecuteReaderAsync();
        while (await rd.ReadAsync())
        {
            list.Add(rd.GetDateTime(0).ToString("yyyy-MM-dd"));
        }
        return Results.Json(new { user_id, activity_dates = list });
    }
    catch (Exception e)
    {
        logger.LogError("retention-cohort: activity-user: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.Run();

record SignupReq(string user_id, string signup_date_iso);
record ActivityReq(string user_id, string activity_date_iso);

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
