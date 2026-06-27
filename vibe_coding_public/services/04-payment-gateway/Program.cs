// 04-payment-gateway — accept charge requests, call mock-upstream/charge,
// surface the upstream verdict.
//
// Endpoints:
//   GET  /healthz
//   POST /charge       body {"user_id":"...","amount_cents":N}

using System.Net;
using System.Text.Json;

var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.Logging.AddConsole();

var upstreamUrl = Environment.GetEnvironmentVariable("UPSTREAM_URL") ?? "http://mock-upstream:8080";
var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };

var app = builder.Build();
var log = app.Logger;
log.LogInformation("payment-gateway starting, upstream={url}", upstreamUrl);

app.MapGet("/healthz", () => Results.Json(new { ok = true }));

app.MapPost("/charge", async (HttpContext ctx) =>
{
    using var doc = await JsonDocument.ParseAsync(ctx.Request.Body);
    var root = doc.RootElement;
    if (!root.TryGetProperty("user_id", out var uid)
        || !root.TryGetProperty("amount_cents", out var amt))
    {
        return Results.BadRequest(new { error = "user_id and amount_cents required" });
    }

    var payload = JsonSerializer.Serialize(new
    {
        user_id = uid.GetString(),
        amount_cents = amt.GetInt64(),
        idem_key = Guid.NewGuid().ToString("N"),
    });
    var req = new HttpRequestMessage(HttpMethod.Post, upstreamUrl + "/charge")
    {
        Content = new StringContent(payload, System.Text.Encoding.UTF8, "application/json"),
    };

    HttpResponseMessage resp;
    try
    {
        resp = await http.SendAsync(req);
    }
    catch (TaskCanceledException ex)
    {
        log.LogError(ex, "ERROR upstream timeout (charge)");
        return Results.Json(new { error = "upstream timeout", detail = ex.Message }, statusCode: (int)HttpStatusCode.GatewayTimeout);
    }
    catch (Exception ex)
    {
        log.LogError(ex, "ERROR upstream error (charge): {msg}", ex.Message);
        return Results.Json(new { error = "upstream error", detail = ex.Message }, statusCode: (int)HttpStatusCode.BadGateway);
    }

    var body = await resp.Content.ReadAsStringAsync();
    if ((int)resp.StatusCode >= 500)
    {
        log.LogError("ERROR upstream 5xx status={s} body={b}", resp.StatusCode, body[..Math.Min(120, body.Length)]);
        return Results.Json(new { error = "upstream 5xx", status = (int)resp.StatusCode, body },
                            statusCode: (int)HttpStatusCode.BadGateway);
    }
    return Results.Json(new { ok = true, upstream_status = (int)resp.StatusCode, upstream_body = body });
});

app.Run();
