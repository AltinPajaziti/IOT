using Microsoft.EntityFrameworkCore;
using TrafficApi.Models;

namespace TrafficApi.Data;

public class TrafficDbContext(DbContextOptions<TrafficDbContext> options) : DbContext(options)
{
    public DbSet<TrafficSnapshot> Snapshots => Set<TrafficSnapshot>();

    protected override void OnModelCreating(ModelBuilder b)
    {
        b.Entity<TrafficSnapshot>(e =>
        {
            e.HasKey(x => x.Id);
            e.Property(x => x.CameraId).HasMaxLength(50);
            e.Property(x => x.Density).HasMaxLength(10);
            e.HasIndex(x => x.CapturedAt);
            e.HasIndex(x => x.CameraId);
        });
    }
}
