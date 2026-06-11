# Start IoT infrastructure (Kafka + Spark + Cassandra + UIs)
Write-Host "Starting IoT stack (Kafka, Spark, Cassandra, UIs)..." -ForegroundColor Cyan
docker compose up -d

Write-Host "Waiting for Cassandra to be ready (up to 90s)..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 18; $i++) {
    Start-Sleep -Seconds 5
    docker exec ioth-cassandra cqlsh -e "DESCRIBE KEYSPACES" 2>$null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
}
if (-not $ready) {
    Write-Host "Cassandra is not ready yet. Re-run this script after Docker reports it healthy." -ForegroundColor Red
    exit 1
}

Write-Host "Initializing Cassandra schema..." -ForegroundColor Cyan
Get-Content "$PSScriptRoot\..\cassandra\schema.cql" | docker exec -i ioth-cassandra cqlsh

Write-Host ""
Write-Host "IoT stack ready!" -ForegroundColor Green
Write-Host "  Kafka:     localhost:9092"
Write-Host "  Kafka UI:  http://localhost:8080"
Write-Host "  Spark UI:  http://localhost:8081"
Write-Host "  Cassandra: localhost:9042 (keyspace: traffic_iot)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. cd backend && pip install -r requirements.txt"
Write-Host "  2. uvicorn main:app --reload --port 8000"
Write-Host "  3. Spark Streaming runs in Docker as ioth-spark-streaming"
