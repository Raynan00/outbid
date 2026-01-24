# Start 3 Cloudflare Bypass Servers with different residential proxies
# Run this script locally for testing before EC2 deployment

$ProxyFile = "Webshare residential proxies.txt"

if (-not (Test-Path $ProxyFile)) {
    Write-Error "Error: $ProxyFile not found"
    exit 1
}

# Read proxies from different positions in the file
$lines = Get-Content $ProxyFile
$proxy1_parts = $lines[0].Split(':')
$proxy2_parts = $lines[99].Split(':')
$proxy3_parts = $lines[199].Split(':')

# Convert to URL format: http://user:pass@host:port
$PROXY_1 = "http://$($proxy1_parts[2]):$($proxy1_parts[3])@$($proxy1_parts[0]):$($proxy1_parts[1])"
$PROXY_2 = "http://$($proxy2_parts[2]):$($proxy2_parts[3])@$($proxy2_parts[0]):$($proxy2_parts[1])"
$PROXY_3 = "http://$($proxy3_parts[2]):$($proxy3_parts[3])@$($proxy3_parts[0]):$($proxy3_parts[1])"

Write-Host "Starting 3 Cloudflare Bypass Servers..." -ForegroundColor Green
Write-Host "Proxy 1: $($proxy1_parts[0]):$($proxy1_parts[1])"
Write-Host "Proxy 2: $($proxy2_parts[0]):$($proxy2_parts[1])"
Write-Host "Proxy 3: $($proxy3_parts[0]):$($proxy3_parts[1])"

# Stop existing containers
docker stop cloudflare_bypass_1 cloudflare_bypass_2 cloudflare_bypass_3 2>$null
docker rm cloudflare_bypass_1 cloudflare_bypass_2 cloudflare_bypass_3 2>$null

Write-Host "`nStarting container 1 on port 8001..." -ForegroundColor Cyan
docker run -d -p 8001:8000 --name cloudflare_bypass_1 -e PROXY_URL="$PROXY_1" --restart unless-stopped ghcr.io/sarperavci/cloudflarebypassforscraping:latest

Write-Host "Starting container 2 on port 8002..." -ForegroundColor Cyan
docker run -d -p 8002:8000 --name cloudflare_bypass_2 -e PROXY_URL="$PROXY_2" --restart unless-stopped ghcr.io/sarperavci/cloudflarebypassforscraping:latest

Write-Host "Starting container 3 on port 8003..." -ForegroundColor Cyan
docker run -d -p 8003:8000 --name cloudflare_bypass_3 -e PROXY_URL="$PROXY_3" --restart unless-stopped ghcr.io/sarperavci/cloudflarebypassforscraping:latest

Write-Host "`nAll 3 bypass servers started!" -ForegroundColor Green
Write-Host "`nContainer status:" -ForegroundColor Yellow
docker ps --filter "name=cloudflare_bypass" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
