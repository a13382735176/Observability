using Npgsql;
using StackExchange.Redis;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
builder.Services.AddSingleton<NpgsqlDataSource>(sp => {
    var pgDsn = Environment.GetEnvironmentVariable("PG_DSN") ?? "Host=postgres;Port=5432;Database=vibe;Username=vibe;Password=vibe";
    // Convert postgres:// DSN to Npgsql format if needed
    var connStr = pgDsn.StartsWith("postgres://") ? ConvertDsn(pgDsn) : pgDsn;
    var ds = NpgsqlDataSource.Create(connStr);
    InitDb(ds).GetAwaiter().GetResult();
    return ds;
});
builder.Services.AddSingleton<IConnectionMultiplexer>(sp => {
    var host = Environment.GetEnvironmentVariable("REDIS_CACHE_HOST") ?? "redis-cache";
    return ConnectionMultiplexer.Connect(new ConfigurationOptions {
        EndPoints = { { host, 6379 } }, ConnectTimeout = 2000, SyncTimeout = 2000
    });
});

var app = builder.Build();
app.UseRouting();
app.MapControllers();
// ensure DI init
app.Services.GetRequiredService<NpgsqlDataSource>();
app.Run();

static string ConvertDsn(string uri) {
    var u = new Uri(uri);
    var parts = u.UserInfo.Split(':');
    return $"Host={u.Host};Port={u.Port};Database={u.AbsolutePath.TrimStart('/')};Username={parts[0]};Password={parts[1]};Timeout=2;Command Timeout=2";
}

static async Task InitDb(NpgsqlDataSource ds) {
    await using var cmd = ds.CreateCommand(@"
        CREATE TABLE IF NOT EXISTS schedule_slots(
            id serial PRIMARY KEY,
            doctor_id text,
            slot_datetime timestamptz,
            patient_id text,
            booked bool DEFAULT false
        )");
    await cmd.ExecuteNonQueryAsync();
}
