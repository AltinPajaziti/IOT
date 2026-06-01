using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TrafficApi.Data;
using TrafficApi.Models;

namespace TrafficApi.Controllers;

public record SimulateRequest(string? CameraId = null, int Cars = 200);

[ApiController]
[Route("api/[controller]")]
public class SnapshotsController(TrafficDbContext db) : ControllerBase
{
    /// <summary>Latest snapshot per camera (for the map view).</summary>
    [HttpGet("latest")]
    public async Task<IActionResult> Latest()
    {
        var rows = await db.Snapshots
            .GroupBy(s => s.CameraId)
            .Select(g => g.OrderByDescending(s => s.CapturedAt).First())
            .ToListAsync();
        return Ok(rows);
    }

    /// <summary>All snapshots for one camera (time-series for the chart).</summary>
    [HttpGet("history/{cameraId}")]
    public async Task<IActionResult> History(string cameraId, [FromQuery] int hours = 3)
    {
        var cutoff = DateTime.UtcNow.AddHours(-hours);
        var rows = await db.Snapshots
            .Where(s => s.CameraId == cameraId && s.CapturedAt >= cutoff)
            .OrderBy(s => s.CapturedAt)
            .ToListAsync();
        return Ok(rows);
    }

    /// <summary>Summary across all cameras for the current 5-min window.</summary>
    [HttpGet("summary")]
    public async Task<IActionResult> Summary()
    {
        var latest = await db.Snapshots
            .GroupBy(s => s.CameraId)
            .Select(g => g.OrderByDescending(s => s.CapturedAt).First())
            .ToListAsync();

        var summary = new
        {
            UpdatedAt     = latest.Select(s => s.CapturedAt).DefaultIfEmpty().Max(),
            TotalVehicles = latest.Sum(s => s.TotalVehicles),
            Cameras       = latest.Select(s => new
            {
                s.CameraId, s.CameraName, s.Location,
                s.TotalVehicles, s.Density, s.CapturedAt,
                s.Latitude, s.Longitude,
            }),
        };
        return Ok(summary);
    }

    /// <summary>
    /// Inserts simulated high-traffic snapshots into the database so the map client
    /// can pick them up on the next refresh and trigger congestion alerts.
    /// </summary>
    [HttpPost("simulate")]
    public async Task<IActionResult> Simulate([FromBody] SimulateRequest? req)
    {
        var cars = req?.Cars is > 0 and <= 500 ? req.Cars : 200;
        var trucks      = Math.Max(1, cars / 40);
        var buses       = Math.Max(1, cars / 50);
        var motorcycles = Math.Max(1, cars / 25);
        var total       = cars + trucks + buses + motorcycles;

        var targets = req?.CameraId is { Length: > 0 } id
            ? CameraCatalog.Find(id) is { } one ? new[] { one } : Array.Empty<CameraCatalog.CameraMeta>()
            : CameraCatalog.All;

        if (targets.Length == 0)
            return BadRequest(new { error = $"Unknown camera: {req?.CameraId}" });

        var now = DateTime.UtcNow;
        var created = new List<TrafficSnapshot>();

        foreach (var cam in targets)
        {
            var snap = new TrafficSnapshot
            {
                CameraId      = cam.Id,
                CameraName    = cam.Name,
                Location      = cam.Location,
                City          = cam.City,
                CapturedAt    = now,
                TotalVehicles = total,
                Cars          = cars,
                Trucks        = trucks,
                Buses         = buses,
                Motorcycles   = motorcycles,
                Density       = "High",
                Fps           = 24.0,
                Latitude      = cam.Lat,
                Longitude     = cam.Lng,
            };
            db.Snapshots.Add(snap);
            created.Add(snap);
        }

        await db.SaveChangesAsync();

        return Ok(new
        {
            message = $"Simulated {total} vehicles ({cars} cars) on {created.Count} camera(s)",
            snapshots = created,
        });
    }
}
