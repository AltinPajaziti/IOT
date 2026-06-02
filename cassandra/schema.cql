-- Traffic IoT keyspace — processed sensor data from Spark Streaming
CREATE KEYSPACE IF NOT EXISTS traffic_iot
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE traffic_iot;

-- Raw processed snapshots (one row per sensor reading after Spark validation)
CREATE TABLE IF NOT EXISTS sensor_snapshots (
  camera_id       text,
  captured_at     timestamp,
  camera_name     text,
  location        text,
  city            text,
  total_vehicles  int,
  cars            int,
  trucks          int,
  buses           int,
  motorcycles     int,
  density         text,
  fps             double,
  latitude        double,
  longitude       double,
  source          text,
  PRIMARY KEY (camera_id, captured_at)
) WITH CLUSTERING ORDER BY (captured_at DESC);

-- Sliding-window aggregates (Spark Streaming 1-minute tumbling windows)
CREATE TABLE IF NOT EXISTS sensor_aggregates (
  camera_id       text,
  window_start    timestamp,
  window_end      timestamp,
  avg_vehicles    double,
  max_vehicles    int,
  sample_count    int,
  dominant_density text,
  PRIMARY KEY (camera_id, window_start)
) WITH CLUSTERING ORDER BY (window_start DESC);
