#!/bin/bash

# Outbid Bot - EC2 Deployment Script
# Run this on your EC2 instance (Ubuntu/Amazon Linux 2)

echo ">>> Starting Outbid Bot Deployment..."

# 1. Update System
echo ">>> Updating system packages..."
sudo apt-get update -y && sudo apt-get upgrade -y

# 2. Install Docker & Docker Compose
echo ">>> Installing Docker..."
if ! command -v docker &> /dev/null; then
    sudo apt-get install -y docker.io
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker $USER
    echo "Docker installed."
else
    echo "Docker already installed."
fi

echo ">>> Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "Docker Compose installed."
else
    echo "Docker Compose already installed."
fi

# 3. Build and Run
echo ">>> Building and starting containers..."
# Use sudo if user group hasn't updated in current session
sudo docker-compose down
sudo docker-compose up -d --build

echo ">>> Deployment Complete!"
echo ">>> Check logs with: sudo docker-compose logs -f"
