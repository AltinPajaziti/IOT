using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TrafficApi.Data;

namespace TrafficApi.Controllers;

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
}
