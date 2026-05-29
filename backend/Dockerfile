FROM python:3.10-slim-bookworm

# The API image should stay light. Heavy video work runs in the worker image;
# keeping ffmpeg/Chromium out of this image makes Coolify builds much less fragile.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Command is specified in docker-compose
