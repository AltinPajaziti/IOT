using Microsoft.EntityFrameworkCore;
using TrafficApi.Controllers;
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

// Auto-migrate on startup + seed default settings
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<TrafficDbContext>();
    db.Database.EnsureCreated();

    // Ensure AppSettings table exists on databases created before this feature
    await db.Database.ExecuteSqlRawAsync("""
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'AppSettings')
        CREATE TABLE AppSettings (
            [Key]   NVARCHAR(100)  NOT NULL PRIMARY KEY,
            [Value] NVARCHAR(500)  NOT NULL
        );
        """);

    if (!await db.AppSettings.AnyAsync(s => s.Key == SettingsController.RefreshSecondsKey))
    {
        db.AppSettings.Add(new TrafficApi.Models.AppSetting
        {
            Key   = SettingsController.RefreshSecondsKey,
            Value = SettingsController.DefaultRefreshSeconds.ToString(),
        });
        await db.SaveChangesAsync();
    }
}

app.UseCors();
app.UseAuthorization();
app.MapControllers();

app.Run();
