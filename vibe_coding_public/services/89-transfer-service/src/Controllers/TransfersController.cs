using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Npgsql;
using StackExchange.Redis;
using System.Threading.Tasks;

[ApiController]
[Route("")]
public class TransfersController : ControllerBase
{
    private static readonly ILogger<TransfersController> _log =
        LoggerFactory.Create(b => b.AddConsole()).CreateLogger<TransfersController>();

    private static NpgsqlDataSource? _ds;
    private static IDatabase? _redis;
    private static readonly object _lock = new();

    private static NpgsqlDataSource GetDs()
    {
        if (_ds != null) return _ds;
        lock (_lock) {
            if (_ds != null) return _ds;
            var dsn = Environment.GetEnvironmentVariable("PG_DSN") ?? "Host=postgres;Username=vibe;Password=vibe;Database=vibe";
            var pg = dsn.StartsWith("postgres://") ? ConvertDsn(dsn) : dsn;
            var sb = new NpgsqlDataSourceBuilder(pg);
            sb.ConnectionStringBuilder.CommandTimeout = 2;
            _ds = sb.Build();
            EnsureTable();
            return _ds;
        }
    }

    private static string ConvertDsn(string dsn)
    {
        var u = new Uri(dsn);
        var info = u.UserInfo.Split(':');
        return $"Host={u.Host};Port={u.Port};Username={info[0]};Password={info[1]};Database={u.AbsolutePath.TrimStart('/')}";
    }

    private static void EnsureTable()
    {
        try {
            using var conn = _ds!.OpenConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = @"CREATE TABLE IF NOT EXISTS transfers(
                id serial PRIMARY KEY, from_account text, to_account text,
                amount_cents bigint, reference text, status text DEFAULT 'completed',
                ts timestamptz DEFAULT now())";
            cmd.ExecuteNonQuery();
        } catch (Exception e) { _log.LogError("transfer-service: {Error}", e.Message); }
    }

    private static IDatabase GetRedis()
    {
        if (_redis != null) return _redis;
        var host = Environment.GetEnvironmentVariable("REDIS_STREAM_HOST") ?? "redis-stream";
        var mux = ConnectionMultiplexer.Connect($"{host}:6379,connectTimeout=2000,syncTimeout=2000");
        _redis = mux.GetDatabase();
        return _redis;
    }

    [HttpGet("/healthz")]
    public IActionResult Healthz() => Ok(new { status = "ok", service = "transfer-service" });

    [HttpPost("/transfers")]
    public IActionResult Create([FromBody] TransferReq req)
    {
        try {
            var ds = GetDs();
            using var conn = ds.OpenConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "INSERT INTO transfers(from_account,to_account,amount_cents,reference) VALUES($1,$2,$3,$4) RETURNING id,from_account,to_account,amount_cents,reference,status,ts::text";
            cmd.Parameters.AddWithValue(req.FromAccount);
            cmd.Parameters.AddWithValue(req.ToAccount);
            cmd.Parameters.AddWithValue(req.AmountCents);
            cmd.Parameters.AddWithValue(req.Reference ?? "");
            using var rd = cmd.ExecuteReader();
            rd.Read();
            var id = rd.GetInt32(0);
            var r = GetRedis();
            r.StreamAdd("events:transfers", new NameValueEntry[] {
                new("transfer_id", id.ToString()),
                new("from_account", req.FromAccount),
                new("to_account", req.ToAccount),
                new("amount_cents", req.AmountCents.ToString())
            });
            return StatusCode(201, new { id, from_account = req.FromAccount, to_account = req.ToAccount, amount_cents = req.AmountCents, status = "completed" });
        } catch (Exception e) {
            _log.LogError("transfer-service: {Error}", e.Message);
            return StatusCode(503, new { error = "error" });
        }
    }

    [HttpGet("/transfers/{id:int}")]
    public IActionResult GetById(int id)
    {
        try {
            var ds = GetDs();
            using var conn = ds.OpenConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "SELECT id,from_account,to_account,amount_cents,reference,status,ts::text FROM transfers WHERE id=$1";
            cmd.Parameters.AddWithValue(id);
            using var rd = cmd.ExecuteReader();
            if (!rd.Read()) return NotFound(new { error = "not found" });
            return Ok(new { id = rd.GetInt32(0), from_account = rd.GetString(1), to_account = rd.GetString(2), amount_cents = rd.GetInt64(3), reference = rd.GetString(4), status = rd.GetString(5), ts = rd.GetString(6) });
        } catch (Exception e) {
            _log.LogError("transfer-service: {Error}", e.Message);
            return StatusCode(503, new { error = "db error" });
        }
    }

    [HttpGet("/transfers/account/{account_id}")]
    public IActionResult GetByAccount(string account_id)
    {
        try {
            var ds = GetDs();
            using var conn = ds.OpenConnection();
            using var cmd = conn.CreateCommand();
            cmd.CommandText = "SELECT id,from_account,to_account,amount_cents,reference,status,ts::text FROM transfers WHERE from_account=$1 OR to_account=$1";
            cmd.Parameters.AddWithValue(account_id);
            using var rd = cmd.ExecuteReader();
            var list = new List<object>();
            while (rd.Read()) list.Add(new { id = rd.GetInt32(0), from_account = rd.GetString(1), to_account = rd.GetString(2), amount_cents = rd.GetInt64(3), reference = rd.GetString(4), status = rd.GetString(5), ts = rd.GetString(6) });
            return Ok(list);
        } catch (Exception e) {
            _log.LogError("transfer-service: {Error}", e.Message);
            return StatusCode(503, new { error = "db error" });
        }
    }
}

public record TransferReq(string FromAccount, string ToAccount, long AmountCents, string? Reference);
