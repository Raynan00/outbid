# Use Python 3.10 as the base
FROM python:3.10-slim

# Install Chrome, Xvfb, and system dependencies
# (Removed libgconf-2-4 which causes the error)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    xvfb \
    x11-utils \
    libnss3 \
    libxi6 \
    libglib2.0-0 \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome (Stable) - using modern GPG key method
RUN wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y /tmp/google-chrome.deb \
    && rm /tmp/google-chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency file first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Fix Windows line endings for the entrypoint script
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

# Set the display port for Xvfb
ENV DISPLAY=:99

# Default command (can be overridden by docker-compose)
# entrypoint.sh starts Xvfb + main.py
# For webhook_server, override with: command: ["python", "webhook_server.py"]
CMD ["./entrypoint.sh"]