// 15-webhook-fanout — receive a webhook, fan it out to 3 upstream paths in
// parallel, return per-destination status.
//
// Endpoints:
//   GET  /healthz
//   POST /webhook    body forwarded as-is to /dest-1 /dest-2 /dest-3 on UPSTREAM_URL.

using System.Net;
using System.Text;
using System.Text.Json;

var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.Logging.AddConsole();

var upstreamUrl = Environment.GetEnvironmentVariable("UPSTREAM_URL") ?? "http://mock-upstream:8080";
var destinations = new[] { "/dest-1", "/dest-2", "/dest-3" };
var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };

var app = builder.Build();
var log = app.Logger;
log.LogInformation("webhook-fanout starting, upstream={url} dests={dests}",
    upstreamUrl, string.Join(",", destinations));

app.MapGet("/healthz", () => Results.Json(new { ok = true }));

app.MapPost("/webhook", async (HttpContext ctx) =>
{
    using var ms = new MemoryStream();
    await ctx.Request.Body.CopyToAsync(ms);
    var bodyBytes = ms.ToArray();

    async Task<(string dest, int status, string body)> SendOne(string dest)
    {
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, upstreamUrl + dest)
            {
                Content = new ByteArrayContent(bodyBytes),
            };
            req.Content.Headers.ContentType =
                new System.Net.Http.Headers.MediaTypeHeaderValue(
                    ctx.Request.ContentType ?? "application/octet-stream");
            var resp = await http.SendAsync(req);
            var text = await resp.Content.ReadAsStringAsync();
            if ((int)resp.StatusCode >= 500)
            {
                log.LogError("ERROR upstream 5xx dest={d} status={s} body={b}",
                    dest, (int)resp.StatusCode, text[..Math.Min(80, text.Length)]);
            }
            return (dest, (int)resp.StatusCode, text);
        }
        catch (TaskCanceledException ex)
        {
            log.LogError(ex, "ERROR upstream timeout dest={d}", dest);
            return (dest, 504, "timeout: " + ex.Message);
        }
        catch (Exception ex)
        {
            log.LogError(ex, "ERROR upstream error dest={d} msg={m}", dest, ex.Message);
            return (dest, 502, "error: " + ex.Message);
        }
    }

    var tasks = destinations.Select(SendOne).ToArray();
    var results = await Task.WhenAll(tasks);
    var anyFail = results.Any(r => r.status >= 500);
    return Results.Json(new
    {
        ok = !anyFail,
        results = results.Select(r => new { r.dest, r.status, body = r.body.Length > 200 ? r.body[..200] : r.body }),
    }, statusCode: anyFail ? (int)HttpStatusCode.BadGateway : 200);
});

app.Run();
