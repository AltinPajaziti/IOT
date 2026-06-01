using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TrafficApi.Data;

namespace TrafficApi.Controllers;

[ApiController]
[Route("api/[controller]")]
public class SettingsController(TrafficDbContext db) : ControllerBase
{
    public const string RefreshSecondsKey = "RefreshSeconds";
    public const int DefaultRefreshSeconds = 15;

    /// <summary>Client-facing settings stored in SQL Server.</summary>
    [HttpGet]
    public async Task<IActionResult> Get()
    {
        var raw = await db.AppSettings
            .Where(s => s.Key == RefreshSecondsKey)
            .Select(s => s.Value)
            .FirstOrDefaultAsync();

        var seconds = int.TryParse(raw, out var n) && n >= 5 && n <= 300
            ? n
            : DefaultRefreshSeconds;

        return Ok(new { refreshSeconds = seconds });
    }
}
