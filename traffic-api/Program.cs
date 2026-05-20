using Microsoft.EntityFrameworkCore;
using TrafficApi.Data;
using TrafficApi.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();

// SQL Server
builder.Services.AddDbContext<TrafficDbContext>(opt =>
    opt.UseSqlServer(builder.Configuration.GetConnectionString("DefaultConnection")));

// HTTP client for polling Python backend
builder.Services.AddHttpClient("python");

// Background poller
builder.Services.AddHostedService<SnapshotPollerService>();

// CORS — allow Angular dev server and production client
builder.Services.AddCors(opt =>
    opt.AddDefaultPolicy(p =>
        p.WithOrigins(
            "http://localhost:4201",
            "http://127.0.0.1:4201",
            "http://localhost:4200",
            "http://127.0.0.1:4200"
        )
        .AllowAnyMethod()
        .AllowAnyHeader()));

var app = builder.Build();

// Auto-migrate on startup
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<TrafficDbContext>();
    db.Database.EnsureCreated();
}

app.UseCors();
app.UseAuthorization();
app.MapControllers();

app.Run();
