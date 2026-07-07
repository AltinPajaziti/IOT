using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using TrafficApi.Data;
using TrafficApi.Models;

namespace TrafficApi.Services;

/// <summary>
/// Background service that polls the Python backend every few seconds
/// stores a snapshot per camera in SQL Server, and prunes records older
/// than <see cref="RetentionHours"/> hours.
/// </summary>
public class SnapshotPollerService(
    IServiceScopeFactory scopeFactory,
    IHttpClientFactory   httpFactory,
    ILogger<SnapshotPollerService> logger,
    IConfiguration config) : BackgroundService
{
    private static readonly TimeSpan PollInterval  = TimeSpan.FromSeconds(2);
    private static readonly TimeSpan RetentionTime = TimeSpan.FromHours(24);

    // Known camera coordinates (Prishtina)
    private static readonly Dictionary<string, double[]> CameraCoords = new()
    {
        ["pejton"]    = [42.6594, 21.1558],
        ["pejton2"]   = [42.6601, 21.1565],
        ["tokbashqe"] = [42.6572, 21.1621],
    };

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        // Run once immediately on startup so the client has data right away
        await PollAndStoreAsync(stoppingToken);

        using var timer = new PeriodicTimer(PollInterval);
        while (!stoppingToken.IsCancellationRequested && await timer.WaitForNextTickAsync(stoppingToken))
        {
            await PollAndStoreAsync(stoppingToken);
        }
    }

    private async Task PollAndStoreAsync(CancellationToken ct)
    {
        var pythonBase = config["PythonApi:BaseUrl"] ?? "http://localhost:8000";
        var http = httpFactory.CreateClient("python");

        try
        {
            // 1. Fetch camera list
            var cameras = await FetchJsonAsync<List<CameraDto>>(
                http, $"{pythonBase}/api/traffic/cameras", ct);
            if (cameras is null) return;

            using var scope = scopeFactory.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<TrafficDbContext>();

            var now = DateTime.UtcNow;

            foreach (var cam in cameras.Where(c => c.Active))
            {
                // 2. Fetch latest stats for this camera
                var stats = await FetchJsonAsync<StatsDto>(
                    http, $"{pythonBase}/api/traffic/stats/{cam.Id}", ct);
                if (stats is null || stats.Counts is null) continue;

                var coords = CameraCoords.TryGetValue(cam.Id, out var c) ? c : [42.6629, 21.1655];

                var snap = new TrafficSnapshot
                {
                    CameraId       = cam.Id,
                    CameraName     = cam.Name,
                    Location       = cam.Location,
                    City           = cam.City,
                    CapturedAt     = now,
                    TotalVehicles  = stats.TotalVehicles,
                    Cars           = stats.Counts.Car,
                    Trucks         = stats.Counts.Truck,
                    Buses          = stats.Counts.Bus,
                    Motorcycles    = stats.Counts.Motorcycle,
                    Density        = stats.Density,
                    Fps            = stats.Fps,
                    Latitude       = coords[0],
                    Longitude      = coords[1],
                };

                db.Snapshots.Add(snap);
                logger.LogInformation("Stored snapshot for {Camera}: {Total} vehicles, {Density}",
                    cam.Id, snap.TotalVehicles, snap.Density);
            }

            // 3. Prune old records
            var cutoff = now - RetentionTime;
            await db.Snapshots
                    .Where(s => s.CapturedAt < cutoff)
                    .ExecuteDeleteAsync(ct);

            await db.SaveChangesAsync(ct);
        }
        catch (Exception ex) when (!ct.IsCancellationRequested)
        {
            logger.LogError(ex, "Snapshot poll failed");
        }
    }

    private static async Task<T?> FetchJsonAsync<T>(HttpClient http, string url, CancellationToken ct)
    {
        try
        {
            var resp = await http.GetAsync(url, ct);
            resp.EnsureSuccessStatusCode();
            var json = await resp.Content.ReadAsStringAsync(ct);
            return JsonSerializer.Deserialize<T>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            });
        }
        catch { return default; }
    }

    // ── DTOs for deserialising Python API responses ──────────────────────────
    private sealed class CameraDto
    {
        [System.Text.Json.Serialization.JsonPropertyName("id")]
        public string Id { get; init; } = "";
        [System.Text.Json.Serialization.JsonPropertyName("name")]
        public string Name { get; init; } = "";
        [System.Text.Json.Serialization.JsonPropertyName("location")]
        public string Location { get; init; } = "";
        [System.Text.Json.Serialization.JsonPropertyName("city")]
        public string City { get; init; } = "";
        [System.Text.Json.Serialization.JsonPropertyName("running")]
        public bool Running { get; init; }
        [System.Text.Json.Serialization.JsonPropertyName("active")]
        public bool Active { get; init; }
    }

    private sealed class CountsDto
    {
        [System.Text.Json.Serialization.JsonPropertyName("car")]
        public int Car { get; init; }
        [System.Text.Json.Serialization.JsonPropertyName("truck")]
        public int Truck { get; init; }
        [System.Text.Json.Serialization.JsonPropertyName("bus")]
        public int Bus { get; init; }
        [System.Text.Json.Serialization.JsonPropertyName("motorcycle")]
        public int Motorcycle { get; init; }
    }

    private sealed class StatsDto
    {
        [System.Text.Json.Serialization.JsonPropertyName("total_vehicles")]
        public int TotalVehicles { get; init; }
        [System.Text.Json.Serialization.JsonPropertyName("counts")]
        public CountsDto? Counts { get; init; }
        [System.Text.Json.Serialization.JsonPropertyName("density")]
        public string Density { get; init; } = "Low";
        [System.Text.Json.Serialization.JsonPropertyName("fps")]
        public double Fps { get; init; }
    }
}
