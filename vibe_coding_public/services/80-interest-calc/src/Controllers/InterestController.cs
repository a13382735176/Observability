using Microsoft.AspNetCore.Mvc;
using Npgsql;
using System.Text.Json;

namespace InterestCalc.Controllers;

[ApiController]
public class InterestController : ControllerBase
{
    private static readonly string ConnStr = BuildConnStr();

    private static string BuildConnStr()
    {
        var pgDsn = Environment.GetEnvironmentVariable("PG_DSN")
            ?? "postgres://vibe:vibe@postgres:5432/vibe";
        // Parse DSN: postgres://user:pass@host:port/db
        var uri = new Uri(pgDsn);
        var userInfo = uri.UserInfo.Split(':');
        return $"Host={uri.Host};Port={(uri.Port > 0 ? uri.Port : 5432)};Username={userInfo[0]};Password={userInfo[1]};Database={uri.AbsolutePath.TrimStart('/')}";
    }

    static InterestController()
    {
        try
        {
            using var conn = new NpgsqlConnection(ConnStr);
            conn.Open();
            using var cmd = new NpgsqlCommand(@"
                CREATE TABLE IF NOT EXISTS interest_rates(
                    id serial PRIMARY KEY,
                    product_type text UNIQUE,
                    rate_pct double precision,
                    updated_at timestamptz DEFAULT now()
                )", conn);
            cmd.ExecuteNonQuery();
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"interest-calc: pg init: {e.Message}");
        }
    }

    [HttpGet("/healthz")]
    public IActionResult Healthz() =>
        Ok(new { status = "ok", service = "interest-calc" });

    [HttpPost("/calculate")]
    public IActionResult Calculate([FromBody] CalcRequest req)
    {
        if (req.TermMonths <= 0 || req.AnnualRatePct <= 0 || req.PrincipalCents <= 0)
            return BadRequest(new { error = "invalid input" });

        double r = req.AnnualRatePct / 100.0 / 12.0;
        int n = req.TermMonths;
        double monthlyPaymentCents;
        if (r == 0)
        {
            monthlyPaymentCents = (double)req.PrincipalCents / n;
        }
        else
        {
            double factor = Math.Pow(1 + r, n);
            monthlyPaymentCents = req.PrincipalCents * (r * factor) / (factor - 1);
        }
        long totalPaymentCents = (long)(monthlyPaymentCents * n);
        long totalInterestCents = totalPaymentCents - req.PrincipalCents;
        return Ok(new
        {
            principal_cents = req.PrincipalCents,
            annual_rate_pct = req.AnnualRatePct,
            term_months = n,
            monthly_payment_cents = (long)monthlyPaymentCents,
            total_interest_cents = totalInterestCents
        });
    }

    [HttpPost("/rates")]
    public IActionResult UpsertRate([FromBody] RateRequest req)
    {
        try
        {
            using var conn = new NpgsqlConnection(ConnStr);
            conn.Open();
            using var cmd = new NpgsqlCommand(@"
                INSERT INTO interest_rates(product_type, rate_pct, updated_at)
                VALUES(@product_type, @rate_pct, now())
                ON CONFLICT(product_type) DO UPDATE SET rate_pct=EXCLUDED.rate_pct, updated_at=now()", conn);
            cmd.Parameters.AddWithValue("product_type", req.ProductType);
            cmd.Parameters.AddWithValue("rate_pct", req.RatePct);
            cmd.ExecuteNonQuery();
            return StatusCode(201, new { ok = true });
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"interest-calc: pg: {e.Message}");
            return StatusCode(503, new { error = "db error" });
        }
    }

    [HttpGet("/rates")]
    public IActionResult GetRates()
    {
        try
        {
            var results = new List<object>();
            using var conn = new NpgsqlConnection(ConnStr);
            conn.Open();
            using var cmd = new NpgsqlCommand("SELECT product_type, rate_pct FROM interest_rates ORDER BY product_type", conn);
            using var reader = cmd.ExecuteReader();
            while (reader.Read())
            {
                results.Add(new { product_type = reader.GetString(0), rate_pct = reader.GetDouble(1) });
            }
            return Ok(results);
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"interest-calc: pg: {e.Message}");
            return StatusCode(503, new { error = "db error" });
        }
    }
}

public record CalcRequest(long PrincipalCents, double AnnualRatePct, int TermMonths);
public record RateRequest(string ProductType, double RatePct);
