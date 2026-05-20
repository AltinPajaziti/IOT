namespace TrafficApi.Models;

public class TrafficSnapshot
{
    public int Id { get; set; }
    public string CameraId   { get; set; } = string.Empty;
    public string CameraName { get; set; } = string.Empty;
    public string Location   { get; set; } = string.Empty;
    public string City       { get; set; } = string.Empty;
    public DateTime CapturedAt { get; set; }

    public int   TotalVehicles { get; set; }
    public int   Cars          { get; set; }
    public int   Trucks        { get; set; }
    public int   Buses         { get; set; }
    public int   Motorcycles   { get; set; }
    public string Density      { get; set; } = "Low";   // Low | Medium | High
    public double Fps          { get; set; }

    // GPS coords for the map (Prishtina cameras)
    public double Latitude  { get; set; }
    public double Longitude { get; set; }
}
