using Microsoft.EntityFrameworkCore;
using TrafficApi.Models;

namespace TrafficApi.Data;

public class TrafficDbContext(DbContextOptions<TrafficDbContext> options) : DbContext(options)
{
    public DbSet<TrafficSnapshot> Snapshots   => Set<TrafficSnapshot>();
    public DbSet<AppSetting>      AppSettings => Set<AppSetting>();

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

        b.Entity<AppSetting>(e =>
        {
            e.HasKey(x => x.Key);
            e.Property(x => x.Key).HasMaxLength(100);
            e.Property(x => x.Value).HasMaxLength(500);
        });
    }
}
