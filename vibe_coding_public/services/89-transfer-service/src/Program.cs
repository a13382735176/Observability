using Npgsql;
using StackExchange.Redis;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();

var app = builder.Build();
app.UseRouting();
app.MapControllers();
app.Run();
