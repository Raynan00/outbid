#!/bin/bash
# Start 3 Cloudflare Bypass Servers with different residential proxies
# Run this script on your EC2 instance before starting the bot

# Load proxies from file (first 3 lines)
PROXY_FILE="Webshare residential proxies.txt"

if [ ! -f "$PROXY_FILE" ]; then
    echo "Error: $PROXY_FILE not found"
    exit 1
fi

# Read first 3 proxies and convert to URL format
PROXY_1=$(sed -n '1p' "$PROXY_FILE" | awk -F: '{print "http://"$3":"$4"@"$1":"$2}')
PROXY_2=$(sed -n '100p' "$PROXY_FILE" | awk -F: '{print "http://"$3":"$4"@"$1":"$2}')
PROXY_3=$(sed -n '200p' "$PROXY_FILE" | awk -F: '{print "http://"$3":"$4"@"$1":"$2}')

echo "Starting 3 Cloudflare Bypass Servers..."
echo "Proxy 1: ${PROXY_1##*@}"
echo "Proxy 2: ${PROXY_2##*@}"
echo "Proxy 3: ${PROXY_3##*@}"

# Stop existing containers
docker stop cloudflare_bypass_1 cloudflare_bypass_2 cloudflare_bypass_3 2>/dev/null
docker rm cloudflare_bypass_1 cloudflare_bypass_2 cloudflare_bypass_3 2>/dev/null

# Start container 1 on port 8001
docker run -d \
    -p 8001:8000 \
    --name cloudflare_bypass_1 \
    -e PROXY_URL="$PROXY_1" \
    --restart unless-stopped \
    --memory=800m \
    ghcr.io/sarperavci/cloudflarebypassforscraping:latest

# Start container 2 on port 8002
docker run -d \
    -p 8002:8000 \
    --name cloudflare_bypass_2 \
    -e PROXY_URL="$PROXY_2" \
    --restart unless-stopped \
    --memory=800m \
    ghcr.io/sarperavci/cloudflarebypassforscraping:latest

# Start container 3 on port 8003
docker run -d \
    -p 8003:8000 \
    --name cloudflare_bypass_3 \
    -e PROXY_URL="$PROXY_3" \
    --restart unless-stopped \
    --memory=800m \
    ghcr.io/sarperavci/cloudflarebypassforscraping:latest

echo ""
echo "All 3 bypass servers started!"
echo "Container status:"
docker ps --filter "name=cloudflare_bypass" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
