"""
Apache Spark Structured Streaming job — Professor Project 2 requirement.

Reads traffic sensor events from Kafka, applies real-time processing
(validation, filtering, 1-minute tumbling window aggregations), and
writes results to Apache Cassandra.

Run (after docker compose up -d):
  pip install -r requirements.txt
  spark-submit traffic_streaming.py

Requires: Java 11+, Apache Spark 3.5+, Kafka & Cassandra running.
"""
from __future__ import annotations

import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, count, avg, max as spark_max, window, from_json,
    when, current_timestamp, lit,
)
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType,
)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_TOPIC     = os.getenv("KAFKA_TOPIC", "traffic-sensor-events")
CASSANDRA_HOST  = os.getenv("CASSANDRA_HOST", "127.0.0.1")
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "traffic_iot")

EVENT_SCHEMA = StructType([
    StructField("camera_id",       StringType()),
    StructField("camera_name",     StringType()),
    StructField("location",        StringType()),
    StructField("city",            StringType()),
    StructField("captured_at",     StringType()),
    StructField("total_vehicles",  IntegerType()),
    StructField("cars",            IntegerType()),
    StructField("trucks",          IntegerType()),
    StructField("buses",           IntegerType()),
    StructField("motorcycles",     IntegerType()),
    StructField("density",         StringType()),
    StructField("fps",             DoubleType()),
    StructField("latitude",        DoubleType()),
    StructField("longitude",       DoubleType()),
    StructField("source",          StringType()),
])


def main() -> None:
    spark = (
        SparkSession.builder
        .appName("TrafficIoT-Streaming")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.cassandra.connection.host", CASSANDRA_HOST)
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    raw = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", KAFKA_TOPIC)
        .option("startingOffsets", "latest")
        .load()
    )

    events = (
        raw.select(from_json(col("value").cast("string"), EVENT_SCHEMA).alias("e"))
        .select("e.*")
        .filter(col("camera_id").isNotNull())
        .filter(col("total_vehicles") >= 0)
        .withColumn("event_time", current_timestamp())
    )

    # ── Write validated raw snapshots to Cassandra ────────────────────────────
    snapshots = events.select(
        col("camera_id"),
        col("event_time").alias("captured_at"),
        col("camera_name"),
        col("location"),
        col("city"),
        col("total_vehicles"),
        col("cars"),
        col("trucks"),
        col("buses"),
        col("motorcycles"),
        col("density"),
        col("fps"),
        col("latitude"),
        col("longitude"),
        col("source"),
    )

    snapshot_query = (
        snapshots.writeStream
        .format("org.apache.spark.sql.cassandra")
        .option("keyspace", CASSANDRA_KEYSPACE)
        .option("table", "sensor_snapshots")
        .option("checkpointLocation", "/tmp/spark-checkpoint/snapshots")
        .outputMode("append")
        .trigger(processingTime="2 seconds")
        .start()
    )

    # Sensor metadata is upserted by camera_id so Cassandra keeps the latest
    # known description/location for each sensor.
    metadata = events.select(
        col("camera_id"),
        col("camera_name"),
        col("location"),
        col("city"),
        col("latitude"),
        col("longitude"),
        col("source"),
        col("event_time").alias("updated_at"),
    )

    metadata_query = (
        metadata.writeStream
        .format("org.apache.spark.sql.cassandra")
        .option("keyspace", CASSANDRA_KEYSPACE)
        .option("table", "sensor_metadata")
        .option("checkpointLocation", "/tmp/spark-checkpoint/metadata")
        .outputMode("append")
        .trigger(processingTime="2 seconds")
        .start()
    )

    # ── 1-minute tumbling window aggregations per camera ──────────────────────
    aggregated = (
        events
        .withWatermark("event_time", "2 minutes")
        .groupBy(col("camera_id"), window(col("event_time"), "1 minute"))
        .agg(
            avg("total_vehicles").alias("avg_vehicles"),
            spark_max("total_vehicles").alias("max_vehicles"),
            count("*").alias("sample_count"),
        )
        .select(
            col("camera_id"),
            col("window.start").alias("window_start"),
            col("window.end").alias("window_end"),
            col("avg_vehicles"),
            col("max_vehicles"),
            col("sample_count"),
            when(col("avg_vehicles") <= 5, lit("Low"))
            .when(col("avg_vehicles") <= 15, lit("Medium"))
            .otherwise(lit("High"))
            .alias("dominant_density"),
        )
    )

    aggregate_query = (
        aggregated.writeStream
        .format("org.apache.spark.sql.cassandra")
        .option("keyspace", CASSANDRA_KEYSPACE)
        .option("table", "sensor_aggregates")
        .option("checkpointLocation", "/tmp/spark-checkpoint/aggregates")
        .outputMode("append")
        .trigger(processingTime="2 seconds")
        .start()
    )

    print("Spark Streaming started — reading from Kafka, writing to Cassandra")
    print(f"  Kafka:     {KAFKA_BOOTSTRAP} / topic={KAFKA_TOPIC}")
    print(f"  Cassandra: {CASSANDRA_HOST} / keyspace={CASSANDRA_KEYSPACE}")
    print("Press Ctrl+C to stop.")

    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()
