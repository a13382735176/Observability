using System.Text.Json;
using Npgsql;
using StackExchange.Redis;

const string SERVICE = "invoice-generator";

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
        CREATE TABLE IF NOT EXISTS invoices (
            id bigserial PRIMARY KEY,
            customer_id text,
            total_cents bigint,
            status text DEFAULT 'unpaid',
            issued_at timestamptz DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS invoice_lines (
            id bigserial PRIMARY KEY,
            invoice_id bigint,
            description text,
            amount_cents bigint,
            quantity int
        );", conn);
    await cmd.ExecuteNonQueryAsync();
}
catch (Exception e)
{
    logger.LogError("invoice-generator: schema init: {Error}", e.Message);
}

app.MapGet("/healthz", () => Results.Json(new { status = "ok", service = SERVICE }));

app.MapPost("/invoices", async (HttpContext ctx, PgFactory pgf) =>
{
    try
    {
        var body = await JsonSerializer.DeserializeAsync<NewInvoiceReq>(ctx.Request.Body);
        if (body is null || string.IsNullOrEmpty(body.customer_id) || body.line_items is null || body.line_items.Length == 0)
            return Results.BadRequest(new { error = "customer_id and non-empty line_items required" });

        long total = 0;
        foreach (var li in body.line_items)
        {
            total += li.amount_cents * li.quantity;
        }

        await using var conn = await pgf.OpenAsync();
        await using var tx = await conn.BeginTransactionAsync();

        long invoiceId; DateTime issuedAt;
        await using (var insInv = new NpgsqlCommand(
            "INSERT INTO invoices(customer_id, total_cents) VALUES (@c, @t) RETURNING id, issued_at", conn, tx))
        {
            insInv.Parameters.AddWithValue("@c", body.customer_id);
            insInv.Parameters.AddWithValue("@t", total);
            await using var rd = await insInv.ExecuteReaderAsync();
            await rd.ReadAsync();
            invoiceId = rd.GetInt64(0);
            issuedAt = rd.GetDateTime(1);
        }

        foreach (var li in body.line_items)
        {
            await using var insLine = new NpgsqlCommand(
                "INSERT INTO invoice_lines(invoice_id, description, amount_cents, quantity) VALUES (@i, @d, @a, @q)",
                conn, tx);
            insLine.Parameters.AddWithValue("@i", invoiceId);
            insLine.Parameters.AddWithValue("@d", (object?)li.description ?? DBNull.Value);
            insLine.Parameters.AddWithValue("@a", li.amount_cents);
            insLine.Parameters.AddWithValue("@q", li.quantity);
            await insLine.ExecuteNonQueryAsync();
        }

        await tx.CommitAsync();

        try
        {
            var db = redis.GetDatabase();
            await db.StreamAddAsync("events:invoices", new NameValueEntry[]
            {
                new("invoice_id", invoiceId.ToString()),
                new("total_cents", total.ToString()),
            });
        }
        catch (Exception e)
        {
            logger.LogError("invoice-generator: XADD events:invoices: {Error}", e.Message);
        }

        return Results.Json(new
        {
            id = invoiceId,
            customer_id = body.customer_id,
            total_cents = total,
            status = "unpaid",
            issued_at = issuedAt,
            line_items = body.line_items,
        });
    }
    catch (Exception e)
    {
        logger.LogError("invoice-generator: create: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/invoices/{id:long}", async (long id, PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();

        await using var headCmd = new NpgsqlCommand(
            "SELECT id, customer_id, total_cents, status, issued_at FROM invoices WHERE id = @i", conn);
        headCmd.Parameters.AddWithValue("@i", id);
        await using var hrd = await headCmd.ExecuteReaderAsync();
        if (!await hrd.ReadAsync())
        {
            return Results.NotFound(new { error = "invoice not found" });
        }
        var header = new
        {
            id = hrd.GetInt64(0),
            customer_id = hrd.GetString(1),
            total_cents = hrd.GetInt64(2),
            status = hrd.GetString(3),
            issued_at = hrd.GetDateTime(4),
        };
        await hrd.CloseAsync();

        await using var linesCmd = new NpgsqlCommand(
            "SELECT id, description, amount_cents, quantity FROM invoice_lines WHERE invoice_id = @i ORDER BY id ASC", conn);
        linesCmd.Parameters.AddWithValue("@i", id);
        var lines = new List<object>();
        await using var lrd = await linesCmd.ExecuteReaderAsync();
        while (await lrd.ReadAsync())
        {
            lines.Add(new
            {
                id = lrd.GetInt64(0),
                description = lrd.IsDBNull(1) ? null : lrd.GetString(1),
                amount_cents = lrd.GetInt64(2),
                quantity = lrd.GetInt32(3),
            });
        }

        return Results.Json(new
        {
            id = header.id,
            customer_id = header.customer_id,
            total_cents = header.total_cents,
            status = header.status,
            issued_at = header.issued_at,
            line_items = lines,
        });
    }
    catch (Exception e)
    {
        logger.LogError("invoice-generator: get: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapGet("/invoices/customer/{customerId}", async (string customerId, PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "SELECT id, customer_id, total_cents, status, issued_at FROM invoices WHERE customer_id = @c ORDER BY id DESC LIMIT 20", conn);
        cmd.Parameters.AddWithValue("@c", customerId);
        var list = new List<object>();
        await using var rd = await cmd.ExecuteReaderAsync();
        while (await rd.ReadAsync())
        {
            list.Add(new
            {
                id = rd.GetInt64(0),
                customer_id = rd.GetString(1),
                total_cents = rd.GetInt64(2),
                status = rd.GetString(3),
                issued_at = rd.GetDateTime(4),
            });
        }
        return Results.Json(new { customer_id = customerId, items = list });
    }
    catch (Exception e)
    {
        logger.LogError("invoice-generator: by-customer: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.MapPut("/invoices/{id:long}/mark-paid", async (long id, PgFactory pgf) =>
{
    try
    {
        await using var conn = await pgf.OpenAsync();
        await using var cmd = new NpgsqlCommand(
            "UPDATE invoices SET status='paid' WHERE id = @i RETURNING id, total_cents", conn);
        cmd.Parameters.AddWithValue("@i", id);
        await using var rd = await cmd.ExecuteReaderAsync();
        if (!await rd.ReadAsync())
        {
            return Results.NotFound(new { error = "invoice not found" });
        }
        long invId = rd.GetInt64(0);
        long total = rd.GetInt64(1);
        await rd.CloseAsync();

        try
        {
            var db = redis.GetDatabase();
            await db.StreamAddAsync("events:invoice_paid", new NameValueEntry[]
            {
                new("invoice_id", invId.ToString()),
                new("total_cents", total.ToString()),
            });
        }
        catch (Exception e)
        {
            logger.LogError("invoice-generator: XADD events:invoice_paid: {Error}", e.Message);
        }

        return Results.Json(new { id = invId, status = "paid", total_cents = total });
    }
    catch (Exception e)
    {
        logger.LogError("invoice-generator: mark-paid: {Error}", e.Message);
        return Results.StatusCode(502);
    }
});

app.Run();

record NewInvoiceLine(string? description, long amount_cents, int quantity);
record NewInvoiceReq(string customer_id, NewInvoiceLine[] line_items);

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
