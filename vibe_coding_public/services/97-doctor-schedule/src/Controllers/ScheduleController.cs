using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Npgsql;
using StackExchange.Redis;
using System.Threading.Tasks;

[ApiController]
public class ScheduleController : ControllerBase {
    private readonly NpgsqlDataSource _db;
    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<ScheduleController> _logger;

    public ScheduleController(NpgsqlDataSource db, IConnectionMultiplexer redis, ILogger<ScheduleController> logger) {
        _db = db; _redis = redis; _logger = logger;
    }

    [HttpGet("/healthz")]
    public IActionResult Healthz() => Ok(new { status = "ok", service = "doctor-schedule" });

    [HttpPost("/schedules")]
    public async Task<IActionResult> CreateSlot([FromBody] SlotReq req) {
        try {
            await using var cmd = _db.CreateCommand("INSERT INTO schedule_slots(doctor_id,slot_datetime) VALUES($1,$2) RETURNING id");
            cmd.Parameters.AddWithValue(req.doctor_id);
            cmd.Parameters.AddWithValue(DateTime.Parse(req.slot_datetime_iso).ToUniversalTime());
            var id = await cmd.ExecuteScalarAsync();
            return StatusCode(201, new { id, doctor_id = req.doctor_id, slot_datetime = req.slot_datetime_iso });
        } catch (Exception e) {
            _logger.LogError("doctor-schedule: {Error}", e.Message);
            return StatusCode(503, new { error = "db error" });
        }
    }

    [HttpGet("/schedules/{doctorId}/available")]
    public async Task<IActionResult> Available(string doctorId) {
        try {
            var cacheKey = $"schedule:{doctorId}:available";
            var db = _redis.GetDatabase();
            var cached = await db.StringGetAsync(cacheKey);
            if (cached.HasValue) return Ok(System.Text.Json.JsonSerializer.Deserialize<object>(cached!));
            await using var cmd = _db.CreateCommand("SELECT id,doctor_id,slot_datetime::text,booked FROM schedule_slots WHERE doctor_id=$1 AND booked=false ORDER BY slot_datetime");
            cmd.Parameters.AddWithValue(doctorId);
            await using var reader = await cmd.ExecuteReaderAsync();
            var rows = new List<object>();
            while (await reader.ReadAsync())
                rows.Add(new { id = reader.GetInt32(0), doctor_id = reader.GetString(1), slot_datetime = reader.GetString(2), booked = reader.GetBoolean(3) });
            var json = System.Text.Json.JsonSerializer.Serialize(rows);
            await db.StringSetAsync(cacheKey, json, TimeSpan.FromSeconds(30));
            return Ok(rows);
        } catch (Exception e) {
            _logger.LogError("doctor-schedule: {Error}", e.Message);
            return StatusCode(503, new { error = "db error" });
        }
    }

    [HttpPost("/book")]
    public async Task<IActionResult> Book([FromBody] BookReq req) {
        try {
            var slotDt = DateTime.Parse(req.slot_datetime_iso).ToUniversalTime();
            await using var cmd = _db.CreateCommand("UPDATE schedule_slots SET booked=true,patient_id=$1 WHERE doctor_id=$2 AND slot_datetime=$3 AND booked=false RETURNING id");
            cmd.Parameters.AddWithValue(req.patient_id);
            cmd.Parameters.AddWithValue(req.doctor_id);
            cmd.Parameters.AddWithValue(slotDt);
            var id = await cmd.ExecuteScalarAsync();
            if (id == null) return NotFound(new { error = "slot not available" });
            var db = _redis.GetDatabase();
            await db.KeyDeleteAsync($"schedule:{req.doctor_id}:available");
            return Ok(new { id, doctor_id = req.doctor_id, patient_id = req.patient_id, booked = true });
        } catch (Exception e) {
            _logger.LogError("doctor-schedule: {Error}", e.Message);
            return StatusCode(503, new { error = "db error" });
        }
    }
}

public record SlotReq(string doctor_id, string slot_datetime_iso);
public record BookReq(string doctor_id, string slot_datetime_iso, string patient_id);
