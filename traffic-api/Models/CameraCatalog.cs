namespace TrafficApi.Models;

public static class CameraCatalog
{
    public record CameraMeta(string Id, string Name, string Location, string City, double Lat, double Lng);

    public static readonly CameraMeta[] All =
    [
        new("pejton",    "Pejton",    "Rr. Agim Ramadani, Pejton", "Prishtinë", 42.6594, 21.1558),
        new("pejton2",   "Pejton 2",  "Rr. Agim Ramadani, Pejton", "Prishtinë", 42.6601, 21.1565),
        new("tokbashqe", "Tokbashqe", "Rr. Tokbashqe",             "Prishtinë", 42.6572, 21.1621),
    ];

    public static CameraMeta? Find(string cameraId) =>
        All.FirstOrDefault(c => c.Id == cameraId);
}
