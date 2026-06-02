FROM python:3.11-slim

# System deps: matplotlib (headless) + carball runtime libs; curl for the healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# rrrocket Linux binary (x86_64 musl static) is vendored in the repo — copy it in.
# No build-time download, so the build is fully reproducible and offline-safe.
COPY rrrocket_bin/linux/rrrocket /app/rrrocket_bin/rrrocket
RUN chmod +x /app/rrrocket_bin/rrrocket && /app/rrrocket_bin/rrrocket --version

ENV RRROCKET_PATH=/app/rrrocket_bin/rrrocket
# Matplotlib non-interactive backend
ENV MPLBACKEND=Agg

# Install Python dependencies
COPY requirements_web.txt .
RUN pip install --no-cache-dir -r requirements_web.txt

# Copy application code
COPY rlcoach/ ./rlcoach/
COPY rlapi/ ./rlapi/
COPY static/ ./static/
COPY web_app.py web_database.py ./

# Create data directory (will be volume-mounted in production)
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000"]
